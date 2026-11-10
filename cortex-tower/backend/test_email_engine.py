"""Regression tests for the Cortex Control Tower email engine.

Dependency-free: run with ``python3 test_email_engine.py`` from the ``backend``
directory (exit code 0 = all pass). These are the guardrail tests that the
adversarial review produced — keep them green before any send path is wired.

Covers: ERP-down block, empty-facts block, ambiguous-party block, mixed-currency
block, outstanding-vs-grand_total correctness, conditional overdue wording, intent
mapping, grounding enforcement, and the no-internal-branding rule.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import email_engine as E  # noqa: E402

_FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        _FAILURES.append(name)


def facts(**over):
    base = {
        "sos": [], "invoices": [], "draft_mrs": [], "mrs": [], "shipments": [],
        "variances": [], "nonzero_var": [], "quality": [], "not_extracted": [],
        "fails": [], "open_gaps": [], "gaps": [], "work_orders": [],
        "order_book": 0.0, "si_total": 0.0, "earliest_delivery": None,
        "latest_delivery": None, "customers": [], "companies": [],
        "purchase_orders": [], "bom_total": 0, "variants_total": 0,
        "coverage_pct": 0, "delivery_notes": 0, "payment_entries": 0,
        "item_prices": 0, "fabric_rolls": 0,
    }
    base.update(over)
    return base


def one_order(customer="Bella Dahl", **over):
    so = {"name": "SAL-ORD-2026-00001", "customer": customer, "po_no": "69785",
          "grand_total": 1000.0, "currency": "USD", "delivery_date": "2026-02-01",
          "items": [{"qty": 50}]}
    so.update(over)
    return facts(sos=[so], customers=[customer],
                 companies=["CORTEX FASHION (HK) LIMITED"],
                 order_book=so["grand_total"], earliest_delivery="2026-02-01",
                 latest_delivery="2026-02-01")


DELIVERY = "Email the buyer (Bella Dahl) with the delivery plan for the orders"
STATEMENT = "Email the buyer (Bella Dahl) a receivables statement"
RFQ = "Email the trim suppliers for quotation against the requisitions"


print("guardrails")
g = E.generate_email(one_order(), {"risk_type": "shipment_risk"}, DELIVERY, live=False)
check("ERP down blocks",
      bool(g.get("blocked")) and g["blocked"]["code"] == "erp_unavailable")

g = E.generate_email(facts(), {"risk_type": "shipment_risk"}, DELIVERY, live=True)
check("empty facts blocks", bool(g.get("blocked")), str(g.get("blocked")))

two = facts(sos=[
    {"name": "SO-1", "customer": "Bella Dahl", "grand_total": 100.0, "currency": "USD",
     "delivery_date": "2026-02-01", "items": [{"qty": 1}]},
    {"name": "SO-2", "customer": "Acme Retail", "grand_total": 999.0, "currency": "USD",
     "delivery_date": "2026-02-01", "items": [{"qty": 1}]}],
    customers=["Acme Retail", "Bella Dahl"], companies=["CORTEX FASHION (HK) LIMITED"],
    order_book=1099.0, earliest_delivery="2026-02-01", latest_delivery="2026-02-01")
g = E.generate_email(two, {"risk_type": "shipment_risk"},
                    "Email the buyer with the delivery plan for all open orders", live=True)
check("two buyers blocks when unnamed",
      bool(g.get("blocked")) and g["blocked"]["code"] == "ambiguous_buyer",
      str(g.get("blocked")))

mixed = facts(
    invoices=[{"name": "I-1", "grand_total": 1000.0, "outstanding_amount": 1000.0,
               "customer": "Bella Dahl", "currency": "USD", "posting_date": "2026-01-01", "status": "Overdue"},
              {"name": "I-2", "grand_total": 8000.0, "outstanding_amount": 8000.0,
               "customer": "Bella Dahl", "currency": "HKD", "posting_date": "2026-01-02", "status": "Overdue"}],
    customers=["Bella Dahl"], companies=["CORTEX FASHION (HK) LIMITED"])
g = E.generate_email(mixed, {"risk_type": "invoicing_risk"}, STATEMENT, live=True)
check("mixed currency blocks",
      bool(g.get("blocked")) and g["blocked"]["code"] == "mixed_currency",
      str(g.get("blocked")))


print("receivables correctness (the D2 defect)")
partly = facts(
    invoices=[{"name": "ACC-SINV-2026-00001", "grand_total": 100000.0,
               "outstanding_amount": 10000.0, "customer": "Bella Dahl", "currency": "USD",
               "posting_date": "2026-01-10", "status": "Partly Paid"}],
    customers=["Bella Dahl"], companies=["CORTEX FASHION (HK) LIMITED"])
g = E.generate_email(partly, {"risk_type": "invoicing_risk"}, STATEMENT, live=True)
body = (g.get("email") or {}).get("body", "")
check("total uses outstanding_amount", "Total outstanding: USD 10,000.00" in body, body[:200])
check("does not claim overdue when not overdue",
      "shown as overdue" not in body and "are overdue" not in body)
check("paid invoices excluded", "Outstanding invoices: 1" in body)

od = facts(
    invoices=[{"name": "ACC-SINV-2026-00001", "grand_total": 5000.0,
               "outstanding_amount": 5000.0, "customer": "Bella Dahl", "currency": "USD",
               "posting_date": "2026-01-10", "status": "Overdue"}],
    customers=["Bella Dahl"], companies=["CORTEX FASHION (HK) LIMITED"])
g = E.generate_email(od, {"risk_type": "invoicing_risk"}, STATEMENT, live=True)
check("overdue wording only when status is Overdue",
      "shown as overdue" in (g.get("email") or {}).get("body", ""))


print("intent mapping")
cases = [
    (DELIVERY, {"risk_type": "shipment_risk"}, E.INTENT_DELIVERY),
    (STATEMENT, {"risk_type": "invoicing_risk"}, E.INTENT_STATEMENT),
    (RFQ, {"risk_type": "fabric_shortage"}, E.INTENT_RFQ),
    ("Ask Cortex for machine-readable test rows for the packs", {"risk_type": "quality_risk"}, E.INTENT_DATA),
    ("Request the per-size BOM consumption from Cortex", {"risk_type": "production_delay"}, E.INTENT_DATA),
    ("Ask Cortex for the evidence behind the open migration data gaps", {"risk_type": "data_quality"}, E.INTENT_DATA),
    ("Ask Cortex to approve the over-shipment tolerance", {"risk_type": "shipment_risk"}, E.INTENT_APPROVAL),
]
for action, risk, want in cases:
    check(f"intent <- {action[:38]}...", E.detect_intent(facts(), risk, action) == want,
          E.detect_intent(facts(), risk, action))


print("grounding + branding")
bad = {"subject": "Statement", "body": "Your total is USD 999,999.99 as at 2026-01-01."}
chk = E.validate_grounding(bad, E.build_fact_sheet(
    facts(), {"risk_type": "invoicing_risk"}, STATEMENT, E.INTENT_STATEMENT,
    {"kind": "internal", "display": "Cortex", "candidates": []}))
check("validator rejects an unsourced number", chk["ok"] is False and chk["unsourced"])

for action, risk, f in [(DELIVERY, {"risk_type": "shipment_risk"}, one_order()),
                        (STATEMENT, {"risk_type": "invoicing_risk"}, partly)]:
    g = E.generate_email(f, risk, action, live=True)
    txt = (g.get("email") or {}).get("body", "") + (g.get("email") or {}).get("subject", "")
    check(f"no internal branding ({E.detect_intent(f, risk, action)})",
          "KOGO" not in txt and "Control Tower" not in txt)


print("party confidence")
g = E.generate_email(
    facts(sos=[{"name": "SO-1", "customer": "Bella Dahl", "grand_total": 1.0,
                "currency": "USD", "delivery_date": "2026-02-01", "items": [{"qty": 1}]}],
          customers=["Bella Dahl"], companies=["CORTEX FASHION (HK) LIMITED"],
          purchase_orders=[{"supplier": "Acme Trim Co"}],
          draft_mrs=[{"name": "MAT-MR-2026-00001", "custom_trim_requisition": "TR-1",
                      "schedule_date": "2026-02-01"}]),
    {"risk_type": "fabric_shortage"}, RFQ, live=True)
check("single-source supplier flagged unconfirmed",
      g.get("party_status") == "unconfirmed", str(g.get("party_status")))


print()
if _FAILURES:
    print(f"FAILED: {len(_FAILURES)} -> {_FAILURES}")
    sys.exit(1)
print("ALL PASS")
