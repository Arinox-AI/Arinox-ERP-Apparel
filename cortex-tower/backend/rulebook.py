"""Cortex Control Tower — generic, live, data-driven detection engine.

Design goals (per the gap analysis)
-----------------------------------
* **Generic** — rules are defined against ERP *entities and fields*, never
  against a specific style / order / file. A brand-new order, style or supplier
  is covered the moment it exists in the ERP.
* **Per-record** — detectors emit one risk per offending record (per order,
  style, supplier, invoice, shipment), not a single global counter.
* **Conditional** — a rule fires only when its condition is actually true, so
  the dashboard can show a genuine "all clear".
* **Threshold-driven severity** — danger/warning is computed from live
  magnitudes and time (days to deadline, % short, USD exposure). Every threshold
  lives in ``rulebook.json``, not in code.
* **Preventive + predictive-lite** — rules look forward (stock vs demand, lead
  time vs due date, production run-rate vs remaining days), not just at totals.

Nothing here writes to the ERP. Read-only over ``erp.py``.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import erp
import erp_model

# ── config ──────────────────────────────────────────────────────────────────
_CFG_PATH = Path(__file__).resolve().parent / "rulebook.json"

# Fallback mirror of rulebook.json (used only if the file is missing/unreadable).
# Keep these keys in sync with rulebook.json — that file is the effective source.
_DEFAULTS = {
    "delivery": {"overdue_warning_days": 0, "overdue_critical_days": 7,
                 "due_soon_critical_days": 30, "due_soon_warning_days": 60},
    "bom": {"coverage_warning_below_pct": 100, "coverage_critical_below_pct": 50},
    "fabric": {"shortage_warning_pct": 5, "shortage_critical_pct": 20},
    "payment": {"overdue_warning_days": 1, "overdue_critical_days": 30,
                "outstanding_warning_usd": 0},
    "shipment": {"variance_warning_pct": 2, "variance_critical_pct": 10},
    "production": {"shortfall_warning_pct": 5, "shortfall_critical_pct": 20},
    "supplier": {"po_late_warning_days": 0, "po_late_critical_days": 7},
    "trim": {"unmapped_critical_at": 10, "mr_draft_critical_at": 10},
    "limits": {"max_risks_per_rule": 25, "max_recommendations": 60},
}


def _cfg() -> dict:
    try:
        raw = json.loads(_CFG_PATH.read_text())
    except Exception:
        raw = {}
    out = {k: dict(v) for k, v in _DEFAULTS.items()}
    for k, v in (raw or {}).items():
        if isinstance(v, dict):
            out.setdefault(k, {}).update(v)
    return out


# ── small helpers ───────────────────────────────────────────────────────────
def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _d(v) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return None


def _days_until(v) -> Optional[int]:
    day = _d(v)
    return None if day is None else (day - date.today()).days


def _style_of(item_code: str) -> str:
    """First three dash-groups of an item code = the style. Generic, tolerant of
    short codes (returns the code unchanged when it can't be split)."""
    parts = (item_code or "").strip().split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else (item_code or "")


def _base(order_name: str) -> str:
    """Strip a trailing amendment suffix (``-1``, ``-2`` …) so a document that
    references the original order still matches its later amendment."""
    import re as _re
    return _re.sub(r"-\d+$", "", (order_name or "").strip())


def _sev_by_days(days: Optional[int], crit: int, warn: int) -> str:
    """Lower `days` = more urgent. crit/warn are day thresholds."""
    if days is None:
        return "warning"
    if days <= crit:
        return "critical"
    if days <= warn:
        return "warning"
    return "info"


def _sev_by_pct(pct: float, warn: float, crit: float) -> str:
    if pct >= crit:
        return "critical"
    if pct >= warn:
        return "warning"
    return "info"


# ── live fact pack (generic, read-only) ─────────────────────────────────────
_FACT_TTL = 45
_fact_cache: Optional[tuple] = None


def _meta_fields(doctype: str) -> set:
    """Every fieldname the doctype really has — own fields AND custom fields.

    Reading only ``DocType.fields`` silently dropped every custom field, so a
    read of e.g. ``Client Purchase Order`` came back with ``qty`` / ``amount_usd``
    pruned out and the rule then reported "USD 0.00".
    """
    # Implicit columns every Frappe doctype has but which never appear in
    # DocType.fields — pruning them turned `docstatus` into None and silently
    # disabled every draft/submitted test.
    out: set = {"name", "docstatus", "modified", "creation", "owner", "parent"}
    try:
        meta = erp.erp_doc("DocType", doctype) or {}
        out |= {f.get("fieldname") for f in (meta.get("fields") or []) if f.get("fieldname")}
    except Exception:
        pass
    try:
        out |= {f.get("fieldname") for f in
                (erp.erp_get("Custom Field", fields=["fieldname"], filters=[["dt", "=", doctype]],
                             limit=0) or [])
                if f.get("fieldname")}
    except Exception:
        pass
    return out


def _list(doctype: str, fields, filters=None, limit=0, order=None) -> list:
    """List, pruning `fields` to those that actually exist on the doctype."""
    try:
        have = _meta_fields(doctype)
        use = [f for f in fields if (not have or f in have)]
        if "name" not in use:
            use = ["name"] + use
        return erp.erp_get(doctype, fields=use, filters=filters, limit=limit, order=order) or []
    except Exception:
        return []


def _all_children(parent_doctype: str, child_field: str, parent_filters=None) -> list:
    """Read a child table by walking its PARENT documents.

    Child doctypes (``Delivery Note Item``, ``Sales Invoice Item``…) are NOT
    list-permitted for this ERP user, so a direct ``get_list`` silently returns
    nothing — which would blind the risk engine. Reading the parents instead is
    the only reliable route.
    """
    out: list = []
    try:
        parents = _list(parent_doctype, ["name"], filters=parent_filters)
    except Exception:
        return out
    for p in parents:
        name = p.get("name")
        if not name:
            continue
        try:
            doc = erp.erp_doc(parent_doctype, name) or {}
        except Exception:
            continue
        for row in (doc.get(child_field) or []):
            if isinstance(row, dict):
                out.append({**row, "parent": name})
    return out


def live_facts() -> dict:
    """Assemble the live facts the rules run on. Cached briefly. Never raises."""
    global _fact_cache
    if _fact_cache and (time.time() - _fact_cache[0]) < _FACT_TTL:
        return _fact_cache[1]

    today = date.today()
    f: dict = {"today": today}

    # Orders (live = submitted)
    sos = _list("Sales Order", ["name", "customer", "customer_name", "po_no", "delivery_date",
                                "transaction_date", "status", "per_delivered", "per_billed",
                                "currency", "grand_total"], filters=[["docstatus", "=", 1]])
    orders = []
    so_quotes: set = set()
    so_styles: dict = {}
    for s in sos:
        doc = erp.erp_doc("Sales Order", s["name"]) or {}
        items = []
        earliest = None
        for it in (doc.get("items") or []):
            code = it.get("item_code")
            dd = it.get("delivery_date") or s.get("delivery_date")
            items.append({"item_code": code, "qty": _num(it.get("qty")), "rate": _num(it.get("rate")),
                          "amount": _num(it.get("amount")), "delivery_date": dd, "row": it.get("name")})
            day = _d(dd)
            if day and (earliest is None or day < earliest):
                earliest = day
            st = so_styles.setdefault(_style_of(code), {"qty": 0.0, "orders": set(), "item_codes": set()})
            st["qty"] += _num(it.get("qty"))
            st["orders"].add(s["name"])
            st["item_codes"].add(code)
        if doc.get("custom_quotation"):
            so_quotes.add(doc["custom_quotation"])
        orders.append({**s, "items": items, "earliest_delivery": earliest})
    for st in so_styles.values():
        st["orders"] = sorted(st["orders"])
        st["item_codes"] = sorted(st["item_codes"])
    f["sos"] = orders
    f["so_styles"] = so_styles
    # quotations already turned into an order — never "still in play"
    f["quotation_refs"] = so_quotes

    # BOMs (submitted) + their components
    boms = _list("BOM", ["name", "item", "item_name", "total_cost", "docstatus"],
                 filters=[["docstatus", "=", 1]])
    bom_by_style: dict = {}
    bom_items: dict = {}
    for b in boms:
        doc = erp.erp_doc("BOM", b["name"]) or {}
        comps = [{"item_code": i.get("item_code"), "qty": _num(i.get("stock_qty") or i.get("qty")),
                  "uom": i.get("stock_uom") or i.get("uom")}
                 for i in (doc.get("items") or []) if i.get("item_code")]
        bom_items[b["name"]] = comps
        st = _style_of(b.get("item"))
        bom_by_style.setdefault(st, b)
    f["boms"] = boms
    f["bom_items"] = bom_items
    f["bom_by_style"] = bom_by_style
    f["bom_styles"] = set(bom_by_style.keys())

    # FG variants + stock
    variants = _list("Item", ["name", "variant_of", "item_name"], filters=[["variant_of", "!=", ""]])
    f["variants"] = variants
    var_by_style: dict = {}
    for v in variants:
        var_by_style.setdefault(_style_of(v.get("name")), []).append(v["name"])
    f["variants_by_style"] = var_by_style

    bins = _list("Bin", ["item_code", "actual_qty", "warehouse"])
    stock: dict = {}
    for b in bins:
        stock[b.get("item_code")] = stock.get(b.get("item_code"), 0.0) + _num(b.get("actual_qty"))
    f["stock"] = stock

    # Delivery notes raised (against SO). Child tables are not listable, so walk
    # the parent Delivery Notes — otherwise the engine never sees a raised DN.
    dn_items = _all_children("Delivery Note", "items", [["docstatus", "!=", 2]])
    f["delivered_by_so"] = {d.get("against_sales_order") for d in dn_items if d.get("against_sales_order")}

    # Invoices + payments
    invoices = _list("Sales Invoice", ["name", "customer", "grand_total", "outstanding_amount",
                                       "due_date", "posting_date", "status", "currency", "docstatus"],
                     filters=[["docstatus", "=", 1]])
    f["invoices"] = invoices
    f["invoiced_by_so"] = set()
    si_items = _all_children("Sales Invoice", "items", [["docstatus", "=", 1]])
    f["invoiced_by_so"] = {r.get("sales_order") for r in si_items if r.get("sales_order")}
    f["payment_entries"] = _list("Payment Entry", ["name", "party", "paid_amount", "docstatus"],
                                 filters=[["docstatus", "=", 1]])
    # Invoices that already have a Payment Request — used so the receivables risk
    # does not keep flagging an invoice the Tower has already acted on.
    f["payment_request_refs"] = {
        r.get("reference_name") for r in
        _list("Payment Request", ["name", "reference_name", "docstatus"], filters=[["docstatus", "!=", 2]])
        if r.get("reference_name")
    }

    # Manufacturing
    f["work_orders"] = _list("Work Order", ["name", "production_item", "qty", "produced_qty",
                                            "docstatus", "status", "planned_start_date"])
    f["material_requests"] = _list("Material Request", ["name", "docstatus", "transaction_date",
                                                        "material_request_type", "status"])

    # Procurement
    f["purchase_orders"] = _list("Purchase Order", ["name", "supplier", "transaction_date",
                                                    "schedule_date", "status", "docstatus",
                                                    "grand_total", "per_received"],
                                 filters=[["docstatus", "=", 1]])
    f["purchase_receipts"] = _list("Purchase Receipt", ["name", "supplier", "posting_date",
                                                        "grand_total", "docstatus"],
                                   filters=[["docstatus", "=", 1]])
    f["purchase_invoices"] = _list("Purchase Invoice", ["name", "supplier", "grand_total",
                                                        "outstanding_amount", "due_date", "currency", "status",
                                                        "docstatus"], filters=[["docstatus", "=", 1]])

    # Quality
    f["quality_evidence"] = _list("Fabric Quality Evidence",
                                  ["name", "source_fabric_code", "inspection_result",
                                   "source_document", "detailed_metrics_extracted"])
    f["quality_inspections"] = _list("Quality Inspection",
                                     ["name", "status", "docstatus", "item_code",
                                      "reference_name", "inspection_type"])

    # Logistics — read from the objects that exist TODAY.
    # `Garment Shipment Evidence` was retired (0 rows); the customs leg lives in
    # `Shipment Document Evidence` + `Freight Booking`, grouped per shipment by
    # erp_model.shipment_leg() so a declaration row and its size-grid row are one
    # shipment (not two, and not 3,040 pcs of a 1,520-pc order).
    try:
        leg = erp_model.shipment_leg()
    except Exception:
        leg = {"rows": [], "groups": [], "bookings": []}
    f["shipments"] = leg.get("rows") or []
    f["shipment_groups"] = leg.get("groups") or []
    f["shipment_docs"] = leg.get("groups") or []   # kept for older callers

    f["trim_exceptions"] = _list("Trim Mapping Exception", ["name"])
    f["mdg"] = _list("Migration Data Gap", ["name", "gap_key", "process_area", "status"])
    f["production_daily"] = _list("Production Daily Evidence",
                                  ["name", "style_no", "sales_order", "source_order_qty_pcs",
                                   "source_total_packed", "source_total_cutting", "source_total_sewing",
                                   "data_scope", "packed_qty", "delivery_date"])

    # ── the Stage-1 buyer side + pre-order + requisitions + floor ──────────
    f["client_pos"] = _list("Client Purchase Order",
                            ["name", "client_po_no", "order_ref", "order_ref_label",
                             "order_ref_type", "customer", "status", "qty",
                             "amount_usd", "style_no", "linked_sales_order"])
    f["buyer_packs"] = _list("Buyer Tech Pack",
                             ["name", "status", "style_no", "pack_revision", "readiness",
                              "buyer_decision", "corrected_due", "bom_line_count"])
    f["buyer_boms"] = _list("Buyer BOM",
                            ["name", "status", "style_no", "line_count", "mapped_count",
                             "unmapped_count", "generated_bom_count"])
    f["cost_sheets"] = _list("Cost Sheet",
                             ["name", "status", "style_no", "order_qty", "total_fob",
                              "avg_margin_pct", "gate_ok", "gate_notes", "pack_stale",
                              "docstatus"])
    f["quotations"] = _list("Quotation",
                            ["name", "party_name", "workflow_state", "status", "docstatus",
                             "grand_total", "valid_till", "transaction_date"])
    f["trim_requisitions"] = _list("Cortex Trim Requisition",
                                   ["name", "status", "docstatus", "style", "sales_order",
                                    "required_by", "material_request"])
    f["fabric_requisitions"] = _list("Cortex Fabric Requisition",
                                     ["name", "status", "docstatus", "style", "sales_order",
                                      "required_by", "material_request"])
    f["pp_meetings"] = _list("PP Meeting",
                             ["name", "status", "sales_order", "style_no", "meeting_date",
                              "open_actions", "bulk_cutting_allowed", "pilot_run_closed"])
    f["allowance_bands"] = _list("Contract Allowance Band",
                                 ["name", "band_from", "band_to", "tolerance_pct",
                                  "applies_to", "active"])

    # the allowance is judged inside erp_model.shipment_leg() — one place, so the
    # decks, the dossier and this page cannot disagree about it.
    # Fabric stock is tracked as *rolls* (length in metres), not in Bin.
    rolls = _list("Fabric Roll", ["name", "item", "roll_length", "roll_uom", "receipt_status"])
    roll_m: dict = {}
    for r in rolls:
        if (r.get("receipt_status") or "Received").strip().lower() == "received":
            roll_m[r.get("item")] = roll_m.get(r.get("item"), 0.0) + _num(r.get("roll_length"))
    f["fabric_roll_m"] = roll_m

    # Order lifecycle: shipment evidence references the ORIGINAL (un-suffixed)
    # order name. A shipped/billed order is not an *open* operational risk — the
    # remaining issues on it are documentation/completeness, not live danger.
    shipped_base = {_base(s.get("sales_order")) for s in f["shipments"] if s.get("sales_order")}
    f["shipped_base"] = shipped_base
    for s in f["sos"]:
        s["base"] = _base(s["name"])
        s["closed"] = (s["base"] in shipped_base) or _num(s.get("per_billed")) >= 100 \
            or s["name"] in f["delivered_by_so"]
    f["open_sos"] = [s for s in f["sos"] if not s["closed"]]
    open_qty_by_style: dict = {}
    for s in f["open_sos"]:
        for it in s["items"]:
            st = _style_of(it.get("item_code"))
            open_qty_by_style[st] = open_qty_by_style.get(st, 0.0) + _num(it.get("qty"))
    f["open_qty_by_style"] = open_qty_by_style

    _fact_cache = (time.time(), f)
    return f


def invalidate() -> None:
    global _fact_cache
    _fact_cache = None


# ── recommendation templates (attached to each risk) ────────────────────────
def _act(slug, action, impact, team, priority="medium", write=None):
    return {"slug": slug, "action": action, "expected_impact": impact,
            "responsible_team": team, "priority": priority, "write": write}


# ── RULES ───────────────────────────────────────────────────────────────────
def _r_order_overdue(f, cfg):
    out = []
    for s in f["sos"]:
        if s.get("closed"):
            continue
        dd = s.get("earliest_delivery")
        days = (dd - f["today"]).days if dd else None
        if days is None or days > 0:
            continue
        late = -days
        sev = "critical" if late >= cfg["delivery"]["overdue_critical_days"] else "warning"
        out.append({
            "key": f"ORDER_OVERDUE#{s['name']}", "risk_type": "shipment_risk", "severity": sev,
            "title": f"{s['name']} is {late} day(s) past its delivery date and not delivered",
            "affected_order": s["name"], "required_date": str(dd), "style": _style_of((s['items'] or [{}])[0].get('item_code')),
            "days_to_deadline": days, "record": s["name"],
            "extra": _act("raise_delivery_notes",
                          f"Raise the Delivery Note for {s['name']} and re-plan the overdue shipment",
                          "Clears an overdue order before it becomes a claim", "Logistics", "high"),
        })
    return out


def _r_no_delivery_note(f, cfg):
    out = []
    for s in f["sos"]:
        if s["name"] in f["delivered_by_so"]:
            continue
        days = (s["earliest_delivery"] - f["today"]).days if s.get("earliest_delivery") else None
        if s.get("closed"):
            # Already shipped/billed but no goods-movement document -> completeness gap.
            out.append({
                "key": f"DOC_GAP_NO_DELIVERY#{s['name']}", "risk_type": "logistics_risk",
                "severity": "warning",
                "title": f"{s['name']} is shipped/invoiced but has no Delivery Note (migration completeness gap)",
                "affected_order": s["name"], "record": s["name"],
                "extra": _act("raise_delivery_notes",
                              f"Raise the Delivery Note for {s['name']} to close the goods-movement gap",
                              "Aligns shipped goods with the system record", "Logistics", "medium"),
            })
            continue
        sev = _sev_by_days(days, cfg["delivery"]["due_soon_critical_days"],
                           cfg["delivery"]["due_soon_warning_days"])
        out.append({
            "key": f"NO_DELIVERY_NOTE#{s['name']}", "risk_type": "shipment_risk", "severity": sev,
            "title": f"No Delivery Note raised for {s['name']}"
                     + (f" — due in {days} day(s)" if days is not None and days >= 0 else ""),
            "affected_order": s["name"], "required_date": str(s.get("earliest_delivery") or ""),
            "days_to_deadline": days, "record": s["name"],
            "extra": _act("raise_delivery_notes",
                          f"Raise the Delivery Note for {s['name']}",
                          "Required before shipment and invoicing", "Logistics",
                          "high" if (days is not None and days <= 30) else "medium"),
        })
    return out


def _r_invoiced_not_delivered(f, cfg):
    out = []
    for s in f["sos"]:
        if s["name"] in f["invoiced_by_so"] and s["name"] not in f["delivered_by_so"]:
            out.append({
                "key": f"INVOICED_NOT_DELIVERED#{s['name']}", "risk_type": "compliance_risk",
                "severity": "warning",
                "title": f"{s['name']} is invoiced but has no Delivery Note (compliance mismatch)",
                "affected_order": s["name"], "record": s["name"],
                "extra": _act("raise_delivery_notes",
                              f"Raise the Delivery Note for {s['name']} to match the invoice",
                              "Aligns revenue with goods movement", "Finance", "high"),
            })
    return out


def _r_bom_missing_order(f, cfg):
    out = []
    seen = set()
    for s in f["sos"]:
        for it in s["items"]:
            style = _style_of(it["item_code"])
            if style in f["bom_styles"] or style in seen:
                continue
            seen.add(style)
            days = (s["earliest_delivery"] - f["today"]).days if s.get("earliest_delivery") else None
            out.append({
                "key": f"BOM_MISSING_ORDER#{style}", "risk_type": "production_delay",
                "severity": _sev_by_days(days, cfg["delivery"]["due_soon_critical_days"],
                                         cfg["delivery"]["due_soon_warning_days"]),
                "title": f"No BOM for style {style} — live order {s['name']} cannot be costed/produced",
                "style": style, "affected_order": s["name"], "record": style,
                "days_to_deadline": days,
                "extra": _act("create_boms", f"Create the BOM for style {style}",
                              "Unblocks manufacturing and material planning", "Industrial Engineering", "high"),
            })
    return out


def _r_work_order_missing(f, cfg):
    wo_styles = {_style_of(w.get("production_item")) for w in f["work_orders"]}
    producing = {_style_of(w.get("production_item")) for w in f["work_orders"]
                 if _num(w.get("produced_qty")) > 0}
    open_styles = set(f["open_qty_by_style"].keys())
    out = []
    for style, st in f["so_styles"].items():
        if style in producing:
            continue
        covered = style in wo_styles
        date_ = None
        for s in f["sos"]:
            if s["name"] in st["orders"]:
                date_ = s.get("earliest_delivery")
                break
        days = (date_ - f["today"]).days if date_ else None
        # Open orders = live operational risk; already-shipped orders = completeness gap.
        sev = (_sev_by_days(days, cfg["delivery"]["due_soon_critical_days"],
                            cfg["delivery"]["due_soon_warning_days"])
               if style in open_styles else "warning")
        out.append({
            "key": f"WORK_ORDER_MISSING#{style}", "risk_type": "production_delay",
            "severity": sev,
            "title": (f"Style {style} has {'no Work Order' if not covered else 'no producing Work Order'} "
                      f"({int(st['qty']):,} pcs on order)"),
            "style": style, "affected_orders": st["orders"], "required_date": str(date_ or ""),
            "record": style, "days_to_deadline": days,
            "extra": _act("raise_work_orders", f"Raise a production Work Order for {style}",
                          "Starts real production tracking against the delivery window",
                          "Production Planning", "high"),
        })
    return out


def _r_payment_overdue(f, cfg):
    out = []
    have_pr = f.get("payment_request_refs") or set()
    for inv in f["invoices"]:
        outstanding = _num(inv.get("outstanding_amount"))
        if outstanding <= 0:
            continue
        if inv.get("name") in have_pr:
            # A Payment Request already exists for this invoice — the actionable
            # gap (no request raised) is closed, so it is no longer a Tower risk.
            continue
        days = _days_until(inv.get("due_date"))
        overdue = days is not None and days < 0
        sev = "warning"
        if overdue:
            late = -days
            sev = "critical" if late >= cfg["payment"]["overdue_critical_days"] else "warning"
        label = f"{inv['name']} ({inv.get('customer')}) outstanding USD {outstanding:,.2f}"
        out.append({
            "key": f"PAYMENT_OVERDUE#{inv['name']}", "risk_type": "invoicing_risk", "severity": sev,
            "title": f"{label} — {'overdue ' + str(-days) + ' day(s)' if overdue else ('due in ' + str(days) + ' day(s)' if days is not None else 'no due date')}",
            "current_margin": f"USD {outstanding:,.2f} outstanding", "record": inv["name"],
            "days_to_deadline": days,
            "extra": _act("review_receivables", f"Chase payment on {inv['name']}",
                          f"Brings USD {outstanding:,.2f} onto the books", "Finance",
                          "high" if sev == "critical" else "medium"),
        })
    return out


def _r_bom_coverage(f, cfg):
    out = []
    for style, var_names in f["variants_by_style"].items():
        if style not in f["so_styles"]:
            continue  # only styles with live demand
        total = len(var_names)
        have_bom = style in f["bom_styles"]
        covered = total if have_bom else 0
        if covered >= total:
            continue
        pct_missing = round(100.0 * (total - covered) / total) if total else 0
        sev = _sev_by_pct(pct_missing, 1, cfg["bom"]["coverage_critical_below_pct"])
        out.append({
            "key": f"BOM_COVERAGE#{style}", "risk_type": "production_delay", "severity": sev,
            "title": f"Per-size BOM coverage {covered}/{total} variants for {style} ({pct_missing}% missing)",
            "style": style, "affected_orders": f["so_styles"][style]["orders"], "record": style,
            "extra": _act("create_boms", f"Create the missing per-size BOMs for {style}",
                          "Enables sizing-level material planning", "Industrial Engineering", "high"),
        })
    return out


def _r_fabric_shortage(f, cfg):
    """Required fabric (BOM consumption × OPEN order qty) vs received rolls — preventive."""
    out = []
    for style, order_qty in f.get("open_qty_by_style", {}).items():
        if order_qty <= 0:
            continue
        st = f["so_styles"].get(style, {"orders": []})
        bom = f["bom_by_style"].get(style)
        if not bom:
            continue
        comps = [c for c in f["bom_items"].get(bom["name"], [])
                 if (c.get("item_code") or "").upper().startswith("FAB-")]
        if not comps:
            continue
        req = sum(_num(c["qty"]) * order_qty for c in comps)
        avail = sum(_num(f.get("fabric_roll_m", {}).get(c["item_code"])) for c in comps)
        if req <= 0:
            continue
        short = req - avail
        if short <= 0:
            continue
        pct = round(100.0 * short / req)
        sev = _sev_by_pct(pct, cfg["fabric"]["shortage_warning_pct"], cfg["fabric"]["shortage_critical_pct"])
        out.append({
            "key": f"FABRIC_SHORTAGE#{style}", "risk_type": "fabric_shortage", "severity": sev,
            "title": f"{style}: fabric short by {short:,.0f} m ({pct}% of {req:,.0f} m needed for {int(order_qty):,} pcs)",
            "style": style, "material": ", ".join(c["item_code"] for c in comps[:3]),
            "required_qty": f"{req:,.0f} m", "affected_orders": st["orders"], "record": style,
            "extra": _act("raise_trim_mrs", f"Raise a fabric purchase requisition for {style}",
                          "Prevents a fabric stock-out from stopping the line", "Supply Chain",
                          "high" if sev == "critical" else "medium"),
        })
    return out


def _r_trim_unmapped(f, cfg):
    out = []
    n = len(f["trim_exceptions"])
    if n:
        out.append({
            "key": "TRIM_UNMAPPED", "risk_type": "fabric_shortage",
            "severity": "warning" if n < cfg["trim"]["unmapped_critical_at"] else "critical",
            "title": f"{n} trim specifications are unmapped in Trim Mapping Exception — these styles cannot be fully planned",
            "record": "Trim Mapping Exception",
            "extra": _act("request_evidence", "Request the missing trim specifications/mappings",
                          "Unblocks trim ordering for affected styles", "Sourcing", "high"),
        })
    return out


def _r_po_late(f, cfg):
    out = []
    for po in f["purchase_orders"]:
        if _num(po.get("per_received")) >= 100:
            continue
        days = _days_until(po.get("schedule_date"))
        if days is None or days >= 0:
            continue
        late = -days
        sev = "critical" if late >= cfg["supplier"]["po_late_critical_days"] else "warning"
        out.append({
            "key": f"PO_LATE#{po['name']}", "risk_type": "supplier_risk", "severity": sev,
            "title": f"{po['name']} from {po.get('supplier')} is {late} day(s) past schedule ({_num(po.get('per_received')):.0f}% received)",
            "record": po["name"], "days_to_deadline": days,
            "extra": _act("chase_supplier", f"Chase supplier {po.get('supplier')} on {po['name']}",
                          "Protects the inbound material plan", "Procurement", "high" if sev == "critical" else "medium"),
        })
    return out


def _r_payable_outstanding(f, cfg):
    out = []
    total = 0.0
    n = 0
    for pi in f["purchase_invoices"]:
        o = _num(pi.get("outstanding_amount"))
        if o > 0:
            total += o
            n += 1
    if n:
        out.append({
            "key": "PAYABLE_OUTSTANDING", "risk_type": "cash_risk",
            "severity": "warning",
            "title": f"{n} supplier invoice(s) fully outstanding — USD {total:,.2f} payable",
            "cost_variance": f"USD {total:,.2f}", "record": "Purchase Invoice",
            "extra": _act("review_payables", "Review the supplier payables and schedule payment",
                          "Protects supplier relationships / avoids hold-ups", "Accounts Payable", "medium"),
        })
    return out


def _r_fabric_quality_fail(f, cfg):
    out = []
    for q in f["quality_evidence"]:
        code = q.get("source_fabric_code") or q.get("name")
        res = (q.get("inspection_result") or "").strip().lower()
        if res and res not in ("fail", "failed"):
            continue
        sev = "critical" if res in ("fail", "failed") else "warning"
        out.append({
            "key": f"FABRIC_QUALITY_FAIL#{code}", "risk_type": "quality_risk", "severity": sev,
            "title": (f"Fabric {code}: quality {'FAIL' if sev == 'critical' else 'not conclusively extracted'}"
                      f" ({q.get('source_document') or ''})"),
            "material": code, "inspection_stage": "Fabric inspection & testing",
            "defect_rate": "FAIL" if sev == "critical" else "undetermined", "record": q["name"],
            "extra": _act("reinspection_fabric", f"Schedule a 100% re-inspection for fabric {code}",
                          "Contains the quality risk before shipment", "Quality",
                          "high" if sev == "critical" else "medium"),
        })
    return out


def _r_quality_inspection_open(f, cfg):
    out = []
    for qi in f["quality_inspections"]:
        # draft (0) = genuinely open; 1 = submitted; 2 = cancelled (the old test
        # rows) — neither of the last two is an open gate any more.
        if str(qi.get("docstatus")) != "0":
            continue
        out.append({
            "key": f"QUALITY_INSPECTION_OPEN#{qi['name']}", "risk_type": "quality_risk",
            "severity": "warning",
            "title": f"Quality Inspection {qi['name']} is open ({qi.get('item_code') or 'item n/a'})",
            "record": qi["name"], "inspection_stage": qi.get("inspection_type") or "Inspection",
            "extra": _act("close_quality_inspection", f"Complete Quality Inspection {qi['name']}",
                          "Closes an open quality gate", "Quality", "medium"),
        })
    return out


def _r_shipment_variance(f, cfg):
    """Declared (customs) quantity vs the order quantity, per SHIPMENT GROUP.

    Read from `Shipment Document Evidence`; a shipment is described by several
    evidence rows (customs declaration, bill of lading, size grid), so the
    comparison is made on the group, never on a single document row.
    """
    out = []
    for g in f.get("shipment_groups", []):
        if not g.get("qty_captured") or _num(g.get("ordered")) <= 0:
            continue
        ordered = _num(g.get("ordered"))
        shipped = _num(g.get("shipped"))
        var = _num(g.get("variance_qty"))
        pct = abs(_num(g.get("variance_pct")))
        verdict = g.get("allowance_verdict")
        over = verdict == "Over"
        if verdict == "Within":
            continue          # the band clears it — the stored stamp is irrelevant
        if verdict == "UNCONFIRMED":
            # a shipment nobody can judge is a data gap, not a breach: say so, and
            # name the quantity that has no band instead of quoting a tolerance.
            out.append({
                "key": f"SHIPMENT_ALLOWANCE_UNCONFIRMED#{g.get('group')}", "risk_type": "data_gap",
                "severity": "warning",
                "title": (f"{g.get('group')}: shipped {shipped:,.0f} vs ordered {ordered:,.0f} pcs "
                          f"({var:+,.0f}, {pct:.2f}%) — cannot be judged: "
                          f"{g.get('allowance_source') or 'no allowance band'}"),
                "affected_order": g.get("sales_order"), "style": g.get("style"),
                "record": g.get("group"),
                "extra": _act("record_allowance_band",
                              f"Record the contract tolerance for {ordered:,.0f} pcs before this shipment is closed",
                              "Turns an unjudgeable shipment into a checked one", "Merchandising", "medium"),
            })
            continue
        if pct < cfg["shipment"]["variance_warning_pct"] and not over:
            continue
        sev = "critical" if over else _sev_by_pct(
            pct, cfg["shipment"]["variance_warning_pct"], cfg["shipment"]["variance_critical_pct"])
        out.append({
            "key": f"SHIPMENT_VARIANCE#{g.get('group')}", "risk_type": "shipment_risk",
            "severity": sev,
            "title": (f"{g.get('group')}: shipped {shipped:,.0f} vs ordered {ordered:,.0f} pcs "
                      f"({var:+,.0f}, {pct:.2f}%)"
                      + (f" — {g.get('variance_status')}" if g.get("variance_status") else "")),
            "affected_order": g.get("sales_order"), "style": g.get("style"),
            "record": g.get("group"),
            "extra": _act("review_shipment_variance",
                          f"Review the declared quantity on shipment {g.get('group')} against the order allowance",
                          "Prevents a customs/claim exposure on an out-of-allowance shipment",
                          "Logistics", "high"),
        })
    return out


def _r_missing_shipment_docs(f, cfg):
    """One risk per shipment GROUP that is missing a customs declaration or a B/L.

    Grouped, because one shipment used to produce 3-4 separate "missing document"
    risks — one per evidence row — which buried every other signal.
    """
    out = []
    for g in f.get("shipment_groups", []):
        missing = g.get("missing") or []
        if not missing:
            continue
        out.append({
            "key": f"MISSING_SHIPMENT_DOCS#{g.get('group')}", "risk_type": "logistics_risk",
            "severity": "warning",
            "title": f"Shipment {g.get('group')} missing: {', '.join(missing)}",
            "affected_order": g.get("sales_order"), "record": g.get("group"),
            "extra": _act("chase_shipment_docs",
                          f"Obtain the missing shipping documents for {g.get('group')}",
                          "Prevents customs/shipment delays", "Logistics", "medium"),
        })
    unlinked = [r for r in f.get("shipments", [])
                if not r.get("sales_order") and not r.get("client_purchase_order")]
    if unlinked:
        out.append({
            "key": "SHIPMENT_ROWS_UNLINKED", "risk_type": "data_quality", "severity": "info",
            "title": (f"{len(unlinked)} shipment evidence row(s) name neither an order nor a buyer PO "
                      f"({', '.join(r['name'] for r in unlinked[:6])}{'…' if len(unlinked) > 6 else ''})"),
            "record": "Shipment Document Evidence",
            "extra": _act("request_evidence",
                          "Tie the unlinked shipment evidence rows to their Client PO / Sales Order",
                          "Makes the shipment leg auditable per order", "Data Governance", "low"),
        })
    return out


def _r_production_shortfall(f, cfg):
    """Predictive-lite: packed vs ordered with days left."""
    out = []
    packed_by_style: dict = {}
    for p in f["production_daily"]:
        st = p.get("style_no") or _style_of(p.get("sales_order"))
        if not st:
            continue
        packed_by_style[st] = max(_num(p.get("source_total_packed")), packed_by_style.get(st, 0.0))
    for style, ordered in f.get("open_qty_by_style", {}).items():
        if style not in packed_by_style or ordered <= 0:
            continue
        st = f["so_styles"].get(style, {"orders": []})
        packed = packed_by_style[style]
        if ordered <= 0:
            continue
        gap = ordered - packed
        if gap <= 0:
            continue
        pct = round(100.0 * gap / ordered)
        sev = _sev_by_pct(pct, cfg["production"]["shortfall_warning_pct"], cfg["production"]["shortfall_critical_pct"])
        date_ = None
        for s in f["sos"]:
            if s["name"] in st["orders"]:
                date_ = s.get("earliest_delivery")
                break
        days = (date_ - f["today"]).days if date_ else None
        if days is not None and days >= 0:
            sev = "critical" if (pct >= cfg["production"]["shortfall_critical_pct"] or days <= 30) else sev
        out.append({
            "key": f"PRODUCTION_SHORTFALL#{style}", "risk_type": "production_delay", "severity": sev,
            "title": f"{style}: {packed:,.0f} of {ordered:,.0f} pcs packed ({pct}% short)"
                     + (f", due in {days} day(s)" if days is not None else ""),
            "style": style, "planned_output": f"{ordered:,.0f} pcs", "actual_output": f"{packed:,.0f} pcs",
            "affected_orders": st["orders"], "record": style, "days_to_deadline": days,
            "extra": _act("replan_production", f"Re-plan production for {style} to close the {pct}% packing gap",
                          "Protects the delivery date", "Production Planning",
                          "high" if sev == "critical" else "medium"),
        })
    return out


def _r_trim_mr_draft(f, cfg):
    drafts = [m for m in f["material_requests"] if str(m.get("docstatus")) == "0"]
    if not drafts:
        return []
    return [{
        "key": "TRIM_MR_DRAFT", "risk_type": "fabric_shortage",
        "severity": "warning" if len(drafts) < cfg["trim"]["mr_draft_critical_at"] else "critical",
        "title": f"{len(drafts)} Material Request(s) still Draft — no RFQ or Purchase Order raised",
        "material": "Trims (labels, thread, fusing, elastic)", "required_qty": f"{len(drafts)} requisitions",
        "record": "Material Request",
        "extra": _act("submit_trim_mrs", f"Convert the {len(drafts)} Draft Material Requests into RFQs / POs",
                      "Prevents a trim shortage from blocking live orders", "Supply Chain", "high"),
    }]


def _r_mdg_open(f, cfg):
    open_gaps = [g for g in f["mdg"] if (g.get("status") or "").strip().lower() != "resolved"]
    if not open_gaps:
        return []
    areas = sorted({g.get("process_area") for g in open_gaps if g.get("process_area")})
    return [{
        "key": "MDG_OPEN", "risk_type": "data_quality", "severity": "warning",
        "title": f"{len(f['mdg'])} migration data gaps recorded, {len(open_gaps)} awaiting Cortex evidence",
        "affected_orders": areas, "record": "Migration Data Gap",
        "extra": _act("assign_data_owners", f"Assign an owner and due date to each of the {len(open_gaps)} open data gaps",
                      "Tracks closure of the remaining migration gaps", "Data Governance", "medium"),
    }]


# ── the buyer side + the pre-order chain (2026-11-02) ──────────────────────
def _r_client_po_unlinked(f, cfg):
    """Buyer POs on file with no Sales Order behind them — demand the ERP has not
    turned into an order (or a link somebody forgot). One aggregate risk, because
    a dozen near-identical rows bury every other signal on the page."""
    unlinked = [c for c in f.get("client_pos", [])
                if not c.get("linked_sales_order")
                and (c.get("status") or "").strip().lower() in ("", "confirmed", "received")]
    if not unlinked:
        return []
    usd = sum(_num(c.get("amount_usd")) for c in unlinked)
    pcs = sum(_num(c.get("qty")) for c in unlinked)
    names = ", ".join(str(c.get("client_po_no") or c.get("name")) for c in unlinked[:6])
    return [{
        "key": "CLIENT_PO_UNLINKED", "risk_type": "data_quality",
        "severity": "warning" if usd >= 5000 else "info",
        "title": (f"{len(unlinked)} buyer PO(s) worth USD {usd:,.2f} ({pcs:,.0f} pcs) carry no Sales Order "
                  f"— {names}{'…' if len(unlinked) > 6 else ''}"),
        "affected_orders": [c.get("name") for c in unlinked],
        "record": "Client Purchase Order",
        "extra": _act("link_client_po",
                      f"Raise or link the Sales Order for the {len(unlinked)} buyer PO(s) that have none",
                      "Turns received demand into an order the factory can plan",
                      "Merchandising", "high" if usd >= 5000 else "medium"),
    }]


def _r_buyer_pack_not_ready(f, cfg):
    """A buyer pack that cannot produce a BOM — the pre-order chain stops here."""
    out = []
    for p in f.get("buyer_packs", []):
        why = (p.get("readiness") or "").strip()
        st = (p.get("status") or "").strip().lower()
        if not why and st not in ("superseded", "cancelled", "not ready"):
            continue
        out.append({
            "key": f"BUYER_PACK_NOT_READY#{p['name']}", "risk_type": "data_quality",
            "severity": "warning",
            "title": (f"Buyer pack {p['name']} ({p.get('style_no') or 'style n/a'}, rev "
                      f"{p.get('pack_revision') or '—'}) is not ready: {why or st}"),
            "style": p.get("style_no"), "record": p["name"],
            "extra": _act("request_evidence",
                          f"Close the gap on buyer pack {p['name']} so a BOM can be generated",
                          "Unblocks sizing-level material planning", "Merchandising", "medium"),
        })
    return out


def _r_buyer_bom_unmapped(f, cfg):
    """Buyer BOM lines whose buyer code is not mapped to one of our items."""
    out = []
    for b in f.get("buyer_boms", []):
        unmapped = _num(b.get("unmapped_count"))
        if unmapped <= 0:
            continue
        out.append({
            "key": f"BUYER_BOM_UNMAPPED#{b['name']}", "risk_type": "data_quality",
            "severity": "warning",
            "title": (f"Buyer BOM {b['name']} ({b.get('style_no') or 'style n/a'}) has "
                      f"{unmapped:,.0f} unmapped line(s) of {_num(b.get('line_count')):,.0f}"),
            "style": b.get("style_no"), "record": b["name"],
            "extra": _act("request_evidence",
                          f"Map the {unmapped:,.0f} unmapped buyer line(s) on {b['name']} to our items",
                          "Every buyer line answers to one of our items", "Sourcing", "medium"),
        })
    return out


def _r_cost_gate_blocked(f, cfg):
    """A draft cost sheet whose gate is shut, or one costed on a pack that moved."""
    out = []
    for c in f.get("cost_sheets", []):
        blocked = str(c.get("status") or "").lower() == "draft" and not _num(c.get("gate_ok"))
        stale = bool(_num(c.get("pack_stale")))
        if not blocked and not stale:
            continue
        out.append({
            "key": f"COST_GATE_BLOCKED#{c['name']}", "risk_type": "margin_risk",
            "severity": "warning",
            "title": (f"Cost sheet {c['name']} ({c.get('style_no') or 'style n/a'}) is "
                      + ("costed against a buyer pack that has since moved"
                         if stale else "still gated — the price cannot be locked")
                      + (f" — {c.get('gate_notes')}" if c.get("gate_notes") else "")),
            "style": c.get("style_no"), "record": c["name"],
            "extra": _act("review_cost_sheet",
                          f"Re-cost / clear the gate on {c['name']} before quoting",
                          "A blocked gate means an unpriceable order", "Costing", "high"),
        })
    return out


def _r_pp_gate_open(f, cfg):
    """Pre-production gate: actions still open, or bulk cutting not released."""
    out = []
    for m in f.get("pp_meetings", []):
        open_actions = _num(m.get("open_actions"))
        released = bool(_num(m.get("bulk_cutting_allowed")))
        if open_actions <= 0 and released:
            continue
        out.append({
            "key": f"PP_GATE_OPEN#{m['name']}", "risk_type": "production_delay",
            "severity": "critical" if not released else "warning",
            "title": (f"PP meeting {m['name']} ({m.get('style_no') or 'style n/a'}) "
                      + (f"has {open_actions:,.0f} open action(s)" if open_actions
                         else "has not released bulk cutting")
                      + ("" if released else " — bulk cutting is held")),
            "style": m.get("style_no"), "affected_order": m.get("sales_order"),
            "record": m["name"],
            "extra": _act("close_pp_actions",
                          f"Close the open PP actions on {m['name']} and release bulk cutting",
                          "The floor cannot cut while the PP gate is open", "Production", "high"),
        })
    return out


def _r_requisition_no_cover(f, cfg):
    """A submitted fabric/trim requisition with no Material Request behind it."""
    out = []
    for r in f.get("trim_requisitions", []) + f.get("fabric_requisitions", []):
        if str(r.get("docstatus")) != "1" or r.get("material_request"):
            continue
        kind = "Trim" if r.get("name", "").startswith("TMR") else "Fabric"
        out.append({
            "key": f"REQ_NO_COVER#{r['name']}", "risk_type": "fabric_shortage",
            "severity": "warning",
            "title": (f"{kind} requisition {r['name']} ({r.get('style') or 'style n/a'}) is submitted "
                      f"with no Material Request — required by {r.get('required_by') or '—'}"),
            "style": r.get("style"), "affected_order": r.get("sales_order"),
            "record": r["name"], "required_date": str(r.get("required_by") or ""),
            "extra": _act("raise_material_request",
                          f"Raise the Material Request for {r['name']} and send it to purchasing",
                          "Turns a requisition into an actual buy", "Supply Chain", "high"),
        })
    return out


def _r_quotation_expired(f, cfg):
    """A quotation still in play whose validity date has passed."""
    out = []
    today = f["today"]
    for q in f.get("quotations", []):
        if str(q.get("docstatus")) != "0":
            continue
        if q.get("name") in (f.get("quotation_refs") or set()):
            continue
        if (q.get("workflow_state") or "").lower() in ("rejected", "expired", "lost", "cancelled"):
            continue
        valid = _d(q.get("valid_till"))
        if not valid or valid >= today:
            continue
        days = (today - valid).days
        out.append({
            "key": f"QUOTE_EXPIRED#{q['name']}", "risk_type": "margin_risk",
            "severity": "warning" if days <= 30 else "critical",
            "title": (f"Quotation {q['name']} ({q.get('party_name') or 'buyer n/a'}, "
                      f"USD {_num(q.get('grand_total')):,.2f}) expired {days} day(s) ago"),
            "record": q["name"], "required_date": str(valid),
            "extra": _act("renew_quotation",
                          f"Re-issue quotation {q['name']} at the current cost before the buyer accepts it",
                          "Stops an expired price being accepted", "Merchandising", "medium"),
        })
    return out


RULES = [
    # predictive / preventive first (they are the "get ahead" signals)
    _r_fabric_shortage,
    _r_production_shortfall,
    _r_bom_missing_order,
    _r_work_order_missing,
    _r_bom_coverage,
    # time-critical
    _r_order_overdue,
    _r_no_delivery_note,
    _r_invoiced_not_delivered,
    _r_payment_overdue,
    # supply / quality
    _r_po_late,
    _r_fabric_quality_fail,
    _r_quality_inspection_open,
    _r_trim_unmapped,
    # logistics / finance / data
    _r_shipment_variance,
    _r_missing_shipment_docs,
    # the buyer side / pre-order chain (2026-11-02)
    _r_client_po_unlinked,
    _r_buyer_pack_not_ready,
    _r_buyer_bom_unmapped,
    _r_cost_gate_blocked,
    _r_pp_gate_open,
    _r_requisition_no_cover,
    _r_quotation_expired,
    _r_payable_outstanding,
    _r_trim_mr_draft,
    _r_mdg_open,
]

_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}

