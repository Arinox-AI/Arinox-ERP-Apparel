"""Step 5 of the Order page (order_materials): material status table and the requisition -> PO -> inspection actions, on a seeded in-memory ERP with the
ERP scripts and the Material Status report stubbed.   Run from backend/:  python3 tests/test_order_materials.py   Synthetic data only."""
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
import order_materials as M  # noqa: E402
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
W = []                                   # every write the actions sent through the pipeline
REPORT = []


def line(**kw):
    base = {"type": "FR", "requisition": "FR-1", "sales_order": "SO-1", "style_no": "ST1", "colour": "Navy", "item": "FAB-NAVY", "supplier": "Mill A", "required_by": "2027-01-10",
            "net": 1000.0, "ordered": 1000.0, "received": 1000.0, "accepted": 1000.0, "rejected": 0.0, "in_inspection": 0.0, "po": "PO-1", "eta": "2026-12-20", "status": "Accepted"}
    base.update(kw)
    return base


def fake_report(reg, eng, be, name, filters, user="x", limit=2000):
    assert name == "Material Status" and filters == {"sales_order": "SO-1"}, (name, filters)
    return {"rows": REPORT}


M.tsr_reports.run = fake_report
M.cortex_api._reg = lambda: None
M.pipeline.engine = lambda: None
SCRIPT = {}


def fake_read(me, method, params=None):
    if method in SCRIPT:
        v = SCRIPT[method]
        if isinstance(v, Exception):
            raise v
        return v
    raise AssertionError(method)


def fake_ex(db_, me, req):
    W.append(req)
    if req.get("approval_id") is None and req.get("method") == "arinox_purchase_order_make_purchase_orders" and not req.get("preview") and SCRIPT.get("_need_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": 7, "error": "A manager must approve this before it runs.", "preview": {"operations": []}}
    if req.get("op") == "insert":
        return {"ok": True, "doc": {"name": "NEW-1", "rolls": req["data"].get("rolls") or []}, "preview": {"operations": [{"op": "insert"}]}}
    if req.get("op") == "api":
        res = {"arinox_purchase_order_make_purchase_orders": ["PO-9"], "arinox_rolls_import_roll_list": {"rolls": 2, "total": 176.4}}.get(req["method"], "FR-NEW")
        return {"ok": True, "result": res, "preview": {"operations": [{"op": "call"}]}}
    return {"ok": True, "doc": {"name": req.get("name")}, "preview": {"operations": []}}


M.read_script = fake_read
deals._ex = fake_ex
import order_samples as S  # noqa: E402
S.read_script = fake_read
S.deals._ex = fake_ex

be = FakeBackend()
be.seed("Item", "ST1", variant_of=None)
be.seed("Item", "ST1-NAVY-M", variant_of="ST1")
be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", company="Demo Co", items=[{"doctype": "Sales Order Item", "item_code": "ST1-NAVY-M", "apparel_colour": "Navy", "qty": 1000}])
be.seed("Factory Allocation", "FA-1", sales_order="SO-1", docstatus=1,
        items=[], lines=[{"doctype": "Factory Allocation Line", "style_item": "ST1", "style_no": "ST1", "colour": "Navy", "pcd": "2027-01-15"}])
deals.BACKEND = be

# 1 · the status table: the ERP's words stay, the PCD comparison is arithmetic on two dates
REPORT[:] = [line(), line(requisition="FR-1", item="FAB-RED", colour="Red", status="Short", accepted=400.0, received=600.0, eta="2027-01-20"),
             line(type="TR", requisition="TR-1", item="TRIM-ZIP", colour="Navy", status="Ordered", ordered=1000.0, received=0.0, accepted=0.0, eta=None),
             line(type="TR", requisition="TR-1", item="TRIM-BTN", colour="Navy", status="Requested", ordered=0.0, received=0.0, accepted=0.0, eta=None, net=0.0)]
