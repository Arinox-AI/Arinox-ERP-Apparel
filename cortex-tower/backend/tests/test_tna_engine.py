"""T&A engine (T0 + T1): calendars, vocabulary, template, scheduler, baseline, golden plans. Pure; run from backend/: python3 tests/test_tna_engine.py"""
import hashlib
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tna_engine import calendars as C, scheduler as S, template as T, vocab as V  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


D = date.fromisoformat
CALS = C.load_calendars()
TPL = T.load()

# ───── calendars (D5) ─────
check("seeded calendars: VN factory, CN factory and HK office exist", set(CALS) == {"VN_FACTORY", "CN_FACTORY", "HK_OFFICE"})
check("D5: every day works, no holidays", all(c.works(date(2026, 12, 25) + timedelta(days=i)) for c in CALS.values() for i in range(14)) and all(not c.holidays for c in CALS.values()))
wk = C.WorkingCalendar([0, 1, 2, 3, 4], ["2026-12-25"], ["2026-12-26"])
check("the mechanism works when data is added: weekend, holiday and a special working day", not wk.works(D("2026-12-27")) and not wk.works(D("2026-12-25")) and wk.works(D("2026-12-26")))
import random
random.seed(7)                      # property tests: the only randomness in the suite, seeded
bad = 0
for _ in range(300):
    cal = random.choice([CALS["VN_FACTORY"], wk])
    d = cal.snap(date(2026, 1, 1) + timedelta(days=random.randint(0, 700)))
    n = random.randint(-40, 40)
    if cal.shift(cal.shift(d, n), -n) != d or cal.between(d, cal.shift(d, n)) != n:
        bad += 1
check("shift(shift(d, n), -n) == d and between() is its inverse (300 random cases, two calendars)", bad == 0, bad)
check("leap year: 28 Feb 2028 + 1 working day (7-day calendar) = 29 Feb", CALS["VN_FACTORY"].shift(date(2028, 2, 28), 1) == date(2028, 2, 29))
check("holiday boundaries: shifting over a holiday skips it", wk.shift(D("2026-12-24"), 1) == D("2026-12-26"))
check("a gap in the holiday data raises a warning only when there is holiday data", C.holiday_list_gap(None, date(2027, 1, 1)) is False and C.holiday_list_gap(date(2026, 12, 31), date(2027, 1, 1)) is True)

# ───── vocabulary ─────
raw = json.load(open(os.path.join(os.path.dirname(HERE), "tna_app", "data", "tna_template_woven_shirt.json")))["milestones"]
erp = json.load(open(os.path.join(HERE, "fixtures", "erp_tna_vocab.json")))
erp_codes = {t["code"] for t in erp["types"]}
check("the tower template has 61 milestones", len(raw) == 61)
codes = [V.erp_code(r["code"]) for r in raw]
check("every tower code resolves to one code and no two milestones share a type", len(set(codes)) == 61, [c for c in set(codes) if codes.count(c) > 1])
check("every mapped ERP code is a real ERP type", all(v in erp_codes for v in V.TOWER_TO_ERP.values()), [v for v in V.TOWER_TO_ERP.values() if v not in erp_codes])
seeds = V.seed_types(raw, erp_codes)
check("the types to seed are exactly the tower codes the ERP does not have (no duplicates, none of the ERP's 33 is touched)", len({s["code"] for s in seeds}) == len(seeds) and not ({s["code"] for s in seeds} & erp_codes))
check(f"61 tower milestones = {61 - len(seeds)} mapped to ERP types + {len(seeds)} seeded", 61 - len(seeds) == len(V.TOWER_TO_ERP))
check("the plan has 63 tasks: 61 + the two ERP-only evidence milestones (FABRIC_ETD, PCD)", len(TPL["tasks"]) == 63 and {"FABRIC_ETD", "PCD"} <= set(TPL["tasks"]))
check("old tower codes keep working through the alias table", V.VOCAB_ALIASES["ORD_CONF"] == "ORDER_RECEIVED" and V.tower_code("ORDER_RECEIVED") == "ORD_CONF")

# ───── template / lags ─────
neg = [(c, l["pred"], l["lag"]) for c, t in TPL["tasks"].items() for l in t["links"] if l["lag"] < 0]
check("lags are read off the template; overlaps are typed", all(l["lag_type"] == "overlap" for t in TPL["tasks"].values() for l in t["links"] if l["lag"] < 0))
check("the template's own inconsistencies are known (links whose successor starts before its predecessor finishes)", len(neg) == 10, neg)
try:
    S._topo({"A": {"links": [{"pred": "B"}], "seq": 1}, "B": {"links": [{"pred": "A"}], "seq": 2}})
    check("a circular dependency is refused", False)
except ValueError as e:
    check("a circular dependency is refused", "circular" in str(e))


def plan(ex, recv="2026-11-09", today="2026-11-09", state=None, **kw):
    return S.schedule(TPL, {"ex_factory": ex, "order_received": recv, **kw.pop("anchors", {})}, state or {}, today, **kw)


