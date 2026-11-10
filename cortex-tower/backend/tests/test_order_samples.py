"""Step 4 of the Order page (order_samples): approval matrix, bulk gate card and the actions, on a seeded in-memory ERP with the ERP scripts stubbed.

Run from backend/:  python3 tests/test_order_samples.py        Synthetic data only (invented buyer 'Acme Apparel Co', invented styles); no ERP, no mail.
"""
import json
import os
import sys
import tempfile

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
import guardrails  # noqa: E402
import order_samples as S  # noqa: E402
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
RULES = {"Proto": {"gate": "No", "per_colour": 0}, "Fit": {"gate": "Required", "per_colour": 0, "due_basis": "PCD", "days_before": 45},
         "Lab Dip": {"gate": "Required", "per_colour": 1}, "Bulk Fabric": {"gate": "Required", "per_colour": 1}, "PP": {"gate": "Required", "per_colour": 0},
         "Strike Off": {"gate": "If Raised", "per_colour": 1}, "Garment Test (GPT)": {"gate": "Required", "per_colour": 0, "split_po_exempt": 1}}
STATE = {"blockers": ["Fit approval missing."], "calls": [], "writes": []}


def fake_read(me, method, params=None):
    STATE["calls"].append((method, params))
    if method == "arinox_sample_approval_get_sample_rules":
        return RULES
    if method == "arinox_work_order_get_bulk_gate":
        return {"applies": True, "colour": "x", "blockers": STATE["blockers"].get(params["production_item"], []) if isinstance(STATE["blockers"], dict) else STATE["blockers"]}
    if method == "arinox_pp_meeting_add_standard_participants":
        return {"arinox_doc": {"participants": [{"department": d, "attended": 0} for d in ("Planning", "Cutting", "QC")]}, "count": 3}
    if method == "arinox_pp_meeting_load_from_requisitions":
        return {"arinox_doc": {"colours": [{"colour": "Navy", "order_qty": 600, "fabric_required_m": 900.0}], "sewing_trims": "Available"}, "count": 1}
    if method == "arinox_pp_meeting_get_buyer_comments":
        return {"arinox_doc": {"actions": [{"sample_approval": "SA-FIT", "comment_ref": "c1", "source": "Buyer Comment", "comment": "[Fit] lengthen body"}]}, "count": 1}
    if method == "arinox_sample_approval_load_spec_from_tech_pack":
        if not (params and json.loads(params["doc"]).get("tech_pack")):
            raise RuntimeError("Select the Tech Pack first.")
        return {"arinox_doc": {"measurements": [{"pom_code": "A", "spec": 50}]}, "count": 1}
    raise AssertionError(method)


def fake_ex(db_, me, req):
    STATE["writes"].append(req)
    if req.get("op") == "insert":
        n = f"{req['doctype'][:3].upper()}-{len(STATE['writes'])}"
        return {"ok": True, "doc": {"name": n, **req["data"]}, "preview": {"operations": [{"op": "insert", "doctype": req["doctype"]}]} if req.get("preview") else None}
    if req.get("op") == "save":
        return {"ok": True, "doc": {"name": req["name"], "status": "Approved"}}
    return {"ok": True, "preview": {"operations": []}}


S.read_script = fake_read
deals._ex = fake_ex


def world():
    be = FakeBackend()
    be.seed("Item", "ST1", variant_of=None)
    for c, code in (("Navy", "ST1-NAVY-M"), ("Red", "ST1-RED-M")):
        be.seed("Item", code, variant_of="ST1")
    be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", delivery_date="2027-03-20", items=[
        {"doctype": "Sales Order Item", "item_code": "ST1-NAVY-M", "apparel_colour": "Navy", "qty": 600}, {"doctype": "Sales Order Item", "item_code": "ST1-RED-M", "apparel_colour": "Red", "qty": 400}])
    be.seed("Sample Approval", "SA-FIT", sales_order="SO-1", sample_type="Fit", style_item="ST1", colour="", status="Approved", docstatus=0, due_date="2027-01-01")
    be.seed("Sample Approval", "SA-LD-N", sales_order="SO-1", sample_type="Lab Dip", style_item="ST1", colour="Navy", status="Submitted", docstatus=0,
            rounds=[{"doctype": "Sample Approval Round", "round_no": 1, "sent_on": "2026-11-01", "decision": "Pending"}])
    deals.BACKEND = be
    return be


