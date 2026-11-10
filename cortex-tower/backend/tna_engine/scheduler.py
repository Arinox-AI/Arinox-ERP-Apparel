"""The T&A scheduler (TNA plan section 6): one plan, one scheduler. Pure and deterministic: nothing reads the clock or the ERP.

Inputs: the template (``template.load``), the order's anchors (``ex_factory`` required; ``order_received``, ``pcd`` optional), the human
and evidence layer (``state``: per ERP code ``actual_date`` / ``actual_start`` / ``partial`` / ``not_applicable`` / ``revised_date``) and ``today``.

Per task the result carries four lanes: ``planned`` (the baseline: template offsets backward from ex-factory, on the task's own calendar),
``earliest`` (forward pass), ``latest`` (backward pass, hence ``float``) and ``forecast`` (the forward pass again with actuals in place and
slips propagated: a milestone that is late pushes every successor that now misses its own planned date). ``feasible`` is a number, not a flag:
how many working days the ship milestone is expected to miss the ex-factory date, and which milestone drives it.

Links are finish-to-start with a typed lag (``wait``, ``approval``, ``transit``, ``buffer``, or ``overlap`` for a negative lag). A not-applicable
milestone passes its predecessors through with zero time. A pinned date (``PCD`` from the factory allocation, an override) can only push later.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .calendars import WorkingCalendar, as_date, load_calendars

LATE_STATUSES = ("Overdue", "At risk")


def _topo(tasks: dict) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []

    def visit(c: str, path: tuple):
        if seen.get(c) == 2:
            return
        if seen.get(c) == 1:
            raise ValueError("circular dependency: " + " -> ".join(path + (c,)))
        seen[c] = 1
        for l in tasks[c]["links"]:
            if l["pred"] in tasks:
                visit(l["pred"], path + (c,))
        seen[c] = 2
        out.append(c)

    for c in sorted(tasks, key=lambda k: (tasks[k].get("seq", 0), k)):
        visit(c, ())
    return out


def _fin(cal: WorkingCalendar, start: date, dur: int) -> date:
    return cal.shift(start, dur - 1) if dur > 0 else cal.snap(start, 1)


def _st(cal: WorkingCalendar, finish: date, dur: int) -> date:
    return cal.shift(finish, -(dur - 1)) if dur > 0 else cal.snap(finish, -1)


def schedule(tpl: dict, anchors: dict, state: Optional[dict] = None, today=None, calendars: Optional[dict] = None, overrides: Optional[dict] = None,
             baseline: Optional[dict] = None) -> dict:
    """Compute the plan. ``anchors``: ``ex_factory`` (required), ``order_received``, ``pcd``. Returns ``{tasks, order, summary}``.

    ``baseline`` (``{code: {planned_start, planned_finish}}``) is the frozen plan of a locked order: its dates replace the template's as the
    ``planned`` lane, so the forecast, the status and the slip are measured against what was agreed, not against a recomputation."""
    cals = calendars or load_calendars()
    tasks = tpl["tasks"]
    ex = as_date(anchors.get("ex_factory"))
    if not ex:
        raise ValueError("no ex-factory date: the plan is not computed")
    today = as_date(today)
    if not today:
        raise ValueError("today must be passed in (the scheduler never reads the clock)")
    recv = as_date(anchors.get("order_received"))
    pcd = as_date(anchors.get("pcd"))
    state = {k: dict(v or {}) for k, v in (state or {}).items()}
    if recv and recv <= today and "ORDER_RECEIVED" in tasks and not state.get("ORDER_RECEIVED", {}).get("actual_date"):
        state.setdefault("ORDER_RECEIVED", {})["actual_date"] = recv.isoformat()    # the Sales Order date is the evidence (TNA plan section 8.1)
    pins = {k: as_date(v) for k, v in (overrides or {}).items() if v}
    if pcd and "PCD" not in pins:
        pins["PCD"] = pcd
    order = _topo(tasks)
    succ: dict[str, list] = {c: [] for c in tasks}
    for c in order:
        for l in tasks[c]["links"]:
            if l["pred"] in tasks:
                succ[l["pred"]].append((c, l))
    na = {c for c, s in state.items() if s.get("not_applicable") and c in tasks}
    R: dict[str, dict] = {}
    # 1 · baseline: template offsets backward from ex-factory (a pinned date replaces its own planned date)
    for c in order:
        t = tasks[c]
        cal = cals[t["calendar"]]
        dur = 0 if c in na else t["duration"]
        bl = (baseline or {}).get(c)
        f = as_date(bl["planned_finish"]) if bl else (pins.get(c) or cal.shift(ex, t["offset"]))
        R[c] = {"code": c, "name": t["name"], "category": t["category"], "owner_role": t["owner_role"], "calendar": t["calendar"], "duration": dur, "is_critical": t["is_critical"],
                "planned_finish": f, "planned_start": (as_date(bl.get("planned_start")) if bl and bl.get("planned_start") else _st(cal, f, dur)), "pinned": c in pins, "not_applicable": c in na}
    # 2 · backward pass (latest): the ship milestone is pinned to ex-factory
    ship = "EX_FACTORY" if "EX_FACTORY" in tasks else order[-1]
    for c in reversed(order):
        t, cal = tasks[c], cals[tasks[c]["calendar"]]
        cands = []
        if c == ship:
            cands.append(ex)
        for s, l in succ[c]:
            sc = cals[tasks[s]["calendar"]]
            cands.append(sc.shift(R[s]["latest_start"], -(l["lag"] + 1)))
        lf = min(cands) if cands else R[c]["planned_finish"]
        R[c]["latest_finish"] = lf
        R[c]["latest_start"] = _st(cal, lf, R[c]["duration"])
    # 3 · forward pass (earliest): from the order-received date (or today), durations and lags; a recorded actual is where it happened
    floor = max(recv, today) if recv else today
    for c in order:
        t, cal = tasks[c], cals[tasks[c]["calendar"]]
        act = as_date((state.get(c) or {}).get("actual_date"))
        cand = [(cal.shift(R[l["pred"]]["earliest_finish"], l["lag"] + 1), l["pred"]) for l in t["links"] if l["pred"] in R]
        if act and c not in na:
            R[c]["earliest_start"] = as_date(state[c].get("actual_start")) or act
            R[c]["earliest_finish"] = act
            R[c]["early_driver"] = None
        else:
            s, who = max(cand) if cand else (cal.snap(floor, 1), None)
            if not cand:
                who = None
            R[c]["earliest_start"] = s
            R[c]["earliest_finish"] = _fin(cal, s, R[c]["duration"])
            R[c]["early_driver"] = who
        R[c]["float_wd"] = cal.between(R[c]["earliest_finish"], R[c]["latest_finish"])
    # 4 · forecast: actuals fixed, everything else pushed by what is late; nothing starts before its planned start or before today
    for c in order:
        t, cal, r = tasks[c], cals[tasks[c]["calendar"]], R[c]
        stt = state.get(c) or {}
        act_f = as_date(stt.get("actual_date"))
        if c in na:
            ps = [R[l["pred"]]["forecast_finish"] for l in t["links"] if l["pred"] in R]
            r["forecast_start"] = r["forecast_finish"] = max(ps) if ps else r["planned_finish"]
            r["driver"] = None
            continue
        if act_f:
            r["forecast_finish"] = act_f
            r["forecast_start"] = as_date(stt.get("actual_start")) or act_f
            r["driver"] = None
            continue
        drivers = []
        for l in t["links"]:
            if l["pred"] in R:
                drivers.append((cal.shift(R[l["pred"]]["forecast_finish"], l["lag"] + 1), l["pred"]))
        net = max(drivers) if drivers else (cal.snap(floor, 1), None)
        s = max(net[0], r["planned_start"] if not r["not_applicable"] else net[0])
        cause = net[1] if net[0] >= r["planned_start"] else None
        if s < today:
            s, cause = cal.snap(today, 1), "today"                    # not recorded and in the past: it cannot be finished earlier than today
        f = _fin(cal, s, r["duration"])
        rev = as_date(stt.get("revised_date"))
        if rev and rev > f:
            f, cause = rev, "revised date"
        if pins.get(c) and f < pins[c]:
            f = pins[c]                                               # a pinned date can only push later
        r["forecast_start"], r["forecast_finish"], r["driver"] = s, f, cause
    # 5 · statuses, slips, and the number the plan is judged by
    done_codes = {c for c, s in state.items() if as_date((s or {}).get("actual_date")) and c in tasks}
    down: dict[str, bool] = {}                                       # "something downstream of me has an actual": the evidence gap test

    def done_below(c: str) -> bool:
        if c in down:
            return down[c]
        down[c] = False
        down[c] = any(s in done_codes or done_below(s) for s, _ in succ[c])
        return down[c]
    for c in order:
        r, cal = R[c], cals[tasks[c]["calendar"]]
        stt = state.get(c) or {}
        act = as_date(stt.get("actual_date"))
        slip = cal.between(r["planned_finish"], r["forecast_finish"])
        r["slip_wd"] = max(0, slip)
        later_done = done_below(c)
        if r["not_applicable"]:
            r["status"] = "Not Applicable"
        elif act:
            r["status"] = "Done"
            r["slip_wd"] = max(0, cal.between(r["planned_finish"], act))
        elif stt.get("partial"):
            r["status"] = "In Progress" if r["planned_finish"] >= today else "Overdue"
        elif r["planned_finish"] < today:
            r["status"] = "Not recorded" if later_done else "Overdue"
        elif slip > 0:
            r["status"] = "At risk"
        else:
            r["status"] = "On track"
        r["actual_date"] = act
        r["revised_date"] = as_date(stt.get("revised_date"))
        r["critical"] = r["float_wd"] <= 0
    ship_r = R[ship]
    sc = cals[tasks[ship]["calendar"]]
    miss = sc.between(ex, ship_r["forecast_finish"])
    early_miss = sc.between(ex, ship_r["earliest_finish"])                # plan-time feasibility: can the network be done at all by ex-factory?
    driver = _driver(R, ship)
    early_driver = _early_driver(R, ship)
    summary = {"ex_factory": ex, "ship_forecast": ship_r["forecast_finish"], "ship_miss_wd": max(0, miss), "feasible": miss <= 0,
               "plan_infeasible_by_wd": max(0, early_miss), "plan_feasible": early_miss <= 0, "driver": driver or (early_driver if early_miss > 0 else None),
               "message": _message(miss, early_miss, driver, early_driver, R), "critical_codes": [c for c in order if R[c]["critical"]],
               "late": [c for c in order if R[c]["status"] in LATE_STATUSES], "today": today}
    return {"tasks": R, "order": order, "summary": summary}


def _driver(R: dict, ship: str) -> Optional[str]:
    """The earliest milestone on the chain that sets the ship forecast and is itself late: the one to chase."""
    cur, last_late, guard = ship, None, 0
    while cur and cur in R and guard < 500:
        r = R[cur]
        if r["forecast_finish"] > r["planned_finish"] and not r["not_applicable"]:
            last_late = cur
        cur = r.get("driver") if r.get("driver") in R else None
        guard += 1
    return last_late


def _early_driver(R: dict, ship: str) -> Optional[str]:
    """The root of the longest chain into ship (what makes a fresh plan infeasible): the first milestone on it that is not yet done."""
    cur, out, guard = ship, None, 0
    while cur and guard < 500:
        if R[cur].get("actual_date") is None and not R[cur]["not_applicable"]:
            out = cur
        cur = R[cur].get("early_driver")
        guard += 1
    return out


def _message(miss: int, early: int, driver: Optional[str], early_driver: Optional[str], R: dict) -> str:
    if early > 0 and early > miss:
        return f"Infeasible by {early} working days: even with no further delay the plan finishes {early} working days after ex-factory" + (f" (the chain starts at {early_driver})." if early_driver else ".")
    if miss > 0:
        return f"Ship is forecast {miss} working days after ex-factory" + (f", driven by {driver} ({R[driver]['slip_wd']} working days late)." if driver else ".")
    return "Feasible: the forecast ships on or before ex-factory."


def moves(before: dict, after: dict) -> list[dict]:
    """The diff between two schedules (a re-plan shown before it is applied): per milestone, planned and forecast dates that changed."""
    out = []
    for c in after["order"]:
        b, a = before["tasks"].get(c), after["tasks"][c]
        if not b:
            out.append({"code": c, "kind": "new", "planned_finish": str(a["planned_finish"])})
            continue
        ch = {}
        for k in ("planned_finish", "forecast_finish", "latest_finish"):
            if b[k] != a[k]:
                ch[k] = [str(b[k]), str(a[k])]
        if b["status"] != a["status"]:
            ch["status"] = [b["status"], a["status"]]
        if ch:
            out.append({"code": c, "name": a["name"], **ch})
    return out


def as_rows(plan: dict) -> list[dict]:
    """JSON-ready rows in template order (dates as ISO strings)."""
    rows = []
    for c in plan["order"]:
        r = plan["tasks"][c]
        rows.append({k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()})
    return rows
