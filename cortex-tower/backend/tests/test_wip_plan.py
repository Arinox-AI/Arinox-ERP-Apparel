"""Regression tests for the WIP plan — the arithmetic a planner acts on.

There is no browser in this container, so the catch-up numbers are asserted directly: a recovery verdict that says
"on time" while the calendar is short would be worse than no verdict at all. Every test reads the **live** ERP
through `wip_plan`, so a change to the milestone template or the writer shows up here.

    python3 tests/test_wip_plan.py

What is asserted
    A · shape      every lane carries one bar per template gate; bars are not inverted (RULES/01 #114)
    B · verdict    PAST ⇔ the ship date has gone · SLACK ⇔ spare ≥ 0 · TIGHT ⇔ 0 > spare and days_left ≥ 0
    C · catch-up   every remaining gate has a target ≥ today; a TIGHT plan's last target lands on or before ship
    D · targets    a TIGHT plan is compressed (targets strictly earlier than the natural pace); SLACK is not
    E · queue      a queue row is either a proposal (has a WIP, Draft) or an order with no plan; never both
    F · thread     the four planner actions answer, and refuse politely instead of raising
    G · phases     the five phases and 29 gates, and the suggestion is anchor − offset for every gate
    H · alerts     only a gate up to the delivery date can be missed, and a missed gate costs the delivery date
    I · apply      the Plan tab's one write refuses an unknown gate, and never moves a gate that is done
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import functions as F                                              # noqa: E402
import wip_plan                                                    # noqa: E402

passed = failed = 0


def ok(cond, what, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"   ok   {what}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"   FAIL {what}" + (f"  [{detail}]" if detail else ""))


def d(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def main():
    p = wip_plan.build(force=True)
    ok(p["live"], "the ERP was read", f"{len(p['orders'])} orders")
    today = date.fromisoformat(p["today"])
    lanes = p["lanes"]
    ok(bool(lanes), "there is at least one lane to check", f"{len(lanes)} lanes")

    print("\nA · shape")
    tpl = len({b["milestone"] for l in lanes for b in l["bars"]})
    for l in lanes:
        ok(len(l["bars"]) == tpl, f"{l['sku']}: {len(l['bars'])} bars = {tpl} template gates")
    inverted = [(l["sku"], b["milestone"]) for l in lanes for b in l["bars"]
                if b.get("start") and b.get("end") and d(b["end"]) < d(b["start"])]
    ok(not inverted, "no bar runs backwards (trap T57)", f"{len(inverted)} inverted")

    print("\nB · verdict")
    for l in lanes:
        r, ship = l["recovery"], d(l["ship_date"])
        dl = r.get("days_left")
        if r["state"] == "DONE":
            ok(not r["remaining"], f"{l['sku']}: DONE with no open gate")
            continue
        if r["state"] == "PAST":
            ok(dl is not None and dl < 0, f"{l['sku']}: PAST because the ship date is gone", f"{dl}d left")
            ok(d(r["projected_ship"]) >= today, f"{l['sku']}: earliest honest ship is not in the past")
        elif r["state"] == "SLACK":
            ok(r["spare_days"] >= 0, f"{l['sku']}: SLACK with {r['spare_days']}d to spare")
        elif r["state"] == "TIGHT":
            ok(r["spare_days"] < 0 and (dl or 0) >= 0,
               f"{l['sku']}: TIGHT — {abs(r['spare_days'])}d short, {dl}d on the calendar")
            ok(0 < r["compression_pct"] <= 100, f"{l['sku']}: compression inside 100 %", f"{r['compression_pct']}%")
        else:
            ok(False, f"{l['sku']}: unknown state {r['state']!r}")

    print("\nC · catch-up schedule")
    for l in lanes:
        r = l["recovery"]
        bad = [x for x in r["remaining"] if not x.get("target") or d(x["target"]) < today]
        ok(not bad, f"{l['sku']}: every remaining gate has a target on/after today", f"{len(bad)} bad")
        if r["state"] == "TIGHT":
            last = r["remaining"][-1]
            ok(d(last["target"]) <= d(l["ship_date"]),
               f"{l['sku']}: a TIGHT plan lands on or before the ship date",
               f"{last['target']} ≤ {l['ship_date']}")

    print("\nD · compression actually compresses")
    for l in lanes:
        r = l["recovery"]
        if r["state"] != "TIGHT" or len(r["remaining"]) < 2:
            continue
        natural = r["remaining"][-1]["target"]
        ok(d(natural) <= d(l["ship_date"]), f"{l['sku']}: targets pulled in to hold the date",
           f"{natural} vs ship {l['ship_date']}")

    print("\nE · the queue")
    for q in p["queue"]:
        has_wip = bool(q.get("wip"))
        ok(has_wip != (q["plan_state"] == "unplanned"),
           f"{q.get('order')}: {'a proposal with a WIP' if has_wip else 'an order with no plan'}", q["plan_state"])
        if has_wip:
            ok(q["status"] == "Draft", f"{q.get('order')}: a proposal is Draft, never live", q["status"])
            ok((q.get("capacity") or {}).get("plant_capacity", 0) > 0,
               f"{q.get('order')}: the proposal carries a capacity check")

    print("\nF · the planner's four actions")
    w = p["orders"][0]["wip"] if p["orders"] else ""
    t = F.get_dashboard(None, bridge_action="get_wip_thread", wip=w)
    ok(t.get("live"), "the thread reads", f"{len(t.get('thread') or [])} comment(s)")
    r1 = F.get_dashboard(None, bridge_action="wip_comment", wip=w, text="")
    ok(r1.get("refused"), "an empty comment is refused, not written", (r1.get("reason") or "")[:48])
    r2 = F.get_dashboard(None, bridge_action="wip_finalise", wip=w)
    live = [o for o in p["orders"] if o["wip"] == w][0]["status"]
    ok(r2.get("ok") or r2.get("refused"), "finalise answers", (r2.get("reason") or r2.get("message") or "")[:48])
    if live != "Draft":
        ok(r2.get("refused"), f"a live plan ({live}) cannot be finalised")

    

    # ────────────────────────────────────────────────────────────────────────────── G · phases
    print("\nG · the five phases and the gate master")
    import wip_gates                                                  # noqa: E402

    chain = wip_gates.chain(force=True)
    phases = wip_gates.phases(force=True)
    ok(len(chain) == 29, "29 gates in the master", str(len(chain)))
    ok([ph["phase"] for ph in phases] == [1, 2, 3, 4, 5], "five phases, numbered 1…5",
       ", ".join(f"P{ph['phase']} {ph['name']} ({ph['count']})" for ph in phases))
    ok(all(1 <= g["phase"] <= 5 for g in chain), "every gate belongs to a phase")
    p1 = [g["milestone"] for g in chain if g["phase"] == 1]
    ok(p1 and p1[-1] == "Order Confirmed", "Phase 1 ends at the order confirmation", p1[-1] if p1 else "—")
    # the client's own measured offsets — from 23OCTWIPDUMMY.xlsx, days before its Delivery column
    MEASURED = {"Fabric Ready at Mill": 55, "Fabric ETD": 50, "PP Sample Approval": 39, "Fabric In-House": 34,
                "Cutting": 30, "TOP Sample Approved": 27}
    for gate, want in MEASURED.items():
        got = next((g for g in chain if g["milestone"] == gate), None)
        ok(got is not None and got["offset_days"] == want and got["duration_source"] == "measured",
           f"{gate} carries the client's measured offset", f"delivery −{got['offset_days'] if got else '?'}d")
    ok(next(g for g in chain if g["milestone"] == "Ship")["offset_days"] == 0, "Ship is the anchor (offset 0)")
    rank = wip_gates.rank(force=True)
    ok(rank.get("Inquiry Received", 0) == 1 and rank.get("Ship", 0) > rank.get("Cutting", 0),
       "rank is DATE order, not the template's sequence", f"inquiry {rank.get('Inquiry Received')}, ship {rank.get('Ship')}")
    anchor = date(2026, 12, 15)
    sug = wip_gates.suggest(anchor, force=True)
    ok(all(d(g["suggested"]) == anchor - __import__("datetime").timedelta(days=g["offset_days"]) for g in sug),
       "every suggested date is anchor − offset", f"{len(sug)} gates")
    for ph in phases:
        mine = [g["offset_days"] for g in chain if g["phase"] == ph["phase"]]
        ok(mine == sorted(mine, reverse=True), f"P{ph['phase']} is in date order inside the phase",
           f"{mine[0]}…{mine[-1]}")

    # ────────────────────────────────────────────────────────────────────────────── H · alerts
    print("\nH · the alert is about work owed, not about a missing file")
    alerts = p.get("alerts") or []
    ok(all(a.get("days_overdue", 0) > 0 for a in alerts), "every alert is actually overdue", f"{len(alerts)} alert(s)")
    off = {g["milestone"]: g["offset_days"] for g in chain}
    ok(all(off.get(a["milestone"], -1) >= 0 for a in alerts),
       "no alert for a gate that falls due after the delivery date (payment, grievance)")
    ok(all(a.get("order") for a in alerts), "every alert names its order")
    done_gates = {(a["order"], a["milestone"]) for a in alerts if a.get("status") == "Done"}
    ok(not done_gates, "a gate that is Done never raises an alert", f"{len(done_gates)} bad")
    for o in p.get("orders", []):
        worst = max([m["days_overdue"] for m in (o.get("missed") or [])] or [0])
        if o.get("ship_date") and worst:
            import datetime as _dt
            want = (d(o["ship_date"]) + _dt.timedelta(days=worst)).isoformat()
            ok(o.get("projected_ship") == want and o.get("slip_days") == worst,
               f"{o['wip']}: the projected delivery moves by the worst late gate",
               f"{o['ship_date']} → {o.get('projected_ship')} ({o.get('slip_days')}d)")
    # ────────────────────────────────────────────────────────────────────────────── I · apply
    print("\nI · the Plan tab's one write")
    import wip_actions                                                 # noqa: E402

    live = next((o for o in p["orders"] if o.get("plan_state") == "committed"), None)
    if live:
        try:
            wip_actions.apply_plan(live["wip"], "Lab Dip=2026-12-01")
            ok(False, "an unknown gate is refused")
        except wip_actions.Refused as ex:
            ok("no gate called" in str(ex), "an unknown gate is refused, with the gates it does have",
               str(ex)[:60])
        try:
            wip_actions.apply_plan(live["wip"], "Cutting=not-a-date")
            ok(False, "a non-date is refused")
        except wip_actions.Refused as ex:
            ok("not a date" in str(ex), "a non-date is refused", str(ex)[:50])
        try:
            wip_actions.apply_plan(live["wip"], "")
            ok(False, "an empty change set is refused")
        except wip_actions.Refused as ex:
            ok("no dates" in str(ex), "an empty change set is refused", str(ex)[:50])
        # a gate whose rows are already done is reported, never moved — writing the same value is a no-op on dates
        done_gate = next((g["milestone"] for g in live["plan"] if g["status"] == "Done"), None)
        if done_gate:
            before = next(g["planned"] for g in live["plan"] if g["milestone"] == done_gate)
            res = wip_actions.apply_plan(live["wip"], f"{done_gate}=2026-01-05")
            ok(res["rows_moved"] == 0 and done_gate in res["gates_kept_done"],
               "a Done gate is not moved by a re-plan", f"{done_gate} kept, {res['rows_moved']} moved")
            after = F.get_wip_plan(None, refresh=True)
            cur = next((g["planned"] for o in after["orders"] if o["wip"] == live["wip"]
                        for g in o["plan"] if g["milestone"] == done_gate), None)
            ok(cur == before, "…and its date on the record is unchanged", f"{before} → {cur}")
    else:
        ok(False, "a committed plan to test the write against")

    print(f"\n{passed} passed · {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
