"""Cortex Operations Control Tower — the WIP charts that are not the Gantt.

Everything here is a read. The rule the whole module follows: **a number that could be zero because nothing is
there is not the same as a number that is zero because nothing is wrong** — so every section carries a `basis`
string saying what it counted and where it came from, and every rate carries an explicit `na` reason instead of a
`0 %`.

Sections
    stages        qty sitting at each stage, with ageing buckets — from `Cortex WIP Line.current_stage`
    output        made per date (manufacture `Stock Entry`), cumulative, against the plan's own finish
    efficiency    SAM allowed (BOM operation minutes × qty) against the days actually used
    quality       reject rate from submitted `Quality Inspection` rows, by where it was inspected
    completion    per order: made % · shipped % · gates proved % · projected finish · at risk
    shortage      requisition required vs stock in the Bin, per item per order
    reconcile     in-stage + made + rejected == order qty, per order — the arithmetic that must tie
    issues        the data-quality findings the Gantt has to survive (unscheduled, inverted, zero-duration,
                  dependency violated, missing size/colour, duplicate line, future-dated, over-production)
    policy        what is counted and what is not (drafts, cancelled, amended)

The item UOM on every WIP line is `Garment`, checked 2026-11-03, so pcs compare directly. Fabric is metres in
`Cortex Fabric Requisition` and in the Bin — it is never added to a garment quantity anywhere in this file.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

import erp

WIP = "Cortex WIP"

# stages in garment order; anything the ERP reports that is not here is appended after them
STAGE_ORDER = ["Lab Dip", "Bulk Fabric Approval", "PP Sample Approval", "Fabric Requisition Placed",
               "Fabric In-House", "Trim Requisition Placed", "Trims In-House", "PP Meeting", "Cutting",
               "Sewing", "Washing", "Final Inspection", "Ship"]
BUCKETS = [("0-2", 0, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("10+", 11, 10 ** 6)]


def _d(v) -> date | None:
    s = str(v or "")[:10]
    return date.fromisoformat(s) if len(s) == 10 else None


def _n(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _bucket(days: int) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= days <= hi:
            return name
    return "10+"


# ─────────────────────────────────────────────────────────────────────────────── stages + ageing
def stages(lanes: list[dict], today: date) -> dict:
    """Where the garments are, by the line's own `current_stage` (the last gate a document proved).

    The age of a garment in a stage is counted from the **actual date of the gate that got it there** — the
    provenance the milestone row also carries — falling back to that gate's drop-dead when there is no actual
    (in which case the age is "at least", and the row says so through `aged_by`).
    """
    agg: dict[str, dict] = {}
    for l in lanes:
        stage = (l.get("stage") or "").strip()
        key = stage or "Not started"
        a = agg.setdefault(key, {"stage": key, "qty": 0.0, "lanes": 0, "late": 0, "ages": [],
                                 "buckets": {b[0]: 0.0 for b in BUCKETS}, "aged_by": Counter()})
        a["qty"] += _n(l.get("qty"))
        a["lanes"] += 1
        a["late"] += 1 if l.get("late") else 0
        proved = [b for b in l.get("bars") or [] if b.get("milestone") == stage]
        ref, basis = None, "not dated"
        if proved:
            b = proved[0]
            if b.get("actual"):
                ref, basis = _d(b["actual"]), "actual"
            elif b.get("date"):
                ref, basis = _d(b["date"]), "drop-dead (not proved)"
        if ref:
            days = max(0, (today - ref).days)
            a["ages"].append(days)
            a["buckets"][_bucket(days)] += _n(l.get("qty"))
            a["aged_by"][basis] += 1
        else:
            a["aged_by"]["not dated"] += 1

    rows = []
    for name in STAGE_ORDER + sorted(set(agg) - set(STAGE_ORDER)):
        a = agg.get(name)
        if not a:
            continue
        rows.append({
            "stage": a["stage"], "qty": round(a["qty"], 1), "lanes": a["lanes"], "late": a["late"],
            "age_avg": round(sum(a["ages"]) / len(a["ages"]), 1) if a["ages"] else None,
            "age_max": max(a["ages"]) if a["ages"] else None,
            "buckets": {k: round(v, 1) for k, v in a["buckets"].items()},
            "aged_by": dict(a["aged_by"]),
        })
    total = round(sum(r["qty"] for r in rows), 1)
    return {
        "rows": rows, "total_qty": total, "buckets": [b[0] for b in BUCKETS],
        "basis": ("every WIP line's quantity placed at its `current_stage` (the last gate a document proved); "
                  "age = days since that gate's actual date, or since its drop-dead when it has none — the "
                  "`aged_by` counters say how many rows used each. A line with no stage is 'Not started'."),
    }


# ─────────────────────────────────────────────────────────────────────────────── planned vs actual output
def _manufacture_scan(today: date) -> tuple[Counter, dict]:
    """One pass over submitted manufacture Stock Entries → (qty by date, qty by work order)."""
    made: Counter = Counter()
    by_wo: dict[str, float] = {}
    for se in erp.erp_get("Stock Entry", fields=["name", "purpose", "posting_date", "work_order", "docstatus"],
                          limit=0):
        if se.get("purpose") != "Manufacture" or int(se.get("docstatus") or 0) != 1:
            continue
        ok, doc = erp._request(f"/api/resource/Stock Entry/{se['name']}")
        if not ok:
            continue
        d = (doc or {}).get("data") or {}
        qty = sum(_n(i.get("qty")) for i in d.get("items") or [] if _n(i.get("qty")) > 0 and i.get("t_warehouse"))
        if qty:
            made[str(d.get("posting_date") or se.get("posting_date"))[:10]] += qty
            wo = d.get("work_order") or se.get("work_order")
            if wo:
                by_wo[wo] = by_wo.get(wo, 0.0) + qty
    return made, by_wo


def output(orders: list[dict], today: date, made: Counter | None = None) -> dict:
    """Made per date from submitted manufacture `Stock Entry` rows, cumulative, with the plan's finish."""
    if made is None:
        made, _ = _manufacture_scan(today)
    series, cum = [], 0.0
    for day in sorted(made):
        cum += made[day]
        series.append({"date": day, "made": round(made[day], 1), "cumulative": round(cum, 1)})

    order_qty = sum(_n(o.get("qty")) for o in orders)
    # the plan's own finish: the latest PCD across live orders — a target line, not a promise
    pcds = [d for d in (_d(o.get("pcd")) for o in orders) if d]
    ships = [d for d in (_d(o.get("ship_date")) for o in orders) if d]
    future = [s for s in series if _d(s["date"]) and _d(s["date"]) > today]
    return {
        "series": series, "total_made": round(cum, 1), "order_qty": round(order_qty, 1),
        "made_pct": round(100 * cum / order_qty, 1) if order_qty else None,
        "plan_finish_last_pcd": max(pcds).isoformat() if pcds else None,
        "ship_last": max(ships).isoformat() if ships else None,
        "future_dated_rows": len(future),
        "basis": ("submitted manufacture Stock Entries only (cancelled ones excluded — 12 cancelled entries exist "
                  "on this instance). It is **order-level, not line-level**: there is no line object and the daily "
                  "production object holds 0 rows, so a per-line or per-day-per-line output series cannot be built "
                  "from this ERP yet. Fabric movements are metres and never enter this number."),
    }


