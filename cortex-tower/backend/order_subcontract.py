"""Order page step 7, Subcontract and finish (ORDER_TO_SHIP_PLAN section 4): the out / back balance per process, short-close, settlement invoices and the
finishing receipt.

Same rules as ``order_cutsew``. The balance is the Production Movement ledger (SC_OUT, SC_BACK_GOOD, SC_BACK_REJECT_VENDOR, SC_BACK_REJECT_FACTORY, per
``subcontract_process``) set against the challans; a short-closed challan's gap is shown as short, never as out. Short-closing and making the vendor's
invoices are risky classes (approval); submitting a challan, return or finishing receipt posts the ledger and is risky too. The ERP's own settlement
script works the amounts out; the tower only presents them.
"""

from __future__ import annotations

from typing import Callable

import deals
import guardrails
import order_flow
from order_cutsew import DEAD, _can, _live_cards, _num, need
from order_samples import _ex, read_script
import deal_api

guarded = deal_api.guarded
OUT = "SC_OUT"
BACK = ("SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY")


def balance_rows(moves: list[dict], challans: list[dict]) -> list[dict]:
    """Out / back per process: `moves` are ledger rows `{subcontract_process, stage, qty}`, `challans` carry `{subcontract_process, status, total_qty, returned_qty}`.
    `short_closed` is what a Short Closed challan will never get back; `balance` is what is still at the vendor (never below zero). Pure arithmetic."""
    procs: dict = {}
    for m in moves:
        p = procs.setdefault(m.get("subcontract_process") or "", {"process": m.get("subcontract_process") or "", "sent": 0.0, "good": 0.0, "reject_vendor": 0.0, "reject_factory": 0.0,
                                                                  "short_closed": 0.0, "challans": 0, "open_challans": 0})
        q = _num(m.get("qty"))
        st = m.get("stage")
        if st == OUT:
            p["sent"] += q
        elif st == "SC_BACK_GOOD":
            p["good"] += q
        elif st == "SC_BACK_REJECT_VENDOR":
            p["reject_vendor"] += q
        elif st == "SC_BACK_REJECT_FACTORY":
            p["reject_factory"] += q
    for c in challans:
        p = procs.setdefault(c.get("subcontract_process") or "", {"process": c.get("subcontract_process") or "", "sent": 0.0, "good": 0.0, "reject_vendor": 0.0, "reject_factory": 0.0,
                                                                  "short_closed": 0.0, "challans": 0, "open_challans": 0})
        p["challans"] += 1
        if c.get("status") == "Short Closed":
            p["short_closed"] += max(_num(c.get("total_qty")) - _num(c.get("returned_qty")), 0.0)
        elif c.get("status") in ("Open", "Partly Returned"):
            p["open_challans"] += 1
    out = []
    for p in sorted(procs.values(), key=lambda x: x["process"]):
        back = p["good"] + p["reject_vendor"] + p["reject_factory"]
        p["back"] = back
        p["balance"] = max(p["sent"] - back - p["short_closed"], 0.0)
        out.append(p)
    return out


