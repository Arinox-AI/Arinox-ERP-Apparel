"""Reads for the allocation board (ORDER_TO_SHIP_PLAN section 5): turns the ERP into the plain ``ctx`` that ``allocation.suggest`` takes.

Read only. The planning context itself comes from the Arinox API script ``arinox_factory_allocation_get_planning_context`` (run by
``order_api`` through the pipeline); everything the script does not carry (the Operation Bulletins, the line headcount and type,
the settings) is read here with plain ``get_list`` calls. Nothing is guessed: a missing value stays missing and the suggester
says "capacity unknown".
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import allocation


def _num(v, default=0.0):
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def read_settings(be) -> dict:
    s = be.get_single("Apparel Settings") or {}
    return {
        "work_minutes_per_day": _num(s.get("work_minutes_per_day")),
        "planned_efficiency_pct": _num(s.get("planned_efficiency_pct")),
        "finish_pack_days": int(_num(s.get("alloc_finish_pack_days"))),
        "cut_lead_days": int(_num(s.get("alloc_cut_lead_days"))),
        "min_batch_qty": int(_num(s.get("alloc_min_batch_qty"))),
        "learning_curve": [[int(r.get("day_no") or 0), _num(r.get("pct_of_target"), 100)] for r in s.get("learning_curve") or []],
        "defaults": {r["product_type"]: {"sewing_sam": _num(r.get("sewing_sam")), "efficiency_pct": _num(r.get("efficiency_pct")),
                                         "finish_pack_days": int(_num(r.get("finish_pack_days"))), "cut_lead_days": int(_num(r.get("cut_lead_days"))),
                                         "source": r.get("source") or ""}
                     for r in s.get("alloc_defaults") or [] if r.get("product_type")},
    }


def read_lines(be, factories: list[dict]) -> list[dict]:
    """The factories of the planning context with each line's headcount and type (Workstation custom fields)."""
    rows = be.get_list("Workstation", [["disabled", "=", 0]],
                       ["name", "plant_floor", "status", "apparel_line_type", "apparel_default_operators", "apparel_default_helpers"], limit=500)
    by_floor: dict[str, list] = {}
    for r in rows:
        by_floor.setdefault(r.get("plant_floor") or "", []).append(
            {"name": r["name"], "status": r.get("status") or "", "line_type": r.get("apparel_line_type") or "",
             "operators": int(_num(r.get("apparel_default_operators"))), "helpers": int(_num(r.get("apparel_default_helpers")))})
    out = []
    for f in factories:
        out.append({"name": f["name"], "company": f.get("company"), "lines": sorted(by_floor.get(f["name"], []), key=lambda x: x["name"])})
    return out


def read_obs(be, styles: list[str]) -> dict:
    """The active Operation Bulletin of each style: the highest version (colour is not used to pick one)."""
    if not styles:
        return {}
    rows = be.get_list("Operation Bulletin", [["style_item", "in", styles], ["status", "=", "Active"]],
                       ["name", "style_item", "version", "total_sam", "sewing_sam", "expected_efficiency_pct", "working_minutes", "operators", "colour"],
                       limit=500)
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (int(_num(r.get("version"))), r["name"])):
        out[r["style_item"]] = r                              # a later (higher) version replaces an earlier one
    return out


def read_product_types(be, styles: list[str]) -> dict:
    """style -> Product Type: the Tech Pack of the style says it; else the Item Group each Product Type owns (the style Item is made
    in that group). Unknown stays empty (the suggester then has no default SAM for it and says so)."""
    if not styles:
        return {}
    out = {s: "" for s in styles}
    for tp in be.get_list("Tech Pack", [["style_item", "in", styles], ["docstatus", "!=", 2]], ["name", "style_item", "product_type"],
                          order_by="modified asc", limit=500):
        if tp.get("product_type"):
            out[tp["style_item"]] = tp["product_type"]        # the latest non-empty one wins (ordered oldest first)
    missing = [s for s, t in out.items() if not t]
    if missing:
        items = be.get_list("Item", [["name", "in", missing]], ["name", "item_group"], limit=500)
        types = be.get_list("Product Type", [], ["name", "item_group"], limit=200)
        by_group: dict[str, str] = {}
        for t in sorted(types, key=lambda t: t["name"]):
            if t.get("item_group"):
                by_group.setdefault(t["item_group"], t["name"])
        for i in items:
            out[i["name"]] = by_group.get(i.get("item_group") or "", "")
    return out


def build_ctx(be, planning: dict, today: date) -> dict:
    """``allocation.suggest`` input from the planning-context script's answer plus the extra reads."""
    order_lines = planning.get("order_lines") or []
    styles = sorted({o["style_item"] for o in order_lines})
    settings = read_settings(be)
    defaults = settings.pop("defaults")
    factories = read_lines(be, planning.get("factories") or [])
    return {"today": today.isoformat(), "order_lines": order_lines, "factories": factories, "obs": read_obs(be, styles),
            "defaults": defaults, "style_product_type": read_product_types(be, styles), "settings": settings,
            "other_allocations": planning.get("other_allocations_in_window") or [],
            "calendar": {}}                                    # D5: every day works; holidays stay data for later