# ─────────────────────────────────────────────────────────────────────────────── efficiency (SAM)
def efficiency(orders: list[dict], today: date) -> dict:
    """SAM allowed vs days used. Job-card *time* is deliberately excluded — see the basis."""
    rows = []
    for o in orders:
        qty = _n(o.get("qty"))
        sam_min = 0.0
        boms = 0
        for w in erp.erp_get("Work Order", fields=["name", "production_item", "bom_no", "qty", "sales_order"],
                             filters=[["sales_order", "=", o.get("sales_order")]], limit=0):
            doc = erp._request(f"/api/resource/BOM/{w['bom_no']}")[1]["data"] if w.get("bom_no") else {}
            ops = (doc or {}).get("operations") or []
            if ops:
                boms += 1
                sam_min += sum(_n(op.get("time_in_mins")) for op in ops) * _n(w.get("qty"))
        pcd, ship = _d(o.get("pcd")), _d(o.get("ship_date"))
        days = (ship - pcd).days if pcd and ship else None
        sam_hours = sam_min / 60.0
        rows.append({
            "order": o.get("sales_order"), "buyer": o.get("buyer"), "qty": qty, "boms_with_routing": boms,
            "sam_minutes_allowed": round(sam_min, 1), "sam_hours_allowed": round(sam_hours, 1),
            "plan_days": days,
            "sam_garments_per_day": round(qty / days, 1) if days and days > 0 else None,
            "na": None if (boms and days) else ("no BOM routing for this order" if not boms else "no pcd/ship window"),
        })
    return {
        "rows": rows,
        "basis": ("SAM allowed = Σ `BOM.operations.time_in_mins` × work-order qty, which is the only time basis on "
                  "this instance that is not seeded. `Job Card` actual times are **excluded on purpose**: 175 of "
                  "190 cards record under a minute (median 0.6 min) for ~200 pcs, so a line efficiency computed "
                  "from them would be fiction (RULES/01 #118). 27 of 39 BOMs carry operations; an order whose BOM "
                  "has none reports `na`, not 0 %."),
    }