@guarded
def order_subcontract_get(db, me, sales_order: str = "", **_):
    """Everything the step-7 page shows for one order: the **out / back balance per process** (wash, print, embroidery: sent, back good, rejected by the vendor,
    rejected by the factory, short-closed, still out), the challans with what can be done next (return, short-close, settlement), the settlements with
    their invoices and the finishing receipts. Read only. Params: `sales_order`. Returns `{ok, head, balance, challans, settlements, finishing, summary, can_write}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Subcontract Challan", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    cards = [c["name"] for c in _live_cards(be, chain) if c.get("status") not in DEAD]
    challans = be.get_list("Subcontract Challan", [["sales_order", "in", chain], ["docstatus", "!=", 2]],
                           ["name", "supplier", "subcontract_process", "challan_date", "expected_return_date", "total_qty", "returned_qty", "status", "docstatus", "short_close_reason", "production_card"], limit=300)
    names = [c["name"] for c in challans]
    rets = be.get_list("Subcontract Return", [["challan", "in", names], ["docstatus", "!=", 2]], ["name", "challan", "docstatus", "return_date", "total_good", "total_reject_vendor", "total_reject_factory"], limit=300) if names else []
    sets = be.get_list("Subcontract Settlement", [["challan", "in", names], ["docstatus", "!=", 2]],
                       ["name", "challan", "docstatus", "sent_qty", "good_qty", "short_qty", "payable_qty", "gross_amount", "penalty_amount", "net_amount", "purchase_invoice", "debit_note", "variance_note"], limit=300) if names else []
    moves = be.get_list("Production Movement", [["production_card", "in", cards], ["stage", "in", [OUT, *BACK]]], ["subcontract_process", "stage", "qty"], limit=20000) if cards else []
    bal = balance_rows(moves, [c for c in challans if int(c.get("docstatus") or 0) == 1])
    fin = be.get_list("Finishing Receipt", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["name", "receipt_date", "docstatus", "source", "total_qty", "supplier", "line"], limit=100)
    sw = {s["challan"]: s for s in sets}
    rw: dict = {}
    for r in rets:
        rw.setdefault(r["challan"], []).append(r)
    for c in challans:
        sub = int(c.get("docstatus") or 0) == 1
        left = max(_num(c.get("total_qty")) - _num(c.get("returned_qty")), 0.0)
        c["left"] = left
        c["returns"] = rw.get(c["name"], [])
        c["settlement"] = sw.get(c["name"])
        c["can_return"] = sub and c.get("status") in ("Open", "Partly Returned")
        c["can_short_close"] = sub and c.get("status") in ("Open", "Partly Returned")
        c["can_settle"] = sub and not sw.get(c["name"]) and (c.get("status") in ("Returned", "Short Closed", "Closed") or _num(c.get("returned_qty")) > 0)
    for s in sets:
        s["can_invoice"] = int(s.get("docstatus") or 0) == 1 and not (s.get("purchase_invoice") and (s.get("debit_note") or not _num(s.get("penalty_amount"))))
    out_now = sum(b["balance"] for b in bal)
    fin_qty = sum(_num(f.get("total_qty")) for f in fin if int(f.get("docstatus") or 0) == 1)
    return {"ok": True, "head": head, "can_write": _can(me), "balance": bal, "challans": challans, "settlements": sets, "finishing": fin, "cards": cards,
            "summary": {"out_now": out_now, "sent": sum(b["sent"] for b in bal), "back": sum(b["back"] for b in bal), "short_closed": sum(b["short_closed"] for b in bal),
                        "finishing_received": fin_qty, "nothing_out": out_now == 0, "finishing_done": fin_qty > 0}}


@guarded
def order_challan_short_close(db, me, name: str = "", reason: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Accept that the rest of a challan will not come back (`arinox_subcontract_challan_short_close`): Production Manager only, a reason is required; the gap
    shows as Short on the settlement. A risky class: `needs_approval` until a manager approves; run it again with the `approval_id`. Params: `name`, `reason`,
    `preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`."""
    need(me, "make", "short-close a challan")
    if not (reason or "").strip():
        return {"ok": False, "error": "Write the reason for short-closing."}
    if not name:
        return {"ok": False, "error": "Say which challan."}
    res = deals._ex(db, me, {"op": "api", "method": "arinox_subcontract_challan_short_close", "doctype": "Subcontract Challan", "preview": bool(preview), "approval_id": approval_id or None,
                             "params": {"challan": name, "reason": reason.strip()}})
    if res.get("needs_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": res.get("approval_id"), "error": res.get("error"), "preview": res.get("preview")}
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the short-close.")), "preview": res.get("preview")}
    return {"ok": True, "name": name, "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_settlement_invoices(db, me, name: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Draft the vendor's Purchase Invoice (and a debit note for the penalty) from a submitted Subcontract Settlement
    (`arinox_subcontract_settlement_make_invoices`). The drafts are not submitted here: Accounts submits them. A risky class: `needs_approval` until a manager
    approves; run it again with the `approval_id`. Params: `name`, `preview`, `approval_id`. Returns `{ok, purchase_invoice, debit_note}`."""
    need(me, "make", "make settlement invoices")
    if not name:
        return {"ok": False, "error": "Say which settlement."}
    res = deals._ex(db, me, {"op": "api", "method": "arinox_subcontract_settlement_make_invoices", "doctype": "Subcontract Settlement", "preview": bool(preview), "approval_id": approval_id or None,
                             "params": {"settlement": name}})
    if res.get("needs_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": res.get("approval_id"), "error": res.get("error"), "preview": res.get("preview")}
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the invoices.")), "preview": res.get("preview")}
    r = res.get("result") if isinstance(res.get("result"), dict) else {}
    return {"ok": True, "name": name, "purchase_invoice": r.get("purchase_invoice"), "debit_note": r.get("debit_note"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_prefill_sub(db, me, sales_order: str = "", kind: str = "", challan: str = "", card: str = "", **_):
    """Pre-filled starting values of a subcontract or finishing document for the generic form: `kind` is `challan` (rows = what was sewn and not yet sent), `return`
    (against `challan`: one row per challan row with what is still out), `settlement` (against `challan`) or `finishing` (rows = what is sewn or back, not yet
    received). Read only. Params: `sales_order`, `kind`, `challan`, `card`. Returns `{ok, doctype, initial, note}`."""
    need(me, "make", "make a subcontract document")
    import datetime as _dt
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    today = _dt.date.today().isoformat()
    cards = [c for c in _live_cards(be, chain) if int(c.get("docstatus") or 0) == 1 and c.get("status") not in DEAD]
    c = next((x for x in cards if x["name"] == card), None) if card else (cards[0] if cards else None)
    if kind in ("return", "settlement"):
        if not challan:
            return {"ok": False, "error": "Say which challan."}
        ch = be.get_doc("Subcontract Challan", challan)
        if int(ch.get("docstatus") or 0) != 1:
            return {"ok": False, "error": f"Challan {challan} is not submitted."}
        if kind == "settlement":
            return {"ok": True, "doctype": "Subcontract Settlement", "note": "The amounts are worked out by the ERP when you save; enter the rate and the vendor's invoice reference.",
                    "initial": {"challan": challan, "production_card": ch.get("production_card"), "supplier": ch.get("supplier"), "subcontract_process": ch.get("subcontract_process"), "settlement_date": today}}
        rows = []
        for r in ch.get("rows") or []:
            left = _num(r.get("qty")) - _num(r.get("returned_qty"))
            if left > 0:
                rows.append({"production_card": ch.get("production_card"), "challan_row": r.get("name"), "colour": r.get("colour"), "size": r.get("size"), "sent_qty": int(_num(r.get("qty"))),
                             "good_qty": int(left), "reject_vendor_qty": 0, "reject_factory_qty": 0})
        if not rows:
            return {"ok": False, "error": "Everything on this challan has already come back."}
        return {"ok": True, "doctype": "Subcontract Return", "note": "Good quantities are what is still out; change them to what came back and add any rejects.",
                "initial": {"challan": challan, "production_card": ch.get("production_card"), "supplier": ch.get("supplier"), "subcontract_process": ch.get("subcontract_process"), "return_date": today, "rows": rows}}
    if not c:
        return {"ok": False, "error": "Issue a production card first."}
    s = read_script(me, "arinox_production_card_get_summary", {"name": c["name"]}) or {}
    if kind == "challan":
        rows = [{"colour": r["colour"], "size": r["size"], "qty": int(_num(r.get("SEW_OUT")) - _num(r.get("SC_OUT")))} for r in s.get("rows") or [] if _num(r.get("SEW_OUT")) - _num(r.get("SC_OUT")) > 0]
        if not rows:
            return {"ok": False, "error": "Nothing is sewn and waiting to be sent."}
        return {"ok": True, "doctype": "Subcontract Challan", "note": "Choose the supplier and the process; the quantities are what is sewn and not yet sent.",
                "initial": {"production_card": c["name"], "sales_order": head, "challan_date": today, "rows": rows}}
    if kind == "finishing":
        # the ERP caps FIN_IN at what the previous step of the route released: the vendor's good pieces when an after-sewing process is on the route, else what was sewn
        route = be.get_doc("Production Card", c["name"]).get("processes") or []
        after = any((p.get("position") or "") == "After Sewing" for p in route)
        rows = []
        for r in s.get("rows") or []:
            have = (_num(r.get("SC_BACK_GOOD")) if after else _num(r.get("SEW_OUT"))) - _num(r.get("FIN_IN"))
            if have > 0:
                rows.append({"colour": r["colour"], "size": r["size"], "qty": int(have)})
        if not rows:
            return {"ok": False, "error": "Nothing is waiting for finishing."}
        return {"ok": True, "doctype": "Finishing Receipt", "note": "Quantities are what the previous step released (back from the vendor, or sewn) and not yet received in finishing; change them to what arrived.",
                "initial": {"production_card": c["name"], "sales_order": head, "receipt_date": today, "source": "Subcontract Return" if after else "Sewing", "line": c.get("line") or "", "rows": rows,
                            **({"supplier": next((p.get("supplier") for p in route if (p.get("position") or "") == "After Sewing" and p.get("supplier")), "")} if after else {})}}
    return {"ok": False, "error": "kind is challan, return, settlement or finishing"}


FUNCTIONS: dict[str, Callable] = {"order_subcontract_get": order_subcontract_get, "order_challan_short_close": order_challan_short_close,
                                  "order_settlement_invoices": order_settlement_invoices, "order_prefill_sub": order_prefill_sub}
