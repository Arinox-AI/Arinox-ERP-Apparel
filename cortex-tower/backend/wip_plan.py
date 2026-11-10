"""Cortex Operations Control Tower — the WIP plan, as something you can *work*.

The ERP's surface for `Cortex WIP` is a list and a child grid: 5 orders x 28 SKU lines x 13 milestones = **364
rows**. The client's words, 2026-11-03: *"the table format I am not able to understand"*. This module turns the
same records into a plan a planner can act on:

    lanes[]      one per (order, SKU) — 13 bars, each with the window it owns, its slack and its lateness
    recovery     per lane: what is late, what the next gates are, and **how to make the date** — the arithmetic
                 of catch-up, not advice
    queue[]      orders that are NOT planned yet (a Draft proposal the writer made, or a live order with no
                 plan at all) — the place to discuss one and then finalise it
    facets       the values to filter on (buyers, plants, departments, statuses, plan states)

Three pieces of arithmetic, each stated as what it is:

**windows.**  a milestone's bar runs from the gate before it to its own drop-dead, taken in **DATE order**. The
template's `sequence` is the workflow order and is not monotonic in time (`Fabric Requisition Placed` is seq 4 at
ship−55, `PP Sample Approval` is seq 3 at ship−40) — drawing by sequence inverts 84 of 364 bars (RULES/01 #114).

**slack.**  the last gate is the ship date. Working backwards, each open gate's *latest* date is the ship date
minus the template intervals of every gate after it; `slack = latest − drop_dead`. Negative slack means the gate
is already inside its own window before you do anything.

**recovery.**  if work resumes **today** and the remaining gates take the time the template gives them
(`required = Σ intervals`), the gates land at `today + Σ`, so the achievable ship date is `today + required`.
Then: `slip = (today + required) − ship` in days, and `compression = (ship − today) / required` — the fraction of
the planned time the remaining gates would have to fit into to keep the date. When `compression ≤ 100 %` the
catch-up schedule is spelled out gate by gate (`target`); when it is above 100 % (or the ship date is already
past) the honest answer is a new ship date and `slip` says how many days.

Read-only. Never raises: an unreachable ERP returns `live: false` with empty views.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote as _quote

import erp
import wip_analytics
import wip_gates

WIP = "Cortex WIP"
CACHE_TTL = 60.0
_cache: dict = {"t": 0.0, "v": None}

# statuses a plan is *committed* in; anything else (`Draft`) is a proposal waiting for a planner
COMMITTED = {"Planned", "In Production", "Shipped", "Closed"}

# How far along a gate is, is a fact about DATES, not about the template's `sequence`: since 2026-11-03 the
# template is the client's five phases in ownership order and two of them overlap in time (sampling runs while
# fabric is chased), so `sequence` cannot answer "is this gate behind the factory floor". `wip_gates.rank()`
# ranks the gates by their offset instead. The literal below is only the fallback when the master is unreadable.
GATE_SEQ = {"Inquiry Received": 1, "Tech Pack Received": 2, "Buyer BOM Received": 3, "Costing Issued": 4,
            "Price Negotiated & Locked": 5, "Order Confirmed": 6, "Production Plan & Capacity Slot": 7,
            "Fit Samples 1-3": 8, "PP Sample Approval": 9, "Bulk Standard Approved": 10,
            "Fabric Requisition Placed": 11, "Trim Requisition Placed": 12, "Purchase Order Placed": 13,
            "Fabric Ready at Mill": 14, "Fabric ETD": 15, "Fabric In-House": 16,
            "Fabric Tested & Inspected": 17, "Stock Entry Receipt": 18, "PP Meeting": 19,
            "Job Cards Issued": 20, "Cutting": 21, "TOP Sample Approved": 22, "Sewing Complete": 23,
            "Washing": 24, "Final Check & Pack": 25, "Buyer Final Inspection": 26, "Ship": 27,
            "Payment Maturity": 28, "Grievance Closed": 29}


def _rank() -> dict:
    """gate -> date rank, from the master; falls back to the literal above."""
    try:
        r = wip_gates.rank()
        return r or GATE_SEQ
    except Exception:                                            # noqa: BLE001
        return GATE_SEQ


def _iso(v) -> str | None:
    if not v:
        return None
    s = str(v)[:10]
    return s if len(s) == 10 else None


def _num(v, d=0.0) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return d


def _d(v) -> date | None:
    s = _iso(v)
    return date.fromisoformat(s) if s else None


def _intervals(bars: list[dict]) -> dict:
    """The template's own interval for each gate: the distance to the next gate, and for the last non-ship gate
    the distance to the ship date. No number is invented — they are the client's offsets read as gaps."""
    out = {}
    for i, b in enumerate(bars):
        end = _d(b.get("date"))
        nxt = _d(bars[i + 1].get("date")) if i + 1 < len(bars) else None
        if end and nxt:
            out[b["milestone"]] = max(0, (nxt - end).days)
    return out