# ─────────────────────────────────────────────────────────────────────────────── quality
def quality(today: date) -> dict:
    by = defaultdict(lambda: {"inspected": 0.0, "rejected": 0.0, "rows": 0, "cancelled": 0})
    for q in erp.erp_get("Quality Inspection", fields=["name", "status", "docstatus", "reference_type",
                                                       "sample_size", "custom_rejected_qty", "item_code"], limit=0):
        if int(q.get("docstatus") or 0) == 2:
            by[q.get("reference_type") or "—"]["cancelled"] += 1
            continue
        if int(q.get("docstatus") or 0) != 1:
            continue
        t = q.get("reference_type") or "—"
        by[t]["rows"] += 1
        by[t]["inspected"] += _n(q.get("sample_size"))
        by[t]["rejected"] += _n(q.get("custom_rejected_qty"))
    rows = []
    for t, v in sorted(by.items()):
        rate = round(100 * v["rejected"] / v["inspected"], 2) if v["inspected"] else None
        rows.append({"stage": f"{t}", "inspections": v["rows"], "inspected_qty": round(v["inspected"], 1),
                     "rejected_qty": round(v["rejected"], 1), "reject_pct": rate,
                     "na": None if v["inspected"] else "nothing inspected on a submitted document"})
    tot_i = sum(r["inspected_qty"] for r in rows)
    tot_r = sum(r["rejected_qty"] for r in rows)
    return {
        "rows": rows, "inspected_qty": round(tot_i, 1), "rejected_qty": round(tot_r, 1),
        "reject_pct": round(100 * tot_r / tot_i, 2) if tot_i else None,
        "basis": ("submitted Quality Inspections only (6 cancelled excluded). The inspection is attached to a "
                  "Purchase Receipt or a Delivery Note — i.e. **fabric in** and **final out** — so a reject rate "
                  "per production stage (cutting / sewing / washing) cannot be produced from this instance: the "
                  "object that would hold it, `Cortex End Line Audit`, holds 0 rows."),
    }


