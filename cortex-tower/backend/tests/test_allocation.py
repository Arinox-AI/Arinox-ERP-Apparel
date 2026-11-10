"""The allocation suggester: capacity, fit, split, shortfall, learning curve, determinism, unknown capacity (pure, no ERP).

Run from backend/:  python3 tests/test_allocation.py
"""
import copy
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import allocation as A  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


CURVE = [[1, 53.85], [2, 69.23], [3, 84.62], [4, 92.31], [5, 100]]
TODAY = date(2026, 11, 9)


def ctx(**kw):
    c = {"today": "2026-11-09",
         "order_lines": [{"style_item": "ST1", "colour": "RED", "qty": 2000, "ex_factory_date": "2027-02-15", "ship_to": "", "buyer_po": ""}],
         "factories": [{"name": "F1", "lines": [{"name": "F1-L1", "operators": 21, "helpers": 7, "line_type": "Sewing", "status": "Production"},
                                                {"name": "F1-L2", "operators": 21, "helpers": 7, "line_type": "Sewing", "status": "Production"}]}],
         "obs": {"ST1": {"total_sam": 24.4, "sewing_sam": 18.8, "expected_efficiency_pct": 65, "working_minutes": 480, "operators": 28}},
         "defaults": {}, "style_product_type": {"ST1": "Knit Top"},
         "settings": {"work_minutes_per_day": 480, "planned_efficiency_pct": 65, "learning_curve": CURVE, "min_batch_qty": 500,
                      "finish_pack_days": 9, "cut_lead_days": 4},
         "other_allocations": [], "calendar": {}}
    c.update(kw)
    return c


# 1 · the capacity formula reproduces the company's operation bulletin sheet (28 workers, 480 min, 65 %, 24.4 SAM -> 358.03 pcs/day)
spec = A.style_spec(ctx(), "ST1")
full = A.full_day_pcs({"operators": 21, "helpers": 7}, spec)
check("capacity = workers x minutes x eff / SAM (358.03)", abs(full - 358.0327868852459) < 1e-6, full)
check("the sheet's second style (570 min, 17.2 SAM) gives 603.14", abs(A.full_day_pcs({"operators": 21, "helpers": 7}, {"sam": 17.2, "eff": 65, "minutes": 570, "ob_operators": 0}) - 603.1395348837209) < 1e-6)
check("Workstation.production_capacity is never read as pieces", A.full_day_pcs({"production_capacity": 1, "operators": 0, "helpers": 0}, {**spec, "ob_operators": 0}) == 0)

# 2 · learning curve
check("learning curve day 1 = 53.85 %", A.learning_pct(CURVE, 1) == 53.85)
check("day 3 = 84.62, day 5 = 100, day 40 = 100", (A.learning_pct(CURVE, 3), A.learning_pct(CURVE, 5), A.learning_pct(CURVE, 40)) == (84.62, 100.0, 100.0))
check("no curve = 100 % every day", A.learning_pct([], 1) == 100.0)
cal = A.Calendar()
fin = A._simulate(date(2026, 12, 1), 358.0327868852459 * 5, full, CURVE, cal, {}, date(2027, 3, 1))
fin_flat = A._simulate(date(2026, 12, 1), 358.0327868852459 * 5, full, [], cal, {}, date(2027, 3, 1))
check("the learning curve makes the first days slower (5 flat days need 6 with the curve)", fin_flat == date(2026, 12, 5) and fin == date(2026, 12, 6), (fin, fin_flat))

# 3 · fit on one line, dates follow the section 5 rules
r = A.suggest(ctx())
check("one line takes the whole style x colour", len(r["lines"]) == 1 and r["lines"][0]["qty"] == 2000 and not r["shortfalls"], r)
ln = r["lines"][0]
check("sewing_end = ex-factory - finish_pack_days (15 Feb - 9 = 6 Feb)", ln["sewing_end"] <= "2027-02-06" and ln["sewing_end"] >= "2027-02-05", ln["sewing_end"])
check("pcd = sewing_start - cut_lead_days", date.fromisoformat(ln["sewing_start"]) - date.fromisoformat(ln["pcd"]) == (date(2027, 1, 2) - date(2026, 12, 29)), ln)
check("every day works (D5): 2000 pcs at 358/day with the curve is 7 days", len(A.Calendar().days(date.fromisoformat(ln["sewing_start"]), date.fromisoformat(ln["sewing_end"]))) == 7, ln)
check("the reason sentence names line, factory, dates and basis", all(x in ln["reason"] for x in ("F1-L1", "F1", "pcs/day", "28 workers", "24.4 SAM", "operation bulletin")), ln["reason"])
check("ties go to the first line by name (deterministic)", ln["line"] == "F1-L1")

# 4 · determinism: the same input, the same draft, byte for byte
a, b = A.suggest(ctx()), A.suggest(copy.deepcopy(ctx()))
check("deterministic", a == b)
rev = ctx(); rev["factories"][0]["lines"].reverse(); rev["order_lines"] = rev["order_lines"][::-1]
check("deterministic whatever the order of the input", A.suggest(rev)["lines"] == a["lines"])

# 5 · load already on a line moves the work to the free one
busy = ctx(other_allocations=[{"line": "F1-L1", "qty": 40000, "sewing_start": "2026-11-10", "sewing_end": "2027-02-06", "style_item": "OTHER"}])
r = A.suggest(busy)
check("a loaded line is avoided", r["lines"][0]["line"] == "F1-L2", r["lines"])
check("other load is spread over working days", abs(sum(A.line_load(busy, A.Calendar())["F1-L1"].values()) - 40000) < 1e-6)