# Doctype gate: a rule whose source doctype is absent on the connected site cannot say anything
# true, so it is skipped. A plain name means "doctype must exist"; ("X", "rows") means it must
# also hold at least one record (stock BOM / Work Order exist but are empty on a site that keeps
# its BOM model elsewhere, so every "no BOM" / "no Work Order" line there is an artefact).
# An UNREADABLE ERP never skips a rule: the rule is kept and the unknown is noted.
RULE_NEEDS = {
    "_r_fabric_shortage": [("BOM", "rows")],
    "_r_bom_missing_order": [("BOM", "rows")],
    "_r_bom_coverage": [("BOM", "rows")],
    "_r_work_order_missing": [("Work Order", "rows")],
    "_r_production_shortfall": ["Production Daily Evidence"],
    "_r_trim_unmapped": ["Trim Mapping Exception"],
    "_r_fabric_quality_fail": ["Fabric Quality Evidence"],
    "_r_client_po_unlinked": ["Client Purchase Order"],
    "_r_buyer_pack_not_ready": ["Buyer Tech Pack"],
    "_r_buyer_bom_unmapped": ["Buyer BOM"],
    "_r_requisition_no_cover": ["Cortex Fabric Requisition"],
    "_r_mdg_open": ["Migration Data Gap"],
}


