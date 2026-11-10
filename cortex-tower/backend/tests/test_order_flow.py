"""The order read model (order_flow, order_api): every step state on a seeded in-memory ERP.

Run from backend/:  python3 tests/test_order_flow.py        Synthetic data only; no ERP, no mail.
"""
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"
os.environ["USER_EMAIL"] = "plan@test.local"
os.environ["USER_NAME"] = "Planner"
os.environ["USER_IS_ADMIN"] = "1"

from database import get_session, init_db  # noqa: E402
init_db()
import deals  # noqa: E402
import erp  # noqa: E402
import functions  # noqa: E402
import order_flow  # noqa: E402
from tsr.fake import FakeBackend  # noqa: E402

erp._base_key = lambda: "https://erp.test:9446"
erp._DESK_PREFIX = ("https://erp.test:9446", "desk")
N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


TODAY = date(2026, 11, 9)


def base():
    be = FakeBackend()
    for dt in ("Production Card", "Order TNA", "Factory Allocation"):
        be.seed("DocType", dt)
    return be


def so(be, name, qty=1000, ds=1, status="To Deliver and Bill", **kw):
    return be.seed("Sales Order", name, docstatus=ds, customer="BUYER A", customer_name="Buyer A", grand_total=5000, currency="USD",
                   delivery_date="2027-01-31", transaction_date="2026-11-01", status=status,
                   items=[{"doctype": "Sales Order Item", "item_code": "ST1-RED-S", "qty": qty / 2}, {"doctype": "Sales Order Item", "item_code": "ST1-RED-M", "qty": qty / 2}], **kw)


def step(out, key):
    return next(s for s in out["steps"] if s["key"] == key)


# 1 · a brand-new submitted order: only "confirm" is done, the rest are todo, the next action is the allocation
be = base()
so(be, "SO-1")
o = order_flow.status(be, "SO-1", TODAY)
check("ten steps in plan order", [s["key"] for s in o["steps"]] == order_flow.STEP_KEYS, [s["key"] for s in o["steps"]])
check("confirm done on a submitted order", step(o, "confirm")["state"] == "done")
check("allocate is todo with the board as its action", step(o, "allocate")["state"] == "todo" and step(o, "allocate")["next"]["action"] == "allocate")
check("everything else todo", all(step(o, k)["state"] == "todo" for k in order_flow.STEP_KEYS[2:]), [(s["key"], s["state"]) for s in o["steps"]])
check("next banner = allocation", o["next"]["step"] == "allocate", o["next"])
check("header qty / ex-factory / days", o["header"]["qty"] == 1000 and o["header"]["ex_factory"] == "2027-01-31" and o["header"]["days_to_ex_factory"] == 83, o["header"])
check("by_step has an ERP page for each step", len(o["by_step"]) == 10 and all(v["url"].startswith("https://erp.test:9446/desk/") for v in o["by_step"].values()), o["by_step"])
check("confirm page is the order itself", o["by_step"]["confirm"]["url"].endswith("/sales-order/SO-1"), o["by_step"]["confirm"])
check("no errors, profile arinox", not o["errors"] and o["erp_profile"] == "arinox", (o["errors"], o["erp_profile"]))

# 2 · draft and cancelled orders
be = base(); so(be, "SO-D", ds=0)
check("draft order: confirm doing", step(order_flow.status(be, "SO-D", TODAY), "confirm")["state"] == "doing")
be = base(); so(be, "SO-C", ds=2)
o = order_flow.status(be, "SO-C", TODAY)
check("cancelled order: confirm blocked", step(o, "confirm")["state"] == "blocked" and o["next"]["step"] == "confirm", o["next"])

# 3 · a fully worked order: every step done
be = base(); so(be, "SO-F", qty=1000, status="Closed")
be.seed("Sales Contract", "SC-F", sales_order="SO-F", docstatus=1, status="Ordered")
be.seed("Factory Allocation", "FA-SO-F", sales_order="SO-F", status="Planned", docstatus=0, order_qty=1000,
        lines=[{"doctype": "Factory Allocation Line", "parent": "FA-SO-F", "style_item": "ST1", "colour": "RED", "qty": 1000, "pcd": "2026-12-01", "factory": "F1", "line": "L1"}])