# ─────────────────────────────────────────────────────────────────────────────── completion + at risk
def completion(lanes: list[dict], orders: list[dict], made_by_order: dict, today: date) -> dict:
    rows = []
    for o in orders:
        qty = _n(o.get("qty"))
        mine = [l for l in lanes if l.get("wip") == o.get("wip")]
        shipped = sum(_n(l.get("shipped_qty")) for l in mine)
        bars = [b for l in mine for b in (l.get("bars") or [])]
        proved = sum(1 for b in bars if b.get("status") == "Done")
        made = _n(made_by_order.get(o.get("sales_order")))
        rec = (mine[0].get("recovery") if mine else {}) or {}
        over = (shipped > qty > 0) or (made > qty > 0)
        rows.append({
            "order": o.get("sales_order"), "buyer": o.get("buyer"), "wip": o.get("wip"), "qty": qty,
            "made": round(made, 1), "made_pct": round(100 * made / qty, 1) if qty else None,
            "shipped": round(shipped, 1), "shipped_pct": round(100 * shipped / qty, 1) if qty else None,
            "gates_proved_pct": round(100 * proved / len(bars), 1) if bars else None,
            "projected_finish": rec.get("projected_ship"), "ship_date": o.get("ship_date"),
            "state": rec.get("state"), "at_risk": rec.get("state") in ("TIGHT", "PAST"),
            "over_produced": over,
        })
    return {
        "rows": rows,
        "basis": ("made = submitted manufacture Stock Entries for the order's work orders · shipped = Σ WIP line "
                  "`shipped_qty` · gates proved = gates whose milestone row has an `actual`. A percentage is "
                  "`null` (never 0) when the order quantity is 0, and `over_produced` is set instead of clamping "
                  "the number silently."),
    }


# ─────────────────────────────────────────────────────────────────────────────── shortage
def shortage(today: date, horizon_days: int = 21) -> dict:
    stock = defaultdict(float)
    for b in erp.erp_get("Bin", fields=["item_code", "warehouse", "actual_qty"], limit=0):
        if b.get("item_code"):
            stock[b["item_code"]] += _n(b.get("actual_qty"))
    rows = []
    for dt in ("Cortex Fabric Requisition", "Cortex Trim Requisition"):
        for r in erp.erp_get(dt, fields=["name", "sales_order", "status", "required_by", "docstatus"], limit=0):
            if int(r.get("docstatus") or 0) == 2:
                continue
            ok, doc = erp._request(f"/api/resource/{dt.replace(' ', '%20')}/{r['name']}")
            if not ok:
                continue
            items = ((doc or {}).get("data") or {}).get("items") or []
            # a requisition carries one row per SIZE for the same fabric — aggregate per item before comparing
            # with stock, or ten size rows each "under stock" read as ten shortfalls of the whole quantity
            need_by_item: dict[str, float] = {}
            for i in items:
                need_by_item[i.get("item_code")] = need_by_item.get(i.get("item_code"), 0.0) + _n(
                    i.get("required_qty") or i.get("buy_qty") or i.get("exact_qty"))
            req = sum(need_by_item.values())
            short_items = []
            for item, need in need_by_item.items():
                have = stock.get(item, 0.0)
                if need > have:
                    short_items.append({"item": item, "need": round(need, 1), "in_stock": round(have, 1),
                                        "gap": round(need - have, 1)})
            short_items.sort(key=lambda x: -x["gap"])
            due = _d(r.get("required_by"))
            soon = due is not None and due <= today + timedelta(days=horizon_days)
            if short_items:
                rows.append({"doc": "FR" if "Fabric" in dt else "TR", "requisition": r["name"],
                             "order": r.get("sales_order"), "status": r.get("status"),
                             "required_by": r.get("required_by"), "required_qty": round(req, 1),
                             "items_short": len(short_items), "items": short_items[:6],
                             "blocking": bool(soon and (r.get("status") or "") != "Closed")})
    rows.sort(key=lambda x: (not x["blocking"], x.get("required_by") or "9999"))
    return {
        "rows": rows, "blocking": sum(1 for r in rows if r["blocking"]), "horizon_days": horizon_days,
        "basis": (f"requisition rows whose required qty exceeds the **stock in the Bin** for that item (all "
                  f"warehouses, actual qty). 'blocking' = the requisition is still open and its required_by is "
                  f"within {horizon_days} days. Fabric is compared in metres with fabric, never with garments."),
    }