def setup_checklist(be, ctx: dict) -> list[dict]:
    """What is missing before the suggester can place work, each with the ERP page that fixes it. Never invents data."""
    import erp as _erp
    items: list[dict] = []
    facs = ctx.get("factories") or []
    if not facs:
        items.append({"text": "No factory exists. Create the factories (Plant Floor) in the ERP.", "url": _erp.url_for("Plant Floor"), "label": "Open Plant Floor"})
    lines = [ln for f in facs for ln in f.get("lines") or []]
    if facs and not lines:
        items.append({"text": "No production line exists. Create the lines (Workstation) and set each one's factory.", "url": _erp.url_for("Workstation"), "label": "Open Workstation"})
    no_ops = [ln["name"] for ln in lines if ln["operators"] + ln["helpers"] <= 0]
    if no_ops:
        items.append({"text": f"{len(no_ops)} line(s) have no operators set: {', '.join(no_ops[:6])}{'...' if len(no_ops) > 6 else ''}. Set default operators and helpers on each line.",
                      "url": _erp.url_for("Workstation"), "label": "Open Workstation"})
    no_type = [ln["name"] for ln in lines if not ln["line_type"]]
    if no_type:
        items.append({"text": f"{len(no_type)} line(s) have no line type (Sewing, Cutting ...): they rank below lines marked Sewing.",
                      "url": _erp.url_for("Workstation"), "label": "Open Workstation"})
    st = ctx.get("settings") or {}
    if not st.get("planned_efficiency_pct") or not st.get("work_minutes_per_day"):
        items.append({"text": "Planning efficiency and/or working minutes per day are not set, so line capacity is unknown. Set them in Apparel Settings (Operation Bulletins and 'suggest from my history' can inform them). Nothing is assumed.",
                      "url": _erp.url_for("Apparel Settings"), "label": "Open Apparel Settings"})
    if not st.get("finish_pack_days") or not st.get("cut_lead_days"):
        items.append({"text": "Finish/pack days and cut lead days are not set in Apparel Settings; the suggester will not guess them.",
                      "url": _erp.url_for("Apparel Settings"), "label": "Open Apparel Settings"})
    nosam = sorted({o["style_item"] for o in ctx.get("order_lines") or []
                    if allocation.style_spec(ctx, o["style_item"])["sam"] <= 0})
    if nosam:
        items.append({"text": f"No SAM for {', '.join(nosam)}. Make an active Operation Bulletin, or add the Product Type's default in Apparel Settings.",
                      "url": _erp.url_for("Operation Bulletin"), "label": "Open Operation Bulletin"})
    return items


def _median(v: list) -> float:
    v = sorted(v)
    n = len(v)
    return 0.0 if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def suggest_defaults(be) -> dict:
    """'Suggest from my history': a proposed SAM and efficiency per Product Type, from this tenant's OWN active Operation Bulletins
    and Daily Line Reports only. Read only (writes nothing). With no history every list is empty and the counts are 0, so the
    caller shows 'nothing to suggest yet'. Efficiency per Product Type comes from the bulletins' expected efficiency; the Daily Line
    Reports' measured efficiency is reported as one tenant-wide figure (a report is per line, not per style)."""
    obs = be.get_list("Operation Bulletin", [["status", "=", "Active"]], ["name", "style_item", "total_sam", "expected_efficiency_pct"], limit=1000)
    styles = sorted({o["style_item"] for o in obs if o.get("style_item")})
    ptype = read_product_types(be, styles)
    by: dict[str, dict] = {}
    for o in obs:
        t = ptype.get(o.get("style_item") or "")
        if not t:
            continue
        d = by.setdefault(t, {"sam": [], "eff": []})
        if _num(o.get("total_sam")) > 0:
            d["sam"].append(_num(o["total_sam"]))
        if _num(o.get("expected_efficiency_pct")) > 0:
            d["eff"].append(_num(o["expected_efficiency_pct"]))
    rows = [{"product_type": t, "sewing_sam": round(_median(d["sam"]), 2) if d["sam"] else None, "sam_samples": len(d["sam"]),
             "efficiency_pct": round(_median(d["eff"]), 1) if d["eff"] else None, "efficiency_samples": len(d["eff"]),
             "source": f"median of {len(d['sam'])} Operation Bulletin(s)"} for t, d in sorted(by.items())]
    dlr = [_num(r.get("efficiency_pct")) for r in be.get_list("Daily Line Report", [["docstatus", "=", 1]], ["name", "efficiency_pct"], limit=2000)
           if _num(r.get("efficiency_pct")) > 0]
    measured = {"efficiency_pct": round(_median(dlr), 1) if dlr else None, "samples": len(dlr),
                "note": "Median measured efficiency over your submitted Daily Line Reports (all products)."}
    return {"ok": True, "suggestions": rows, "measured_efficiency": measured, "writes": False,
            "empty": not rows and not dlr,
            "note": "Nothing to suggest yet: make Operation Bulletins and Daily Line Reports first." if not rows and not dlr
                    else "Proposals only. Nothing was saved; copy the ones you accept into Apparel Settings > Capacity Defaults."}


def load_strip(ctx: dict, weeks: int = 8) -> dict:
    """Per line, the pieces already booked in each of the next ``weeks`` weeks (other allocations spread over their sewing days)."""
    today = allocation._d(ctx["today"])
    cal = allocation.Calendar((ctx.get("calendar") or {}).get("weekend") or (), (ctx.get("calendar") or {}).get("holidays") or ())
    load = allocation.line_load(ctx, cal)
    starts = [today + timedelta(days=7 * i) for i in range(weeks)]
    out: dict[str, list] = {}
    for f in ctx.get("factories") or []:
        for ln in f.get("lines") or []:
            per = load.get(ln["name"], {})
            out[ln["name"]] = [round(sum(v for d, v in per.items() if s <= d < s + timedelta(days=7))) for s in starts]
    return {"weeks": [s.isoformat() for s in starts], "load": out}
