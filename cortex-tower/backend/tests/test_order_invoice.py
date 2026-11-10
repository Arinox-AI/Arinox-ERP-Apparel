"""Step 10 of the Order page (order_invoice): invoice, collect, close, on a seeded in-memory ERP with the ERP scripts stubbed.   Run from backend/:  python3 tests/test_order_invoice.py   Synthetic data only."""
import os
import re
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"
os.environ["USER_EMAIL"] = "buy@test.local"
os.environ["USER_NAME"] = "Buyer"
os.environ["USER_IS_ADMIN"] = "1"

from database import get_session, init_db  # noqa: E402
init_db()
import deals  # noqa: E402
import erp  # noqa: E402
import functions  # noqa: E402
import guardrails  # noqa: E402
import order_invoice as I  # noqa: E402
from tsr.fake import FakeBackend  # noqa: E402

erp._base_key = lambda: "https://erp.test:9446"
erp._DESK_PREFIX = ("https://erp.test:9446", "desk")
N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


F = functions.FUNCTIONS
db = get_session()
TODAY = date.today()
iso = lambda n: (TODAY + timedelta(days=n)).isoformat()
CHK = [{"label": "Production finished", "ok": True, "detail": ""}, {"label": "Everything shipped is invoiced", "ok": True, "detail": ""}, {"label": "Customer invoices paid", "ok": False, "detail": "SINV-1"},
       {"label": "No claim open", "ok": True, "detail": ""}, {"label": "Claim windows over", "ok": False, "detail": "SHP-1"}]
I.read_script = lambda me, m, p=None: CHK if m == "arinox_close_get_checklist" else (_ for _ in ()).throw(AssertionError(m))
W = []


def fake_ex(db_, me, req):
    W.append(req)
    m = req.get("method")
    if m in ("arinox_invoicing_submit_invoices", "arinox_buyer_claim_make_credit_note", "arinox_close_commercial_close") and req.get("approval_id") is None and not req.get("preview"):
        return {"ok": False, "needs_approval": True, "approval_id": 5, "error": "A manager must approve this before it runs.", "preview": {"operations": []}}
    if m == "arinox_invoicing_prepare_invoices":
        return {"ok": True, "result": ["SINV-D1"], "preview": {"operations": []}}
    if m == "arinox_invoicing_submit_invoices":
        return {"ok": True, "result": ["SINV-D1"]}
    if m == "arinox_buyer_claim_make_credit_note":
        return {"ok": True, "result": "SINV-CN1"}
    if m == "arinox_followup_log_follow_up":
        return {"ok": True, "result": "Promised"}
    return {"ok": True, "result": True}


