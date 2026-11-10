"""An in-memory ERP for unit tests: documents, child tables, filters, docstatus, optimistic ``modified``.

Behaves like the parts of Frappe the runtime relies on — nothing more. Failure injection: ``fail_on = (op, doctype)``.
"""

from __future__ import annotations

import copy
import itertools
import re

from .backend import Backend
from .errors import TSRBackendError, TSRConflict, TSRNotFound, TSRValidationError


class FakeBackend(Backend):
    def __init__(self, meta: dict | None = None):
        self.docs: dict[str, dict[str, dict]] = {}
        self.metas = meta or {}
        self._t = itertools.count(1)
        self._n = itertools.count(1)
        self.calls: list[tuple] = []
        self.fail_on: tuple | None = None
        self.comments: list[tuple] = []
        self.singles: dict[str, dict] = {}
        self.call_results: dict[str, object] = {}
        self.autonames: dict[str, str] = {}

    # ---- helpers ----
    def _ts(self) -> str:
        return "2026-11-06 10:00:%02d.%06d" % (next(self._t) // 1000000 % 60, next(self._t))

    def _maybe_fail(self, op, dt):
        if self.fail_on and self.fail_on == (op, dt):
            raise TSRBackendError(f"injected failure on {op} {dt}", 500, "")

    def seed(self, doctype: str, name: str, **fields) -> dict:
        d = {"doctype": doctype, "name": name, "docstatus": 0, "modified": self._ts(), **fields}
        self.docs.setdefault(doctype, {})[name] = d
        return d

    def is_single(self, doctype):
        return doctype in self.singles

    # ---- filters ----
    @staticmethod
    def _match(d: dict, filters) -> bool:
        if not filters:
            return True
        items = filters.items() if isinstance(filters, dict) else [(f[0] if len(f) == 3 else f[1], f[1:] if len(f) == 3 else f[2:]) for f in filters]
        for k, v in items:
            if isinstance(filters, dict):
                op, val = ("=", v) if not isinstance(v, (list, tuple)) else (v[0], v[1])
            else:
                op, val = v[0], v[1]
            cur = d.get(k)
            if op == "=":
                ok = (cur == val) or (cur is not None and str(cur).lower() == str(val).lower())
            elif op == "!=":
                ok = cur != val
            elif op == "in":
                ok = cur in val or (isinstance(cur, str) and cur.lower() in [str(x).lower() for x in val])
            elif op == "not in":
                ok = cur not in val and not (isinstance(cur, str) and cur.lower() in [str(x).lower() for x in val])
            elif op == ">":
                ok = cur is not None and cur > val
            elif op == "<":
                ok = cur is not None and cur < val
            elif op == ">=":
                ok = cur is not None and cur >= val
            elif op == "<=":
                ok = cur is not None and cur <= val
            elif op == "like":
                ok = cur is not None and re.fullmatch(re.escape(str(val)).replace("%", ".*").replace("\\%", ".*"), str(cur), re.I) is not None
            else:
                raise TSRBackendError(f"fake: filter op {op}")
            if not ok:
                return False
        return True

    # ---- reads ----
    def get_doc(self, doctype, name):
        try:
            return copy.deepcopy(self.docs[doctype][name])
        except KeyError:
            raise TSRNotFound(doctype, name)

    def get_list(self, doctype, filters=None, fields=None, order_by=None, limit=None, parent=None):
        rows = []
        for d in self.docs.get(doctype, {}).values():
            if self._match(d, filters):
                rows.append(d)
        # child tables live inside parents
        if not rows and not self.docs.get(doctype):
            for pdt, pdocs in self.docs.items():
                for p in pdocs.values():
                    for k, v in p.items():
                        if isinstance(v, list):
                            for r in v:
                                if isinstance(r, dict) and r.get("doctype") == doctype and self._match({**r, "parent": p["name"]}, filters):
                                    rows.append({**r, "parent": p["name"]})
        if order_by:
            col, _, direction = order_by.partition(" ")
            rows.sort(key=lambda r: (r.get(col) is None, str(r.get(col))), reverse=direction.strip().lower() == "desc")
        if limit:
            rows = rows[:limit]
        if fields and fields != ["*"]:
            return [{f: copy.deepcopy(r.get(f)) for f in fields} for r in rows]
        return [copy.deepcopy(r) for r in rows]

    def get_single(self, doctype):
        return dict(self.singles.get(doctype, {}))

    def count(self, doctype, filters=None):
        return len(self.get_list(doctype, filters, ["name"]))

    def meta(self, doctype):
        return self.metas.get(doctype) or {"name": doctype, "istable": False, "issingle": doctype in self.singles, "is_submittable": True,
                                           "autoname": None, "fields": [], "permissions": []}

    # ---- writes ----
    def _stamp_children(self, d: dict) -> None:
        """Like the server: every child row knows its doctype, parent and position (meta-driven, when meta is known)."""
        m = self.metas.get(d.get("doctype")) or {}
        tables = {f["fieldname"]: f.get("options") for f in m.get("fields", []) if f.get("fieldtype") in ("Table", "Table MultiSelect")}
        for field, child_dt in tables.items():
            for i, r in enumerate(d.get(field) or []):
                if isinstance(r, dict):
                    r.setdefault("doctype", child_dt)
                    r["parentfield"], r["idx"] = field, i + 1
                    if d.get("name"):
                        r["parent"] = d["name"]
                        r.setdefault("name", "%s-%s-%d-%d" % (d["name"], field, i + 1, next(self._n)))

    def insert(self, doc):
        self._maybe_fail("insert", doc["doctype"])
        dt = doc["doctype"]
        d = copy.deepcopy(doc)
        name = d.get("name") or (self.autonames.get(dt, dt.upper().replace(" ", "-") + "-") + "%05d" % next(self._n))
        if name in self.docs.get(dt, {}):
            raise TSRValidationError(f"Duplicate entry {dt} {name}")
        d.update(name=name, docstatus=0, modified=self._ts())
        self._stamp_children(d)
        self.docs.setdefault(dt, {})[name] = d
        self.calls.append(("insert", dt, name))
        return copy.deepcopy(d)

    def save(self, doc):
        self._maybe_fail("save", doc["doctype"])
        dt, name = doc["doctype"], doc["name"]
        cur = self.docs.get(dt, {}).get(name)
        if cur is None:
            raise TSRNotFound(dt, name)
        if doc.get("modified") and doc["modified"] != cur["modified"]:
            raise TSRConflict(dt, name, doc["modified"], cur["modified"])
        new = copy.deepcopy(doc)
        new.update(modified=self._ts(), docstatus=cur["docstatus"])
        self._stamp_children(new)
        self.docs[dt][name] = new
        self.calls.append(("save", dt, name))
        return copy.deepcopy(new)

    def submit(self, doctype, name, doc=None):
        self._maybe_fail("submit", doctype)
        cur = self.docs[doctype][name]
        if doc:
            cur.update({k: v for k, v in doc.items() if k not in ("docstatus", "modified")})
        cur.update(docstatus=1, modified=self._ts())
        self.calls.append(("submit", doctype, name))
        return copy.deepcopy(cur)

    def cancel(self, doctype, name):
        self._maybe_fail("cancel", doctype)
        cur = self.docs[doctype][name]
        cur.update(docstatus=2, modified=self._ts())
        self.calls.append(("cancel", doctype, name))
        return copy.deepcopy(cur)

    def delete(self, doctype, name):
        self._maybe_fail("delete", doctype)
        d = self.docs.get(doctype, {}).get(name)
        if d is None:
            return
        if d.get("docstatus") == 1:
            raise TSRValidationError(f"Cannot delete submitted {doctype} {name}")
        del self.docs[doctype][name]
        self.calls.append(("delete", doctype, name))

    def set_value(self, doctype, name, values):
        self._maybe_fail("set_value", doctype)
        if doctype in self.singles:
            self.singles[doctype].update(values)
            return {"doctype": doctype, "name": doctype, **values}
        cur = self.docs.get(doctype, {}).get(name)
        if cur is None:
            for pdocs in self.docs.values():                  # a child row lives inside its parent
                for p in pdocs.values():
                    for v in p.values():
                        if isinstance(v, list):
                            for r in v:
                                if isinstance(r, dict) and r.get("doctype") == doctype and r.get("name") == name:
                                    r.update(values)
                                    self.calls.append(("set_value", doctype, name))
                                    return copy.deepcopy(r)
            raise TSRNotFound(doctype, name)
        cur.update(values)
        cur["modified"] = self._ts()
        self.calls.append(("set_value", doctype, name))
        return copy.deepcopy(cur)

    def call(self, method, kwargs):
        self.calls.append(("call", method, kwargs))
        return self.call_results.get(method)

    def add_comment(self, doctype, name, text, kind="Comment"):
        self.comments.append((doctype, name, text))

    def user_roles(self, user):
        return []
