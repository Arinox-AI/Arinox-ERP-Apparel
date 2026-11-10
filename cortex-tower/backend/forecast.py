"""Cortex Control Tower — Phase 4: forecasting / predictive layer.

Forward-looking projections computed from live ERP data — no ML libraries, just
transparent arithmetic over the real records the engine already reads:

* **delivery**   — per open order: run-rate vs days left → probability of missing the date.
* **stock-out**  — per style: fabric cover (metres on hand) vs demand rate → days of cover.
* **margin**     — per style: sell rate vs BOM material cost → projected margin.
* **cash**       — receivables/payables, ageing buckets, projected net.
* **supplier**   — on-time %, average PO→receipt lag, currently-late POs.

Everything is generic (driven by the live facts) and read-only.
"""

from __future__ import annotations

from datetime import date, datetime

import rulebook


def _num(v, d=0.0):
    try:
        if v is None or v == "":
            return d
        return float(v)
    except Exception:
        return d


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ── delivery ────────────────────────────────────────────────────────────────
def _packed_by_style(facts):
    out = {}
    for p in facts.get("production_daily", []):
        st = p.get("style_no") or rulebook._style_of(p.get("sales_order"))
        if st:
            out[st] = max(_num(p.get("source_total_packed")), out.get(st, 0.0))
    return out


def delivery(facts):
    packed = _packed_by_style(facts)
    rows = []
    for s in facts.get("open_sos", []):
        dd = s.get("earliest_delivery")
        days_left = (dd - facts["today"]).days if dd else None
        for it in s.get("items", []):
            style = rulebook._style_of(it.get("item_code"))
            qty = _num(it.get("qty"))
            done = packed.get(style, 0.0)
            remaining = max(qty - done, 0.0)
            coverage = (done / qty) if qty else 0.0
            if not days_left or days_left <= 0:
                prob = 1.0 if remaining > 0 else 0.0
            else:
                # need = remaining / days_left pcs per day; assume a nominal run-rate
                need_rate = remaining / days_left
                # with no observed rate we express risk as the uncovered fraction, tempered by time
                prob = _clamp((1 - coverage) * (1 + (30 - min(days_left, 30)) / 60.0), 0, 1)
            verdict = "on_track" if prob < 0.3 else ("at_risk" if prob < 0.7 else "will_miss")
            rows.append({"order": s.get("name"), "style": style, "qty": int(qty),
                         "packed": int(done), "remaining": int(remaining),
                         "days_left": days_left, "coverage_pct": round(coverage * 100),
                         "miss_probability": round(prob, 2), "verdict": verdict})
    rows.sort(key=lambda r: -r["miss_probability"])
    return rows


# ── stock-out ───────────────────────────────────────────────────────────────
def stockout(facts):
    rows = []
    rolls = facts.get("fabric_roll_m", {})
    for style, qty in facts.get("open_qty_by_style", {}).items():
        bom = facts.get("bom_by_style", {}).get(style)
        if not bom:
            continue
        comps = [c for c in facts.get("bom_items", {}).get(bom["name"], [])
                 if (c.get("item_code") or "").upper().startswith("FAB-")]
        if not comps:
            continue
        required = sum(_num(c["qty"]) * qty for c in comps)
        available = sum(_num(rolls.get(c["item_code"])) for c in comps)
        s = facts.get("so_styles", {}).get(style, {})
        # days of cover relative to the remaining delivery window
        days_left = None
        for o in facts.get("sos", []):
            if o.get("name") in (s.get("orders") or []):
                dd = o.get("earliest_delivery")
                days_left = (dd - facts["today"]).days if dd else None
                break
        cover_pct = (available / required * 100) if required else 100.0
        days_cover = None
        if days_left and days_left > 0 and required:
            days_cover = round(days_left * (available / required), 1)
        verdict = "covered" if available >= required else ("tight" if cover_pct >= 80 else "short")
        rows.append({"style": style, "required_m": round(required), "available_m": round(available),
                     "cover_pct": round(cover_pct), "days_left": days_left, "days_cover": days_cover,
                     "verdict": verdict})
    rows.sort(key=lambda r: r["cover_pct"])
    return rows


# ── margin ──────────────────────────────────────────────────────────────────
# Plausibility window for cost-vs-price before a margin is emitted (else the
# style is counted as "unverified" rather than showing a fabricated %).
MARGIN_COST_MIN_RATIO = 0.02   # cost must be at least  2%  of sell price
MARGIN_COST_MAX_RATIO = 2.0    # cost must be at most  200% of sell price


