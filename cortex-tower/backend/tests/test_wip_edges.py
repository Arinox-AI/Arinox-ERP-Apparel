"""Edge-case tests for the WIP engine — synthetic rows, so nothing is written to the ERP and nothing to clean up.

The Gantt and the analytics are pure functions over lane dictionaries, so every edge case the client listed can be
built as a dictionary here instead of as a document on the live site. That is deliberate: a seeded *document*
would have to be submitted to be realistic (and submitted documents cannot be deleted — RULES/01 #97), so the
engine is tested in memory and the **live** reconciliation is asserted separately at the end.

    python3 tests/test_wip_edges.py

Covered
    null dates · end before start · zero duration · dependency order · future-dated actual · duplicate line
    over-production · divide-by-zero · negative WIP · a stage with no date · a ship date in the past
"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import wip_analytics as A                                          # noqa: E402
import wip_plan                                                    # noqa: E402

passed = failed = 0
TODAY = date(2026, 11, 3)


def ok(cond, what, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"   ok   {what}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"   FAIL {what}" + (f"  [{detail}]" if detail else ""))


def bar(milestone, start=None, end=None, status="Pending", actual=None, dept="Production Planner",
        window=0, marker=False, critical_now=False):
    return {"milestone": milestone, "department": dept, "start": start, "end": end, "date": end,
            "actual": actual, "status": status, "late_days": 0, "critical": True, "source": "test",
            "slack_days": 0, "window_days": window, "critical_now": critical_now, "marker_only": marker}


def lane(sku="STY-1-S", bars=None, qty=100.0, ship="2026-12-01", stage="Cutting", wip="WIP-T-1",
         order="SAL-T-1", shipped=0.0):
    return {"wip": wip, "order": order, "buyer": "Buyer", "plant": "Plant A", "sku": sku, "size": None,
            "colour": None, "qty": qty, "shipped_qty": shipped, "cut_qty": 0.0, "status": "Planned",
            "plan_state": "committed", "stage": stage, "next_milestone": None, "next_due": None,
            "late": False, "pct": 0, "ship_date": ship, "pcd": ship, "bars": bars or [],
            "recovery": {"state": "SLACK", "headline": "", "days_late": 0, "late_gates": [], "remaining": [],
                         "required_days": 0, "days_left": 30, "projected_ship": ship, "ship": ship,
                         "spare_days": 30, "compression_pct": 0, "started_from": TODAY.isoformat()}}


def order(wip="WIP-T-1", so="SAL-T-1", qty=100.0, ship="2026-12-01"):
    return {"wip": wip, "sales_order": so, "buyer": "Buyer", "plant": "Plant A", "plant_city": "X",
            "pcd": ship, "ship_date": ship, "status": "Planned", "plan_state": "committed", "qty": qty,
            "late": 0, "next_due": None, "merchandiser": "u", "project": "P", "skus": 1, "lead_days": 30}


def issues_of(lanes, orders=None):
    return A.issues(lanes, orders if orders is not None else [order()], TODAY)


def kinds(res):
    return res["counts"]


def main():
    print("\n1 · null / missing dates")
    r = issues_of([lane(bars=[])]).copy()
    ok("unscheduled" in kinds(r), "a lane with no dated gate is flagged unscheduled", str(kinds(r)))
    r = issues_of([lane(ship=None, bars=[bar("Cutting", "2026-11-01", "2026-11-10")])])
    ok("no ship date" in kinds(r), "a lane with no ship date is flagged, not silently anchored on today")

    print("\n2 · end before start")
    r = issues_of([lane(bars=[bar("Cutting", "2026-11-10", "2026-11-01")])])
    ok("end before start" in kinds(r), "an inverted window is reported", str(kinds(r)))

    print("\n3 · zero duration")
    r = issues_of([lane(bars=[bar("PP Meeting", None, "2026-11-10", window=0)])])
    ok("zero duration" in kinds(r), "a gate with no window is reported (and drawn as a gate)")

    print("\n4 · dependency order — two different findings")
    a = bar("Cutting", "2026-10-01", "2026-10-05", status="Done", actual="2026-10-05")
    b = bar("Sewing", "2026-10-05", "2026-10-20", status="Done", actual="2026-10-01")   # before its predecessor
    r = issues_of([lane(bars=[a, b])])
    ok("dependency violated" in kinds(r), "sewing finishing before cutting is a VIOLATION", str(kinds(r)))
    b2 = bar("Sewing", "2026-10-05", "2026-10-20", status="Done", actual="2026-10-06")
    a2 = bar("Cutting", "2026-10-01", "2026-10-05", status="Pending", actual=None)
    r = issues_of([lane(bars=[a2, b2])])
    ok(kinds(r).get("dependency not evidenced") == 1 and "dependency violated" not in kinds(r),
       "a successor proved while the predecessor has no document is NOT EVIDENCE, not a violation")

    print("\n5 · future-dated actual")
    r = issues_of([lane(bars=[bar("Ship", "2026-11-01", "2026-12-20", status="Done", actual="2026-12-20")])])
    ok("future-dated actual" in kinds(r), "an actual in the future is reported", str(kinds(r)))

    print("\n6 · duplicate line")
    r = issues_of([lane(bars=[bar("Cutting", None, "2026-11-10")]), lane(bars=[bar("Cutting", None, "2026-11-10")])])
    ok("duplicate line" in kinds(r), "the same SKU twice in one WIP is reported (it would double-count)")

    print("\n7 · divide-by-zero and over-production")
    co = A.completion([lane(qty=0)], [order(qty=0)], {}, TODAY)
    ok(co["rows"][0]["made_pct"] is None, "0 ordered → made % is null, never 0 %")
    co = A.completion([lane(qty=100, shipped=0)], [order(qty=100)], {"SAL-T-1": 140.0}, TODAY)
    ok(co["rows"][0]["over_produced"] is True, "made 140 of 100 is flagged over-produced")
    ok(co["rows"][0]["made_pct"] == 140.0, "…and the percentage is not silently clamped", str(co["rows"][0]["made_pct"]))

    print("\n8 · negative WIP does not go silent")
    rec = A.reconcile([lane(qty=100, shipped=120)], [order(qty=100)], [], {"SAL-T-1": 120.0}, 0.0, TODAY)
    row = rec["rows"][0]
    ok(row["in_factory"] == 0.0, "shipped more than made → in-factory floors at 0")
    ok(row["ties"] is False, "…and the order therefore does NOT tie, instead of hiding it", str(row["residual"]))
    ok(rec["ties_everywhere"] is False, "the section-level verdict follows")

    print("\n9 · stages and ageing")
    st = A.stages([lane(stage="Cutting", bars=[bar("Cutting", None, (TODAY - timedelta(days=12)).isoformat(),
                                                   status="Done", actual=(TODAY - timedelta(days=12)).isoformat())]),
                   lane(sku="STY-2-S", stage="", bars=[])], TODAY)
    cut = [r for r in st["rows"] if r["stage"] == "Cutting"][0]
    ok(cut["buckets"]["10+"] == 100.0, "a piece 12 days in a stage lands in the 10+ bucket")
    ok(any(r["stage"] == "Not started" for r in st["rows"]), "a line with no stage reports as 'Not started'")

    print("\n10 · the catch-up engine on a passed ship date")
    bars = [bar("Cutting", "2026-09-01", "2026-09-10"), bar("Sewing", "2026-09-10", "2026-09-20"),
            bar("Ship", "2026-09-20", "2026-09-25")]
    l = lane(ship="2026-09-25", bars=bars)
    rec = wip_plan._lane_plan(l, date(2026, 9, 25), TODAY)
    ok(rec["state"] == "PAST", "a ship date in the past is PAST, not 'at risk'", rec["state"])
    ok(rec["projected_ship"] and rec["projected_ship"] > TODAY.isoformat(),
       "…and it names the earliest honest ship instead of an impossible one", rec["projected_ship"])

    print("\n11 · the live reconciliation (read-only, no fixture needed)")
    p = wip_plan.build(force=True)
    a = A.build_all(p["orders"], p["lanes"], date.today())
    ok(a["reconcile"]["ties_everywhere"] is True, "every live order ties: ordered = in factory + shipped + not yet made",
       str(a["reconcile"]["totals"]))
    ok(a["stages"]["total_qty"] == sum(o["qty"] for o in p["orders"]),
       "stage quantities add up to the order book", f"{a['stages']['total_qty']} vs {sum(o['qty'] for o in p['orders'])}")

    print(f"\n{passed} passed · {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
