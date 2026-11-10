"""Step 7 of the Order page (order_subcontract), on a seeded in-memory ERP with the ERP scripts stubbed.   Run from backend/:  python3 tests/test_order_materials.py   Synthetic data only."""
import json
import os
import re
import sys
import tempfile
from datetime import date

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
import order_cutsew as M  # noqa: E402
import order_subcontract as SC  # noqa: E402
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
W = []
SUMMARY = [{"colour": "Navy", "size": "M", "order_qty": 600, "SEW_OUT": 100, "SC_OUT": 0, "SC_BACK_GOOD": 0, "FIN_IN": 0}]


def fake_read(me, method, params=None):
    if method == "arinox_production_card_get_summary":
        return {"card": "PC-1", "rows": SUMMARY}
    raise AssertionError(method)


def fake_ex(db_, me, req):
    W.append(req)
    if req.get("method") in ("arinox_subcontract_challan_short_close", "arinox_subcontract_settlement_make_invoices") and req.get("approval_id") is None and not req.get("preview"):
        return {"ok": False, "needs_approval": True, "approval_id": 4, "error": "A manager must approve this before it runs.", "preview": {"operations": []}}
    if req.get("method") == "arinox_subcontract_settlement_make_invoices":
        return {"ok": True, "result": {"purchase_invoice": "PINV-1", "debit_note": "PINV-2"}, "preview": {"operations": []}}
    return {"ok": True, "result": "Short Closed", "preview": {"operations": []}}


SC.read_script = fake_read
deals._ex = fake_ex

TODAY = date.today().isoformat()
be = FakeBackend()
be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", company="Demo Co", items=[])
be.seed("Production Card", "PC-1", sales_order="SO-1", docstatus=1, status="In Sewing", style_item="ST1", style_no="ST1", line="Line 1",
        processes=[{"doctype": "Production Card Process", "subcontract_process": "Wash", "position": "After Sewing", "supplier": "Wash House"}])
be.seed("Subcontract Challan", "SC-1", sales_order="SO-1", production_card="PC-1", docstatus=1, status="Partly Returned", subcontract_process="Wash", supplier="Wash House", total_qty=60, returned_qty=54,
        rows=[{"doctype": "Subcontract Challan Row", "name": "R1", "colour": "Navy", "size": "M", "qty": 60, "returned_qty": 54}])
be.seed("Subcontract Challan", "SC-2", sales_order="SO-1", production_card="PC-1", docstatus=1, status="Short Closed", subcontract_process="Print", supplier="Print House", total_qty=50, returned_qty=40)
be.seed("Subcontract Challan", "SC-3", sales_order="SO-1", production_card="PC-1", docstatus=0, status="Open", subcontract_process="Print", supplier="Print House", total_qty=10, returned_qty=0)
be.seed("Subcontract Return", "SR-1", challan="SC-1", docstatus=1, total_good=48)
be.seed("Subcontract Settlement", "SS-2", challan="SC-2", docstatus=1, sent_qty=50, good_qty=40, short_qty=10, payable_qty=40, penalty_amount=0, purchase_invoice=None)
for i, (proc, stage, q) in enumerate([("Wash", "SC_OUT", 60), ("Wash", "SC_BACK_GOOD", 48), ("Wash", "SC_BACK_REJECT_VENDOR", 6), ("Print", "SC_OUT", 50), ("Print", "SC_BACK_GOOD", 40), ("", "SEW_OUT", 99)]):
    be.seed("Production Movement", f"PM-{i}", production_card="PC-1", stage=stage, qty=q, subcontract_process=proc, docstatus=0)
be.seed("Finishing Receipt", "FIN-1", sales_order="SO-1", docstatus=1, receipt_date=TODAY, source="Subcontract Return", total_qty=48)
deals.BACKEND = be

# 1 · balance arithmetic
moves = [{"subcontract_process": "Wash", "stage": "SC_OUT", "qty": 60}, {"subcontract_process": "Wash", "stage": "SC_BACK_GOOD", "qty": 48}, {"subcontract_process": "Wash", "stage": "SC_BACK_REJECT_VENDOR", "qty": 6},
         {"subcontract_process": "Wash", "stage": "SC_BACK_REJECT_FACTORY", "qty": 2}]
