"""Order page step 10, Invoice, collect and close (ORDER_TO_SHIP_PLAN section 4): prepare and submit the commercial invoices of a shipment, the payment follow-up
log, the receivable card, the buyer claim's credit note and the commercial close.

Same rules as the other steps. The ERP's scripts decide: one invoice per contract per shipment (an invoice that covers several contracts keeps the first as its
link and lists them all: the tower shows that list and never splits it), group billing legs, the due date from the contract's payment basis, the follow-up
status. Submitting invoices, drafting a credit note and closing the order are risky classes (approval).
"""

from __future__ import annotations

import datetime as _dt
from typing import Callable

import deals
import guardrails
import order_flow
from order_cutsew import _num
from order_pack import need_dt
from order_samples import read_script
from order_ship import _risky
import deal_api

guarded = deal_api.guarded
INV_FIELDS = ["name", "docstatus", "status", "posting_date", "due_date", "currency", "grand_total", "outstanding_amount", "is_return", "return_against", "customer",
              "apparel_expected_due_date", "apparel_followup_status", "apparel_days_overdue", "apparel_promise_date", "apparel_promise_amount", "apparel_next_action_date",
              "apparel_dispute_reason", "apparel_all_contracts", "apparel_commercial_invoice_no", "apparel_shipment", "apparel_route_leg", "apparel_sales_contract"]


def _d(v):
    try:
        return _dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def receivable_row(inv: dict, today: _dt.date) -> dict:
    """One invoice as the receivable card shows it: the due date (the contract's own, else ERPNext's), days overdue worked out from today (never negative; zero
    once paid), what is outstanding and the state. Pure."""
    due = _d(inv.get("apparel_expected_due_date")) or _d(inv.get("due_date"))
    out = _num(inv.get("outstanding_amount"))
    sub = int(inv.get("docstatus") or 0) == 1
    overdue = max((today - due).days, 0) if (due and out > 0.005 and sub) else 0
    promise = _d(inv.get("apparel_promise_date"))
    if not sub:
        state = "Draft"
    elif out <= 0.005:
        state = "Paid"
    elif inv.get("apparel_dispute_reason"):
        state = "Disputed"
    elif overdue and promise and promise >= today:
        state = "Promised"
    elif overdue:
        state = "Overdue"
    elif out < _num(inv.get("grand_total")) - 0.005:
        state = "Partly Paid"
    elif due and 0 <= (due - today).days <= 7:
        state = "Due Soon"
    else:
        state = "Not Due"
    contracts = [c.strip() for c in str(inv.get("apparel_all_contracts") or "").split(",") if c.strip()]
    return {**inv, "due": due.isoformat() if due else "", "days_overdue": overdue, "outstanding": out, "state": state, "contracts": contracts, "multi_contract": len(contracts) > 1,
            "can_follow_up": sub and out > 0.005 and not inv.get("is_return")}


def card_totals(rows: list[dict]) -> dict:
    """Totals of the receivable card over submitted, non-return invoices (credit notes reduce what is owed): invoiced, outstanding, overdue and the oldest overdue days."""
    live = [r for r in rows if int(r.get("docstatus") or 0) == 1]
    inv = [r for r in live if not r.get("is_return")]
    cn = [r for r in live if r.get("is_return")]
    return {"invoiced": sum(_num(r.get("grand_total")) for r in inv), "credited": -sum(_num(r.get("grand_total")) for r in cn),
            "outstanding": sum(r["outstanding"] for r in inv), "overdue": sum(r["outstanding"] for r in inv if r["days_overdue"] > 0),
            "oldest_days": max([r["days_overdue"] for r in inv] or [0]), "paid": all(r["outstanding"] <= 0.005 for r in inv) and bool(inv), "count": len(inv)}


def close_view(checklist: list[dict]) -> dict:
    """The close checklist: each row `{label, ok, detail}`; `hard` are the rows that block (every row but the claim windows), `windows_open` says only the waivable one fails."""
    failed = [r for r in checklist if not r.get("ok")]
    hard = [r for r in failed if r.get("label") != "Claim windows over"]
    return {"rows": checklist, "all_ok": not failed, "hard": hard, "windows_open": bool(failed) and not hard, "can_close": not hard}