def _lane_plan(lane: dict, ship: date | None, today: date) -> dict:
    """slack per open gate + the catch-up schedule. Pure arithmetic over the bars the ERP holds."""
    bars = lane["bars"]
    iv = _intervals(bars)
    open_bars = [b for b in bars if b.get("status") not in ("Done", "Passed", "Waived") and b.get("date")]
    late = [b for b in bars if b.get("status") == "Late" and b.get("date")]

    # slack — walk backwards from the ship date, taking the template's own intervals off it
    tail = 0
    slack = {}
    for b in reversed(open_bars):
        d = _d(b["date"])
        if ship is None or d is None:
            continue
        latest = ship - timedelta(days=tail)
        slack[b["milestone"]] = (latest - d).days
        tail += int(iv.get(b["milestone"], 0))
    for b in bars:
        b["slack_days"] = slack.get(b["milestone"])
        b["window_days"] = int(iv.get(b["milestone"], 0)) or None
        b["critical_now"] = (slack.get(b["milestone"]) is not None and slack[b["milestone"]] <= 0)

    required = sum(int(iv.get(b["milestone"], 0)) for b in open_bars)
    target = {}
    if not open_bars:
        recovery = {"state": "DONE", "headline": "every gate is cleared", "days_late": 0, "late_gates": [],
                    "remaining": [], "required_days": 0, "spare_days": 0, "compression_pct": 0}
    else:
        ship = ship or today
        days_left = (ship - today).days
        projected = today + timedelta(days=required)      # work resumes today, at the template's own pace
        spare = days_left - required                       # > 0 slack · < 0 the calendar is short
        # three states, because "late" and "cannot hold the date" are different questions:
        #   PAST   the ship date has gone — no compression can bring it back
        #   TIGHT  the date holds only if the gates are compressed into fewer days than the template gives them
        #   SLACK  the date holds and there is room to breathe
        if days_left < 0:
            state = "PAST"
            if required == 0:
                head = (f"everything the plan asked for is behind us — the ship date passed "
                        f"{abs(days_left)} day(s) ago and the order has not shipped")
            else:
                head = (f"the ship date has passed by {abs(days_left)} day(s); the {len(open_bars)} open gate(s) "
                        f"still need {required} day(s), so the earliest honest ship is {projected.isoformat()}")
        elif spare >= 0:
            state = "SLACK"
            head = (f"on time with {spare} day(s) to spare — {len(open_bars)} open gate(s) = {required} day(s) "
                    f"of gate time against {days_left} on the calendar")
        else:
            state = "TIGHT"
            head = (f"on time only if the {required} day(s) of remaining gate time fit into {days_left} — "
                    f"{round(100.0 * days_left / required)} % of the planned time, {abs(spare)} day(s) short")
        compression = round(100.0 * days_left / required, 0) if required > 0 else 0
        k = max(0.0, (days_left / required)) if required > 0 else 1.0
        acc = 0
        for b in open_bars:
            acc += int(iv.get(b["milestone"], 0))
            target[b["milestone"]] = (today + timedelta(days=round(acc * (k if state == "TIGHT" else 1.0)))
                                      ).isoformat()
        worst = max([int(b.get("late_days") or 0) for b in late] or [0])
        recovery = {
            "state": state, "headline": head,
            "days_late": worst, "late_gates": [b["milestone"] for b in late],
            "remaining": [{"milestone": b["milestone"], "planned": b["date"], "target": target.get(b["milestone"]),
                           "window_days": iv.get(b["milestone"]), "slack_days": slack.get(b["milestone"]),
                           "department": b.get("department"), "status": b.get("status"),
                           "late_days": b.get("late_days")} for b in open_bars],
            "required_days": required, "days_left": days_left,
            "projected_ship": projected.isoformat(), "ship": ship.isoformat(),
            "spare_days": spare, "compression_pct": compression,
            "started_from": today.isoformat(),
        }
    return recovery