t = M.material_table(REPORT, {("ST1", "NAVY"): date(2027, 1, 15), ("ST1", "RED"): date(2027, 1, 15), "": date(2027, 1, 15)}, date(2026, 11, 9))
check("required, ordered, received, passed, short per line", t[0]["required"] == 1000 and t[0]["passed"] == 1000 and t[0]["short"] == 0 and t[1]["short"] == 600 and t[1]["in_house"], t[:2])
check("a passed line carries no ETA note and is not late", t[0]["note"] == "" and not t[0]["late"] and t[0]["passed_all"])
check("ETA after the PCD is late and says by how many days", t[1]["late"] and "5 day(s) after the PCD 2027-01-15" in t[1]["note"], t[1]["note"])
check("no ETA yet says so while the PCD is ahead", "No ETA yet" in t[2]["note"] and not t[2]["late"], t[2]["note"])
t2 = M.material_table([line(status="Ordered", accepted=0.0, eta=None)], {"": date(2026, 11, 1)}, date(2026, 11, 9))
check("a PCD that has passed with the material not accepted is late", t2[0]["late"] and "has passed" in t2[0]["note"], t2)
t3 = M.material_table([line(status="In Transit", eta="2027-01-05", accepted=0.0)], {"": date(2027, 1, 15)}, date(2026, 11, 9))
check("ETA before the PCD says how much margin", not t3[0]["late"] and "10 day(s) before" in t3[0]["note"], t3[0]["note"])

# 2 · the read
be.seed("Fabric Requisition", "FR-1", status="Approved", docstatus=1, revision_no=0, items=[{"doctype": "Fabric Requisition Item", "sales_order": "SO-1"}])
be.seed("Trim Requisition", "TR-1", status="Draft", docstatus=0, revision_no=0, items=[{"doctype": "Trim Requisition Item", "sales_order": "SO-1"}])
be.seed("Purchase Receipt", "PR-1", docstatus=0, supplier="Mill A", items=[{"doctype": "Purchase Receipt Item", "name": "PRI-1", "sales_order": "SO-1", "item_code": "FAB-NAVY", "qty": 882}])
be.seed("Purchase Receipt", "PR-2", docstatus=1, supplier="Mill A", items=[{"doctype": "Purchase Receipt Item", "name": "PRI-2", "sales_order": "SO-1", "item_code": "FAB-RED", "qty": 600},
                                                                         {"doctype": "Purchase Receipt Item", "name": "PRI-3", "sales_order": "SO-1", "item_code": "TRIM-ZIP", "qty": 500}])
be.seed("Fabric Inspection", "FI-1", purchase_receipt="PR-2", purchase_receipt_item="PRI-2", docstatus=0, lot_result="")
o = F["order_materials_get"](db=db, sales_order="SO-1")
check("read ok, one row per report line", o["ok"] and len(o["rows"]) == 4, o)
check("summary: not all passed, late counted, short summed", o["summary"]["all_passed"] is False and o["summary"]["late"] >= 1 and o["summary"]["short"] == 600.0 + 1000.0, o["summary"])
check("the PCD comes from the saved allocation", o["rows"][0]["pcd"] == "2027-01-15", o["rows"][0])
check("requisitions say what can be done next (a submitted Approved one can be ordered; a draft cannot)", {r["name"]: r["can_order"] for r in o["requisitions"]} == {"FR-1": True, "TR-1": False}, o["requisitions"])
rc = {r["row_name"]: r for r in o["receipts"]}
check("a draft fabric receipt row can take a roll list, a received row can be inspected, one with an inspection cannot be made again",
      rc["PRI-1"]["can_import_rolls"] and not rc["PRI-1"]["can_inspect"] and not rc["PRI-2"]["can_inspect"] and rc["PRI-2"]["inspection"]["name"] == "FI-1" and rc["PRI-3"]["can_inspect"] and rc["PRI-3"]["kind"] == "trim", rc)
REPORT[:] = [line(), line(item="FAB-RED", colour="Red", accepted=1000.0, received=1000.0, status="Accepted")]
o = F["order_materials_get"](db=db, sales_order="SO-1")
check("everything passed and not late: the step's condition holds", o["summary"]["all_passed"] and o["summary"]["all_in_house_before_pcd"], o["summary"])
REPORT[:] = []
o = F["order_materials_get"](db=db, sales_order="SO-1")
check("no approved requisition: empty table, nothing claimed", o["ok"] and o["rows"] == [] and o["summary"]["all_passed"] is False and o["no_requisition"] == ["ST1"], o)
check("no order given", F["order_materials_get"](db=db, sales_order="")["ok"] is False)