be.seed("Order TNA", "TNA-1", sales_order="SO-F", style_no="ST1", colour="RED", status="On Track", plan_feasible=1, baseline_locked=1, docstatus=0)
be.seed("Sample Approval", "SA-1", sales_order="SO-F", status="Approved", docstatus=1)
be.seed("PP Meeting", "PP-1", sales_order="SO-F", status="Closed", docstatus=1)
be.seed("Fabric Requisition", "FR-1", status="Ordered", docstatus=1, items=[{"doctype": "Fabric Requisition Item", "sales_order": "SO-F"}])
be.seed("Purchase Order", "PO-1", status="Completed", docstatus=1, items=[{"doctype": "Purchase Order Item", "sales_order": "SO-F"}])
be.seed("Purchase Receipt", "PR-1", status="Completed", docstatus=1, items=[{"doctype": "Purchase Receipt Item", "sales_order": "SO-F"}])
be.seed("Fabric Inspection", "FI-1", fabric_requisition="FR-1", docstatus=1)
be.seed("Production Card", "PC-1", sales_order="SO-F", status="Packed", docstatus=1)
be.seed("Production Movement", "PM-1", sales_order="SO-F", stage="SEW_OUT", qty=1000, docstatus=1)
be.seed("Finishing Receipt", "FIN-1", sales_order="SO-F", docstatus=1)
be.seed("Packing List", "PL-1", sales_order="SO-F", status="Shipped", shipment="SHP-1", docstatus=1)
be.seed("Final Inspection", "FINSP-1", sales_order="SO-F", result="Accepted", docstatus=1)
be.seed("Shipment", "SHP-1", status="Booked", docstatus=1, apparel_on_board_date="2026-01-20")
be.seed("Delivery Note", "DN-1", status="Completed", docstatus=1, items=[{"doctype": "Delivery Note Item", "against_sales_order": "SO-F"}])
be.seed("Sales Invoice", "SINV-1", status="Paid", docstatus=1, outstanding_amount=0, due_date="2027-02-01", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-F"}])
o = order_flow.status(be, "SO-F", TODAY)
check("every step done", [s["state"] for s in o["steps"]] == ["done"] * 10, [(s["key"], s["state"], s["blockers"]) for s in o["steps"]])
check("documents are grouped by step with ERP links", step(o, "materials")["by_type"]["Purchase Order"] == 1 and step(o, "ship")["docs"][0]["url"].startswith("https://erp.test"), step(o, "ship")["docs"])
check("a shipment is found through its packing list", step(o, "ship")["by_type"]["Shipment"] == 1, step(o, "ship")["by_type"])
check("kpis carry the ledger", o["kpis"]["sewn"] == 1000.0 and o["kpis"]["order_qty"] == 1000.0, o["kpis"])
be.seed("Shipment", "SHP-1", status="Booked", docstatus=1)
o2 = order_flow.status(be, "SO-F", TODAY)
check("ship: a submitted delivery note and shipment but not on board is not done (S9 gate)", step(o2, "ship")["state"] == "doing" and any("on board" in b for b in step(o2, "ship")["blockers"]), step(o2, "ship"))
be.seed("Shipment", "SHP-1", status="Booked", docstatus=1, apparel_on_board_date="2026-01-20")
check("next banner on a finished order", o["next"]["step"] == "done", o["next"])

# 4 · partial and blocked states
be = base(); so(be, "SO-P", qty=1000)
be.seed("Factory Allocation", "FA-SO-P", sales_order="SO-P", status="Partly Planned", docstatus=0,
        lines=[{"doctype": "Factory Allocation Line", "parent": "FA-SO-P", "style_item": "ST1", "colour": "RED", "qty": 600, "factory": "F1", "line": "L1"}])
o = order_flow.status(be, "SO-P", TODAY)
a = step(o, "allocate")
check("partial allocation: doing, says 600 of 1000 and the missing PCD", a["state"] == "doing" and "600 of 1000" in a["blockers"][0] and any("PCD" in b for b in a["blockers"]), a)
be.seed("Order TNA", "TNA-P", sales_order="SO-P", style_no="ST1", colour="RED", status="At Risk", plan_feasible=0, baseline_locked=0, docstatus=0)
check("infeasible T&A plan blocks the step", step(order_flow.status(be, "SO-P", TODAY), "tna")["state"] == "blocked")
be.seed("Sample Approval", "SA-P", sales_order="SO-P", status="Rejected", docstatus=1)
check("a rejected sample blocks samples", step(order_flow.status(be, "SO-P", TODAY), "samples")["state"] == "blocked")
be.seed("Fabric Requisition", "FR-P", status="Approved", docstatus=1, items=[{"doctype": "Fabric Requisition Item", "sales_order": "SO-P"}])
be.seed("Purchase Order", "PO-P", status="To Receive", docstatus=1, items=[{"doctype": "Purchase Order Item", "sales_order": "SO-P"}])
be.seed("Fabric Inspection", "FI-P", fabric_requisition="FR-P", docstatus=1)
m = step(order_flow.status(be, "SO-P", TODAY), "materials")
check("materials: ordered but not received is doing", m["state"] == "doing" and "no receipt" in m["blockers"][0], m)
be.seed("Trim Requisition", "TR-P", status="Approved", docstatus=1, items=[{"doctype": "Trim Requisition Item", "sales_order": "SO-P"}])
be.seed("Trim Inspection", "TI-P", trim_requisition="TR-P", result="Fail", docstatus=1)
check("a failed trim inspection blocks materials", step(order_flow.status(be, "SO-P", TODAY), "materials")["state"] == "blocked")
be.seed("Production Card", "PC-P", sales_order="SO-P", status="In Sewing", docstatus=1)
be.seed("Production Movement", "PM-P", sales_order="SO-P", stage="SEW_OUT", qty=400, docstatus=1)
be.seed("Production Movement", "PM-P2", sales_order="SO-P", stage="CUT", qty=700, docstatus=1)
be.seed("Production Movement", "PM-P3", sales_order="SO-P", stage="SEW_OUT", qty=900, docstatus=2)       # the ledger is not submittable (docstatus 0 on the real ERP); only a cancelled row posts nothing
c = step(order_flow.status(be, "SO-P", TODAY), "cutsew")
check("cut and sew: 400 of 1000 sewn, cancelled rows do not count", c["state"] == "doing" and "Sewn 400 of 1000" in c["blockers"][0], c)
be.seed("Subcontract Challan", "SCH-P", sales_order="SO-P", status="Partly Returned", docstatus=1)
sc = step(order_flow.status(be, "SO-P", TODAY), "subcontract")
check("subcontract: still out is doing", sc["state"] == "doing" and "still out" in sc["blockers"][0], sc)
be.seed("Packing List", "PL-P", sales_order="SO-P", status="Open", docstatus=0)
be.seed("Final Inspection", "FINSP-P", sales_order="SO-P", result="Rejected", docstatus=1)
check("a rejected final inspection blocks pack", step(order_flow.status(be, "SO-P", TODAY), "pack")["state"] == "blocked")
be.seed("Sales Invoice", "SINV-P", status="Unpaid", docstatus=1, outstanding_amount=100, due_date="2026-10-01", items=[{"doctype": "Sales Invoice Item", "sales_order": "SO-P"}])
iv = step(order_flow.status(be, "SO-P", TODAY), "invoice")
check("overdue invoice is named", iv["state"] == "doing" and "overdue" in iv["blockers"][0], iv)
o = order_flow.status(be, "SO-P", TODAY)
check("next banner: the first blocked step wins", o["next"]["step"] == "tna", o["next"])
check("header RAG red when something is blocked", o["header"]["rag"] == "red", o["header"])

be.seed("Shipment", "SHP-P", status="Draft", docstatus=0)
be.seed("Packing List", "PL-P2", sales_order="SO-P", shipment="SHP-P", status="On Shipment", docstatus=1)
be.seed("Delivery Note", "DN-P", status="Draft", docstatus=0, items=[{"doctype": "Delivery Note Item", "against_sales_order": "SO-P"}])
sh = step(order_flow.status(be, "SO-P", TODAY), "ship")
check("ship: a draft shipment and a draft DN give blockers, not a crash", sh["state"] == "doing" and any("shipment is not submitted" in b for b in sh["blockers"]), sh)
be_p = be

# 5 · amended order: documents of the old amendment are history, not counted
be = base(); so(be, "SO-A", ds=2); so(be, "SO-A-1", amended_from="SO-A")
be.seed("Production Card", "PC-OLD", sales_order="SO-A", status="Cancelled", docstatus=2)
be.seed("Production Card", "PC-OLD2", sales_order="SO-A", status="Issued", docstatus=1)
be.seed("Production Card", "PC-NEW", sales_order="SO-A-1", status="Issued", docstatus=1)
for opened in ("SO-A", "SO-A-1"):
    o = order_flow.status(be, opened, TODAY)
    check(f"amended ({opened}): follows to the head", o["head"] == "SO-A-1" and o["chain"] == ["SO-A", "SO-A-1"], (o["head"], o["chain"]))
cs = step(o, "cutsew")
check("amended: only the live amendment's card is counted", cs["counts"]["total"] == 1 and cs["counts"]["cancelled"] == 1, cs["counts"])
check("amended: old documents shown as history", any(d["history"] for d in cs["docs"]) and sum(1 for d in cs["docs"] if not d["history"]) == 1, cs["docs"])
check("amended: opening the old name says it was superseded", order_flow.status(be, "SO-A", TODAY)["superseded_by"] == "SO-A-1")

# 6 · more than 100 documents: the chunked "in" lists
be = base(); so(be, "SO-B")
for i in range(230):
    be.seed("Production Card", f"PCB-{i}", sales_order="SO-B", status="Issued", docstatus=1)
    be.seed("Lay Report", f"LAY-{i}", production_card=f"PCB-{i}", docstatus=1)
o = order_flow.status(be, "SO-B", TODAY)
check("230 cards and 230 lay reports are all found", step(o, "cutsew")["by_type"]["Production Card"] == 230 and step(o, "cutsew")["by_type"]["Lay Report"] == 230, step(o, "cutsew")["by_type"])
check("chunks are never longer than 100", list(order_flow._chunks(list(range(230)))) [0].__len__() == 100)

# 7 · one document type failing is reported, not raised
class Flaky(FakeBackend):
    def get_list(self, doctype, *a, **k):
        if doctype == "Packing List":
            raise RuntimeError("boom")
        return super().get_list(doctype, *a, **k)
fb = Flaky(); [fb.seed("DocType", d) for d in ("Production Card", "Order TNA", "Factory Allocation")]; so(fb, "SO-X")
o = order_flow.status(fb, "SO-X", TODAY)
check("a failing type is listed in errors", "Packing List" in o["errors"] and o["ok"], o["errors"])

# 8 · no Arinox layer: profile says so
nb = FakeBackend(); so(nb, "SO-N")
check("erp_profile: cortex_evidence without the Arinox doctypes", order_flow.erp_profile(nb) == "cortex_evidence")

# 9 · the guarded functions: sign-in, role filter, ERP down, order book
F = functions.FUNCTIONS
db = get_session()
check("order_get / order_list are registered", "order_get" in F and "order_list" in F)
deals.BACKEND = be
r = F["order_get"](db=db, sales_order="SO-B")
check("order_get via the registry", r.get("ok") and r["head"] == "SO-B" and len(r["steps"]) == 10, {k: r.get(k) for k in ("ok", "error")})
check("order_get needs a sales order", F["order_get"](db=db, sales_order="")["ok"] is False)
check("order_get: unknown order is a sentence", F["order_get"](db=db, sales_order="NOPE")["ok"] is False)
import order_api  # noqa: E402
me_qc = {"roles": ["QC"], "is_admin": False}
o = order_flow.status(be, "SO-B", TODAY)
f = order_api._filter_for(me_qc, o)
check("QC cannot read the invoice step", step(f, "invoice").get("restricted") and step(f, "cutsew").get("docs"), step(f, "invoice"))
f = order_api._filter_for({"roles": ["Accounts"], "is_admin": False}, order_flow.status(be, "SO-B", TODAY))
check("Accounts reads step 10", not step(f, "invoice").get("restricted"))


class Down(FakeBackend):
    def get_list(self, *a, **k):
        raise ConnectionError("erp down")
    def get_doc(self, *a, **k):
        raise ConnectionError("erp down")
deals.BACKEND = Down()
r = F["order_get"](db=db, sales_order="SO-B")
check("ERP down: stale flag and a sentence", r["ok"] is False and r.get("stale") is True or "could not be read" in str(r.get("error")), r)
r = F["order_list"](db=db)
check("ERP down: order_list is stale, not a traceback", r["ok"] is False and r.get("stale") is True, r)
deals.BACKEND = be_p
r = F["order_list"](db=db)
check("order book lists submitted orders with chips", r["ok"] and {x["name"] for x in r["orders"]} == {"SO-P"} and len(r["orders"][0]["chips"]) == 8, r.get("error") or r["orders"][:1])
chips = {c["key"]: c["state"] for x in r["orders"] if x["name"] == "SO-P" for c in x["chips"]}
check("order book chips reflect the follow-on documents", chips.get("cutsew") == "doing" and chips.get("tna") == "doing" and chips.get("confirm") == "done", chips)
check("order book search", [x["name"] for x in F["order_list"](db=db, q="SO-P")["orders"]] == ["SO-P"])

# two styles sharing colours and sizes: the header counts styles, not the first token of the item code (found on the S11 end-to-end order)
check("style of a colour/size variant line", order_flow._style_of({"item_code": "ACME-TEE-100-BLACK-S", "apparel_size": "S"}) == "ACME-TEE-100"
      and order_flow._style_of({"item_code": "ACME-SHT-200-SAND-XXS", "apparel_size": "XXS"}) == "ACME-SHT-200" and order_flow._style_of({"item_code": "PLAIN"}) == "PLAIN")
# an amended Sales Order: the allocation functions work on the live version
import order_api  # noqa: E402
check("allocation follows an amendment to the live head", order_api._head_of(be_p, "SO-P") == "SO-P")

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