# 6 · split: one style x colour too big for any one line goes over lines, each part above the minimum batch
big = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 20000, "ex_factory_date": "2027-01-05"}])
r = A.suggest(big)
check("too big for one line: split over both lines", len(r["lines"]) == 2 and sum(x["qty"] for x in r["lines"]) == 20000 and not r["shortfalls"], r)
check("each part respects the minimum batch", all(x["qty"] >= 500 for x in r["lines"]))
check("a split says why", all("split" in x["reason"] for x in r["lines"]))
one_ln = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 20000, "ex_factory_date": "2027-01-05"}])
one_ln["factories"][0]["lines"] = one_ln["factories"][0]["lines"][:1]
r = A.suggest(one_ln)
check("one line only and not enough: a shortfall, not an over-load", not r["lines"] and len(r["shortfalls"]) == 1, r)
sf = r["shortfalls"][0]
check("the shortfall carries the earliest feasible ex-factory, after the asked date", sf["earliest_ex_factory"] and sf["earliest_ex_factory"] > "2027-01-05", sf)
check("the shortfall explains itself", "late" in sf["reason"] and "F1-L1" in sf["reason"], sf["reason"])
check("agent_notes carries the shortfall", "SHORTFALL" in r["notes"])

# 7 · a sliver below the minimum batch is not placed on a line of its own
sl = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 4000, "ex_factory_date": "2027-01-20"}])
r = A.suggest(sl)
check("no part below the minimum batch (or the whole group is reported short)", all(x["qty"] >= 500 for x in r["lines"]) and (sum(x["qty"] for x in r["lines"]) == 4000 or r["shortfalls"]), r)

# 8 · capacity unknown is never silently used
nosam = ctx(obs={}, defaults={})
r = A.suggest(nosam)
check("no SAM anywhere: nothing placed", not r["lines"] and r["shortfalls"] and "unknown" in r["shortfalls"][0]["reason"].lower(), r)
check("setup checklist names the missing SAM", any("no SAM" in s for s in r["setup"]), r["setup"])
nops = ctx(); nops["factories"][0]["lines"][0].update(operators=0, helpers=0)
nops["obs"]["ST1"]["operators"] = 0
r = A.suggest(nops)
check("a line with no operators is named as unknown and skipped", any("F1-L1" in u and "unknown" in u for u in r["unknown_lines"]) and r["lines"][0]["line"] == "F1-L2", r)
dflt = ctx(obs={}, defaults={"Knit Top": {"sewing_sam": 17.2, "efficiency_pct": 65}})
r = A.suggest(dflt)
check("Product Type default SAM used when there is no bulletin", r["lines"] and "default for Knit Top" in r["lines"][0]["reason"], r)
nof = ctx(factories=[])
r = A.suggest(nof)
check("no factories: setup note, no invention", not r["lines"] and any("Plant Floor" in s for s in r["setup"]), r)

# 9 · line type fit ranks first
lt = ctx(); lt["factories"][0]["lines"][0]["line_type"] = ""
r = A.suggest(lt)
check("a Sewing line wins over an earlier-named line whose type is not recorded", r["lines"][0]["line"] == "F1-L2", r["lines"])
lt["factories"][0]["lines"][1]["line_type"] = "Packing"
r = A.suggest(lt)
check("a Packing line is never used to sew", r["lines"][0]["line"] == "F1-L1", r["lines"])

# 10 · same factory for all colours of a style
two = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 1000, "ex_factory_date": "2027-02-15"}, {"style_item": "ST1", "colour": "BLUE", "qty": 1000, "ex_factory_date": "2027-02-15"}])
two["factories"].append({"name": "F0", "lines": [{"name": "F0-L1", "operators": 21, "helpers": 7, "line_type": "Sewing", "status": "Production"}]})
r = A.suggest(two)
check("both colours of a style land in one factory", len({x["factory"] for x in r["lines"]}) == 1, r["lines"])

# 11 · calendars: D5 says no holidays, but the mechanism works as data
hol = A.Calendar(weekend=(5, 6), holidays=["2026-12-25"])
check("weekend and holidays are skipped when given", hol.add(date(2026, 12, 24), 1) == date(2026, 12, 28) and hol.add(date(2026, 12, 28), -1) == date(2026, 12, 24))
check("default calendar: every day works", A.Calendar().add(date(2026, 12, 25), 3) == date(2026, 12, 28) and A.Calendar().works(date(2026, 12, 26)))
w = ctx(calendar={"weekend": [5, 6]})
check("a weekend rule pushes sewing_end back", A.suggest(w)["lines"][0]["sewing_end"] <= A.suggest(ctx())["lines"][0]["sewing_end"])

# 12 · past or missing dates
past = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 2000, "ex_factory_date": "2026-11-12"}])
r = A.suggest(past)
check("an ex-factory already too close is a shortfall with the earliest feasible date", not r["lines"] and r["shortfalls"] and r["shortfalls"][0]["earliest_ex_factory"] > "2026-11-12", r)
nod = ctx(order_lines=[{"style_item": "ST1", "colour": "RED", "qty": 100, "ex_factory_date": None}])
check("no ex-factory date: reported, never guessed", A.suggest(nod)["shortfalls"][0]["reason"].startswith("No ex-factory"))
check("pcd is never before today", all(x["pcd"] >= "2026-11-10" for x in A.suggest(ctx())["lines"]))
check("lines that are Off or in Maintenance are not used", not A.suggest(ctx(factories=[{"name": "F1", "lines": [{"name": "X", "operators": 21, "helpers": 7, "status": "Maintenance"}]}]))["lines"])

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
