"""The T&A writer (tna_plan, ownership, order_api T&A functions) with the ERP stubbed. Run from backend/: python3 tests/test_tna_plan.py"""
import os
import re
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"
os.environ["USER_EMAIL"] = "m@test.local"
os.environ["USER_IS_ADMIN"] = "1"
from database import get_session, init_db  # noqa: E402
init_db()
import deals  # noqa: E402
import guardrails  # noqa: E402
import order_api  # noqa: E402
import tna_plan  # noqa: E402
from models_tna import PlanBaselineModel, PlanRevisionModel  # noqa: E402
from tna_engine import ownership, scheduler  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


# ownership: one writer, a per-field allowlist
for f in ("planned_date", "revised_date"):
    try:
        ownership.check("TNA Milestone", {f}, locked=False)
        check(f"{f} is a tower field before the lock", True)
    except PermissionError:
        check(f"{f} is a tower field before the lock", False)
for bad in ("actual_date", "status", "owner_user", "order_tna"):
    try:
        ownership.check("TNA Milestone", {bad})
        check(f"the writer may not send {bad}", False)
    except PermissionError:
        check(f"the writer may not send {bad} (ERP evidence / person / computed)", True)
try:
    ownership.check("TNA Milestone", {"planned_date"}, locked=True)
    check("after the lock a planned date is refused", False)
except PermissionError as e:
    check("after the lock a planned date is refused and the revised date is offered", "revised date" in str(e))
check("Order TNA identity fields are not writable by the tower", all(f not in ownership.TOWER_WRITES["Order TNA"] for f in ("sales_order", "style_item", "colour", "order_qty")))

# one writer: no other module writes a TNA doctype (the legacy tna_app is a separate project and is not touched)
hits = []
for fn in os.listdir(os.path.dirname(HERE)):
    if fn.endswith(".py") and fn not in ("tna_plan.py", "order_api.py"):
        t = open(os.path.join(os.path.dirname(HERE), fn)).read()
        if re.search(r'"doctype":\s*"(TNA Milestone|Order TNA)"', t) or re.search(r'op"\s*:\s*"(insert|save)"[^}]*"(TNA Milestone)"', t):
            hits.append(fn)