b = SC.balance_rows(moves, [{"subcontract_process": "Wash", "status": "Partly Returned", "total_qty": 60, "returned_qty": 56}])[0]
check("sent, back (good + both rejects) and still out", b["sent"] == 60 and b["back"] == 56 and b["balance"] == 4 and b["open_challans"] == 1, b)
b = SC.balance_rows(moves, [{"subcontract_process": "Wash", "status": "Short Closed", "total_qty": 60, "returned_qty": 56}])[0]
check("a short-closed challan's gap is short, not out", b["short_closed"] == 4 and b["balance"] == 0 and b["open_challans"] == 0, b)
b = SC.balance_rows([{"subcontract_process": "Wash", "stage": "SC_OUT", "qty": 10}, {"subcontract_process": "Wash", "stage": "SC_BACK_GOOD", "qty": 12}], [])[0]
check("the balance never goes below zero", b["balance"] == 0, b)
check("no movement, no challan: no rows", SC.balance_rows([], []) == [])

# 2 · the read
o = F["order_subcontract_get"](db=db, sales_order="SO-1")
bal = {x["process"]: x for x in o["balance"]}
check("read ok; one balance row per process, from the ledger", o["ok"] and bal["Wash"]["sent"] == 60 and bal["Wash"]["back"] == 54 and bal["Wash"]["balance"] == 6 and bal["Print"]["back"] == 40, bal)
check("a short-closed challan's gap is not counted as out", bal["Print"]["short_closed"] == 10 and bal["Print"]["balance"] == 0, bal["Print"])
check("sewn pieces without a process are not in the out/back table", "" not in bal)
ch = {c["name"]: c for c in o["challans"]}
check("a part-returned challan can take a return and be short-closed; a short-closed one can be settled; a draft one can do none", ch["SC-1"]["can_return"] and ch["SC-1"]["can_short_close"] and ch["SC-1"]["can_settle"]
      and not ch["SC-2"]["can_return"] and ch["SC-2"]["can_settle"] is False and not (ch["SC-3"]["can_return"] or ch["SC-3"]["can_short_close"] or ch["SC-3"]["can_settle"]), {k: (v["can_return"], v["can_short_close"], v["can_settle"]) for k, v in ch.items()})
check("what is left on a challan", ch["SC-1"]["left"] == 6.0 and ch["SC-2"]["left"] == 10.0)
check("a settlement without invoices can have them made", o["settlements"][0]["can_invoice"] is True, o["settlements"])
check("summary: still out, short-closed, finishing", o["summary"]["out_now"] == 6 and o["summary"]["short_closed"] == 10 and o["summary"]["finishing_received"] == 48 and o["summary"]["nothing_out"] is False and o["summary"]["finishing_done"], o["summary"])
check("no order given", F["order_subcontract_get"](db=db, sales_order="")["ok"] is False)
be.seed("Subcontract Challan", "SC-1", sales_order="SO-1", production_card="PC-1", docstatus=1, status="Short Closed", subcontract_process="Wash", total_qty=60, returned_qty=54)
o = F["order_subcontract_get"](db=db, sales_order="SO-1")
check("everything back or short-closed and a finishing receipt: nothing out, finishing done", o["summary"]["nothing_out"] and o["summary"]["out_now"] == 0 and o["summary"]["finishing_done"], o["summary"])

# 3 · short-close and invoices (risky class, approval)
W.clear()
check("short-close needs a reason", not F["order_challan_short_close"](db=db, name="SC-1", reason=" ")["ok"] and not W)
check("short-close needs a challan", not F["order_challan_short_close"](db=db, name="", reason="x")["ok"])
r = F["order_challan_short_close"](db=db, name="SC-1", reason="lost in the dye lot")
check("short-close is risky: needs_approval with an approval id", r.get("needs_approval") and r["approval_id"] == 4 and W[-1]["params"] == {"challan": "SC-1", "reason": "lost in the dye lot"}, (r, W[-1]))
r = F["order_challan_short_close"](db=db, name="SC-1", reason="lost in the dye lot", approval_id=4)
check("with the approval it runs", r["ok"] and r["name"] == "SC-1", r)
r = F["order_challan_short_close"](db=db, name="SC-1", reason="lost in the dye lot", preview=True)
check("a preview writes nothing and says what would happen", r["ok"] and r["saved"] is False and W[-1]["preview"] is True)
check("invoices need a settlement", not F["order_settlement_invoices"](db=db, name="")["ok"])
r = F["order_settlement_invoices"](db=db, name="SS-2")
check("making the vendor's invoices is risky: needs_approval", r.get("needs_approval") and W[-1]["params"] == {"settlement": "SS-2"}, r)
r = F["order_settlement_invoices"](db=db, name="SS-2", approval_id=4)
check("with the approval it answers the drafted invoices", r["ok"] and r["purchase_invoice"] == "PINV-1" and r["debit_note"] == "PINV-2", r)

