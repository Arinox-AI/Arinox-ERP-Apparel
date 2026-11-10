"""Steps 6 and 7 of the Order page (order_cutsew, order_subcontract) and the production board, on a seeded in-memory ERP with the ERP scripts stubbed.   Run from backend/:  python3 tests/test_order_materials.py   Synthetic data only."""
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
W = []                                   # every write the actions sent through the pipeline
SUMMARY = {}                             # card -> rows the ERP's summary script answers


def fake_read(me, method, params=None):
    if method == "arinox_production_card_get_summary":
        return {"card": params["name"], "status": "Issued", "rows": SUMMARY.get(params["name"], [])}
    if method == "arinox_production_card_get_production_context":
        return {"sales_order": "SO-1", "styles": [{"style_item": "ST1", "ex_factory_date": "2027-02-01", "lines": [{"colour": "Navy", "size": "M", "order_qty": 600}],
                                                   "allocation": [], "card": None, "fabric_requisitions": [{"parent": "FR-1", "colour": "Navy"}], "trim_requisitions": []}],
                "defaults": {"extra_cut_pct": 5, "bundle_size": 20}}
    if method == "arinox_cut_plan_suggest_rolls":
        return {"lays": [{"lay_no": 1}], "unallocated": [], "short": []}
    if method == "arinox_cutting_get_issuable_rolls":
        return [{"batch": "B-1", "available_m": 100}]
    if method == "arinox_production_card_revise_production_card":
        return {"doctype": "Production Card", "name": params["source_name"], "status": "Issued", "lines": [{"colour": "Navy", "size": "M", "name": "x", "idx": 1}]}
    raise AssertionError(method)


def fake_ex(db_, me, req):
    W.append(req)
    if req.get("method") == "arinox_cutting_issue_fabric" and req.get("approval_id") is None and not req.get("preview"):
        return {"ok": False, "needs_approval": True, "approval_id": 9, "error": "A manager must approve this before it runs.", "preview": {"operations": []}}
    if req.get("op") == "insert":
        return {"ok": True, "doc": {"name": "PC-NEW"}, "preview": {"operations": [{"op": "insert"}]}}
    if req.get("op") == "api":
        res = {"arinox_production_card_save_production_card": {"name": "PC-2", "red_flags": ""}, "arinox_cut_plan_release": "Pending Approval", "arinox_cutting_issue_fabric": "STE-1"}.get(req["method"], "Released")
        return {"ok": True, "result": res, "preview": {"operations": [{"op": "call"}]}}
    return {"ok": True, "doc": {"name": req.get("name")}, "preview": {"operations": []}}


M.read_script = fake_read
deals._ex = fake_ex
import order_samples as S  # noqa: E402
S.read_script = fake_read
S.deals._ex = fake_ex

TODAY = date.today().isoformat()
be = FakeBackend()
be.seed("Item", "ST1", variant_of=None)
be.seed("Item", "ST1-NAVY-M", variant_of="ST1")
be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", company="Demo Co", items=[{"doctype": "Sales Order Item", "item_code": "ST1-NAVY-M", "apparel_colour": "Navy", "qty": 1000}])
be.seed("Production Card", "PC-1", sales_order="SO-1", docstatus=1, status="In Sewing", style_item="ST1", style_no="ST1", line="Line 1", revision_no=0)
be.seed("Production Card", "PC-0", sales_order="SO-1", docstatus=1, status="Superseded", style_item="ST1", style_no="ST1", revision_no=0)
be.seed("Production Card", "PC-D", sales_order="SO-1", docstatus=0, status="Draft", style_item="ST1", style_no="ST1", revision_no=1)
be.seed("Cut Plan", "CP-1", sales_order="SO-1", status="Draft", production_card="PC-1", colour="Navy", fabric_item="FAB", variance_pct=1.0)
be.seed("Cut Plan", "CP-2", sales_order="SO-1", status="Pending Approval", production_card="PC-1", colour="Navy", fabric_item="FAB", variance_pct=-9.0)
be.seed("Cut Plan", "CP-3", sales_order="SO-1", status="Released", production_card="PC-1", colour="Navy", fabric_item="FAB", variance_pct=0.5,
        lays=[{"doctype": "Cut Plan Lay", "lay_no": 1, "marker_length_m": 8.5, "marker_width_cm": 140, "marker_ref": "M1"}, {"doctype": "Cut Plan Lay", "lay_no": 2, "marker_length_m": 9.0}])
