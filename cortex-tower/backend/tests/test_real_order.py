"""A real order (anonymised, tests/fixtures/real_order_a.json) run through the allocation suggester and, in T1, the T&A scheduler.

The point is to check the model against what actually happened on the floor, not only against itself.
Run from backend/:  python3 tests/test_real_order.py
"""
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import allocation as A  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    print(("  ok   " if cond else "  FAIL ") + label + ("" if cond else f"  {extra}"))


F = json.load(open(os.path.join(HERE, "fixtures", "real_order_a.json")))
qty = sum(x["qty"] for x in F["order_lines"])
CURVE = [[1, 53.85], [2, 69.23], [3, 84.62], [4, 92.31], [5, 100]]


def ctx(today, **kw):
    c = {"today": today, "order_lines": [{"style_item": F["style"], "colour": F["colour"], "qty": qty, "ex_factory_date": F["ex_factory"]}],
         "factories": [{"name": "F1", "lines": [{"name": "L6", "status": "Production", "line_type": "Sewing", **F["line"]}]}],
         "obs": {F["style"]: F["operation_bulletin"]}, "defaults": {}, "style_product_type": {},
         "settings": {"work_minutes_per_day": 480, "planned_efficiency_pct": 65, "learning_curve": CURVE, "min_batch_qty": 500, "finish_pack_days": 9, "cut_lead_days": 4},
         "other_allocations": [], "calendar": {}}
    c.update(kw)
    return c


R = F["real"]
spec = A.style_spec(ctx("2026-04-13"), F["style"])
full = A.full_day_pcs(F["line"], spec)
check(f"capacity from the real bulletin: {full:.1f} pcs/day at 100% (28 workers x 570 min x 65% / 10.6 SAM = 978.7)", abs(full - 978.679) < 0.01, full)

# 1 · fabric in house on 13 Apr, order for 4 May: the suggester says it fits, tightly
r = A.suggest(ctx(R["fabric_received"]))
ln = r["lines"][0] if r["lines"] else None
check("with fabric in on 13 Apr the order fits on its one line", ln is not None and not r["shortfalls"], r["shortfalls"])
span = (date.fromisoformat(ln["sewing_end"]) - date.fromisoformat(ln["sewing_start"])).days + 1
check(f"predicted sewing span {span} days (real span with output: {R['sewing_days_with_output']} days)", 5 <= span <= 11, span)
print("       suggestion:", ln["reason"])

# 2 · the model against the floor: real median output was 710 pcs/day against the 979 target
ratio = R["sewn_per_day_median"] / full
check(f"real median output is {ratio:.0%} of the planned target (so planned 65% is optimistic by about {1/ratio:.2f}x for this style)", 0.6 < ratio < 0.85, ratio)
check("the real best day (1001) is at the planned target (979): the target is a ceiling, not an average", R["sewn_per_day_max"] >= full * 0.98)

# 3 · what really happened: fabric was only issued on 5 May. Planned from that day the order cannot make 4 May: a shortfall with a date
r2 = A.suggest(ctx(R["fabric_issued"]))
sf = r2["shortfalls"][0] if r2["shortfalls"] else None
check("planned from the real fabric-issue date the order is a shortfall (as it was: 28 days after the contract date)", sf is not None, r2["lines"])
if sf:
    print("       shortfall:", sf["reason"])
    real_packed = date.fromisoformat(R["last_packed"])
    feasible = date.fromisoformat(sf["earliest_ex_factory"])
    check(f"earliest feasible ex-factory {feasible} vs what happened (last packed {real_packed}): the model is {(real_packed - feasible).days} days faster than the floor",
          0 <= (real_packed - feasible).days <= 25, (real_packed - feasible).days)

# 4 · at the efficiency the floor really achieved (47%) the same order is one day late: the suggester flags the risk instead of promising it
slow = ctx(R["fabric_received"]); slow["obs"][F["style"]] = {**F["operation_bulletin"], "expected_efficiency_pct": 47}
r3 = A.suggest(slow)
check("at 47% efficiency the order is flagged as 1 day late (a shortfall with a date), not promised",
      not r3["lines"] and r3["shortfalls"] and r3["shortfalls"][0]["earliest_ex_factory"] == "2026-05-05", r3["shortfalls"])

# ───── T1: the same real order through the T&A scheduler ─────
from tna_engine import scheduler as S, template as T  # noqa: E402
TPL = T.load()
real_state = {"ORDER_RECEIVED": {"actual_date": F["contract_date"]}, "FABRIC_IN_HOUSE": {"actual_date": R["fabric_received"]},
              "CUT_START": {"actual_date": R["first_cut"]}, "SEW_START": {"actual_date": R["sewing_first"]}, "BULK_FINISH": {"actual_date": R["sewing_last"]},
              "PACK_FINISHED": {"actual_date": R["last_packed"]}}
pl = S.schedule(TPL, {"ex_factory": F["ex_factory"], "order_received": F["contract_date"]}, real_state, "2026-06-02")
t = pl["tasks"]
d = lambda a, b: (a - b).days
print("       planned (template) vs real, in days:")
for code in ("FABRIC_IN_HOUSE", "CUT_START", "SEW_START", "BULK_FINISH", "PACK_FINISHED"):
    print(f"         {code:16s} planned {t[code]['planned_finish']}  real {t[code]['actual_date']}  slip {t[code]['slip_wd']} d")
check("fabric in-house was planned 4 Apr by the template and came on 13 Apr (9 days late)", t["FABRIC_IN_HOUSE"]["slip_wd"] == 9, t["FABRIC_IN_HOUSE"]["slip_wd"])
check("cutting started 27 days after the template's CUT_START (the 22 days waiting between fabric receipt and fabric issue)", 24 <= t["CUT_START"]["slip_wd"] <= 30, t["CUT_START"]["slip_wd"])
check("packing finished 31 days after the template's PACK_END, and the plan says so as a number", 28 <= t["PACKED_FINISHED" if False else "PACK_FINISHED"]["slip_wd"] <= 34, t["PACK_FINISHED"]["slip_wd"])
check("the scheduler's forecast for this order is its real last-packed date (no estimate once the actual is in)", t["PACK_FINISHED"]["forecast_finish"] == date.fromisoformat(R["last_packed"]))
# the plan made on the day the contract was signed, with nothing recorded yet: feasible on paper (84 days available, 75 needed)
at_signing = S.schedule(TPL, {"ex_factory": F["ex_factory"], "order_received": F["contract_date"]}, {}, F["contract_date"])
check("on the day the contract was signed the template said feasible (99 days to ex-factory, 75 needed)", at_signing["summary"]["plan_feasible"], at_signing["summary"]["message"])

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