be = world()
o = F["order_samples_get"](db=db, sales_order="SO-1")
check("get ok", o.get("ok"), o)
types = [t["type"] for t in o["types"]]
check("columns: required types and raised ones, never a type whose rule is No", "Fit" in types and "Lab Dip" in types and "PP" in types and "Proto" not in types, types)
rows = {r["colour"]: r for r in o["rows"]}
check("two style x colour rows with quantities", set(rows) == {"Navy", "Red"} and rows["Navy"]["qty"] == 600, rows.keys())
check("a per-style approval shows on every colour", rows["Navy"]["cells"]["Fit"]["status"] == "Approved" and rows["Red"]["cells"]["Fit"]["status"] == "Approved" and rows["Red"]["cells"]["Fit"]["tone"] == "ok")
check("a per-colour approval is read per colour: Navy submitted (rounds kept), Red missing", rows["Navy"]["cells"]["Lab Dip"]["status"] == "Submitted" and rows["Navy"]["cells"]["Lab Dip"]["rounds"][0]["decision"] == "Pending"
      and rows["Red"]["cells"]["Lab Dip"]["status"] == "Missing" and rows["Red"]["cells"]["Lab Dip"]["tone"] == "bad")
check("an If Raised type is a column that says Not raised", rows["Navy"]["cells"]["Strike Off"]["status"] == "Not raised" and rows["Navy"]["cells"]["Strike Off"]["tone"] is None)
check("a required type with nothing raised is Missing, not blank", rows["Navy"]["cells"]["PP"]["status"] == "Missing")
check("the GPT exemption on a single-destination order still counts as required (not exempt)", rows["Navy"]["cells"]["Garment Test (GPT)"]["status"] == "Missing")
check("gate card: closed with the blockers in plain sentences", rows["Navy"]["gate"]["open"] is False and rows["Navy"]["gate"]["blockers"] == ["Fit approval missing."])
check("summary counts the missing ones and the meetings", o["summary"]["missing"] == 7 and o["summary"]["gate_open"] == 0 and o["summary"]["meeting_submitted"] is False, o["summary"])
STATE["blockers"] = []
o = F["order_samples_get"](db=db, sales_order="SO-1")
check("the gate is green only because the ERP script says no blockers (the tower does not decide)", all(r["gate"]["open"] for r in o["rows"]) and o["summary"]["gate_open"] == 2)
STATE["blockers"] = {"ST1-RED-M": ["PP Meeting not submitted."], "ST1-NAVY-M": []}
o = F["order_samples_get"](db=db, sales_order="SO-1")
check("the gate is per style x colour", [r["gate"]["open"] for r in sorted(o["rows"], key=lambda r: r["colour"])] == [True, False], o["rows"])
check("an order with no style: Sales Order not given", F["order_samples_get"](db=db, sales_order="")["ok"] is False)

# split order: the exempt type stops being required
be.seed("Sales Order", "SO-S", docstatus=1, customer="Acme Apparel Co", items=[
    {"doctype": "Sales Order Item", "item_code": "ST1-NAVY-M", "apparel_colour": "Navy", "qty": 10, "apparel_ship_to": "Dock A"}, {"doctype": "Sales Order Item", "item_code": "ST1-RED-M", "apparel_colour": "Red", "qty": 10, "apparel_ship_to": "Dock B"}])
o2 = F["order_samples_get"](db=db, sales_order="SO-S")
check("a split-destination order drops the type the rule exempts", "Garment Test (GPT)" not in [t["type"] for t in o2["types"]], [t["type"] for t in o2["types"]])

