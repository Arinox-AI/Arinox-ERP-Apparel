"""Step 9 of the Order page (order_ship): the shipment wizard, on a seeded in-memory ERP with the ERP scripts stubbed.   Run from backend/:  python3 tests/test_order_ship.py   Synthetic data only."""
import os
import re
import sys
import tempfile

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
import order_ship as S  # noqa: E402
from models_deal import DealModel  # noqa: E402
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
AVAIL = [{"name": "PL-1", "sales_order": "SO-1", "customer": "Acme Apparel Co", "total_cartons": 22, "total_pieces": 500, "final_inspection": "FI-1", "inspection_result": "Accepted"},
         {"name": "PL-2", "sales_order": "SO-1", "customer": "Acme Apparel Co", "total_cartons": 2, "total_pieces": 48, "final_inspection": None, "inspection_result": None},
         {"name": "PL-3", "sales_order": "SO-1", "customer": "Other Co", "total_cartons": 2, "total_pieces": 48, "final_inspection": "FI-3", "inspection_result": "Accepted with Concession"},
         {"name": "PL-O", "sales_order": "SO-OTHER", "customer": "Acme Apparel Co", "inspection_result": "Accepted"}]


def fake_read(me, method, params=None):
    if method == "arinox_shipment_get_available_packing_lists":
        return AVAIL
    if method == "arinox_freight_allocated_costs":
        return {"rows": [["SC-1", 1.0, 500.0]], "basis": "CBM", "cost": 500.0}
    raise AssertionError(method)


S.read_script = fake_read
W = []


def fake_ex(db_, me, req):
    W.append(req)
    m = req.get("method")
    if req.get("op") in ("submit",) or m == "arinox_shipment_make_delivery_notes":
        if req.get("approval_id") is None and not req.get("preview"):
            return {"ok": False, "needs_approval": True, "approval_id": 9, "error": "A manager must approve this before it runs.", "preview": {"operations": []}}
        return {"ok": True, "result": ["DN-9"], "preview": {"operations": []}}
    return {"ok": True, "doc": {"name": "SHP-9"}, "preview": {"operations": []}}


deals._ex = fake_ex
be = FakeBackend()
be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", company="Demo Co", items=[])
be.seed("Packing List", "PL-S", sales_order="SO-1", docstatus=1, shipment="SHP-1")
be.seed("Packing List", "PL-T", sales_order="SO-1", docstatus=1, shipment="SHP-2")
be.seed("Shipment", "SHP-1", docstatus=0, status="Draft", modified="2026-11-09 10:00:00", apparel_packing_lists=[{"doctype": "Shipment Packing List", "packing_list": "PL-S"}], shipment_delivery_note=[])
be.seed("Shipment", "SHP-2", docstatus=1, status="Submitted", apparel_on_board_date="2026-11-01", apparel_packing_lists=[{"doctype": "Shipment Packing List", "packing_list": "PL-T"}],
        shipment_delivery_note=[{"doctype": "Delivery Note", "delivery_note": "DN-1"}])
be.seed("Delivery Note", "DN-1", docstatus=1, status="Completed", customer="Acme Apparel Co")
deals.BACKEND = be

# 1 · stages (pure)
check("lists picked, no delivery note", S.stage_of({}, [])["key"] == "picked")
check("a draft delivery note", S.stage_of({}, [{"docstatus": 0}, {"docstatus": 1}])["key"] == "dn_draft")
check("all notes submitted, not on board", S.stage_of({}, [{"docstatus": 1}])["key"] == "dn_done")
check("on board needs the notes too", S.stage_of({"apparel_on_board_date": "2026-11-01"}, [{"docstatus": 1}])["key"] == "on_board" and S.stage_of({"apparel_on_board_date": "2026-11-01"}, [])["key"] == "picked")
check("a cancelled note does not count", S.stage_of({}, [{"docstatus": 2}])["key"] == "picked")

# 2 · the read
o = F["order_ship_get"](db=db, sales_order="SO-1")
check("read ok; only this order's lists are waiting, each with its inspection state", o["ok"] and [a["name"] for a in o["available"]] == ["PL-1", "PL-2", "PL-3"]
      and [a["ready"] for a in o["available"]] == [True, False, True], o.get("available"))
sh = {s["name"]: s for s in o["shipments"]}
check("shipments found through the packing lists, with their stage", sh["SHP-1"]["stage"]["key"] == "picked" and sh["SHP-2"]["stage"]["key"] == "on_board", {k: v["stage"] for k, v in sh.items()})
check("make-DN only where there are lists and no note yet; submit only after all notes are in", sh["SHP-1"]["can_make_dns"] and not sh["SHP-2"]["can_make_dns"] and not sh["SHP-1"]["can_submit"])
check("tracking facts and freight share come with the shipment", sh["SHP-2"]["on_board"] == "2026-11-01" and sh["SHP-2"]["freight"]["basis"] == "CBM")
check("summary", o["summary"]["shipments"] == 2 and o["summary"]["on_board"] == 1 and o["summary"]["delivery_notes_submitted"] == 1 and o["summary"]["done"] is True, o["summary"])
check("no deal yet: deal_id 0", o["deal_id"] == 0)
db.add(DealModel(refs='{"sales_order": "SO-1"}')); db.commit()
check("the deal the order came from is found, so the shipping clocks can be shown", F["order_ship_get"](db=db, sales_order="SO-1")["deal_id"] > 0)
check("no order given", F["order_ship_get"](db=db, sales_order="")["ok"] is False)

