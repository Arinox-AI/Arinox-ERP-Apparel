"""Write sinks. A script on a real site runs inside one DB transaction; over REST nothing is atomic, so every
write goes through a sink that remembers how to undo it.

* :class:`LiveSink` — performs the write on the ERP and appends a journal entry **with its inverse**.
  ``compensate()`` applies the inverses newest-first; what cannot be undone is reported, never hidden.
* :class:`RecordingSink` — performs nothing. Used for *preview* (what would happen?) and *check* (does this
  ERP-side change still satisfy the rules?). Reads still hit the ERP.

Reversibility: insert → delete; save / set_value → restore the previous values; submit → cancel;
cancel and delete are **irreversible** (a cancelled document cannot be un-cancelled, a deleted one is
re-inserted from its snapshot only as a best effort) and the entry says so.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Optional

from .backend import Backend
from .errors import TSRBackendError, TSRConflict, TSRNeedsSchemaFix, TSRNotFound, TSRValidationError

#: ERPNext methods whose result is only a draft in memory (safe to execute in preview/check mode).
READ_ONLY_CALLS = {
    "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
    "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
    "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
    "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
    "erpnext.controllers.item_variant.get_variant",
    # builds an unsaved variant Item in memory (frappe.new_doc, no write); the script inserts it, and that insert is journaled.
    # Without it here a preview of "make Sales Order" got None back and crashed, so no Sales Order could be made (2026-11-07).
    "erpnext.controllers.item_variant.create_variant",
    "erpnext.stock.doctype.batch.batch.get_batch_qty",
}


class Entry(dict):
    """One journaled write. Plain dict so it serialises."""


class LiveSink:
    mode = "live"

    def __init__(self, backend: Backend, persist: Optional[Callable[[dict], None]] = None):
        self.backend = backend
        self.entries: list[Entry] = []
        self._persist = persist
        self.created: list[tuple[str, str]] = []
        self.skipped: list[dict] = []

    # ---- helpers ----
    def _log(self, op, doctype, name, inverse=None, irreversible=False, note="") -> Entry:
        e = Entry(seq=len(self.entries) + 1, op=op, doctype=doctype, name=name, inverse=inverse,
                  irreversible=irreversible, note=note, at=time.time(), state="done")
        self.entries.append(e)
        if self._persist:
            try:
                self._persist(e)
            except Exception:
                pass
        return e

    # ---- writes ----
    def insert(self, data: dict) -> dict:
        res = self.backend.insert(data)
        self.created.append((res["doctype"], res["name"]))
        self._log("insert", res["doctype"], res["name"], inverse={"op": "delete", "doctype": res["doctype"], "name": res["name"]})
        return res

    def save(self, data: dict) -> dict:
        dt, name = data["doctype"], data["name"]
        try:
            before = self.backend.get_doc(dt, name)
        except TSRNotFound:
            before = None
        res = self.backend.save(data)
        self._log("save", dt, name, inverse={"op": "restore", "doctype": dt, "name": name, "before": before,
                                              "after_modified": res.get("modified")}, irreversible=before is None)
        return res

    def submit(self, data: dict) -> dict:
        res = self.backend.submit(data["doctype"], data["name"], data)
        self._log("submit", data["doctype"], data["name"],
                  inverse={"op": "cancel", "doctype": data["doctype"], "name": data["name"]},
                  note="posts stock/ledger entries where the doctype does" )
        return res

    def cancel(self, doctype: str, name: str) -> dict:
        res = self.backend.cancel(doctype, name)
        self._log("cancel", doctype, name, irreversible=True, note="a cancelled document cannot be reopened")
        return res

    def delete(self, doctype: str, name: str) -> None:
        try:
            snap = self.backend.get_doc(doctype, name)
        except TSRNotFound:
            return
        self.backend.delete(doctype, name)
        self._log("delete", doctype, name, inverse={"op": "reinsert", "doc": snap}, irreversible=True,
                  note="re-insert is best effort; links to it may have been lost")

    def set_value(self, doctype: str, name: str, values: dict) -> dict:
        before = {}
        try:
            row = self.backend.get_list(doctype, {"name": name}, list(values), limit=1) if not self.backend.is_single(doctype) else [self.backend.get_single(doctype)]
            before = {k: (row[0].get(k) if row else None) for k in values}
        except Exception:
            pass
        try:
            res = self.backend.set_value(doctype, name, values)
        except TSRValidationError as e:
            msg = str(e)
            if "cannot edit cancelled" in msg.lower():
                # The ERP refuses ANY edit to a cancelled document; on a hosted site without server scripts a raw
                # db_set is impossible. Cancelled is already carried by docstatus = 2, so this is recorded, not fatal.
                self.skipped.append({"doctype": doctype, "name": name, "values": values, "why": "document is cancelled"})
                return {"doctype": doctype, "name": name}
            if "after submission" in msg.lower() or "cannot update after submit" in msg.lower():
                raise TSRNeedsSchemaFix(doctype, list(values))
            raise
        self._log("set_value", doctype, name, inverse={"op": "set_value", "doctype": doctype, "name": name, "values": before})
        return res

    def call(self, method: str, kw: dict) -> Any:
        res = self.backend.call(method, kw)
        if method not in READ_ONLY_CALLS:
            self._log("call", "", method, irreversible=True, note="ERPNext method with side effects")
        return res

    def add_comment(self, doctype, name, text, kind="Comment"):
        self.backend.add_comment(doctype, name, text, kind)

    # ---- undo ----
    def compensate(self) -> dict:
        """Undo newest-first. Returns {undone:[...], irreversible:[...], failed:[...]}."""
        undone, irrev, failed = [], [], []
        for e in reversed(self.entries):
            if e["state"] != "done":
                continue
            inv = e.get("inverse")
            if e.get("irreversible") and not inv:
                irrev.append(f'{e["op"]} {e["doctype"]} {e["name"]}: {e.get("note", "")}')
                continue
            try:
                self._apply(inv)
                e["state"] = "undone"
                undone.append(f'{e["op"]} {e["doctype"]} {e["name"]}')
                if self._persist:
                    self._persist(e)
            except Exception as ex:
                e["state"] = "undo_failed"
                failed.append(f'{e["op"]} {e["doctype"]} {e["name"]}: {str(ex)[:200]}')
            if e.get("irreversible") and inv:
                irrev.append(f'{e["op"]} {e["doctype"]} {e["name"]}: {e.get("note", "")}')
        return {"undone": undone, "irreversible": irrev, "failed": failed}

    def _apply(self, inv: dict) -> None:
        b = self.backend
        op = inv["op"]
        if op == "delete":
            doc = None
            try:
                doc = b.get_doc(inv["doctype"], inv["name"])
            except TSRNotFound:
                return
            if doc.get("docstatus") == 1:
                b.cancel(inv["doctype"], inv["name"])
            b.delete(inv["doctype"], inv["name"])
        elif op == "cancel":
            b.cancel(inv["doctype"], inv["name"])
        elif op == "set_value":
            b.set_value(inv["doctype"], inv["name"], inv["values"])
        elif op == "restore":
            before = inv["before"]
            if before is None:
                return
            cur = b.get_doc(inv["doctype"], inv["name"])
            restored = copy.deepcopy(before)
            restored["modified"] = cur["modified"]
            b.save(restored)
        elif op == "reinsert":
            doc = copy.deepcopy(inv["doc"])
            doc.pop("modified", None)
            b.insert(doc)
        else:
            raise TSRBackendError(f"unknown inverse {op}")


class RecordingSink:
    """Performs nothing. ``ops`` is the list of what *would* happen."""

    mode = "record"

    def __init__(self, backend: Backend, run_read_only_calls: bool = True):
        self.backend = backend
        self.ops: list[dict] = []
        self._n = 0
        self.entries: list = []
        self.skipped: list = []
        self._ro = run_read_only_calls

    def _rec(self, **kw):
        self.ops.append(kw)

    def insert(self, data: dict) -> dict:
        self._n += 1
        out = copy.deepcopy(data)
        prefix = data.get("prefix")
        out["name"] = (str(prefix) + "0") if prefix is not None else f"(new {data['doctype']} {self._n})"
        out["docstatus"] = data.get("docstatus", 0)
        self._rec(op="insert", doctype=data["doctype"], name=out["name"], data=data)
        return out

    def save(self, data: dict) -> dict:
        before = None
        try:
            before = self.backend.get_doc(data["doctype"], data["name"])
        except TSRNotFound:
            pass
        self._rec(op="save", doctype=data["doctype"], name=data["name"], changes=_diff(before, data))
        return copy.deepcopy(data)

    def submit(self, data: dict) -> dict:
        self._rec(op="submit", doctype=data["doctype"], name=data.get("name"), changes=_diff(None, {}))
        out = copy.deepcopy(data)
        out["docstatus"] = 1
        return out

    def cancel(self, doctype, name):
        self._rec(op="cancel", doctype=doctype, name=name)
        return {"doctype": doctype, "name": name, "docstatus": 2}

    def delete(self, doctype, name):
        self._rec(op="delete", doctype=doctype, name=name)

    def set_value(self, doctype, name, values):
        self._rec(op="set_value", doctype=doctype, name=name, values=values)
        return {"doctype": doctype, "name": name, **values}

    def call(self, method, kw):
        if self._ro and method in READ_ONLY_CALLS:
            return self.backend.call(method, kw)
        self._rec(op="call", doctype="", name=method, kwargs=kw)
        return None

    def add_comment(self, doctype, name, text, kind="Comment"):
        self._rec(op="comment", doctype=doctype, name=name, text=text)

    def compensate(self):
        return {"undone": [], "irreversible": [], "failed": []}


def _diff(before: Optional[dict], after: dict) -> dict:
    out = {}
    skip = {"modified", "modified_by", "creation", "owner", "idx"}
    for k, v in after.items():
        if k in skip or isinstance(v, list):
            continue
        old = (before or {}).get(k)
        if old != v:
            out[k] = {"from": old, "to": v}
    for k, v in after.items():
        if isinstance(v, list):
            old = (before or {}).get(k) or []
            if len(old) != len(v):
                out[k] = {"from": f"{len(old)} row(s)", "to": f"{len(v)} row(s)"}
    return out