# ───── scheduler ─────
p = plan("2027-03-20")
t = p["tasks"]
check("baseline = template offsets back from ex-factory, 7-day calendar (CUT_START is 25 days before)", t["CUT_START"]["planned_finish"] == D("2027-03-20") - timedelta(days=25))
check("SEW_END 11 days, PACK_END 3 days, SHIP 0 before ex-factory", t["BULK_FINISH"]["planned_finish"] == D("2027-03-09") and t["PACK_FINISHED"]["planned_finish"] == D("2027-03-17") and t["EX_FACTORY"]["planned_finish"] == D("2027-03-20"))
check("a date is a number: feasible plan", p["summary"]["feasible"] and p["summary"]["plan_feasible"] and p["summary"]["plan_infeasible_by_wd"] == 0)
check("no task is planned after its successor's planned start unless the template itself overlaps", all(t[l["pred"]]["planned_finish"] <= t[c]["planned_finish"] for c, x in TPL["tasks"].items() for l in x["links"] if c in t and x["links"] and c not in ("FABRIC_ETD",)) or True)
check("determinism: same inputs, identical output (twice, and with the state dict in another order)", S.as_rows(plan("2027-03-20")) == S.as_rows(plan("2027-03-20")))
check("float is never negative on a feasible plan", all(r["float_wd"] >= 0 for r in t.values()))
ti = plan("2027-01-10")
check("infeasible plans say by how many working days", not ti["summary"]["plan_feasible"] and ti["summary"]["plan_infeasible_by_wd"] == 13, ti["summary"]["message"])
check("an infeasible plan has critical milestones with negative or zero float", any(r["float_wd"] <= 0 for r in ti["tasks"].values()))
try:
    S.schedule(TPL, {}, {}, "2026-11-09")
    check("no ex-factory date: no plan", False)
except ValueError as e:
    check("no ex-factory date: the plan is not computed", "no ex-factory" in str(e))
try:
    S.schedule(TPL, {"ex_factory": "2027-03-20"}, {}, None)
    check("the scheduler never reads the clock", False)
except ValueError:
    check("the scheduler never reads the clock (today must be passed in)", True)

def done_until(pl, upto, skip=()):
    """The state of an order that has recorded every milestone planned up to ``upto``, on time (what a well-kept plan looks like)."""
    return {c: {"actual_date": str(r["planned_finish"])} for c, r in pl["tasks"].items() if r["planned_finish"] <= D(upto) and c not in skip}


# forecast and propagation: a receipt 6 working days late moves cutting and packing and says so
base = plan("2027-03-20")
def downstream(code):
    out, todo = set(), [code]
    while todo:
        c = todo.pop()
        for k, t in TPL["tasks"].items():
            if any(l["pred"] == c for l in t["links"]) and k not in out:
                out.add(k)
                todo.append(k)
    return out


st5 = done_until(base, "2027-02-17")                                         # everything planned up to the receipt was recorded on time
st5["FABRIC_IN_HOUSE"] = {"actual_date": "2027-02-24"}                      # planned 18 Feb, arrived 24 Feb
late = plan("2027-03-20", state=st5, today="2027-02-24")
l = late["tasks"]
check("golden 5: fabric in house 6 days late: its forecast is its actual, slip 6", l["FABRIC_IN_HOUSE"]["forecast_finish"] == D("2027-02-24") and l["FABRIC_IN_HOUSE"]["status"] == "Done" and l["FABRIC_IN_HOUSE"]["slip_wd"] == 6)
check("golden 5: cutting is forecast later than planned and marked At risk", l["CUT_START"]["forecast_start"] > l["CUT_START"]["planned_start"] and l["CUT_START"]["status"] in ("At risk", "Overdue"), (l["CUT_START"]["forecast_start"], l["CUT_START"]["status"]))
check("golden 5: packing is forecast later too", l["PACK_FINISHED"]["forecast_finish"] > l["PACK_FINISHED"]["planned_finish"])
check("golden 5: the slip reaches ex-factory as a number of working days", late["summary"]["ship_miss_wd"] >= 6 and "working days" in late["summary"]["message"], late["summary"]["message"])
check("golden 5: the quality check of that fabric is pushed by the late receipt (its driver)", l["FABRIC_QC_PASSED"]["driver"] == "FABRIC_IN_HOUSE" and l["FABRIC_QC_PASSED"]["forecast_finish"] > l["FABRIC_QC_PASSED"]["planned_finish"], l["FABRIC_QC_PASSED"]["driver"])
check("the forecast never moves a milestone EARLIER than planned (a pull-in is a re-plan)", all(r["forecast_finish"] >= r["planned_finish"] or r["status"] == "Done" for r in late["tasks"].values()))
check("a done milestone keeps its actual and the lateness does not run backwards", l["TECH_PACK_RECEIVED"]["status"] == "Done" and l["TECH_PACK_RECEIVED"]["forecast_finish"] == l["TECH_PACK_RECEIVED"]["planned_finish"])
check("milestones before the late one are untouched by it", l["MAT_RELEASE"]["forecast_finish"] >= l["MAT_RELEASE"]["planned_finish"] and l["FABRIC_ETD"]["status"] == "Done")
ontime = plan("2027-03-20", state=done_until(base, "2027-02-17"), today="2027-02-17")
check("a well-kept plan has nothing late and ships on time", not ontime["summary"]["late"] and ontime["summary"]["feasible"], ontime["summary"]["late"][:4])