# 4 · pre-filled documents
W.clear()
p = F["order_prefill_sub"](db=db, sales_order="SO-1", kind="challan")
check("challan: rows are what is sewn and not yet sent, header has the card and the order", p["ok"] and p["doctype"] == "Subcontract Challan" and p["initial"]["rows"] == [{"colour": "Navy", "size": "M", "qty": 100}]
      and p["initial"]["production_card"] == "PC-1" and p["initial"]["sales_order"] == "SO-1", p)
SUMMARY[0].update(SC_OUT=100)
check("nothing waiting to be sent: refused", not F["order_prefill_sub"](db=db, sales_order="SO-1", kind="challan")["ok"])
be.seed("Subcontract Challan", "SC-9", sales_order="SO-1", production_card="PC-1", docstatus=1, status="Open", subcontract_process="Wash", supplier="Wash House", total_qty=30, returned_qty=10,
        rows=[{"doctype": "Subcontract Challan Row", "name": "R9", "colour": "Navy", "size": "M", "qty": 30, "returned_qty": 10}, {"doctype": "Subcontract Challan Row", "name": "R8", "colour": "Navy", "size": "L", "qty": 5, "returned_qty": 5}])
p = F["order_prefill_sub"](db=db, sales_order="SO-1", kind="return", challan="SC-9")
check("return: one row per challan row with something still out, good = what is left", p["ok"] and p["initial"]["rows"] == [{"production_card": "PC-1", "challan_row": "R9", "colour": "Navy", "size": "M", "sent_qty": 30, "good_qty": 20,
                                                                                                                              "reject_vendor_qty": 0, "reject_factory_qty": 0}] and p["initial"]["supplier"] == "Wash House", p)
p = F["order_prefill_sub"](db=db, sales_order="SO-1", kind="settlement", challan="SC-9")
check("settlement: header only, the ERP works out the amounts", p["ok"] and p["doctype"] == "Subcontract Settlement" and p["initial"]["challan"] == "SC-9" and "rows" not in p["initial"], p)
check("a draft challan cannot be returned or settled", not F["order_prefill_sub"](db=db, sales_order="SO-1", kind="return", challan="SC-3")["ok"])
check("return needs a challan", not F["order_prefill_sub"](db=db, sales_order="SO-1", kind="return")["ok"])
SUMMARY[0].update(SC_BACK_GOOD=40, SC_OUT=60)
p = F["order_prefill_sub"](db=db, sales_order="SO-1", kind="finishing")
check("finishing after an after-sewing process: only the vendor's good pieces, from the route's supplier (the ERP caps FIN_IN there, found live)", p["ok"] and p["initial"]["rows"][0]["qty"] == 40
      and p["initial"]["source"] == "Subcontract Return" and p["initial"]["supplier"] == "Wash House", p)
be.seed("Production Card", "PC-1", sales_order="SO-1", docstatus=1, status="In Sewing", style_item="ST1", style_no="ST1", line="Line 1", processes=[])
p = F["order_prefill_sub"](db=db, sales_order="SO-1", kind="finishing")
check("finishing with no process on the route: what was sewn", p["ok"] and p["initial"]["rows"][0]["qty"] == 100 and p["initial"]["source"] == "Sewing", p)
check("nothing was written by any pre-fill", not [w for w in W if w.get("op")])
check("a kind that does not exist is refused", not F["order_prefill_sub"](db=db, sales_order="SO-1", kind="x")["ok"])

# 5 · roles and structure
for role, ok in (("Production", True), ("Planner", True), ("Management", True), ("Accounts", False), ("QC", False), ("Purchase", False)):
    try:
        SC.need({"roles": [role]}, "make"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} work on subcontract documents", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_subcontract.py")).read()
check("every write or pre-fill function starts with a role check", all("need(me" in src.split(f"def {f}(")[1].split("\n@guarded")[0] or "need(me" in src.split(f"def {f}(")[1].split("\ndef ")[0]
                                                                       for f in ("order_challan_short_close", "order_settlement_invoices", "order_prefill_sub")))
check("the module never writes through a backend", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src))
check("no idem_key in a function that creates documents", "idem_key" not in src)
check("short-close and settlement invoices are in the risky class", all(guardrails.classify("api", "x", m) == "risky" for m in ("arinox_subcontract_challan_short_close", "arinox_subcontract_settlement_make_invoices")))
check("submitting a challan, return and finishing receipt is in the risky (ledger) class", all(guardrails.classify("submit", d) == "risky" for d in ("Subcontract Challan", "Subcontract Return", "Finishing Receipt")))
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