@guarded
def order_invoice_get(db, me, sales_order: str = "", **_):
    """Everything the step-10 page shows for one order: the **receivable card** (each customer invoice with due date, days overdue, outstanding, state, the buyer's
    promise, the next action, and the contracts it covers), its totals, the payment entries, the follow-up log (the notes), the shipments that can be invoiced (with
    their draft and submitted invoices), the buyer claims, and the **close checklist** from the ERP. Read only. Params: `sales_order`.
    Returns `{ok, head, invoices, totals, payments, claims, shipments, checklist, close, summary, can_write, can_close}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Sales Invoice", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    today = _dt.date.today()
    pls = be.get_list("Packing List", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["shipment"], limit=300)
    ships = sorted({p["shipment"] for p in pls if p.get("shipment")})
    names: list = []
    for c in be.get_list("Sales Invoice Item", [["sales_order", "in", chain]], ["parent"], limit=2000, parent="Sales Invoice"):
        if c.get("parent") and c["parent"] not in names:
            names.append(c["parent"])
    if ships:
        for r in be.get_list("Sales Invoice", [["apparel_shipment", "in", ships], ["docstatus", "!=", 2]], ["name"], limit=500):
            if r["name"] not in names:
                names.append(r["name"])
    if names:                                               # a credit note (a return) carries no order line of its own: it is found through the invoice it credits
        for r in be.get_list("Sales Invoice", [["return_against", "in", list(names)], ["docstatus", "!=", 2]], ["name"], limit=500):
            if r["name"] not in names:
                names.append(r["name"])
    invs = be.get_list("Sales Invoice", [["name", "in", names], ["docstatus", "!=", 2]], INV_FIELDS, limit=500) if names else []
    rows = sorted((receivable_row(i, today) for i in invs), key=lambda r: (r.get("apparel_shipment") or "", r.get("apparel_commercial_invoice_no") or "", r.get("apparel_route_leg") or 0, r["name"]))
    # the follow-up log: the notes written on each invoice (a comment each), newest first
    for r in rows:
        r["log"] = []
        if int(r.get("docstatus") or 0) == 1:
            try:
                import re
                for c in be.get_list("Comment", [["reference_doctype", "=", "Sales Invoice"], ["reference_name", "=", r["name"]], ["comment_type", "=", "Comment"]], ["content", "creation", "owner"], order_by="creation desc", limit=16):
                    text = re.sub(r"<[^>]+>", " ", str(c.get("content") or "")).strip()[:300]
                    if not text.startswith("Cortex Tower:"):          # the tower's own audit line is not a follow-up note
                        r["log"].append({"at": str(c.get("creation") or "")[:16], "by": c.get("owner") or "", "text": text})
                r["log"] = r["log"][:8]
            except Exception:                               # noqa: BLE001 - the log is a courtesy
                pass
    pes: list = []
    if names:
        for c in be.get_list("Payment Entry Reference", [["reference_name", "in", names]], ["parent", "reference_name", "allocated_amount"], limit=2000, parent="Payment Entry"):
            pes.append(c)
    pay = []
    for p in pes:
        h = (be.get_list("Payment Entry", [["name", "=", p["parent"]]], ["name", "posting_date", "docstatus", "paid_amount"], limit=1) or [{}])[0]
        if int(h.get("docstatus") or 0) != 2:
            pay.append({"name": p["parent"], "invoice": p.get("reference_name"), "allocated": _num(p.get("allocated_amount")), "date": str(h.get("posting_date") or "")[:10], "docstatus": int(h.get("docstatus") or 0)})
    contracts = sorted({c for r in rows for c in (r["contracts"] or [r.get("apparel_sales_contract")]) if c})
    cfields = ["name", "docstatus", "status", "claim_type", "claimed_amount", "accepted_amount", "settlement", "credit_note", "sales_invoice", "reported_on"]
    claims = be.get_list("Buyer Claim", [["sales_contract", "in", contracts], ["docstatus", "!=", 2]], cfields, limit=100) if contracts else []
    for c in (be.get_list("Buyer Claim", [["sales_invoice", "in", names], ["docstatus", "!=", 2]], cfields, limit=100) if names else []):    # an order with no contract is found by its invoices
        if c["name"] not in {x["name"] for x in claims}:
            claims.append(c)
    for c in claims:
        c["can_credit_note"] = int(c.get("docstatus") or 0) == 1 and c.get("settlement") == "Credit Note" and _num(c.get("accepted_amount")) > 0 and not c.get("credit_note")
    # shipments that can be invoiced: every delivery note submitted
    ship_rows = []
    by_ship: dict = {}
    for r in rows:
        by_ship.setdefault(r.get("apparel_shipment"), []).append(r)
    for s in ships:
        doc = be.get_doc("Shipment", s)
        dns = [x.get("delivery_note") for x in (doc.get("shipment_delivery_note") or []) if x.get("delivery_note")]
        dn_rows = be.get_list("Delivery Note", [["name", "in", dns]], ["name", "docstatus"], limit=100) if dns else []
        sub = [d for d in dn_rows if int(d.get("docstatus") or 0) == 1]
        mine = by_ship.get(s, [])
        drafts = [r for r in mine if int(r.get("docstatus") or 0) == 0]
        done = [r for r in mine if int(r.get("docstatus") or 0) == 1]
        ship_rows.append({"name": s, "delivery_notes": len(dn_rows), "dn_submitted": len(sub), "on_board_date": str(doc.get("apparel_on_board_date") or "")[:10], "drafts": [r["name"] for r in drafts],
                          "submitted": [r["name"] for r in done], "can_prepare": bool(dn_rows) and len(sub) == len(dn_rows) and not done and int(doc.get("docstatus") or 0) != 2,
                          "can_submit": bool(drafts)})
    try:
        chk = read_script(me, "arinox_close_get_checklist", {"sales_order": head}) or []
        chk = [{"label": r.get("label"), "ok": bool(r.get("ok")), "detail": r.get("detail") or ""} for r in chk]
    except Exception as e:                                  # noqa: BLE001
        chk = []
        chk_err = deals._strip_html(str(getattr(e, "message", None) or e))[:200]
    else:
        chk_err = ""
    totals = card_totals(rows)
    so = (be.get_list("Sales Order", [["name", "=", head]], ["status"], limit=1) or [{}])[0]
    close = close_view(chk)
    return {"ok": True, "head": head, "invoices": rows, "totals": totals, "payments": pay, "claims": claims, "shipments": ship_rows, "checklist": chk, "checklist_error": chk_err, "close": close,
            "can_write": guardrails.can(me["roles"], "Sales Invoice", "write"), "can_close": guardrails.can(me["roles"], "Sales Invoice", "write"),
            "summary": {"closed": so.get("status") == "Closed", "order_status": so.get("status") or "", "overdue_invoices": sum(1 for r in rows if r["days_overdue"] > 0 and not r.get("is_return")),
                        "invoices_submitted": totals["count"]}}


@guarded
def order_invoice_prepare(db, me, shipment: str = "", preview: bool = False, **_):
    """Draft the commercial invoices of a shipment whose delivery notes are all submitted (`arinox_invoicing_prepare_invoices`): one per contract per shipment
    (an invoice may list several contracts), a group customer gets two legs. Re-running replaces the drafts and keeps their numbers; submitted invoices are left alone.
    Drafts are not posted. Params: `shipment`, `preview`. Returns `{ok, made:[names]}`."""
    need_dt(me, "Sales Invoice", "prepare invoices")
    if not shipment:
        return {"ok": False, "error": "Say which shipment."}
    res = _risky(deals._ex(db, me, {"op": "api", "method": "arinox_invoicing_prepare_invoices", "doctype": "Shipment", "preview": bool(preview), "params": {"shipment": shipment}}), "the invoices")
    if not res.get("ok"):
        return res
    r = res.get("result")
    made = [x for x in (r if isinstance(r, list) else [r] if r else []) if isinstance(x, str)]
    return {"ok": True, "name": shipment, "made": made, "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_invoice_submit(db, me, shipment: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Submit the draft invoices of a shipment, the factory's leg first (`arinox_invoicing_submit_invoices`). Posts the ledger: a risky class, `needs_approval`
    until a manager approves; run it again with the `approval_id`. A contract that counts payment from the bill of lading needs the on-board date first (the ERP
    refuses otherwise). Params: `shipment`, `preview`, `approval_id`. Returns `{ok, made:[names]}` or `{ok: false, needs_approval: true, approval_id}`."""
    need_dt(me, "Sales Invoice", "submit invoices")
    if not shipment:
        return {"ok": False, "error": "Say which shipment."}
    res = _risky(deals._ex(db, me, {"op": "api", "method": "arinox_invoicing_submit_invoices", "doctype": "Shipment", "preview": bool(preview), "approval_id": approval_id or None,
                                    "params": {"shipment": shipment}}), "the invoices")
    if not res.get("ok"):
        return res
    r = res.get("result")
    made = [x for x in (r if isinstance(r, list) else [r] if r else []) if isinstance(x, str)]
    return {"ok": True, "name": shipment, "made": made, "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_followup_log(db, me, invoice: str = "", note: str = "", promise_date: str = "", promise_amount: float = 0, next_action_date: str = "", dispute_reason: str | None = None,
                       preview: bool = False, **_):
    """Log a call or a promise on a customer invoice (`arinox_followup_log_follow_up`): the note becomes a comment, the promised date and amount and the next action
    are fields, the follow-up status is recomputed. The note is required; a promise needs a future date and an amount no larger than what is owed. Params: `invoice`,
    `note`, `promise_date`, `promise_amount`, `next_action_date`, `dispute_reason` (empty string clears a dispute), `preview`. Returns `{ok, name, status}`."""
    need_dt(me, "Sales Invoice", "log a follow-up")
    if not invoice:
        return {"ok": False, "error": "Say which invoice."}
    if not (note or "").strip():
        return {"ok": False, "error": "Write what was said or agreed."}
    if promise_date and _d(promise_date) and _d(promise_date) < _dt.date.today():
        return {"ok": False, "error": "The promised date is in the past. Log the new date the buyer gave."}
    if promise_date and _num(promise_amount) <= 0:
        return {"ok": False, "error": "Enter the amount the buyer promised to pay."}
    p = {"invoice": invoice, "note": note.strip()}
    if promise_date:
        p.update(promise_date=promise_date, promise_amount=_num(promise_amount))
    if next_action_date:
        p["next_action_date"] = next_action_date
    if dispute_reason is not None:
        p["dispute_reason"] = dispute_reason
    res = deals._ex(db, me, {"op": "api", "method": "arinox_followup_log_follow_up", "doctype": "Sales Invoice", "name": invoice, "preview": bool(preview), "params": p})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the follow-up.")), "preview": res.get("preview")}
    return {"ok": True, "name": invoice, "status": res.get("result"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_claim_credit_note(db, me, claim: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Draft the credit note of an accepted buyer claim against the customer invoice (`arinox_buyer_claim_make_credit_note`): only a submitted claim settled by
    credit note with an accepted amount; it answers the existing note if there is one. The accountant submits the note. A risky class: `needs_approval` until a
    manager approves. Params: `claim`, `preview`, `approval_id`. Returns `{ok, name, credit_note}`."""
    need_dt(me, "Buyer Claim", "make a credit note")
    if not claim:
        return {"ok": False, "error": "Say which claim."}
    res = _risky(deals._ex(db, me, {"op": "api", "method": "arinox_buyer_claim_make_credit_note", "doctype": "Buyer Claim", "name": claim, "preview": bool(preview), "approval_id": approval_id or None,
                                    "params": {"claim": claim}}), "the credit note")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": claim, "credit_note": res.get("result"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_close(db, me, sales_order: str = "", waive_reason: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Close the order commercially (`arinox_close_commercial_close`): production finished, everything shipped invoiced, every customer invoice paid, no claim open.
    Only the claim windows may be waived, with a reason. An accounts or merchandising manager only; sets the Sales Order to Closed: a risky class, `needs_approval`
    until a manager approves. The checklist is read first, so a blocked close says why before an approval is asked for. Params: `sales_order`, `waive_reason`,
    `preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, error | needs_approval}`."""
    need_dt(me, "Sales Invoice", "close an order")
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    be = deals._be()
    _chain, head = order_flow._sales_order_chain(be, str(sales_order))
    try:
        chk = [{"label": r.get("label"), "ok": bool(r.get("ok")), "detail": r.get("detail") or ""} for r in (read_script(me, "arinox_close_get_checklist", {"sales_order": head}) or [])]
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": deals._strip_html(str(getattr(e, "message", None) or e))[:300]}
    v = close_view(chk)
    if v["hard"]:
        return {"ok": False, "error": "The order cannot be closed yet: " + "; ".join(f"{r['label']}{(' (' + r['detail'] + ')') if r['detail'] else ''}" for r in v["hard"]) + "."}
    if v["windows_open"] and not (waive_reason or "").strip():
        return {"ok": False, "error": "A claim window is still open. Write why the order may close anyway."}
    res = _risky(deals._ex(db, me, {"op": "api", "method": "arinox_close_commercial_close", "doctype": "Sales Order", "name": head, "preview": bool(preview), "approval_id": approval_id or None,
                                    "params": {"sales_order": head, "waive_reason": (waive_reason or "").strip()}}), "the close")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": head, "preview": res.get("preview") if preview else None, "saved": not preview}


FUNCTIONS: dict[str, Callable] = {"order_invoice_get": order_invoice_get, "order_invoice_prepare": order_invoice_prepare, "order_invoice_submit": order_invoice_submit,
                                  "order_followup_log": order_followup_log, "order_claim_credit_note": order_claim_credit_note, "order_close": order_close}