def build(force: bool = False, today: date | None = None) -> dict:
    """The whole plan, one read. Cached 60 s so switching tabs does not re-read 5 documents (each with children)."""
    today = today or date.today()
    if not force and _cache["v"] and (time.time() - _cache["t"]) < CACHE_TTL:
        return _cache["v"]

    rk = _rank()                     # gate -> position in DATE order (not the template's sequence)
    gate_master = wip_gates.chain()  # the 29 gates in the client's 5 phases
    gate_by_name = {g["milestone"]: g for g in gate_master}

    ok, heads = erp.erp_get_checked(
        WIP,
        fields=["name", "sales_order", "customer", "company", "plant", "pcd", "ship_date", "status",
                "total_qty", "contract_qty", "late_count", "next_due", "merchandiser", "project",
                "allocation_note", "remarks", "template_applied"],
        filters=[["status", "!=", "Superseded"]],
        limit=0,
        order="ship_date asc",
    )
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {"live": bool(ok), "source": "KOGO ERP", "generated_at": generated, "today": today.isoformat(),
            "connection": {"connected": bool(ok), "base": erp.get_creds().get("BASE", ""),
                           "error": None if ok else "the ERP could not be read"},
            "write_mode": _write_mode()}

    if not ok:
        out = {**base, "orders": [], "lanes": [], "queue": [], "facets": _facets([]),
               "calendar": {"months": [], "chips": [], "departments": []}, "summary": {}, "bar_basis": "",
               "phases": wip_gates.phases(), "alerts": [], "alert_basis": ""}
        _cache.update(t=time.time(), v=out)
        return out

    # What has physically happened, from `Work Order.produced_qty` — the only cheap proof of progress we have.
    # This is the fix for "these are done orders, why are they late": an order that made its full quantity has
    # PASSED every gate up to final inspection, whether or not a document records the date of each one.
    made_by_so: dict[str, float] = {}
    for w in erp.erp_get("Work Order", fields=["name", "sales_order", "qty", "produced_qty", "docstatus"], limit=0):
        if int(w.get("docstatus") or 0) == 2 or not w.get("sales_order"):
            continue
        made_by_so[w["sales_order"]] = made_by_so.get(w["sales_order"], 0.0) + _num(w.get("produced_qty"))

    plants = {p["name"]: p for p in erp.erp_get(
        "Plant Floor", fields=["name", "plant_city", "monthly_capacity_pcs",
                               "standard_production_lead_time_days"], limit=0)}

    orders, lanes, chips, chips_by_missed = [], [], [], []
    for h in heads:
        # A child table is NOT listable over REST (403, `Sales Order Item` — RULES/01 #75). The children come
        # with the parent document, which is what `frappe.db.get_doc` does on the desk too.
        ok_doc, doc = erp._request(f"/api/resource/{WIP}/{_quote(h['name'])}")
        doc = (doc or {}).get("data") if ok_doc else {}
        lines = (doc or {}).get("lines") or []
        ms = (doc or {}).get("milestones") or []

        plant = plants.get(h.get("plant") or "", {})
        committed = (h.get("status") or "") in COMMITTED
        o_qty = _num(h.get("total_qty"))
        o_made = round(made_by_so.get(h.get("sales_order"), 0.0), 1)
        o_shipped = round(sum(_num(l.get("shipped_qty")) for l in lines), 1)
        ratio = (o_made / o_qty) if o_qty else 0.0
        ship_ratio = (o_shipped / o_qty) if o_qty else 0.0
        if ship_ratio >= 0.99 or (h.get("status") == "Closed"):
            floor = rk.get("Ship", 27)
        elif ratio >= 0.99:
            floor = rk.get("Final Check & Pack", 25)
        elif ratio > 0:
            floor = rk.get("Cutting", 21)
        else:
            floor = 0
        order = {
            "wip": h["name"], "sales_order": h.get("sales_order"), "buyer": h.get("customer"),
            "plant": h.get("plant"), "plant_city": plant.get("plant_city"),
            "pcd": _iso(h.get("pcd")), "ship_date": _iso(h.get("ship_date")),
            "status": h.get("status"), "plan_state": "committed" if committed else "proposal",
            "qty": _num(h.get("total_qty")), "late": int(_num(h.get("late_count"))),
            "next_due": _iso(h.get("next_due")), "merchandiser": h.get("merchandiser"),
            "project": h.get("project"), "skus": len(lines),
            "lead_days": int(_num(plant.get("standard_production_lead_time_days"))),
            "allocation_note": h.get("allocation_note"), "proposed_on": _iso(h.get("template_applied")),
            "made_qty": o_made, "shipped_qty": o_shipped, "progress_floor": floor,
            "made_pct": round(100 * ratio, 1) if o_qty else None,
            "shipped_pct": round(100 * ship_ratio, 1) if o_qty else None,
            "complete": floor >= rk.get("Ship", 27),
        }
        orders.append(order)

        by_item: dict[str, list] = {}
        for m in ms:
            by_item.setdefault(m.get("item_code") or "—", []).append(m)

        for ln in lines:
            rows = by_item.get(ln.get("item_code") or "—", [])
            # DATE order, not template sequence — see the module docstring.
            seq = sorted(rows, key=lambda r: (_iso(r.get("drop_dead")) or "9999-99-99",
                                              int(_num(r.get("sequence")))))
            prev = None
            bars = []
            for r in seq:
                dd = _iso(r.get("drop_dead"))
                # a gate behind the production floor with no document is PASSED, not late — the factory made the
                # goods, so the work happened; only the date is unrecorded. Red is kept for work still owed.
                implied = (not r.get("actual") and floor
                           and rk.get(r.get("milestone") or "", 99) <= floor
                           and (r.get("status") or "") not in ("Done", "Waived"))
                gm = gate_by_name.get(r.get("milestone") or "", {})
                bars.append({
                    "milestone": r.get("milestone"), "department": r.get("department"),
                    "phase": gm.get("phase"), "phase_name": gm.get("phase_name"),
                    "evidence_doctype": gm.get("evidence_doctype"),
                    "duration_source": gm.get("duration_source"),
                    "start": prev, "end": dd, "date": dd,
                    "actual": _iso(r.get("actual")),
                    "status": ("Passed" if implied else r.get("status")),
                    "planned_status": r.get("status"),
                    "implied": bool(implied),
                    "late_days": 0 if implied else int(_num(r.get("late_days"))),
                    "critical": bool(r.get("critical")),
                    "source": "implied by production" if implied else r.get("source"),
                    "responsible": r.get("responsible"),
                    "marker_only": prev is None,
                })
                prev = dd
                if dd:
                    chips.append({"date": dd, "wip": h["name"], "order": h.get("sales_order"),
                                  "sku": ln.get("item_code"), "milestone": r.get("milestone"),
                                  "department": r.get("department"),
                                  "status": ("Passed" if implied else r.get("status")),
                                  "late_days": 0 if implied else int(_num(r.get("late_days")))})
            lane = {
                "wip": h["name"], "order": h.get("sales_order"), "buyer": h.get("customer"),
                "plant": h.get("plant"), "sku": ln.get("item_code"), "size": ln.get("size"),
                "qty": _num(ln.get("qty")), "status": h.get("status"),
                "shipped_qty": _num(ln.get("shipped_qty")), "cut_qty": _num(ln.get("cut_qty")),
                "colour": ln.get("colour") or None, "size": ln.get("size") or None,
                "plan_state": order["plan_state"],
                "stage": ln.get("current_stage"), "next_milestone": ln.get("next_milestone"),
                "next_due": _iso(ln.get("next_due")), "late": bool(ln.get("late")),
                "pct": _num(ln.get("pct_complete")), "ship_date": _iso(h.get("ship_date")),
                "pcd": _iso(h.get("pcd")), "bars": bars,
            }
            lane["recovery"] = _lane_plan(lane, _d(h.get("ship_date")), today)
            lanes.append(lane)

        # ── the order's plan, phase by phase: the gate master's suggested date next to the date on the record.
        # Both are shown, because "what we planned" and "what the template says" are two different facts and
        # a planner needs to see the gap, not a number that silently replaced the other.
        ship_d = _d(h.get("ship_date"))
        by_gate: dict[str, list] = {}
        for m in ms:
            by_gate.setdefault(m.get("milestone") or "—", []).append(m)
        plan_rows, missed = [], []
        for g in gate_master:
            rows = by_gate.get(g["milestone"]) or []
            planned = sorted({_iso(r.get("drop_dead")) for r in rows if _iso(r.get("drop_dead"))})
            actuals = sorted({_iso(r.get("actual")) for r in rows if _iso(r.get("actual"))})
            done_n = sum(1 for r in rows if (r.get("status") or "") == "Done" or r.get("actual"))
            late_n = sum(1 for r in rows if (r.get("status") or "") == "Late")
            n = len(rows) or len(lines) or 1
            status = ("Done" if done_n >= n and n else "Late" if late_n else
                      "Pending" if rows else "No plan")
            # A gate behind the order's own reach is PASSED, not late. Two different facts, and they must not
            # collapse into one red row: (a) the Sales Order exists, so everything up to "Order Confirmed" DID
            # happen — only the date is unrecorded; (b) the factory has made the goods, so every gate up to the
            # floor produced_qty proves is behind us. Red is kept for work still owed.
            floor_here = max(int(floor or 0), int(rk.get("Order Confirmed", 6)))
            if status in ("Late", "Pending") and floor_here and rk.get(g["milestone"], 99) <= floor_here:
                status = "Passed"
            due = planned[0] if planned else None
            suggest_d = (ship_d - timedelta(days=g["offset_days"])).isoformat() if ship_d else None
            overdue = 0
            if due and status == "Late" and _d(due) and g["offset_days"] >= 0:
                overdue = max(0, (today - date.fromisoformat(due)).days)
            plan_rows.append({**g, "suggested": suggest_d, "planned": due, "actual": actuals[-1] if actuals else None,
                              "status": status, "late_days": overdue,
                              "delta_days": ((date.fromisoformat(due) - date.fromisoformat(suggest_d)).days
                                             if due and suggest_d else None),
                              "skus_done": done_n, "skus": n})
            if overdue > 0:
                missed.append({"milestone": g["milestone"], "phase": g["phase"],
                               "phase_name": g["phase_name"], "department": g["department"],
                               "due": due, "days_overdue": overdue,
                               "evidence_doctype": g["evidence_doctype"],
                               "status": status})
        # what one missed gate costs the order: a gate that is N days late delays its successors by N days,
        # so the honest projection is the promised date plus the worst single overdue gate — not a sum, and
        # not "on time" because the other gates were comfortable.
        worst = max([m["days_overdue"] for m in missed] or [0])
        order["plan"] = plan_rows
        order["phases"] = sorted({p["phase"] for p in plan_rows if p.get("phase")})
        order["missed"] = sorted(missed, key=lambda m: -m["days_overdue"])
        order["projected_ship"] = ((ship_d + timedelta(days=worst)).isoformat() if ship_d else None)
        order["slip_days"] = worst
        order["gates_total"] = len(plan_rows)
        order["gates_done"] = sum(1 for r in plan_rows if r["status"] == "Done")
        order["gates_missed"] = len(missed)
        order["gates_unset"] = sum(1 for r in plan_rows if r["status"] == "No plan")
        for m in missed:
            chips_by_missed.append({"wip": h["name"], "order": h.get("sales_order"), "buyer": h.get("customer"),
                                    **m})

    # ── the queue: live orders with no plan, plus proposals waiting for a planner
    planned_orders = {o["sales_order"] for o in orders if o["sales_order"]}
    unplanned = [
        {"wip": None, "order": s["name"], "sales_order": s["name"], "buyer": s.get("customer"),
         "qty": _num(s.get("total_qty")),
         "ship_date": _iso(s.get("delivery_date")), "company": s.get("company"), "plant": None,
         "status": "no WIP", "plan_state": "unplanned", "proposed_on": None,
         "allocation_note": "no plan exists yet — the writer has not run since this order was submitted",
         "capacity": None}
        for s in erp.erp_get("Sales Order", fields=["name", "customer", "total_qty", "delivery_date", "company"],
                             filters=[["docstatus", "=", 1]], limit=0)
        if s["name"] not in planned_orders
    ]
    for u in unplanned:
        anchor = _d(u.get("ship_date"))
        u["plan"] = [{**g, "suggested": (anchor - timedelta(days=g["offset_days"])).isoformat() if anchor else None,
                      "planned": None, "actual": None, "status": "No plan", "late_days": 0,
                      "delta_days": None, "skus_done": 0, "skus": 1} for g in gate_master]
        u["phases"] = sorted({g["phase"] for g in gate_master})
        u["missed"], u["projected_ship"], u["slip_days"] = [], u.get("ship_date"), 0
        u["gates_total"], u["gates_done"], u["gates_missed"] = len(gate_master), 0, 0
        u["gates_unset"] = len(gate_master)
    proposals = []
    for o in orders:
        if o["plan_state"] != "proposal":
            continue
        p = plants.get(o["plant"] or "", {})
        month = (o["pcd"] or o["ship_date"] or "")[:7]
        booked = round(sum(x["qty"] for x in orders if x["plant"] == o["plant"] and (x["pcd"] or "")[:7] == month), 0)
        proposals.append({**o, "order": o["sales_order"], "capacity": {
            "month": month, "plant_capacity": int(_num(p.get("monthly_capacity_pcs"))), "booked": booked}})
    queue = proposals + unplanned

    months = sorted({c["date"][:7] for c in chips})
    chips.sort(key=lambda c: (c["date"], c["department"] or "", c["milestone"] or ""))
    late_lanes = [l for l in lanes if l["recovery"]["days_late"] or l["late"]]

    # ── the alert: a gate whose date has passed with nothing to show for it, and what it costs the delivery
    alerts = sorted(chips_by_missed, key=lambda m: (-m["days_overdue"], m["order"] or ""))
    phase_out = wip_gates.phases()
    for p in phase_out:
        p["missed"] = sum(1 for a in alerts if a["phase"] == p["phase"])
        p["done"] = sum(1 for o in orders for g in o.get("plan", [])
                         if g["phase"] == p["phase"] and g["status"] == "Done")
        p["unset"] = sum(1 for o in orders for g in o.get("plan", [])
                         if g["phase"] == p["phase"] and g["status"] == "No plan")

    all_bars = [b for l in lanes for b in l["bars"]]
    summary = {
        "orders": len(orders), "skus": len(lanes), "milestones": len(chips),
        "pcs": round(sum(o["qty"] for o in orders), 1),
        "late": sum(1 for b in all_bars if b.get("status") == "Late"),
        "done": sum(1 for b in all_bars if b.get("status") == "Done"),
        "passed": sum(1 for b in all_bars if b.get("status") == "Passed"),
        "pending": sum(1 for b in all_bars if b.get("status") == "Pending"),
        "next_7_days": sum(1 for c in chips if c.get("date") and
                           today <= date.fromisoformat(c["date"]) <= today + timedelta(days=7)
                           and c.get("status") not in ("Done", "Waived")),
        "late_skus": sum(1 for l in lanes if any(b.get("status") == "Late" for b in l["bars"])),
        "slips": sum(1 for l in lanes if l["recovery"]["state"] in ("TIGHT", "PAST")),
        "past": sum(1 for l in lanes if l["recovery"]["state"] == "PAST"),
        "tight": sum(1 for l in lanes if l["recovery"]["state"] == "TIGHT"),
        "queue": len(queue),
        "proposals": len(proposals),
        "alerts": 0,
        "gates_missed": 0,
        "gates_unset": 0,
        "committed": sum(1 for o in orders if o["plan_state"] == "committed"),
        "capacity": {name: {"pcs_month": int(_num(v.get("monthly_capacity_pcs"))),
                            "city": v.get("plant_city"),
                            "booked": round(sum(o["qty"] for o in orders if o["plant"] == name), 1)}
                     for name, v in plants.items()},
    }

    summary["alerts"] = len(alerts)
    summary["gates_missed"] = len(alerts)
    summary["gates_unset"] = sum(1 for o in orders for g in o.get("plan", []) if g["status"] == "No plan")
    summary["phases"] = len(phase_out)

    cancelled = {}
    for dt in ("Sales Order", "Work Order", "Job Card", "Stock Entry", "Delivery Note", "Quality Inspection"):
        rows = erp.erp_get(dt, fields=["name", "docstatus"], limit=0)
        cancelled[dt] = sum(1 for r in rows if int(r.get("docstatus") or 0) == 2)

    out = {
        **base, "orders": orders, "lanes": lanes, "queue": queue,
        "phases": phase_out, "alerts": alerts,
        "alert_basis": ("a gate is MISSED when its drop-dead has passed and no document proves it — and the "
                        "goods behind it have not moved either. Only gates up to the delivery date can be "
                        "missed: payment and grievance fall due after it and are commercial follow-ups, not "
                        "production deadlines. The cost it prints is the promised delivery date "
                        "plus the worst single overdue gate, because one late gate delays its successors by "
                        "exactly that much; it is not a sum, and it is not zero because the other gates had slack."),
        "calendar": {"months": months, "chips": chips, "departments": _departments(chips)},
        "facets": _facets(orders, lanes, chips), "summary": summary,
        "issues": wip_analytics.issues(lanes, orders, today),
        "policy": wip_analytics.policy(cancelled),
        "working_days": _working_days(),
        "bar_basis": ("a milestone's bar runs from the previous gate to its own drop-dead, taken in DATE order "
                      "— the template's sequence is the workflow order and is not monotonic in time"),
    }
    _cache.update(t=time.time(), v=out)
    return out