deals._ex = fake_ex
be = FakeBackend()
be.seed("Sales Order", "SO-1", docstatus=1, status="To Bill", customer="Acme Apparel Co", company="Demo Co", items=[])
be.seed("Packing List", "PL-1", sales_order="SO-1", docstatus=1, shipment="SHP-1")
be.seed("Shipment", "SHP-1", docstatus=1, apparel_on_board_date=iso(-30), shipment_delivery_note=[{"doctype": "Delivery Note", "delivery_note": "DN-1"}])
be.seed("Delivery Note", "DN-1", docstatus=1)
be.seed("Sales Invoice", "SINV-1", docstatus=1, grand_total=1000, outstanding_amount=600, due_date=iso(-10), apparel_expected_due_date=iso(-10), apparel_all_contracts="SC-1, SC-2", apparel_sales_contract="SC-1",
        apparel_shipment="SHP-1", apparel_commercial_invoice_no="SC-1-INV-01", apparel_route_leg=1, items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-1"}])
be.seed("Sales Invoice", "SINV-2", docstatus=1, grand_total=500, outstanding_amount=0, due_date=iso(-20), apparel_shipment="SHP-1", apparel_sales_contract="SC-1", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-1"}])
be.seed("Sales Invoice", "SINV-3", docstatus=1, grand_total=-100, outstanding_amount=-100, is_return=1, apparel_shipment="SHP-1", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-1"}])
be.seed("Payment Entry", "PE-1", docstatus=1, posting_date=iso(-12), paid_amount=500, references=[{"doctype": "Payment Entry Reference", "reference_name": "SINV-2", "allocated_amount": 500}])
be.seed("Buyer Claim", "BC-1", docstatus=1, sales_contract="SC-1", status="Accepted", claim_type="Quality", claimed_amount=200, accepted_amount=100, settlement="Credit Note", credit_note=None, sales_invoice="SINV-1")
be.seed("Buyer Claim", "BC-2", docstatus=1, sales_contract="SC-1", status="Accepted", accepted_amount=50, settlement="Deduction from Payment", credit_note=None)
deals.BACKEND = be

# 1 · receivable arithmetic (pure)
inv = {"docstatus": 1, "grand_total": 1000, "outstanding_amount": 600, "apparel_expected_due_date": iso(-10), "due_date": iso(5)}
r = I.receivable_row(inv, TODAY)
check("due date: the contract's own beats ERPNext's; days overdue worked out from today", r["due"] == iso(-10) and r["days_overdue"] == 10 and r["state"] == "Overdue", r)
check("not yet due is not overdue", I.receivable_row({**inv, "apparel_expected_due_date": iso(3)}, TODAY)["days_overdue"] == 0 and I.receivable_row({**inv, "apparel_expected_due_date": iso(3)}, TODAY)["state"] == "Partly Paid")
check("paid is zero days and Paid", I.receivable_row({**inv, "outstanding_amount": 0}, TODAY)["days_overdue"] == 0 and I.receivable_row({**inv, "outstanding_amount": 0}, TODAY)["state"] == "Paid")
check("a promise in the future on an overdue invoice", I.receivable_row({**inv, "apparel_promise_date": iso(4)}, TODAY)["state"] == "Promised")
check("a dispute wins over overdue", I.receivable_row({**inv, "apparel_dispute_reason": "short"}, TODAY)["state"] == "Disputed")
check("a draft is a draft and never overdue", I.receivable_row({**inv, "docstatus": 0}, TODAY)["state"] == "Draft" and I.receivable_row({**inv, "docstatus": 0}, TODAY)["days_overdue"] == 0)
check("several contracts on one invoice are listed, not split", I.receivable_row({**inv, "apparel_all_contracts": "A, B, C"}, TODAY)["contracts"] == ["A", "B", "C"] and I.receivable_row({**inv, "apparel_all_contracts": "A, B"}, TODAY)["multi_contract"])
t = I.card_totals([I.receivable_row(inv, TODAY), I.receivable_row({**inv, "grand_total": -100, "outstanding_amount": -100, "is_return": 1}, TODAY)])
check("totals: credit notes reduce what was invoiced, are not counted as owed", t["invoiced"] == 1000 and t["credited"] == 100 and t["outstanding"] == 600 and t["overdue"] == 600 and t["oldest_days"] == 10 and t["count"] == 1, t)
c = I.close_view(CHK)
check("close view: the claim window alone is waivable, a payment gap is hard", c["can_close"] is False and [h["label"] for h in c["hard"]] == ["Customer invoices paid"] and not c["windows_open"])
check("only the window open: waivable", I.close_view([{"label": "Claim windows over", "ok": False}, {"label": "x", "ok": True}])["windows_open"] and I.close_view([{"label": "Claim windows over", "ok": False}])["can_close"])

# 2 · the read
o = F["order_invoice_get"](db=db, sales_order="SO-1")
iv = {i["name"]: i for i in o["invoices"]}
check("read ok; the invoices of the order are found by item and by shipment", o["ok"] and set(iv) == {"SINV-1", "SINV-2", "SINV-3"}, list(iv))
check("receivable card per invoice", iv["SINV-1"]["days_overdue"] == 10 and iv["SINV-1"]["multi_contract"] and iv["SINV-2"]["state"] == "Paid" and iv["SINV-1"]["can_follow_up"] and not iv["SINV-2"]["can_follow_up"], iv["SINV-1"])
check("totals and payment entries", o["totals"]["outstanding"] == 600 and o["totals"]["invoiced"] == 1500 and o["payments"] and o["payments"][0]["invoice"] == "SINV-2", (o["totals"], o["payments"]))
cl = {c["name"]: c for c in o["claims"]}
check("a credit note can be drafted only for an accepted credit-note claim without one", cl["BC-1"]["can_credit_note"] and not cl["BC-2"]["can_credit_note"], cl)
check("shipment: all notes submitted and submitted invoices on it", o["shipments"][0]["can_prepare"] is False and o["shipments"][0]["submitted"] and o["shipments"][0]["dn_submitted"] == 1, o["shipments"])
check("the close checklist is read from the ERP; the order is not closed", len(o["checklist"]) == 5 and o["close"]["can_close"] is False and o["summary"]["closed"] is False and o["summary"]["overdue_invoices"] == 1)
check("no order given", F["order_invoice_get"](db=db, sales_order="")["ok"] is False)
be.seed("Sales Invoice", "SINV-1", docstatus=0, grand_total=1000, outstanding_amount=1000, apparel_shipment="SHP-1", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-1"}])
be.seed("Sales Invoice", "SINV-2", docstatus=0, grand_total=500, outstanding_amount=500, apparel_shipment="SHP-1", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-1"}])
o = F["order_invoice_get"](db=db, sales_order="SO-1")
check("only drafts on a shipment whose notes are in: drafts are listed and can be submitted", o["shipments"][0]["can_submit"] and o["shipments"][0]["drafts"] == ["SINV-1", "SINV-2"], o["shipments"])

# 3 · prepare, submit, follow-up, credit note, close
W.clear()
r = F["order_invoice_prepare"](db=db, shipment="SHP-1")
check("prepare drafts through the pipeline and answers the names", r["ok"] and r["made"] == ["SINV-D1"] and W[-1]["method"] == "arinox_invoicing_prepare_invoices" and W[-1]["params"] == {"shipment": "SHP-1"}, r)
check("prepare needs a shipment", not F["order_invoice_prepare"](db=db, shipment="")["ok"])
r = F["order_invoice_submit"](db=db, shipment="SHP-1")
check("submitting invoices is risky: needs_approval", r.get("needs_approval") and r["approval_id"] == 5, r)
r = F["order_invoice_submit"](db=db, shipment="SHP-1", approval_id=5)
check("with the approval it answers the invoices submitted", r["ok"] and r["made"] == ["SINV-D1"], r)
check("preview of the submit writes nothing real", F["order_invoice_submit"](db=db, shipment="SHP-1", preview=True)["saved"] is False and W[-1]["preview"] is True)
W.clear()
check("follow-up needs an invoice", not F["order_followup_log"](db=db, invoice="", note="x")["ok"])
check("follow-up needs a note", not F["order_followup_log"](db=db, invoice="SINV-1", note="  ")["ok"])
check("a promise in the past refused", not F["order_followup_log"](db=db, invoice="SINV-1", note="called", promise_date=iso(-1), promise_amount=100)["ok"])
check("a promise needs an amount", not F["order_followup_log"](db=db, invoice="SINV-1", note="called", promise_date=iso(3))["ok"])
check("nothing written by the refusals", not W)
r = F["order_followup_log"](db=db, invoice="SINV-1", note="Buyer will pay half", promise_date=iso(3), promise_amount=300, next_action_date=iso(4))
check("follow-up logged with the promise, answers the new status", r["ok"] and r["status"] == "Promised" and W[-1]["params"] == {"invoice": "SINV-1", "note": "Buyer will pay half", "promise_date": iso(3), "promise_amount": 300.0, "next_action_date": iso(4)}, (r, W[-1]))
check("a note alone is enough", F["order_followup_log"](db=db, invoice="SINV-1", note="left a message")["ok"] and W[-1]["params"] == {"invoice": "SINV-1", "note": "left a message"})
r = F["order_claim_credit_note"](db=db, claim="BC-1")
check("credit note is risky: needs_approval", r.get("needs_approval") and W[-1]["params"] == {"claim": "BC-1"}, r)
check("with the approval it answers the note", F["order_claim_credit_note"](db=db, claim="BC-1", approval_id=5)["credit_note"] == "SINV-CN1")
check("a claim is needed", not F["order_claim_credit_note"](db=db, claim="")["ok"])
W.clear()
r = F["order_close"](db=db, sales_order="SO-1")
check("close is refused with the ERP's reasons while a hard row fails; no approval is asked for", not r["ok"] and "Customer invoices paid" in r["error"] and not r.get("needs_approval") and not W, r)
CHK[2].update(ok=True, detail="")
r = F["order_close"](db=db, sales_order="SO-1")
check("an open claim window needs a reason", not r["ok"] and "claim window" in r["error"] and not W, r)
r = F["order_close"](db=db, sales_order="SO-1", waive_reason="buyer confirmed in writing")
check("close is risky: needs_approval", r.get("needs_approval") and W[-1]["params"] == {"sales_order": "SO-1", "waive_reason": "buyer confirmed in writing"}, r)
check("with the approval the order closes", F["order_close"](db=db, sales_order="SO-1", waive_reason="buyer confirmed in writing", approval_id=5)["ok"])
CHK[4].update(ok=True)
check("everything green: no reason needed", F["order_close"](db=db, sales_order="SO-1", preview=True)["ok"])

# 4 · roles and structure
for dt, role, ok in (("Sales Invoice", "Accounts", True), ("Sales Invoice", "Shipping", False), ("Sales Invoice", "Management", True), ("Buyer Claim", "Accounts", True), ("Buyer Claim", "QC", False)):
    try:
        I.need_dt({"roles": [role]}, dt, "x"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} write {dt}", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_invoice.py")).read()
check("the module never writes through a backend directly", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src))
check("no idem_key", "idem_key" not in src)
check("invoice submit, credit note and close are in the risky class", all(guardrails.classify("api", "x", m) == "risky" for m in ("arinox_invoicing_submit_invoices", "arinox_buyer_claim_make_credit_note", "arinox_close_commercial_close")) and guardrails.classify("submit", "Sales Invoice") == "risky")
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