be.seed("Lay Report", "LAY-1", production_card="PC-1", cut_plan="CP-3", lay_no=1, docstatus=1, lay_date=TODAY, pieces_cut=100)
be.seed("Operation Bulletin", "OB-1", style_item="ST1", version=1, status="Draft", total_sam=12.5, operators=20)
be.seed("Production Movement", "PM-1", sales_order="SO-1", production_card="PC-1", stage="SEW_OUT", qty=70, posting_date=TODAY, docstatus=0)
be.seed("Production Movement", "PM-2", sales_order="SO-1", production_card="PC-1", stage="SEW_OUT", qty=30, posting_date="2026-01-01", docstatus=0)
be.seed("Production Movement", "PM-3", sales_order="SO-1", production_card="PC-1", stage="CUT", qty=120, posting_date="2026-01-01", docstatus=0)
deals.BACKEND = be

# 1 · the matrix is arithmetic over the ERP's summary
SUMMARY["PC-1"] = [{"colour": "Navy", "size": "M", "order_qty": 600, "planned_cut_qty": 630, "CUT": 120, "SEW_IN": 110, "SEW_OUT": 100, "FIN_A": 40, "FIN_IN": 50, "PACKED": 10},
                   {"colour": "Navy", "size": "L", "order_qty": 400, "planned_cut_qty": 420, "CUT": 0, "SEW_IN": 0, "SEW_OUT": 0}]
mx = M.build_matrix([{"card": "PC-1", "style": "ST1", "status": "In Sewing", "rows": SUMMARY["PC-1"]}], {"SEW_OUT": 70})
check("stages are cut, input, sewn, QC pass, finished, packed", [s["key"] for s in mx["stages"]] == ["cut", "input", "sewn", "qc_pass", "finished", "packed"], mx["stages"])
check("totals add up across colour x size and the order", mx["totals"]["order_qty"] == 1000 and mx["totals"]["sewn"] == 100 and mx["totals"]["cut"] == 120 and mx["totals"]["qc_pass"] == 40 and mx["totals"]["finished"] == 50, mx["totals"])
check("percentage of the order per stage", mx["pct"]["sewn"] == 10.0 and mx["pct"]["cut"] == 12.0, mx["pct"])
check("today's output per stage", mx["today"]["sewn"] == 70 and mx["today"]["cut"] == 0, mx["today"])
check("an empty order has no percentage, no division by zero", M.build_matrix([], {})["pct"]["sewn"] == 0.0)

# 2 · the read
o = F["order_cutsew_get"](db=db, sales_order="SO-1")
check("read ok; only the issued live card is in the matrix (not the superseded, not the draft)", o["ok"] and [c["card"] for c in o["matrix"]["cards"]] == ["PC-1"], o["matrix"]["cards"])
check("matrix totals and today come through the read", o["matrix"]["totals"]["sewn"] == 100 and o["matrix"]["today"]["sewn"] == 70, o["matrix"]["today"])
check("summary: order quantity from the Sales Order, sewn percentage", o["summary"]["order_qty"] == 1000 and o["summary"]["sewn_pct"] == 10.0 and o["summary"]["today_sewn"] == 70, o["summary"])
check("a draft card can be issued, an issued one revised, a superseded one neither", {c["name"]: (c["can_approve"], c["can_revise"]) for c in o["cards"]} == {"PC-0": (False, False), "PC-1": (False, True), "PC-D": (True, False)}, o["cards"])
check("cut plans say what can be done next", {p["name"]: (p["can_release"], p["can_approve"], p["can_reopen"]) for p in o["cut_plans"]} == {"CP-1": (True, False, False), "CP-2": (False, True, False), "CP-3": (False, False, True)}, o["cut_plans"])
check("the operation bulletins of the order's styles are listed", [b["name"] for b in o["bulletins"]] == ["OB-1"], o["bulletins"])
check("recent lay reports are listed", any(r["name"] == "LAY-1" for r in o["reports"]), o["reports"])
check("no order given", F["order_cutsew_get"](db=db, sales_order="")["ok"] is False)

# 3 · production card: save (zero rows never sent), issue, revise
W.clear()
r = F["order_card_save"](db=db, sales_order="SO-1", style_item="ST1", header={"line": "Line 1"}, fabrics=[{"colour": "Navy", "fabric_item": "FAB", "consumption": 1.5}, {"colour": "Navy", "fabric_item": "ZERO", "consumption": 0}],
                         processes=[{"subcontract_process": "Wash", "position": "After Sewing"}, {"subcontract_process": " "}],
                         lines=[{"colour": "Navy", "size": "M", "order_qty": 600}, {"colour": "Navy", "size": "L", "order_qty": 0}], preview=True)