# 3 · requisition lines and save
SCRIPT["arinox_fabric_requisition_get_lines_from_sales_orders"] = {"arinox_doc": {"items": [{"colour": "Navy", "garment_qty": 600}]}, "count": 1}
r = F["order_req_lines"](db=db, sales_order="SO-1", kind="fabric")
check("the ERP proposes lines (read, nothing written)", r["ok"] and r["items"][0]["colour"] == "Navy" and r["company"] == "Demo Co" and not W, r)
check("kind is checked", not F["order_req_lines"](db=db, sales_order="SO-1", kind="thread")["ok"])
W.clear()
items = [{"colour": "Navy", "garment_qty": 600, "idx": 1, "name": "x", "fabric_item": "FAB-NAVY", "supplier": "Mill A"}, {"colour": "Red", "garment_qty": 0, "fabric_item": "FAB-RED"}, {"colour": "Blk", "garment_qty": "", "fabric_item": "F"}]
r = F["order_req_save"](db=db, sales_order="SO-1", kind="fabric", items=items, preview=True)
data = json.loads(W[-1]["params"]["data"])
check("zero-quantity rows are never sent, bookkeeping keys are stripped, preview passes through", r["ok"] and r["rows"] == 1 and len(data["items"]) == 1 and "idx" not in data["items"][0] and "name" not in data["items"][0]
      and W[-1]["preview"] is True and W[-1]["doctype"] == "Fabric Requisition" and data["customer"] == "Acme Apparel Co", W[-1])
W.clear()
r = F["order_req_save"](db=db, sales_order="SO-1", kind="trim", items=[{"garment_qty": 0}])
check("every row empty: nothing to save, nothing sent", not r["ok"] and "no quantity" in r["error"] and not W)
r = F["order_req_save"](db=db, sales_order="SO-1", kind="trim", items=[{"garment_qty": 5, "trim_item": "T"}], name="TR-1")
check("trim save uses the trim script and updates a named draft", json.loads(W[-1]["params"]["data"])["name"] == "TR-1" and W[-1]["method"] == "arinox_trim_requisition_save_trim_requisition")
r = F["order_items_create"](db=db, kind="fabric", items=[{"fabric_description": "Q1, 100% cotton", "colour": "Navy", "idx": 1}])
check("make items goes through the pipeline with the doc in params", r["ok"] and W[-1]["method"] == "arinox_fabric_requisition_create_fabric_items" and "idx" not in json.loads(W[-1]["params"]["doc"])["items"][0])
check("make items with no rows is refused", not F["order_items_create"](db=db, kind="fabric", items=[])["ok"])

# 4 · approve, revise, purchase orders (risky: approval)
r = F["order_req_approve"](db=db, kind="fabric", name="FR-1", preview=True)
check("approve = submit through the pipeline, preview first", r["ok"] and W[-1]["op"] == "submit" and W[-1]["doctype"] == "Fabric Requisition" and W[-1]["preview"] is True)
check("approve needs a name", not F["order_req_approve"](db=db, kind="fabric", name="")["ok"])
SCRIPT["arinox_fabric_requisition_revise_fabric_requisition"] = {"name": "FR-1", "docstatus": 0, "items": [{"idx": 1, "colour": "Navy", "garment_qty": 700}], "revision_no": 1}
check("a revision needs a reason", not F["order_req_revise"](db=db, kind="fabric", name="FR-1")["ok"])
r = F["order_req_revise"](db=db, kind="fabric", name="FR-1", reason="Order qty up")
check("revision: the ERP's draft is inserted without bookkeeping, with the reason", r["ok"] and W[-1]["data"]["revision_reason"] == "Order qty up" and "name" not in W[-1]["data"] and "idx" not in W[-1]["data"]["items"][0])
SCRIPT["_need_approval"] = True
r = F["order_po_make"](db=db, kind="fabric", name="FR-1")
check("purchase orders are a risky class: needs_approval with the approval id, nothing made", not r["ok"] and r["needs_approval"] and r["approval_id"] == 7)
r = F["order_po_make"](db=db, kind="fabric", name="FR-1", approval_id=7)
check("after approval the same action runs and answers the PO names", r["ok"] and r["made"] == ["PO-9"] and W[-1]["approval_id"] == 7 and W[-1]["params"] == {"requisition_type": "FR", "name": "FR-1"})
r = F["order_po_make"](db=db, kind="trim", name="TR-1", preview=True, approval_id=0)
check("a preview of the purchase orders is a preview", r["ok"] and W[-1]["preview"] is True and W[-1]["params"]["requisition_type"] == "TR")