def _working_days() -> dict:
    """Can the plan say 'working days' or only 'elapsed days'? Answer from the calendar records, not a default."""
    lists = erp.erp_get("Holiday List", fields=["name", "from_date", "to_date", "total_holidays", "weekly_off"],
                        limit=0)
    detail, holidays, weekly = [], 0, []
    for hl in lists:
        ok, doc = erp._request(f"/api/resource/Holiday List/{_quote(hl['name'])}")
        kids = ((doc or {}).get("data") or {}).get("holidays") or [] if ok else []
        holidays += len(kids)
        if hl.get("weekly_off"):
            weekly.append(hl["weekly_off"])
        detail.append({"name": hl["name"], "from": _iso(hl.get("from_date")), "to": _iso(hl.get("to_date")),
                       "holiday_rows": len(kids), "weekly_off": hl.get("weekly_off")})
    return {
        "confirmed": bool(holidays) or bool(weekly),
        "holidays": holidays, "weekly_off": weekly, "lists": detail,
        "basis": ("working days need a calendar, not a constant. The three Holiday Lists exist but carry "
                  f"**{holidays} holiday rows** between them and no weekly off, so every working-day figure in this "
                  "tab is **elapsed days** and is labelled UNCONFIRMED until the client fills the CN / VN factory "
                  "calendars (RULES/01 #117)."),
    }


def _departments(chips):
    return sorted({c["department"] for c in chips if c.get("department")})


def _facets(orders, lanes=None, chips=None):
    lanes = lanes or []
    chips = chips or []
    return {
        "buyers": sorted({o["buyer"] for o in orders if o.get("buyer")}),
        "plants": sorted({o["plant"] for o in orders if o.get("plant")}),
        "departments": _departments(chips) or ["Merchandising", "Fabric Purchase", "Trim Purchase", "Quality",
                                               "Production Planner"],
        "statuses": sorted({o["status"] for o in orders if o.get("status")}),
        "plan_states": ["committed", "proposal"],
        "orders": [{"wip": o["wip"], "order": o["sales_order"], "buyer": o["buyer"]} for o in orders],
        "skus": sorted({l["sku"] for l in lanes if l.get("sku")}),
    }


def _write_mode() -> str:
    try:
        import writes
        return writes.current_mode()
    except Exception:                                            # noqa: BLE001
        return "unknown"