data = json.loads(W[-1]["params"]["data"])
check("save goes through the ERP's script, a zero-quantity line is never sent", r["ok"] and W[-1]["method"] == "arinox_production_card_save_production_card" and len(data["lines"]) == 1 and data["sales_order"] == "SO-1" and data["customer"] == "Acme Apparel Co", data)
check("zero-consumption fabric and nameless process rows are never sent", [f["fabric_item"] for f in data["fabrics"]] == ["FAB"] and [p["subcontract_process"] for p in data["processes"]] == ["Wash"], data)
W.clear()
check("every line zero: nothing is saved", not F["order_card_save"](db=db, sales_order="SO-1", style_item="ST1", lines=[{"colour": "Navy", "size": "M", "order_qty": 0}])["ok"] and not W)
r = F["order_card_approve"](db=db, name="PC-D", preview=True)
check("issuing is a submit through the pipeline", r["ok"] and W[-1]["op"] == "submit" and W[-1]["doctype"] == "Production Card")
check("revise needs a reason", not F["order_card_revise"](db=db, name="PC-1", reason=" ")["ok"])
r = F["order_card_revise"](db=db, name="PC-1", reason="quantities changed", preview=True)
check("revise inserts a draft with the reason", r["ok"] and W[-1]["op"] == "insert" and W[-1]["data"]["revision_reason"] == "quantities changed" and "name" not in W[-1]["data"]["lines"][0], W[-1])
c = F["order_card_context"](db=db, sales_order="SO-1")
check("the context gives the lines, defaults and the fabrics of the approved requisitions", c["ok"] and c["styles"][0]["lines"][0]["order_qty"] == 600 and c["defaults"]["bundle_size"] == 20 and "fabrics" in c["styles"][0], c)

# 4 · cut plan, fabric issue, bulletin
W.clear()
r = F["order_cutplan_suggest"](db=db, name="CP-1")
check("suggest is a read: nothing written", r["ok"] and not W and r["suggestion"]["short"] == [])
check("approve needs a reason", not F["order_cutplan_approve"](db=db, name="CP-2", note="")["ok"] and not W)
r = F["order_cutplan_approve"](db=db, name="CP-2", note="checked with the pattern maker", preview=True)
check("approve sends the note to the ERP's script", r["ok"] and W[-1]["method"] == "arinox_cut_plan_approve" and W[-1]["params"] == {"name": "CP-2", "note": "checked with the pattern maker"}, W[-1])
r = F["order_cutplan_release"](db=db, name="CP-1")
check("release answers the status the ERP gave (a variance sends it to a manager)", r["ok"] and r["status"] == "Pending Approval", r)
check("reopen goes to the ERP's script", F["order_cutplan_reopen"](db=db, name="CP-3", preview=True)["ok"] and W[-1]["method"] == "arinox_cut_plan_reopen")
check("issuable rolls are a read", F["order_cut_issuable"](db=db, card="PC-1")["rolls"][0]["batch"] == "B-1")
W.clear()
check("zero-length rolls are never issued, and nothing is sent", not F["order_cut_issue"](db=db, card="PC-1", rolls=[{"batch": "B-1", "qty": 0}])["ok"] and not W)
r = F["order_cut_issue"](db=db, card="PC-1", rolls=[{"batch": "B-1", "qty": 50}, {"batch": "B-2", "qty": 0}])
check("issuing fabric is risky: needs_approval with an approval id, rolls without length dropped", r.get("needs_approval") and r["approval_id"] == 9 and json.loads(W[-1]["params"]["rolls"]) == [{"batch_no": "B-1", "qty": 50.0}], (r, W[-1]))
r = F["order_cut_issue"](db=db, card="PC-1", rolls=[{"batch": "B-1", "qty": 50}], approval_id=9)
check("with the approval it runs and answers the Stock Entry", r["ok"] and r["name"] == "STE-1", r)
check("activating a bulletin goes to the ERP's script", F["order_ob_activate"](db=db, name="OB-1", preview=True)["ok"] and W[-1]["method"] == "arinox_operation_bulletin_activate")

# 5 · pre-filled floor documents
SUMMARY["PC-1"] = [{"colour": "Navy", "size": "M", "order_qty": 600, "CUT": 120, "SEW_IN": 110, "SEW_OUT": 100}, {"colour": "Navy", "size": "L", "order_qty": 400, "CUT": 50, "SEW_IN": 50, "SEW_OUT": 50}]
W.clear()
be.seed("Cut Bundle", "B1", production_card="PC-1", status="Issued", purpose="Bulk", colour="Navy", size="M", qty=20, sewn_qty=5, rejected_qty=0)
be.seed("Cut Bundle", "B2", production_card="PC-1", status="Cut", purpose="Bulk", colour="Navy", size="M", qty=10, component="Shell")
p = F["order_prefill"](db=db, sales_order="SO-1", kind="dlr")
check("daily line report: today, the card, one row per loaded bundle with what is left", p["ok"] and p["doctype"] == "Daily Line Report" and p["initial"]["report_date"] == TODAY and p["initial"]["line"] == "Line 1"
      and p["initial"]["outputs"] == [{"production_card": "PC-1", "colour": "Navy", "size": "M", "qty": 15, "purpose": "Bulk", "bundle": "B1"}], p)