# create from the rules
STATE["writes"].clear()
r = F["order_samples_create"](db=db, sales_order="SO-1", preview=True)
check("preview: planned rows only for what is missing, nothing written", r["ok"] and r["made"] == [] and len(r["previews"]) == len(r["planned"]) and all(w["preview"] for w in STATE["writes"]), r)
plan = {(p["sample_type"], p["colour"]) for p in r["planned"]}
check("per-colour types once per colour, others once per style, existing ones skipped", ("Lab Dip", "Red") in plan and ("Lab Dip", "Navy") not in plan and ("Fit", "") not in plan and ("PP", "") in plan
      and ("Bulk Fabric", "Navy") in plan and ("Bulk Fabric", "Red") in plan and sum(1 for p in plan if p[0] == "PP") == 1 and ("Strike Off", "Red") not in plan, plan)
STATE["writes"].clear()
r = F["order_samples_create"](db=db, sales_order="SO-1")
check("created through the pipeline (insert; no replay key, so a deleted approval can be raised again), bulk types carry a material placeholder", r["ok"] and len(r["made"]) == len(r["planned"]) and all(w["op"] == "insert" and not w.get("idem_key") for w in STATE["writes"])
      and all("material_description" in w["data"] for w in STATE["writes"] if w["data"]["sample_type"].startswith("Bulk")), STATE["writes"][:2])
r = F["order_samples_create"](db=db, sales_order="SO-1", types=["Strike Off"], preview=True)
check("an If Raised type is created only when asked for", ("Strike Off", "Red") in {(p["sample_type"], p["colour"]) for p in r["planned"]})
be2 = FakeBackend()
be2.seed("Sales Order", "SO-D", docstatus=0, items=[]); deals.BACKEND = be2
check("a draft order is refused", F["order_samples_create"](db=db, sales_order="SO-D")["ok"] is False)
deals.BACKEND = be

# rounds
STATE["writes"].clear()
r = F["order_sample_round"](db=db, sales_order="SO-1", sample_approval="SA-LD-N", decision="Rejected", comment="")
check("a rejection needs the buyer's comment (sentence, nothing sent)", not r["ok"] and "comment" in r["error"] and not STATE["writes"], r)
r = F["order_sample_round"](db=db, sales_order="SO-1", sample_approval="SA-LD-N", decision="Maybe")
check("an unknown decision is refused", not r["ok"])
r = F["order_sample_round"](db=db, sales_order="SO-1", sample_approval="SA-LD-N", decision="Approved", decision_on="2026-11-05", preview=True)
w = STATE["writes"][-1]
check("a Pending last round is decided in place, no bookkeeping keys sent, preview flag passed", r["ok"] and r["round_no"] == 1 and len(w["data"]["rounds"]) == 1 and w["data"]["rounds"][0]["decision"] == "Approved"
      and w["preview"] is True and not any(k in w["data"]["rounds"][0] for k in ("idx", "name", "parent", "doctype")), w)
r = F["order_sample_round"](db=db, sales_order="SO-1", sample_approval="SA-FIT", decision="Rejected", comment="Chest too tight", category="Fit", sent_on="2026-11-02")
w = STATE["writes"][-1]
check("a new round with its comment on that round number", r["ok"] and r["round_no"] == 1 and w["data"]["comments"][0]["round_no"] == 1 and w["data"]["comments"][0]["comment"] == "Chest too tight")
be.seed("Sample Approval", "SA-OTHER", sales_order="SO-X", sample_type="Fit", style_item="ST9", docstatus=0)
check("a sample of another order is refused", not F["order_sample_round"](db=db, sales_order="SO-1", sample_approval="SA-OTHER", decision="Approved")["ok"])
r = F["order_sample_load"](db=db, sales_order="SO-1", sample_approval="SA-FIT", what="spec", sample_size="M")
check("loading the Tech Pack spec: the script's own sentence comes back when the Tech Pack is missing", not r["ok"] and "Tech Pack" in r["error"], r)
be.seed("Sample Approval", "SA-TP", sales_order="SO-1", sample_type="Fit", style_item="ST1", tech_pack="TP-1", docstatus=0)
r = F["order_sample_load"](db=db, sales_order="SO-1", sample_approval="SA-TP", what="spec", sample_size="M", preview=True)
check("loading the spec saves the rows through the pipeline", r["ok"] and r["count"] == 1 and STATE["writes"][-1]["data"]["measurements"][0]["pom_code"] == "A")