# KNOWN EXCEPTION (logged in ORDER_TO_SHIP_STATUS.md, not fixed in T0/T1): the legacy calendar edit `cortex_api.cx_tna_push_milestone` still saves a TNA
# Milestone itself. It must be folded into tna_plan.py (with the per-field allowlist) before the legacy calendar is retired. The test pins it so that it
# cannot spread: any OTHER module that starts writing a TNA doctype fails here.
check("no module other than tna_plan.py / order_api.py names a TNA doctype in a write, except the known legacy cx_tna_push_milestone", hits == ["cortex_api.py"], hits)
oa = open(os.path.join(os.path.dirname(HERE), "order_api.py")).read()
check("order_api writes Order TNA only through the pipeline (deals._ex), never a backend primitive", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", oa))

# roles: a person without the merchandiser / planner / manager role cannot change a date
try:
    order_api._t_planner({"roles": ["QC"], "is_admin": False})
    check("QC cannot make, lock or revise a plan", False)
except guardrails.Denied:
    check("QC cannot make, lock or revise a plan", True)
try:
    order_api._t_planner({"roles": ["Merchandiser"], "is_admin": False})
    check("a merchandiser can", True)
except guardrails.Denied:
    check("a merchandiser can", False)

# lock / revise with the ERP stubbed
calls = []


def fake_ex(db, me, req, **kw):
    calls.append(req)
    return {"ok": True, "result": {"revised": 1}}


deals._ex = fake_ex
db = get_session()
TNA = {"name": "TNA-1", "sales_order": "SO-1", "style_item": "S", "colour": "C", "ex_factory_date": "2027-03-20", "order_received_date": "2026-11-09", "baseline_locked": 0}
today = date(2026, 11, 9)
plan = tna_plan.compute(TNA, [], today)
rows_all = [{"milestone_type": c, "planned_date": str(plan["tasks"][c]["planned_finish"]), "planned_start": str(plan["tasks"][c]["planned_start"]), "actual_date": None, "partial": 0,
             "not_applicable": 0, "revised_date": None} for c in plan["order"]]
me = {"email": "m@test.local", "roles": ["Merchandiser"], "is_admin": False}
mgr = {"email": "boss@test.local", "roles": ["Management"], "is_admin": False}
r = tna_plan.lock(db, me, None, TNA, rows_all[:10], plan)
check("lock refused while the plan is not fully written to the ERP", not r["ok"] and "not written" in r["error"], r)
r = tna_plan.lock(db, me, None, TNA, rows_all, plan)
check("lock: version 1 stored, the ERP's lock script run through the pipeline", r["ok"] and r["version"] == 1 and calls[-1]["method"] == "arinox_order_tna_lock_baseline", r)
b = db.query(PlanBaselineModel).first()
check("the baseline snapshot holds every milestone's planned dates", b and len(b.rows()) == 63 and b.locked_by == "m@test.local")
r = tna_plan.lock(db, me, None, {**TNA, "baseline_locked": 1}, rows_all, plan)
check("a locked plan cannot be locked again", not r["ok"] and "already locked" in r["error"])
tight = tna_plan.compute({**TNA, "ex_factory_date": "2027-01-10"}, [], today)
r = tna_plan.lock(db, me, None, {**TNA, "ex_factory_date": "2027-01-10", "name": "TNA-2"}, rows_all, tight)
check("an infeasible plan cannot be locked and says by how many working days", not r["ok"] and "13 working days" in r["error"], r)

LOCKED = {**TNA, "baseline_locked": 1}
lp = tna_plan.compute(LOCKED, rows_all, today)
check("a locked plan is measured against the frozen planned dates", lp["tasks"]["CUT_START"]["planned_finish"] == plan["tasks"]["CUT_START"]["planned_finish"])
r = tna_plan.revise(db, me, None, LOCKED, rows_all, lp, "FABRIC_IN_HOUSE", "2027-02-27", "", "late")
check("a revision needs a party (Buyer, Supplier, Factory, Logistics, Other)", not r["ok"] and "who caused it" in r["error"].lower())
r = tna_plan.revise(db, me, None, LOCKED, rows_all, lp, "FABRIC_IN_HOUSE", "2027-02-27", "Supplier", "  ")
check("a revision needs a written reason", not r["ok"] and "reason" in r["error"])
r = tna_plan.revise(db, me, None, LOCKED, rows_all, lp, "FABRIC_IN_HOUSE", "2027-02-27", "Supplier", "Mill delayed dyeing")
check("a merchandiser's move that changes the ship date needs a manager (nothing written)", not r["ok"] and r.get("need_approval") and r["ship_after"] > r["ship_before"], r)
n_calls = len(calls)
r = tna_plan.revise(db, mgr, None, LOCKED, rows_all, lp, "FABRIC_IN_HOUSE", "2027-02-27", "Supplier", "Mill delayed dyeing")
check("a manager's revision is written (revised date + reason) and kept with ship impact", r["ok"] and len(calls) == n_calls + 1 and calls[-1]["params"]["rows"][0]["revised_date"] == "2027-02-27" and "Supplier" in calls[-1]["params"]["reason"], r)
rv = db.query(PlanRevisionModel).first()
check("the revision row says who, why, party and the ship impact", rv and rv.reason_code == "Supplier" and rv.approved_by == "boss@test.local" and rv.ship_impact_wd > 0, rv and rv.ship_impact_wd)
check("the planned date sent never moves on a locked plan", calls[-1]["params"]["rows"][0]["planned_date"] == str(plan["tasks"]["FABRIC_IN_HOUSE"]["planned_finish"]))
r = tna_plan.revise(db, mgr, None, LOCKED, rows_all, lp, "PP_MEETING", "2027-02-17", "Buyer", "same day move")
check("a move inside the float that does not change the ship date needs no approval", r["ok"] or r.get("need_approval") is not True, r)
done = [dict(x, actual_date="2027-02-18") if x["milestone_type"] == "FABRIC_IN_HOUSE" else x for x in rows_all]
r = tna_plan.revise(db, mgr, None, LOCKED, done, tna_plan.compute(LOCKED, done, today), "FABRIC_IN_HOUSE", "2027-03-01", "Supplier", "x")
check("a done milestone's actual is not a plan date", not r["ok"] and "done" in r["error"])
r = tna_plan.revise(db, mgr, None, LOCKED, rows_all, lp, "NOPE", "2027-03-01", "Supplier", "x")
check("an unknown milestone is refused", not r["ok"])

import config  # noqa: E402
check("the demo order is OFF by default (TNA plan G25: a client-facing app never shows a demo order as real)", config.TNA_SAMPLE_WHEN_EMPTY is False)
check("...and in the embedded T&A app", 'or "0").strip() == "1"' in open(os.path.join(os.path.dirname(HERE), "tna_app", "config.py")).read())

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