# 3 · create the shipment
W.clear()
check("nothing picked", not F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=[])["ok"])
check("a list twice", not F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-1", "PL-1"])["ok"])
check("a bad mode", not F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-1"], mode="Camel")["ok"])
check("a list that is not available", not F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-ZZ"])["ok"])
check("another order's list", not F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-O"])["ok"])
r = F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-2"])
check("a list with no accepted final inspection is refused", not r["ok"] and "final inspection" in r["error"], r)
r = F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-1", "PL-3"])
check("lists of two customers refused", not r["ok"] and "one customer" in r["error"], r)
check("nothing written by the refusals", not W)
r = F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-1"], mode="Sea LCL", preview=True)
check("preview writes nothing real and says so", r["ok"] and r["saved"] is False and W[-1]["preview"] is True)
r = F["order_shipment_create"](db=db, sales_order="SO-1", packing_lists=["PL-1"], mode="Air")
d = W[-1]["data"]
check("inserted through the pipeline with the lists, the customer and the mode", r["ok"] and r["name"] == "SHP-9" and W[-1]["op"] == "insert" and W[-1]["doctype"] == "Shipment" and d["delivery_customer"] == "Acme Apparel Co"
      and d["pickup_company"] == "Demo Co" and d["apparel_mode"] == "Air" and d["apparel_packing_lists"] == [{"packing_list": "PL-1"}], W[-1])

# 4 · delivery notes and submits (risky, approval)
W.clear()
r = F["order_ship_make_dns"](db=db, shipment="SHP-1")
check("making delivery notes is risky: needs_approval", r.get("needs_approval") and r["approval_id"] == 9 and W[-1]["method"] == "arinox_shipment_make_delivery_notes" and W[-1]["params"] == {"shipment": "SHP-1"}, r)
r = F["order_ship_make_dns"](db=db, shipment="SHP-1", approval_id=9)
check("with the approval it answers the notes made", r["ok"] and r["made"] == ["DN-9"], r)
check("a shipment is needed", not F["order_ship_make_dns"](db=db, shipment="")["ok"])
r = F["order_ship_submit"](db=db, doctype="Delivery Note", name="DN-9")
check("submitting a delivery note needs approval", r.get("needs_approval") and W[-1]["op"] == "submit", r)
check("only a delivery note or a shipment", not F["order_ship_submit"](db=db, doctype="Sales Invoice", name="X")["ok"])
check("a name is needed", not F["order_ship_submit"](db=db, doctype="Shipment", name="")["ok"])
check("submitting after approval", F["order_ship_submit"](db=db, doctype="Shipment", name="SHP-1", approval_id=9)["ok"])

# 5 · booking, bill of lading, tracking
W.clear()
r = F["order_ship_record"](db=db, shipment="SHP-1", values={"apparel_booking_no": "BK-1", "apparel_on_board_date": "2026-11-05", "owner": "x", "apparel_hbl_no": ""})
check("only shipment fields are written, empties dropped, the modified stamp sent", r["ok"] and r["fields"] == ["apparel_booking_no", "apparel_on_board_date"] and W[-1]["data"] == {"apparel_booking_no": "BK-1", "apparel_on_board_date": "2026-11-05"}
      and W[-1]["modified"] == "2026-11-09 10:00:00" and W[-1]["op"] == "save", (r, W[-1]))
check("nothing to save refused", not F["order_ship_record"](db=db, shipment="SHP-1", values={"owner": "x"})["ok"])
check("a shipment is needed to record", not F["order_ship_record"](db=db, shipment="", values={"carrier": "x"})["ok"])

# 6 · roles and structure
for dt, role, ok in (("Shipment", "Shipping", True), ("Shipment", "Production", False), ("Delivery Note", "Shipping", True), ("Delivery Note", "Accounts", False), ("Shipment", "Management", True)):
    try:
        S.need_dt({"roles": [role]}, dt, "x"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} write {dt}", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_ship.py")).read()
check("the module never writes through a backend directly", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src))
check("no idem_key in a function that creates documents", "idem_key" not in src)
check("delivery notes are risky", guardrails.classify("api", "x", "arinox_shipment_make_delivery_notes") == "risky" and guardrails.classify("submit", "Delivery Note") == "risky")
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