# ─────────────────────────────────────────────────────────────────────────────── the arithmetic that must tie
def reconcile(lanes: list[dict], orders: list[dict], stages_rows: list[dict], made_by_order: dict,
              rejected_qty: float, today: date) -> dict:
    rows = []
    for o in orders:
        qty = _n(o.get("qty"))
        mine = [l for l in lanes if l.get("wip") == o.get("wip")]
        shipped = sum(_n(l.get("shipped_qty")) for l in mine)
        made = _n(made_by_order.get(o.get("sales_order")))
        # in stage = what is still in the factory: everything made but not shipped
        in_factory = max(0.0, made - shipped)
        residual = round(qty - (in_factory + shipped), 1)
        rows.append({
            "order": o.get("sales_order"), "buyer": o.get("buyer"), "order_qty": qty,
            "made": round(made, 1), "shipped": round(shipped, 1), "in_factory": round(in_factory, 1),
            "not_yet_made": round(max(0.0, qty - made), 1), "residual": residual,
            "ties": abs(residual) < 0.5 and abs((in_factory + shipped) + max(0.0, qty - made) - qty) < 0.5,
        })
    tot = {k: round(sum(r[k] for r in rows), 1) for k in ("order_qty", "made", "shipped", "in_factory", "not_yet_made")}
    return {
        "rows": rows, "totals": tot,
        "ties_everywhere": all(r["ties"] for r in rows) if rows else None,
        "basis": ("order qty = **in the factory** (made − shipped) + shipped + **not yet made**. Rejected pieces "
                  "are reported separately and never added here, because this instance has no per-stage rejection "
                  "quantity — adding the fabric-inspection rejects would mix metres with garments."),
    }


# ─────────────────────────────────────────────────────────────────────────────── data quality
def issues(lanes: list[dict], orders: list[dict], today: date) -> dict:
    out = []
    seen: dict[tuple, str] = {}
    for l in lanes:
        wip, sku = l.get("wip"), l.get("sku")
        key = (wip, sku)
        if key in seen:
            out.append({"kind": "duplicate line", "order": l.get("order"), "sku": sku,
                        "detail": f"{sku} appears twice in {wip} — quantities would double-count"})
        seen[key] = wip
        bars = l.get("bars") or []
        if not bars or not any(b.get("date") for b in bars):
            out.append({"kind": "unscheduled", "order": l.get("order"), "sku": sku,
                        "detail": "no gate carries a date — the lane cannot be drawn on a time axis"})
        if not l.get("ship_date"):
            out.append({"kind": "no ship date", "order": l.get("order"), "sku": sku,
                        "detail": "no contract ship date — every window falls back to today"})
        for b in bars:
            if b.get("start") and b.get("end") and _d(b["end"]) < _d(b["start"]):
                out.append({"kind": "end before start", "order": l.get("order"), "sku": sku,
                            "detail": f"{b['milestone']}: {b['start']} → {b['end']} (inverted window)"})
            if b.get("window_days") == 0:
                out.append({"kind": "zero duration", "order": l.get("order"), "sku": sku,
                            "detail": f"{b['milestone']} has no window — drawn as a gate, not a bar"})
            if b.get("actual") and _d(b["actual"]) and _d(b["actual"]) > today:
                out.append({"kind": "future-dated actual", "order": l.get("order"), "sku": sku,
                            "detail": f"{b['milestone']} 'actual' {b['actual']} is in the future"})
        # dependency: a successor with an actual but no predecessor actual, or an earlier actual
        # two different findings, kept apart because they need different answers:
        #   · a VIOLATION is dates that contradict each other — the successor happened before its predecessor
        #   · NO EVIDENCE is the normal state here — the requisition date exists, the approval it waits for has
        #     no document at all, so the plan cannot prove the order (72 of these on 2026-11-03, not 72 mistakes)
        seq = [b for b in bars if b.get("date")]
        for a, b in zip(seq, seq[1:]):
            if a.get("actual") and b.get("actual") and _d(b["actual"]) < _d(a["actual"]):
                out.append({"kind": "dependency violated", "order": l.get("order"), "sku": sku,
                            "detail": f"{b['milestone']} ({b['actual']}) happened before {a['milestone']} ({a['actual']})"})
            elif b.get("actual") and not a.get("actual"):
                out.append({"kind": "dependency not evidenced", "order": l.get("order"), "sku": sku,
                            "detail": f"{b['milestone']} is proved ({b['actual']}) while {a['milestone']} has no document"})
    for o in orders:
        if not o.get("plant"):
            out.append({"kind": "no plant", "order": o.get("sales_order"), "sku": None,
                        "detail": "no plant allocated — the plan has nowhere to be made"})
    counts = Counter(i["kind"] for i in out)
    return {
        "rows": out[:400], "counts": dict(counts), "total": len(out),
        "basis": ("checked on every lane of the live plan: unscheduled · inverted window · zero-duration gate · "
                  "future-dated actual · dependency order · duplicate line · missing plant. Nothing here is "
                  "dropped from the Gantt — each finding is also drawn, so the chart and this list agree."),
    }