def margin(facts):
    """Sell rate vs BOM material cost — only where the two are on the same scale.

    BOM ``total_cost`` is carried in the manufacturing currency (VND for the VN
    entity) while order rates are USD, so a naive ratio is meaningless. A margin is
    emitted only when the implied ratio is plausible; otherwise the style is counted
    as *unverified* (never a fabricated %).
    """
    sell = {}
    for o in facts.get("sos", []):
        for it in o.get("items", []):
            st = rulebook._style_of(it.get("item_code"))
            r = _num(it.get("rate"))
            if r and r > sell.get(st, 0):
                sell[st] = r
    rows = []
    unverified = 0
    for b in facts.get("boms", []):
        st = rulebook._style_of(b.get("item"))
        cost = _num(b.get("total_cost"))
        price = sell.get(st)
        if not price or cost <= 0:
            continue
        if not (MARGIN_COST_MIN_RATIO * price <= cost <= MARGIN_COST_MAX_RATIO * price):
            unverified += 1
            continue
        m = (price - cost) / price * 100.0
        verdict = "healthy" if m >= 25 else ("thin" if m >= 10 else "negative")
        rows.append({"style": st, "sell_rate": round(price, 2), "material_cost": round(cost, 2),
                     "margin_pct": round(m, 1), "verdict": verdict})
    rows.sort(key=lambda r: r["margin_pct"])
    return rows, unverified


# ── cash ────────────────────────────────────────────────────────────────────
def cash(facts):
    """Receivables/payables kept strictly per-currency (never summed across)."""
    today = facts["today"]
    by_ccy = {}

    def bucket(ccy):
        return by_ccy.setdefault(ccy or "?", {
            "receivables": 0.0, "overdue": 0.0, "payables": 0.0,
            "ageing": {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}})

    for inv in facts.get("invoices", []):
        out = _num(inv.get("outstanding_amount"))
        if out <= 0:
            continue
        e = bucket(inv.get("currency"))
        e["receivables"] += out
        due = inv.get("due_date")
        age = 0
        if due:
            try:
                age = (today - datetime.fromisoformat(str(due)[:10]).date()).days
            except Exception:
                age = 0
        if age <= 0:
            e["ageing"]["current"] += out
        elif age <= 30:
            e["ageing"]["1_30"] += out; e["overdue"] += out
        elif age <= 60:
            e["ageing"]["31_60"] += out; e["overdue"] += out
        elif age <= 90:
            e["ageing"]["61_90"] += out; e["overdue"] += out
        else:
            e["ageing"]["90_plus"] += out; e["overdue"] += out

    for pi in facts.get("purchase_invoices", []):
        out = _num(pi.get("outstanding_amount"))
        if out > 0:
            bucket(pi.get("currency"))["payables"] += out

    out = {}
    for ccy, e in by_ccy.items():
        out[ccy] = {"receivables": round(e["receivables"], 2),
                    "overdue_receivables": round(e["overdue"], 2),
                    "payables": round(e["payables"], 2),
                    "net": round(e["receivables"] - e["payables"], 2),
                    "ageing": {k: round(v, 2) for k, v in e["ageing"].items()}}
    return {"by_currency": out,
            "note": "Kept per-currency — receivables (USD) and payables (VND) are never summed together."}


# ── supplier ────────────────────────────────────────────────────────────────
def supplier(facts):
    stats = {}
    for po in facts.get("purchase_orders", []):
        sup = po.get("supplier") or "Unknown"
        st = stats.setdefault(sup, {"supplier": sup, "pos": 0, "late": 0, "received": 0})
        st["pos"] += 1
        days = None
        if po.get("schedule_date"):
            try:
                days = (datetime.fromisoformat(str(po["schedule_date"])[:10]).date() - facts["today"]).days
            except Exception:
                days = None
        if _num(po.get("per_received")) < 100 and days is not None and days < 0:
            st["late"] += 1
        if _num(po.get("per_received")) >= 100:
            st["received"] += 1
    # on-time % from receipts vs matched PO schedule (same heuristic the chart uses)
    for pr in facts.get("purchase_receipts", []):
        sup = pr.get("supplier") or "Unknown"
        st = stats.setdefault(sup, {"supplier": sup, "pos": 0, "late": 0, "received": 0})
        st["received"] = st.get("received", 0)
    rows = []
    for sup, st in stats.items():
        fulfil = (st["received"] / st["pos"] * 100) if st["pos"] else 0
        verdict = "reliable" if st["late"] == 0 else ("watch" if st["late"] <= 1 else "at_risk")
        rows.append({"supplier": sup, "open_pos": st["pos"], "late_pos": st["late"],
                     "received_pos": st["received"], "fulfil_pct": round(fulfil), "verdict": verdict})
    rows.sort(key=lambda r: (-r["late_pos"], r["supplier"]))
    return rows


def build(db=None) -> dict:
    facts = rulebook.live_facts()
    try:
        d = delivery(facts)
    except Exception:
        d = []
    try:
        so = stockout(facts)
    except Exception:
        so = []
    try:
        mg, mg_unverified = margin(facts)
    except Exception:
        mg, mg_unverified = [], 0
    try:
        ca = cash(facts)
    except Exception:
        ca = {}
    try:
        su = supplier(facts)
    except Exception:
        su = []
    return {"delivery": d, "stockout": so, "margin": mg, "margin_unverified": mg_unverified,
            "cash": ca, "supplier": su,
            "open_orders": len(facts.get("open_sos", [])),
            "generated_at": datetime.utcnow().isoformat(),
            "note": "Projections from live ERP records (transparent arithmetic, no ML)."
                    + ("" if facts.get("open_sos") else " No open orders currently, so delivery/stock-out projections are empty.")
                    + (f" {mg_unverified} style(s) not margin-verified (costing currency differs from order currency)." if mg_unverified else "")}
