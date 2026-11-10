"""Where to produce: a deterministic, explainable suggester for the Factory Allocation (ORDER_TO_SHIP_PLAN section 5, D3).

Pure module: no ERP calls, no clock, no randomness. The input is a plain ``ctx`` dict (built by ``order_api`` from the planning
context script, the Operation Bulletins, the Workstations and Apparel Settings); the output is a draft the planner edits and
approves. The same input always gives the same draft.

Capacity of a line on one day, in pieces (the ERP's own ``day_target`` in ``lib_sewing.py``, which reproduces the company's
operation bulletin sheet to the digit: 28 workers x 480 min x 65 % / 24.4 SAM = 358.03)::

    headcount x working_minutes x efficiency / total_sam  x  learning-curve %(day on this style)

* headcount: the line's default operators + helpers (Workstation custom fields); else the style's Operation Bulletin ``operators``.
* total_sam / efficiency / minutes: the style's active Operation Bulletin; else the Product Type default row in Apparel Settings;
  efficiency and minutes fall back to the two global settings. With no SAM anywhere the line is **capacity unknown** and is never
  used silently. ``Workstation.production_capacity`` (parallel jobs in ERPNext) is never read as pieces.
* working days: the calendar of the site (D5: every day works; holidays and weekend days stay data so they can be added later).

Algorithm (section 5): ``sewing_end = ex_factory - finish_pack_days``; the sewing window is placed as late as the line's free
capacity allows; ``pcd = sewing_start - cut_lead_days``. A style x colour goes on ONE line when one fits; it is split over lines
only when none does, never below the minimum batch. A group that cannot fit anywhere gets a **shortfall** with the earliest
feasible ex-factory date, never a silent over-load.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Optional

#: the search never looks further back than this many days from the sewing end (a safety stop, not a business rule)
MAX_WINDOW_DAYS = 400


# ───────────────────────── calendar ─────────────────────────

class Calendar:
    """Working days of one site. D5: every day is a working day, so the default has no weekend and no holidays.

    ``weekend`` is a set of weekday numbers (Monday = 0); ``holidays`` a set of dates. Both stay data so a Holiday List can
    feed them later without changing any caller.
    """

    def __init__(self, weekend=(), holidays=()):
        self.weekend = set(weekend or ())
        self.holidays = {_d(h) for h in (holidays or ())}

    def works(self, d: date) -> bool:
        return d.weekday() not in self.weekend and d not in self.holidays

    def add(self, d: date, n: int) -> date:
        """``d`` moved ``n`` working days forward (negative: back). ``n = 0`` is ``d`` itself when it works, else the next working day."""
        step = 1 if n >= 0 else -1
        cur, left = d, abs(n)
        if left == 0:
            while not self.works(cur):
                cur += timedelta(days=1)
            return cur
        guard = 0
        while left and guard < 5000:
            cur += timedelta(days=step)
            if self.works(cur):
                left -= 1
            guard += 1
        return cur

    def days(self, start: date, end: date) -> list[date]:
        out, cur = [], start
        while cur <= end:
            if self.works(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


def _d(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


# ───────────────────────── capacity ─────────────────────────

def learning_pct(curve: list, day_no: int) -> float:
    """% of target on day ``day_no`` (1-based) of a style on a line. ``curve`` is ``[[day, pct], ...]``; past its last day: 100.

    With no curve every day is 100 % (no assumption invented).
    """
    rows = sorted((int(r[0]), _f(r[1], 100.0)) for r in (curve or []))
    if not rows:
        return 100.0
    if day_no > rows[-1][0]:
        return 100.0 if rows[-1][1] >= 100.0 else rows[-1][1]
    pct = rows[0][1]
    for d, p in rows:
        if d <= day_no:
            pct = p
    return pct


def style_spec(ctx: dict, style: str) -> dict:
    """SAM, efficiency and minutes for a style, and where each came from. ``sam`` 0 means unknown."""
    st = ctx.get("settings", {})
    ob = (ctx.get("obs") or {}).get(style) or {}
    ptype = (ctx.get("style_product_type") or {}).get(style, "")
    dflt = (ctx.get("defaults") or {}).get(ptype) or {}
    sam, sam_src = _f(ob.get("total_sam")), "operation bulletin"
    if sam <= 0:
        sam, sam_src = _f(dflt.get("sewing_sam")), f"default for {ptype}" if ptype else "default"
    if sam <= 0:
        sam, sam_src = 0.0, "unknown"
    eff = _f(ob.get("expected_efficiency_pct")) or _f(dflt.get("efficiency_pct")) or _f(st.get("planned_efficiency_pct"))
    minutes = _f(ob.get("working_minutes")) or _f(st.get("work_minutes_per_day"))
    return {"sam": sam, "sam_source": sam_src, "eff": eff, "minutes": minutes, "ob_operators": _f(ob.get("operators")),
            "product_type": ptype,
            "finish_pack_days": int(_f(dflt.get("finish_pack_days")) or _f(st.get("finish_pack_days"))),
            "cut_lead_days": int(_f(dflt.get("cut_lead_days")) or _f(st.get("cut_lead_days")))}


def line_headcount(line: dict, spec: dict) -> tuple[float, str]:
    n = _f(line.get("operators")) + _f(line.get("helpers"))
    if n > 0:
        return n, "line default"
    if spec["ob_operators"] > 0:
        return spec["ob_operators"], "operation bulletin"
    return 0.0, "unknown"


def full_day_pcs(line: dict, spec: dict) -> float:
    """Pieces per day at 100 % of target for this style on this line; 0 when it cannot be known."""
    heads, _ = line_headcount(line, spec)
    if heads <= 0 or spec["sam"] <= 0 or spec["eff"] <= 0 or spec["minutes"] <= 0:
        return 0.0                                            # efficiency and minutes have no built-in value: not set = capacity unknown
    return heads * spec["minutes"] * (spec["eff"] / 100.0) / spec["sam"]


# ───────────────────────── load already on a line ─────────────────────────

def line_load(ctx: dict, cal: Calendar) -> dict:
    """``{line: {date: pieces}}``: every other allocation spread evenly over the working days of its sewing window."""
    out: dict = {}
    for a in ctx.get("other_allocations") or []:
        s, e = _d(a.get("sewing_start")), _d(a.get("sewing_end"))
        qty = _f(a.get("qty"))
        if not (s and e and a.get("line")) or qty <= 0 or e < s:
            continue
        days = cal.days(s, e) or [s]
        per = qty / len(days)
        for d in days:
            out.setdefault(a["line"], {})[d] = out.get(a["line"], {}).get(d, 0.0) + per
    return out


# ───────────────────────── placing one style x colour on one line ─────────────────────────

def _simulate(start: date, qty: float, full: float, curve: list, cal: Calendar, load: dict, horizon: date):
    """Work forward from ``start``: the date the quantity is finished, and the free pieces used; ``None`` if past ``horizon``."""
    left, day_no, cur = qty, 0, start
    while cur <= horizon:
        if cal.works(cur):
            day_no += 1
            free = max(0.0, full * learning_pct(curve, day_no) / 100.0 - load.get(cur, 0.0))
            left -= free
            if left <= 1e-9:
                return cur
        cur += timedelta(days=1)
    return None


def free_in_window(start: date, end: date, full: float, curve: list, cal: Calendar, load: dict) -> float:
    """Pieces the line can still sew between two dates (learning curve counted from ``start``)."""
    total, day_no, cur = 0.0, 0, start
    while cur <= end:
        if cal.works(cur):
            day_no += 1
            total += max(0.0, full * learning_pct(curve, day_no) / 100.0 - load.get(cur, 0.0))
        cur += timedelta(days=1)
    return total


def place(qty: float, full: float, curve: list, cal: Calendar, load: dict, earliest: date, sewing_end_target: date):
    """The latest start whose finish is on or before ``sewing_end_target``; ``(start, end)`` or ``None``.

    Searched day by day backwards from the target, so the answer is the same every time.
    """
    s = sewing_end_target
    floor = max(earliest, sewing_end_target - timedelta(days=MAX_WINDOW_DAYS))
    while s >= floor:
        if cal.works(s):
            end = _simulate(s, qty, full, curve, cal, load, sewing_end_target)
            if end is not None:
                return s, end
        s -= timedelta(days=1)
    return None


def earliest_finish(qty: float, full: float, curve: list, cal: Calendar, load: dict, earliest: date) -> Optional[date]:
    """If work starts as early as allowed: the day the quantity is done (``None`` when the line has no capacity at all)."""
    if full <= 0:
        return None
    return _simulate(earliest, qty, full, curve, cal, load, earliest + timedelta(days=MAX_WINDOW_DAYS))


# ───────────────────────── the suggester ─────────────────────────

def _fits_type(line: dict) -> int:
    """Rank of a line for sewing work: 0 = a Sewing line, 1 = line type not recorded, 9 = Cutting / Finishing / Packing (never used).

    ``Workstation.apparel_line_type`` is the kind of line (Cutting, Sewing, Finishing, Packing), not a garment type, so "fits the
    product type" for a sewing allocation means a Sewing line.
    """
    have = (line.get("line_type") or "").strip().lower()
    return 0 if have == "sewing" else 1 if not have else 9


def suggest(ctx: dict) -> dict:
    """Draft allocation. ``ctx`` keys: ``today``, ``order_lines``, ``factories``, ``obs``, ``defaults``, ``style_product_type``,
    ``settings``, ``other_allocations``, optional ``calendar`` (``weekend``, ``holidays``).

    Returns ``{lines, shortfalls, unknown_lines, notes, setup}``. ``lines`` rows carry ``style_item, colour, qty, factory, line,
    pcd, sewing_start, sewing_end, ship_to, buyer_po, ex_factory_date, reason``. Nothing is written anywhere.
    """
    today = _d(ctx["today"])
    cal_in = ctx.get("calendar") or {}
    cal = Calendar(cal_in.get("weekend") or (), cal_in.get("holidays") or ())
    st = ctx.get("settings", {})
    curve = st.get("learning_curve") or []
    min_batch = int(_f(st.get("min_batch_qty")))   # not set = never split a style x colour below its whole quantity
    load = line_load(ctx, cal)
    out_lines: list[dict] = []
    shortfalls: list[dict] = []
    unknown: dict[str, str] = {}
    setup: list[str] = []

    all_lines = []
    for f in ctx.get("factories") or []:
        for ln in f.get("lines") or []:
            if str(ln.get("status") or "") in ("Off", "Maintenance") or ln.get("disabled"):
                continue
            if _fits_type(ln) == 9:
                continue                                      # a cutting, finishing or packing line does not sew
            all_lines.append({**ln, "factory": f["name"]})
    if not ctx.get("factories"):
        setup.append("No factories (Plant Floor) exist. Create them in the ERP; the tower does not invent any.")
    elif not all_lines:
        setup.append("No production lines (Workstation) are set up for the factories.")

    groups = sorted(ctx.get("order_lines") or [], key=lambda g: (str(g.get("ex_factory_date") or "9999"), g["style_item"], g["colour"],
                                                                 g.get("ship_to") or "", g.get("buyer_po") or ""))
    factory_of_style: dict[str, str] = {}
    own_load: dict[str, dict] = {}                           # what this draft itself puts on a line

    def combined(line_name: str) -> dict:
        d = dict(load.get(line_name, {}))
        for k, v in own_load.get(line_name, {}).items():
            d[k] = d.get(k, 0.0) + v
        return d

    def book(line_name: str, s: date, e: date, qty: float):
        days = cal.days(s, e) or [s]
        for d in days:
            own_load.setdefault(line_name, {})[d] = own_load.get(line_name, {}).get(d, 0.0) + qty / len(days)

    for g in groups:
        style, colour, qty = g["style_item"], g["colour"], _f(g["qty"])
        ex = _d(g.get("ex_factory_date"))
        spec = style_spec(ctx, style)
        if qty <= 0:
            continue
        if not ex:
            shortfalls.append({"style_item": style, "colour": colour, "qty_short": qty, "earliest_ex_factory": None,
                               "reason": "No ex-factory date on the order, so there is nothing to plan against."})
            continue
        if spec["finish_pack_days"] <= 0 or spec["cut_lead_days"] <= 0:
            shortfalls.append({"style_item": style, "colour": colour, "qty_short": qty, "earliest_ex_factory": None,
                               "reason": "Finish/pack days or cut lead days are not set (Apparel Settings > allocation). Nothing is assumed."})
            msg = "Finish/pack days and cut lead days are not set in Apparel Settings; the suggester will not guess them."
            if msg not in setup:
                setup.append(msg)
            continue
        sewing_end_target = cal.add(ex, -spec["finish_pack_days"])
        earliest = cal.add(today, spec["cut_lead_days"] + 1)       # PCD cannot be before today
        cands = []
        for ln in all_lines:
            full = full_day_pcs(ln, spec)
            if full <= 0:
                heads, hsrc = line_headcount(ln, spec)
                why = ("no SAM for this style" if spec["sam"] <= 0 else "no planning efficiency set" if spec["eff"] <= 0
                       else "no working minutes per day set" if spec["minutes"] <= 0 else "no operators set on the line")
                unknown[ln["name"]] = f"{ln['name']} ({ln['factory']}): capacity unknown, {why}."
                continue
            cands.append({"line": ln, "full": full, "fit": _fits_type(ln)})
        if not cands:
            shortfalls.append({"style_item": style, "colour": colour, "qty_short": qty, "earliest_ex_factory": None,
                               "reason": "Capacity is unknown for every line, so nothing is placed. Set operators on the lines, a SAM "
                                         "(Operation Bulletin or Product Type default), and the planning efficiency and working minutes in Apparel Settings."})
            if spec["sam"] > 0 and spec["eff"] <= 0:
                setup.append("Planning efficiency is not set (Apparel Settings > Capacity Defaults, or an Operation Bulletin's expected efficiency). Nothing is assumed.")
            if spec["sam"] > 0 and spec["minutes"] <= 0:
                setup.append("Working minutes per day are not set (Apparel Settings). Nothing is assumed.")
            if spec["sam"] <= 0:
                setup.append(f"{style}: no SAM. Make an active Operation Bulletin or add a default for its Product Type in Apparel Settings.")
            continue

        # 1) one line for the whole quantity
        best = None
        for c in cands:
            ln = c["line"]
            ld = combined(ln["name"])
            p = place(qty, c["full"], curve, cal, ld, earliest, sewing_end_target)
            if not p:
                continue
            s, e = p
            slack = max(0, (sewing_end_target - e).days)
            free = free_in_window(s, e, c["full"], curve, cal, ld)
            key = (c["fit"], -slack, 0 if factory_of_style.get(style) in (None, ln["factory"]) else 1,
                   sum(ld.values()), ln["factory"], ln["name"])
            if best is None or key < best[0]:
                best = (key, c, s, e, slack, free)
        if best:
            _, c, s, e, slack, free = best
            ln = c["line"]
            out_lines.append(_row(g, spec, ln, qty, s, e, cal, slack, free, c, "whole"))
            book(ln["name"], s, e, qty)
            factory_of_style.setdefault(style, ln["factory"])
            continue

        # 2) split over lines, never below the minimum batch
        remaining, parts = qty, []
        ranked = sorted(cands, key=lambda c: (c["fit"], 0 if factory_of_style.get(style) in (None, c["line"]["factory"]) else 1,
                                              sum(combined(c["line"]["name"]).values()), c["line"]["name"]))
        for c in ranked:
            if remaining <= 0:
                break
            ln = c["line"]
            ld = combined(ln["name"])
            cap = free_in_window(earliest, sewing_end_target, c["full"], curve, cal, ld)
            take = min(remaining, math.floor(cap))
            if take < min(min_batch, remaining):
                continue                                     # too small to be worth a changeover
            if remaining - take < min_batch and remaining - take > 0:
                take = min(remaining, math.floor(cap))       # leave no sliver behind: this line takes all it can
            p = place(take, c["full"], curve, cal, ld, earliest, sewing_end_target)
            if not p:
                continue
            parts.append((c, take, p))
            remaining -= take
        if remaining <= 0 and parts:                         # each part is on its own line, so nothing was booked until now
            for c, take, (s, e) in parts:
                ln = c["line"]
                slack = max(0, (sewing_end_target - e).days)
                out_lines.append(_row(g, spec, ln, take, s, e, cal, slack, take, c, "split", of=qty))
                book(ln["name"], s, e, take)
                factory_of_style.setdefault(style, ln["factory"])
            continue
        # earliest feasible ex-factory: all lines together, starting as soon as allowed
        best_e = None
        for c in cands:
            e = earliest_finish(qty, c["full"], curve, cal, combined(c["line"]["name"]), earliest)
            if e and (best_e is None or e < best_e[0]):
                best_e = (e, c["line"])
        if best_e:
            feasible_ex = cal.add(best_e[0], spec["finish_pack_days"])
            late = (feasible_ex - ex).days
            reason = (f"Does not fit by {ex:%d %b %Y}: the best line ({best_e[1]['name']}, {best_e[1]['factory']}) finishes sewing "
                      f"{best_e[0]:%d %b %Y}, so ex-factory {feasible_ex:%d %b %Y} ({late} days late).")
        else:
            feasible_ex, reason = None, "No line has capacity for this style."
        shortfalls.append({"style_item": style, "colour": colour, "qty_short": qty, "earliest_ex_factory": str(feasible_ex) if feasible_ex else None,
                           "reason": reason})

    out_lines.sort(key=lambda r: (r["style_item"], r["colour"], r["factory"], r["line"]))
    notes = _notes(out_lines, shortfalls, list(unknown.values()))
    return {"lines": out_lines, "shortfalls": shortfalls, "unknown_lines": sorted(unknown.values()), "notes": notes, "setup": setup}


def _row(g: dict, spec: dict, ln: dict, qty: float, s: date, e: date, cal: Calendar, slack: int, free: float, c: dict, mode: str, of: float = 0) -> dict:
    heads, hsrc = line_headcount(ln, spec)
    pcd = cal.add(s, -spec["cut_lead_days"])
    days = len(cal.days(s, e))
    rate = c["full"]
    fit = {0: "sewing line", 1: "line type not recorded"}[c["fit"]]
    why = (f"{ln['name']} at {ln['factory']}: {int(qty):,} pcs sewn {s:%d %b} to {e:%d %b} ({days} working days) at "
           f"{int(round(rate)):,} pcs/day ({int(heads)} workers, {spec['eff']:g}% of {spec['sam']:g} SAM from the {spec['sam_source']}"
           f"), {fit}, {slack} days slack to the finishing allowance")
    if mode == "split":
        why += f"; split: no single line could take all {int(of):,} pcs by the date"
    return {"style_item": g["style_item"], "style_no": g["style_item"], "colour": g["colour"], "qty": int(qty), "factory": ln["factory"], "line": ln["name"],
            "pcd": str(pcd), "sewing_start": str(s), "sewing_end": str(e), "ship_to": g.get("ship_to") or "", "buyer_po": g.get("buyer_po") or "",
            "order_qty": int(_f(g["qty"])), "ex_factory_date": str(_d(g.get("ex_factory_date")) or ""), "reason": why + "."}


def _notes(lines: list, shortfalls: list, unknown: list) -> str:
    """The text saved in ``agent_notes``: why each row, what did not fit, which lines were left out."""
    out = [f"Suggested by the tower's allocation suggester ({len(lines)} line(s))."]
    out += [f"- {r['style_item']} / {r['colour']}: {r['reason']}" for r in lines]
    out += [f"- SHORTFALL {s['style_item']} / {s['colour']} ({int(s['qty_short']):,} pcs): {s['reason']}" for s in shortfalls]
    out += [f"- {u}" for u in unknown]
    return "\n".join(out)