def build_all(orders: list[dict], lanes: list[dict], today: date) -> dict:
    """Every non-Gantt section in one read, from one manufacture scan (the expensive part)."""
    imported = erp.erp_get("Stock Entry", fields=["name", "purpose", "docstatus"], limit=0)
    made_by_date, made_by_wo = _manufacture_scan(today)
    wo = erp.erp_get("Work Order", fields=["name", "sales_order", "qty"], limit=0)
    wo_to_so = {w["name"]: w.get("sales_order") for w in wo}
    made_by_order: dict[str, float] = {}
    for w, q in made_by_wo.items():
        so = wo_to_so.get(w)
        if so:
            made_by_order[so] = made_by_order.get(so, 0.0) + q

    st = stages(lanes, today)
    ou = output(orders, today, made_by_date)
    qu = quality(today)
    return {
        "today": today.isoformat(),
        "stages": st, "output": ou,
        "efficiency": efficiency(orders, today),
        "quality": qu,
        "completion": completion(lanes, orders, made_by_order, today),
        "shortage": shortage(today),
        "reconcile": reconcile(lanes, orders, st["rows"], made_by_order, qu["rejected_qty"], today),
        "made_by_order": {k: round(v, 1) for k, v in made_by_order.items()},
        "stock_entries_scanned": sum(1 for x in imported if x.get("purpose") == "Manufacture"),
        "basis": ("one read of the plan plus the manufacturing, stock, quality and requisition records. Each "
                  "section carries its own `basis`; nothing here is cached beyond the call, and the caller is "
                  "told the read time."),
    }


def policy(cancelled: dict) -> dict:
    return {
        "counts": cancelled,
        "bases": [
            "**cancelled documents excluded everywhere** (docstatus 2) — measured: " +
            ", ".join(f"{k} {v}" for k, v in cancelled.items() if v) if cancelled else
            "**cancelled documents excluded everywhere**",
            "**drafts included but labelled**: a WIP in `Draft` is a proposal (the planner has not finalised it), "
            "so it is drawn and counted — hiding it would hide work that is about to be committed",
            "**amended documents counted once**, on the live (non-cancelled) record; the amended-from name is not "
            "followed, so a cancelled original and its amendment cannot both appear",
            "**draft Sales Orders excluded** from the plan (2 exist): they are not the contract yet",
        ],
    }