# PP meeting
STATE["writes"].clear()
be.seed("Sample Approval", "SA-PP", sales_order="SO-1", sample_type="PP", style_item="ST1", status="Approved", docstatus=0)
r = F["order_pp_meeting_make"](db=db, sales_order="SO-1", style_item="ST1", attended=["Planning", "QC"], card_issued_on="2026-11-20", preview=True)
w = STATE["writes"][-1]
check("PP meeting: approved PP sample linked, every standard department listed, attendance as given, buyer comments become action rows, readiness per colour",
      r["ok"] and w["data"]["pp_sample"] == "SA-PP" and {p["department"]: p["attended"] for p in w["data"]["participants"]} == {"Planning": 1, "Cutting": 0, "QC": 1}
      and len(w["data"]["actions"]) == 1 and w["data"]["colours"][0]["fabric_required_m"] == 900.0 and w["data"]["production_card_issued_on"] == "2026-11-20" and w["preview"] is True, w)
check("a style not on the order is refused", not F["order_pp_meeting_make"](db=db, sales_order="SO-1", style_item="NOPE")["ok"])
be.seed("PP Meeting", "PPM-1", sales_order="SO-1", style_item="ST1", docstatus=0, status="Draft", meeting_date="2026-11-20",
        participants=[{"doctype": "PP Meeting Participant", "department": "Planning", "attended": 0}],
        actions=[{"doctype": "PP Meeting Action", "idx": 1, "comment": "[Fit] lengthen", "status": "Open"}])
check("a second meeting for the same style is refused", not F["order_pp_meeting_make"](db=db, sales_order="SO-1", style_item="ST1")["ok"])
r = F["order_pp_meeting_actions"](db=db, name="PPM-1", actions=[{"idx": 1, "action_taken": "Pattern corrected", "action_owner": "cutting@test.local", "target_date": "2026-11-25"}], attended=["Planning"])
w = STATE["writes"][-1]
check("meeting actions: owner and date set on the row, attendance set, no bookkeeping keys", r["ok"] and w["data"]["actions"][0]["action_owner"] == "cutting@test.local" and w["data"]["participants"][0]["attended"] == 1
      and "_n" not in w["data"]["actions"][0] and "idx" not in w["data"]["actions"][0], w)
check("an action row that does not exist is refused", not F["order_pp_meeting_actions"](db=db, name="PPM-1", actions=[{"idx": 9, "action_taken": "x"}])["ok"])
r = F["order_pp_meeting_submit"](db=db, name="PPM-1", preview=True)
check("submit goes through the pipeline as op submit, with preview", r["ok"] and STATE["writes"][-1]["op"] == "submit" and STATE["writes"][-1]["preview"] is True)
o = F["order_samples_get"](db=db, sales_order="SO-1")
m = o["meetings"][0]
check("the meeting card carries attendance, actions and the open count", m["name"] == "PPM-1" and m["open_actions"] == 1 and m["participants"][0]["department"] == "Planning", m)

# roles
for fn, kw in (("order_samples_create", {}), ("order_sample_round", {"decision": "Approved"}), ("order_pp_meeting_make", {}), ("order_pp_meeting_submit", {"name": "PPM-1"})):
    try:
        S.need({"roles": ["QC"]}, "plan")
        check(f"QC may not use {fn}", False)
    except guardrails.Denied:
        check(f"QC may not use {fn}", True)
for role in ("Planner", "Sampling", "Merchandiser", "Management"):
    try:
        S.need({"roles": [role]}, "plan"); check(f"{role} may", True)
    except guardrails.Denied:
        check(f"{role} may", False)
check("the write functions each start with the role check", all("need(me" in open(os.path.join(os.path.dirname(HERE), "order_samples.py")).read().split(f"def {f}(")[1].split("\n@guarded")[0] for f in
      ("order_samples_create", "order_sample_round", "order_sample_load", "order_pp_meeting_make", "order_pp_meeting_actions", "order_pp_meeting_submit")))
check("the module never writes through a backend", not __import__("re").search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", open(os.path.join(os.path.dirname(HERE), "order_samples.py")).read()))
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