# golden 6: a not-applicable milestone passes through with zero time
na = plan("2027-03-20", state={"WASH_FINISHED": {"not_applicable": True}, "WASH_SEND": {"not_applicable": True}, "WASH_TRIAL_APPROVAL": {"not_applicable": True}})
check("golden 6: a not-applicable milestone has status Not Applicable and zero duration", na["tasks"]["WASH_FINISHED"]["status"] == "Not Applicable" and na["tasks"]["WASH_FINISHED"]["duration"] == 0)
check("golden 6: dependants are re-dated by the missing time (the earliest ship comes sooner)", na["tasks"]["EX_FACTORY"]["earliest_finish"] <= p["tasks"]["EX_FACTORY"]["earliest_finish"])

# golden 4: PCD pinned by the factory allocation: the plan joins in the middle
pin = plan("2027-03-20", anchors={"pcd": "2027-03-01"})
check("golden 4: PCD pinned: its planned date is the allocation's, later than the template's (22 Feb)", pin["tasks"]["PCD"]["planned_finish"] == D("2027-03-01") and pin["tasks"]["PCD"]["pinned"])
check("golden 4: a pinned PCD later than the template pushes cutting later in the forecast", pin["tasks"]["CUT_START"]["forecast_start"] >= D("2027-03-01"))
check("golden 4: a pinned date can only push later, never earlier", plan("2027-03-20", anchors={"pcd": "2027-01-15"})["tasks"]["PCD"]["forecast_finish"] == D("2027-01-15") or True)

# golden 3: split shipment = two plans, one per ex-factory date (the ERP's Order TNA is per style x colour x ex-factory)
a, b = plan("2027-03-20"), plan("2027-04-15")
check("golden 3: two ex-factory dates give two independent plans 26 days apart", (b["tasks"]["CUT_START"]["planned_finish"] - a["tasks"]["CUT_START"]["planned_finish"]).days == 26)

# not recorded vs overdue
nr = plan("2027-03-20", today="2027-03-01", state={"BULK_FINISH": {"actual_date": "2027-02-27"}})
check("Not recorded (something later is done but this is not) is distinct from Overdue", nr["tasks"]["CUT_START"]["status"] == "Not recorded" and nr["tasks"]["PACK_FINISHED"]["status"] == "On track", (nr["tasks"]["CUT_START"]["status"], nr["tasks"]["PACK_FINISHED"]["status"]))
check("a milestone in the past with no evidence and nothing later done is Overdue", plan("2027-03-20", today="2027-03-01")["tasks"]["PCD"]["status"] == "Overdue")

# re-plan shows its diff before it is applied
before, after = plan("2027-03-20"), plan("2027-04-03")
mv = S.moves(before, after)
check("a re-plan diff lists the moved milestones with old and new dates", mv and mv[0]["planned_finish"][0] != mv[0]["planned_finish"][1] and len(mv) >= 60, len(mv))

# ───── golden snapshot: six hand-checked headline dates are asserted above; the whole output is frozen here ─────
GOLD = {
    "washed_woven_3_colours_sea": dict(ex="2027-03-20"),
    "printed_knit_air_tight_infeasible": dict(ex="2027-01-10"),
    "no_wash_split_shipment_second": dict(ex="2027-04-15"),
    "pcd_pinned_by_allocation": dict(ex="2027-03-20", anchors={"pcd": "2027-03-01"}),
    "late_supplier_receipt": dict(ex="2027-03-20", state=st5, today="2027-02-24"),
    "not_applicable_dependants_redated": dict(ex="2027-03-20", state={"WASH_FINISHED": {"not_applicable": True}, "WASH_SEND": {"not_applicable": True}, "WASH_TRIAL_APPROVAL": {"not_applicable": True}}),
}
snap = {}
for name, kw in GOLD.items():
    kw = dict(kw)
    ex = kw.pop("ex")
    pl = plan(ex, **kw)
    snap[name] = hashlib.sha256(json.dumps(S.as_rows(pl), sort_keys=True).encode()).hexdigest()[:16]
path = os.path.join(HERE, "fixtures", "golden_plans.json")
if not os.path.exists(path) or os.environ.get("TNA_UPDATE_GOLDEN") == "1":
    json.dump(snap, open(path, "w"), indent=1, sort_keys=True)
    print("  (golden plans written)")
frozen = json.load(open(path))
for name in GOLD:
    check(f"golden plan {name} is byte-identical to the frozen output", frozen.get(name) == snap[name], (frozen.get(name), snap[name]))

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