check("nothing is written by a pre-fill", not W)
be.seed("Cut Bundle", "B1", production_card="PC-1", status="Issued", purpose="Bulk", colour="Navy", size="M", qty=20, sewn_qty=20, rejected_qty=0)
p = F["order_prefill"](db=db, sales_order="SO-1", kind="dlr")
check("a fully sewn bundle is not offered again; the summary's room is used instead", p["ok"] and all(o["qty"] > 0 for o in p["initial"]["outputs"]), p)
SUMMARY["PC-1"] = [{"colour": "Navy", "size": "M", "order_qty": 600, "CUT": 100, "SEW_IN": 100, "SEW_OUT": 100}]
check("nothing left to report: refused, with a sentence", not F["order_prefill"](db=db, sales_order="SO-1", kind="dlr")["ok"])
p = F["order_prefill"](db=db, sales_order="SO-1", kind="line_input")
check("line input: one row per cut shell bundle", p["ok"] and p["initial"]["bundles"] == [{"bundle": "B2", "colour": "Navy", "size": "M", "qty": 10}], p)
p = F["order_prefill"](db=db, sales_order="SO-1", kind="lay", name="CP-3", card="PC-1")
check("lay report: the next lay of the plan that is not cut yet", p["ok"] and p["initial"]["cut_plan"] == "CP-3" and p["initial"]["lay_no"] == 2 and p["initial"]["marker_length_m"] == 9.0, p)
check("a kind that does not exist is refused", not F["order_prefill"](db=db, sales_order="SO-1", kind="x")["ok"])
be2 = FakeBackend()
be2.seed("Sales Order", "SO-9", docstatus=1, customer="C", company="Co", items=[])
deals.BACKEND = be2
check("no issued card: floor documents are refused", not F["order_prefill"](db=db, sales_order="SO-9", kind="dlr")["ok"])
deals.BACKEND = be

# 6 · the production board
be.seed("Production Card Line", "PL-1", parent="PC-1", order_qty=1000)
r = F["production_board_get"](db=db)
row = next((x for x in r["rows"] if x["sales_order"] == "SO-1"), None)
check("the board has one row per order with a live card and reads the ledger (docstatus 0 rows count, as on the real ERP)", r["ok"] and row and row["sewn"] == 100 and row["cut"] == 120 and row["today_sewn"] == 70 and row["order_qty"] == 1000 and row["sewn_pct"] == 10.0, r)
check("the board totals", r["totals"]["sewn"] == 100 and r["totals"]["today_sewn"] == 70, r["totals"])

# 7 · the old WIP screen is retired on a site with the Arinox layer, kept on a cortex-evidence site
import order_flow as _of  # noqa: E402
_of.erp_profile = lambda be_: "arinox"
w = functions.get_wip_plan(db)
check("get_wip_plan answers retired on an Arinox site, pointing at the board", w.get("retired") is True and "Production board" in w["reason"], w)
check("the WIP analytics, thread and planner actions answer retired too", functions.get_wip_analytics(db).get("retired") and functions.get_wip_thread(db, wip="W1").get("retired")
      and functions._wip_do(lambda **k: {"ok": True}, db, wip="W1").get("retired"))
_of.erp_profile = lambda be_: "cortex_evidence"
check("on a cortex-evidence site the old reader is still called", functions._wip_retired() is None)

# 8 · roles and structure
for role, ok in (("Production", True), ("Planner", True), ("Management", True), ("Purchase", False), ("QC", False), ("Shipping", False)):
    try:
        M.need({"roles": [role]}, "make"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} make floor documents", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_cutsew.py")).read()
fns = [f for f in M.FUNCTIONS if f not in ("order_cutsew_get", "production_board_get")]
check("every write or pre-fill function starts with a role check", all("need(me" in src.split(f"def {f}(")[1].split("\n@guarded")[0] or "need(me" in src.split(f"def {f}(")[1].split("\ndef ")[0] for f in fns), fns)
check("the module never writes through a backend", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src))
check("no idem_key in a function that creates documents (found in S5)", "idem_key" not in src)
check("fabric issue is in the risky class", guardrails.classify("api", "Stock Entry", "arinox_cutting_issue_fabric") == "risky")
check("submitting the line, lay and daily line report is in the risky (ledger) class", all(guardrails.classify("submit", d) == "risky" for d in ("Daily Line Report", "Lay Report", "Line Input", "Finishing Receipt")))
check("every function is registered in functions.py", all(f in functions.FUNCTIONS for f in list(M.FUNCTIONS) + list(SC.FUNCTIONS)))
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