# 5 · rolls and inspection
check("roll import needs a receipt, a row and rolls", not F["order_rolls_import"](db=db, purchase_receipt="PR-1", row_name="PRI-1", rolls=[])["ok"])
r = F["order_rolls_import"](db=db, purchase_receipt="PR-1", row_name="PRI-1", rolls="R01, L1, 88.2\nR02, L1, 88.2", length_uom="Meter")
check("rolls go through the ERP script on the receipt doctype (so the materials role is checked)", r["ok"] and r["rolls"] == 2 and W[-1]["doctype"] == "Purchase Receipt" and W[-1]["params"]["pr_name"] == "PR-1")
SCRIPT["arinox_fabric_inspection_make_inspection"] = {"doctype": "Fabric Inspection", "name": None, "purchase_receipt": "PR-2", "purchase_receipt_item": "PRI-2", "rolls": [{"idx": 1, "batch": "B1", "inspected": 1}], "docstatus": 0}
r = F["order_inspection_make"](db=db, kind="fabric", purchase_receipt="PR-2", purchase_receipt_item="PRI-2", preview=True)
check("the inspection is built by the ERP script (a line per roll), saved as a draft through the pipeline (no replay key: an undone inspection can be made again, found live)",
      r["ok"] and r["rolls"] == 1 and W[-1]["op"] == "insert" and W[-1]["doctype"] == "Fabric Inspection" and not W[-1].get("idem_key") and "idx" not in W[-1]["data"]["rolls"][0], W[-1])
SCRIPT["arinox_trim_inspection_make_inspection"] = RuntimeError("Purchase Receipt PR-1 is not submitted. Inspect goods that have been received.")
r = F["order_inspection_make"](db=db, kind="trim", purchase_receipt="PR-1", purchase_receipt_item="PRI-1")
check("the script's own sentence comes back when the receipt is not submitted", not r["ok"] and "not submitted" in r["error"], r)
r = F["order_inspection_submit"](db=db, kind="fabric", name="FI-1", preview=True)
check("submitting the inspection goes through the pipeline as a submit", r["ok"] and W[-1]["op"] == "submit" and W[-1]["doctype"] == "Fabric Inspection")

be.seed("Fabric Inspection", "FI-2", fabric_requisition="FR-1", purchase_receipt="PR-2", docstatus=0)
r = F["order_inspection_submit"](db=db, kind="fabric", name="FI-2")
check("after a real submit the requisition quantities are recomputed (the tower's rule ran on a read made before the submit), under the QC role's own doctype",
      r["ok"] and r["refreshed"] and W[-1]["method"] == "arinox_fabric_requisition_refresh_quantities" and W[-1]["doctype"] == "Fabric Inspection" and W[-1]["params"] == {"requisition_type": "FR", "name": "FR-1"}, (r, W[-1]))

# 6 · roles
for role, ok in (("Production", False), ("QC", False), ("Purchase", True), ("Merchandiser", True), ("Planner", True), ("Management", True)):
    try:
        M.need({"roles": [role]}, "materials"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} raise and order material", got == ok)
for role, ok in (("Purchase", False), ("QC", True), ("Management", True)):
    try:
        M.need({"roles": [role]}, "inspection"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} make an inspection", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_materials.py")).read()
check("every write function starts with a role check", all(("need(me" in src.split(f"def {f}(")[1].split("\n@guarded")[0] or "guardrails.Denied" in src.split(f"def {f}(")[1].split("\n@guarded")[0])
                                                          for f in ("order_req_lines", "order_items_create", "order_req_save", "order_req_approve", "order_req_revise", "order_po_make", "order_rolls_import", "order_inspection_make", "order_inspection_submit")))
check("the module never writes through a backend", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src))
from tsr.backend import HttpBackend  # noqa: E402
check("roll batches are read from the Serial and Batch Bundle, not the first parent the ERP lists (found live in S5)", HttpBackend._PARENT_PREFERENCE.get("Serial and Batch Entry") == "Serial and Batch Bundle")
check("the purchase-order script is in the risky class", guardrails.classify("api", "Purchase Order", "arinox_purchase_order_make_purchase_orders") == "risky")
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