def _need_ok(need, memo: dict):
    """True = satisfied, False = absent/empty, None = could not tell (keep the rule)."""
    dt, rows = (need, False) if isinstance(need, str) else (need[0], True)
    k = (dt, rows)
    if k not in memo:
        try:
            r = erp.erp_list_checked(dt, fields=["name"], limit=1)
        except Exception:
            memo[k] = None
            return None
        if r.state == erp.MISSING:
            memo[k] = False
        elif r.state != erp.FOUND:
            memo[k] = None
        else:
            memo[k] = bool(r.value) if rows else True
    return memo[k]


def rule_gate(rule, memo: Optional[dict] = None) -> tuple:
    """(run, note). run=False only when a needed doctype is positively absent."""
    memo = {} if memo is None else memo
    note = ""
    for need in RULE_NEEDS.get(rule.__name__, []):
        ok = _need_ok(need, memo)
        dt = need if isinstance(need, str) else need[0]
        if ok is False:
            return False, f"skipped: {dt} {'absent' if isinstance(need, str) else 'absent or empty'} on this site"
        if ok is None:
            note = f"kept: could not check {dt} (ERP unreadable)"
    return True, note


LAST_GATE: dict = {"skipped": [], "unchecked": []}


def build_risks() -> list:
    """Run every rule against the live facts. Returns risk dicts (per record)."""
    cfg = _cfg()
    facts = live_facts()
    cap = int(cfg["limits"].get("max_risks_per_rule", 25))
    risks = []
    memo: dict = {}
    LAST_GATE["skipped"], LAST_GATE["unchecked"] = [], []
    for rule in RULES:
        run, note = rule_gate(rule, memo)
        if not run:
            LAST_GATE["skipped"].append(f"{rule.__name__}: {note}")
            continue
        if note:
            LAST_GATE["unchecked"].append(f"{rule.__name__}: {note}")
        try:
            found = rule(facts, cfg) or []
        except Exception:
            found = []
        # keep the most severe when a rule over-produces
        found.sort(key=lambda r: _SEV_RANK.get(r.get("severity"), 9))
        for r in found[:cap]:
            r["status"] = "open"
            risks.append(r)
    risks.sort(key=lambda r: _SEV_RANK.get(r.get("severity"), 9))
    return risks


def build_recommendations(risks: Optional[list] = None) -> list:
    """Flatten the per-risk action templates into recommendation dicts."""
    if risks is None:
        risks = build_risks()
    cfg = _cfg()
    cap = int(cfg["limits"].get("max_recommendations", 60))
    recs = []
    for r in risks:
        extra = r.get("extra")
        if not extra:
            continue
        recs.append({
            "action_key": f"{r['key']}::{extra['slug']}",
            "risk_key": r["key"],
            "action": extra["action"],
            "expected_impact": extra["expected_impact"],
            "responsible_team": extra["responsible_team"],
            "priority": extra["priority"],
        })
    # criticals first
    rank = {r["key"]: _SEV_RANK.get(r.get("severity"), 9) for r in risks}
    recs.sort(key=lambda x: rank.get(x["risk_key"], 9))
    return recs[:cap]


def summarize(risks: list) -> dict:
    c = sum(1 for r in risks if r.get("severity") == "critical")
    w = sum(1 for r in risks if r.get("severity") == "warning")
    i = sum(1 for r in risks if r.get("severity") == "info")
    return {"total": len(risks), "critical": c, "warning": w, "info": i,
            "all_clear": len(risks) == 0}
