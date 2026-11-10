"""Cortex Operations Control Tower — API functions.

Every data function reads **live, read-only** from the client's KOGO ERP
(Frappe / KOGO_SAS) through ``erp.py``. Nothing here ever writes to the ERP.

The SQLite store keeps only the *decision* state this dashboard owns
(``risk_state``, ``action_state``, ``audit_log``). Risks and recommendations are
derived from the live ERP on every call and upserted by ``risk_key`` /
``action_key`` so their ids stay stable across calls, while the stored
``status`` / ``approval_status`` / ``modified_text`` are overlaid on top.

Every function returns the additive contract keys::

    "live": bool, "source": "KOGO ERP", "generated_at": "<iso>",
    "connection": {"connected": bool, "base": str, "error": str|None}

When the ERP is unreachable the functions return their normal shape with empty
collections and ``live: false`` — they never raise and never 500.
"""

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Optional
# (no urllib import: every ERP address is built by erp.url_for, never here)

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session

import config
import erp
import erp_model
import email_engine
import inbound
import wip_plan
import wip_actions
import wip_analytics
import mailer
import writes
from models import (ActionStateModel, AuditLogModel, EmailDraftModel,
                    MailMessageModel, MailSettingsModel, OrderChangeModel,
                    RiskStateModel, KVModel)


SOURCE = "KOGO ERP"

# Short-lived cache for the preview context (see _live_ctx) so repeated previews
# do not re-read the whole ERP snapshot. Keeps the read-only view responsive.
_LIVE_CTX_CACHE: dict = {"t": 0.0, "ctx": None}
_LIVE_CTX_TTL = 15.0  # seconds


# ────────────────────────────────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    # Timezone-aware UTC (ISO 8601 with +00:00) so the UI can render an
    # unambiguous instant — the Cortex Tower frontend displays it in IST.
    return datetime.now(timezone.utc).isoformat()


_DB_READY = False


def _ensure_db() -> None:
    """Make sure the local decision-state tables exist (lazy, run once).
    Safe to call from any entry point — the host may import rather than exec."""
    global _DB_READY
    if _DB_READY:
        return
    try:
        import database
        database.init_db()
        _DB_READY = True
    except Exception:
        pass


def _today_iso() -> str:
    return date.today().isoformat()


def _num(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _style_of_item(item_code: str) -> str:
    """`C2027-S84-304-MICTP-S` -> `C2027-S84-304` (drops colourway/size suffix)."""
    code = (item_code or "").strip()
    parts = code.split("-")
    if len(parts) >= 5:
        return "-".join(parts[:3])
    return code


def _meta(ctx: dict) -> dict:
    return {
        "live": bool(ctx.get("live")),
        "source": SOURCE,
        "generated_at": _now_iso(),
        "connection": ctx.get("status") or {"connected": False, "base": "", "error": "erp_unavailable"},
    }


def _empty_snapshot() -> dict:
    return {
        "error": None,
        "sales_orders": [],
        "boms": [],
        "items": [],
        "fabric_rolls": 0,
        "trim_reqs": 0,
        "material_requests": [],
        "purchase_orders": [],
        "purchase_receipts": [],
        "delivery_notes": 0,
        "sales_invoices": [],
        "payment_entries": 0,
        "work_orders": [],
        "job_cards": 0,
        "quality": [],
        "shipments": [],
        "shipment_groups": [],
        "freight_bookings": [],
        "production": [],
        "gaps": [],
        "item_prices": 0,
        # ── the model as it exists today (2026-11-02) ──────────────────────
        "client_pos": [],
        "buyer_packs": [],
        "buyer_boms": [],
        "style_files": [],
        "cost_sheets": [],
        "consumption_cards": [],
        "quotations": [],
        "trim_requisitions": [],
        "fabric_requisitions": [],
        "pp_meetings": [],
        "sales_contracts": [],
        "allowance_bands": [],
        "quality_inspections": [],
    }


SO_FIELDS = [
    "name", "customer", "po_no", "transaction_date", "delivery_date", "grand_total",
    "status", "docstatus", "per_delivered", "company", "currency", "custom_source_document",
    # terms & conditions actually held on the live order (were never surfaced before)
    "incoterm", "custom_source_terms", "terms", "tc_name",
    "payment_terms_template", "advance_payment_status",
]


def _strip_html(value) -> str:
    """Turn a Frappe Text-Editor (HTML) field into readable plain text."""
    import re as _re
    s = str(value or "")
    if not s:
        return ""
    s = _re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = _re.sub(r"(?s)<br\s*/?>|</p>|</div>|</li>", "\n", s)
    s = _re.sub(r"(?s)<li[^>]*>", "• ", s)
    s = _re.sub(r"(?s)<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"'))
    s = _re.sub(r"[ \t]+", " ", s)
    s = _re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _current_production(snapshot: dict) -> list:
    """Production rows for the CURRENT order scope, from ONE report only.

    The tracker file carries more than one report covering the same production, so
    summing them double-counts and mixes old data into the live view. We keep the
    single current-scope report that attributes best (most rows naming a Sales
    Order), breaking ties by the most recently ingested.
    """
    rows = [r for r in (snapshot.get("production") or [])
            if (r.get("data_scope") or "").strip() == "Current order scope"]
    if not rows:
        return []
    by_doc: dict = {}
    for r in rows:
        by_doc.setdefault(r.get("source_document") or "", []).append(r)
    def _score(rs):
        so = sum(1 for r in rs if (r.get("sales_order") or "").strip())
        ts = max((str(r.get("creation") or "") for r in rs), default="")
        return (so, ts)
    return max(by_doc.values(), key=_score)


def _norm_style(tracker_style: str, erp_styles) -> str:
    """Map a production-tracker style code onto the ERP style code.

    Trackers sometimes drop the wash code ('C9043-U70' vs 'C9043-U70-629').
    """
    ts = (tracker_style or "").strip().upper()
    if not ts:
        return ""
    for s in erp_styles:
        if str(s).upper() == ts:
            return s
    cands = [s for s in erp_styles if str(s).upper().startswith(ts)]
    if cands:
        return max(cands, key=len)
    # fall back to style + colour (first two segments): 'C9360-549-525' -> 'C9360-549-635'
    key2 = "-".join(ts.split("-")[:2])
    cands2 = [s for s in erp_styles
              if "-".join(str(s).upper().split("-")[:2]) == key2]
    return cands2[0] if len(cands2) == 1 else tracker_style


def _packed_production(snapshot: dict) -> list:
    """Current order-scope production rows from the report that carries a GENUINE
    packed figure.

    The 'Cutting, sewing, finishing & packing detail report' mirrors CUTTING into its
    PACKED column, so it cannot support a produced figure. The 'CORTEX VN PRODUCTION
    REPORT' carries a distinct PACK total. Pick the report with the most rows where
    packed differs from cutting; if none do, fall back to the attributable report.
    """
    rows = [r for r in (snapshot.get("production") or [])
            if (r.get("data_scope") or "").strip() == "Current order scope"]
    if not rows:
        return []
    by_doc: dict = {}
    for r in rows:
        by_doc.setdefault(r.get("source_document") or "", []).append(r)

    def _distinct(rs):
        return sum(1 for r in rs
                   if abs(_num(r.get("source_total_packed")) - _num(r.get("source_total_cutting"))) > 0.5)

    def _score(rs):
        return (_distinct(rs), max((str(r.get("creation") or "") for r in rs), default=""))

    best = max(by_doc.values(), key=_score)
    return best if _distinct(best) > 0 else _current_production(snapshot)


def _so_production_index(snapshot: dict) -> tuple[dict, dict]:
    """Split CURRENT production evidence into (by_sales_order, by_style) totals.

    Rows that name a Sales Order are keyed by it; the rest fall back to the style
    code. The two sets are disjoint, so an order is never double-counted.
    """
    by_so: dict = {}
    by_style: dict = {}
    for row in _current_production(snapshot):
        planned = _num(row.get("source_order_qty_pcs"))
        packed = _num(row.get("source_total_packed"))
        so = (row.get("sales_order") or "").strip().upper()
        style = (row.get("style_no") or "").strip().upper()
        if so:
            e = by_so.setdefault(so, {"planned": 0.0, "packed": 0.0})
            e["planned"] += planned
            e["packed"] += packed
        elif style:
            e = by_style.setdefault(style, {"planned": 0.0, "packed": 0.0})
            e["planned"] += planned
            e["packed"] += packed
    return by_so, by_style


def _order_packed(order_name: str, styles: list, by_so: dict, by_style: dict):
    """``(planned, packed, source)`` for one order.

    ``source`` is ``"sales_order"`` when the production evidence names this order
    (exact), ``"style"`` when it only names the style (estimated, and possibly
    shared between orders of the same style), or ``"none"``.
    """
    planned = packed = 0.0
    key = (order_name or "").upper()
    hit = None
    for k, v in by_so.items():
        if k and (key.startswith(k) or k.startswith(key)):
            hit = v
            break
    if hit:
        return hit["planned"], hit["packed"], "sales_order"
    matched = False
    for st in styles or []:
        v = by_style.get((st or "").upper())
        if v:
            planned += v["planned"]
            packed += v["packed"]
            matched = True
    return planned, packed, ("style" if matched else "none")


def _shipment_indexes(snapshot: dict) -> tuple[dict, dict]:
    """Split the shipped quantity into (by_sales_order, by_style).

    Source: `Shipment Document Evidence` + `Freight Booking`, grouped by
    erp_model.shipment_leg(). The figure is taken **per shipment group**, because
    one shipment is described by several evidence rows (the customs declaration,
    the bill of lading, the size grid) and summing the rows double-counts the same
    cartons — that is how 1,000 pcs once read as 1,976.
    """
    by_so: dict = {}
    by_style: dict = {}
    groups = snapshot.get("shipment_groups") or []
    if groups:
        for g in groups:
            if not isinstance(g, dict):
                continue
            qty = _num(g.get("shipped"))
            so = (g.get("sales_order") or "").strip().upper()
            style = (g.get("style") or "").strip().upper()
            if so:
                by_so[so] = by_so.get(so, 0.0) + qty
            elif style:
                by_style[style] = by_style.get(style, 0.0) + qty
        return by_so, by_style
    for row in (snapshot.get("shipments") or []):
        if not isinstance(row, dict):
            continue
        qty = _num(row.get("shipped_qty"))
        so = (row.get("sales_order") or "").strip().upper()
        style = (row.get("item") or "").strip().upper()
        if so:
            by_so[so] = by_so.get(so, 0.0) + qty
        elif style:
            by_style[style] = by_style.get(style, 0.0) + qty
    return by_so, by_style


def _order_shipped(order_name: str, styles: list, by_so: dict, by_style: dict):
    """``(sent_qty, source)`` for one order — the shipped / invoiced quantity.

    ``source`` is ``"sales_order"`` when a shipment record names this order
    (exact), ``"style"`` when it only names the style (estimated), or ``"none"``.
    """
    key = (order_name or "").upper()
    for k, v in by_so.items():
        if k and (key.startswith(k) or k.startswith(key)):
            return v, "sales_order"
    sent = 0.0
    matched = False
    for st in styles or []:
        v = by_style.get((st or "").upper())
        if v:
            sent += v
            matched = True
    return sent, ("style" if matched else "none")


# ────────────────────────────────────────────────────────────────────────────
# Live ERP snapshot
# ────────────────────────────────────────────────────────────────────────────

def _snapshot():
    """Read every ERP slice the dashboard needs. Returns ``(snapshot, status)``.

    Degrades to an empty snapshot with ``connected=False`` on any failure.
    Never raises.
    """
    status = erp.erp_status()
    d = _empty_snapshot()
    if not status.get("connected"):
        return d, status

    try:
        ok, sos = erp.erp_get_checked(
            "Sales Order", fields=SO_FIELDS, filters=[["docstatus", "=", 1]],
            limit=0, order="delivery_date asc",
        )
        if not ok:
            status = dict(status)
            status["connected"] = False
            status["error"] = "erp_read_failed: " + (erp.last_error() or "unknown")
            d["error"] = status["error"]
            return d, status

        # Child tables do not come back on list fields — hydrate `items` per doc.
        for so in sos:
            if not isinstance(so, dict):
                continue
            doc = erp.erp_doc("Sales Order", so.get("name"))
            so["items"] = [
                {"item_code": i.get("item_code"), "qty": i.get("qty"),
                 "rate": i.get("rate"), "amount": i.get("amount")}
                for i in (doc.get("items") or [])
            ]
            # Source exception (e.g. "Customer photo sample PO.") + PO number
            so["source_exception"] = doc.get("custom_source_exception") or ""

            # ── Order basis vs invoiced basis ────────────────────────────────
            # Cortex confirmed (2026-10-06) that the *Sales Order* quantity is
            # the PO/order quantity while the *final commercial invoice* is the
            # actual shipped quantity (incl. tolerance). Where the order was
            # amended, the pre-amendment original holds the PO/order quantity.
            items = doc.get("items") or []
            so_qty = sum(_num(i.get("qty")) for i in items)
            amount = sum(_num(i.get("amount")) for i in items)
            rate = (amount / so_qty) if so_qty else 0.0
            # Rebuilt 2026-10-06: the ERP Sales Orders now carry the PO/order quantity,
            # so the SO quantity IS the order (PO) quantity. The commercial-invoice
            # (shipped) quantity lives on the Sales Invoices.
            so["so_qty"] = int(so_qty)
            so["po_qty"] = int(so_qty)
            so["so_basis_usd"] = round(_num(doc.get("grand_total")), 2)
            so["order_basis_usd"] = so["so_basis_usd"]
            so["rate_usd"] = round(rate, 4)

        # ── Buyer PO number backfill ────────────────────────────────────────
        # The LIVE (amended) Sales Orders lost `po_no` during their amendments —
        # the superseded originals still carry it (e.g. the live
        # SAL-ORD-2026-00001-2 has po_no empty, but SAL-ORD-2026-00001 = 69785).
        # Backfill from any Sales Order sharing the same base number so the buyer
        # PO is never blank — otherwise the Orders tab shows "—" for every
        # amended order.
        try:
            import re as _re
            po_rows = erp.erp_get("Sales Order", fields=["name", "po_no"], limit=0)
            po_by_base: dict = {}
            for r in (po_rows or []):
                p = str((r.get("po_no") or "")).strip()
                if not p:
                    continue
                base = _re.sub(r"-\d+$", "", str(r.get("name") or "").strip())
                po_by_base.setdefault(base, p)
            for so in sos:
                if isinstance(so, dict) and not str(so.get("po_no") or "").strip():
                    base = _re.sub(r"-\d+$", "", str(so.get("name") or "").strip())
                    if po_by_base.get(base):
                        so["po_no"] = po_by_base[base]
        except Exception:
            pass

        d["sales_orders"] = sos
        d["boms"] = erp.erp_get(
            "BOM",
            fields=["name", "item", "total_sam", "op_cm_usd", "op_cost_per_minute_usd",
                    "op_total_operation_cost_usd", "op_target_cost", "op_achieved_cost",
                    "op_planned_operators", "op_planned_helpers", "docstatus"],
            limit=0,
        )
        d["items"] = erp.erp_get(
            "Item", fields=["name", "variant_of", "has_variants", "item_group"], limit=0
        )
        d["fabric_rolls"] = erp.erp_count("Fabric Roll")
        d["trim_requisitions"] = erp.erp_get(
            "Cortex Trim Requisition",
            fields=["name", "status", "docstatus", "style", "sales_order", "required_by",
                    "total_required_qty", "material_request"],
            limit=0,
        )
        d["fabric_requisitions"] = erp.erp_get(
            "Cortex Fabric Requisition",
            fields=["name", "status", "docstatus", "style", "sales_order", "required_by",
                    "total_required_qty", "material_request"],
            limit=0,
        )
        d["trim_reqs"] = len(d["trim_requisitions"])
        d["material_requests"] = erp.erp_get(
            "Material Request",
            fields=["name", "status", "custom_trim_requisition", "transaction_date",
                    "material_request_type", "schedule_date"],
            limit=0,
        )
        d["purchase_orders"] = erp.erp_get(
            "Purchase Order",
            fields=["name", "supplier", "transaction_date", "schedule_date", "status",
                    "per_received", "grand_total", "docstatus"],
            limit=0,
        )
        d["purchase_receipts"] = erp.erp_get(
            "Purchase Receipt",
            fields=["name", "supplier", "posting_date", "status", "grand_total", "docstatus"],
            limit=0,
        )
        d["delivery_notes"] = erp.erp_count("Delivery Note", [["docstatus", "!=", 2]])
        d["sales_invoices"] = erp.erp_get(
            "Sales Invoice",
            fields=["name", "grand_total", "outstanding_amount", "status", "docstatus",
                    "customer", "posting_date", "currency"],
            limit=0,
        )
        d["payment_entries"] = erp.erp_count("Payment Entry", [["docstatus", "!=", 2]])
        d["work_orders"] = erp.erp_get(
            "Work Order",
            fields=["name", "production_item", "bom_no", "qty", "produced_qty",
                    "status", "docstatus", "company"],
            limit=0,
        )
        d["job_cards"] = erp.erp_count("Job Card")
        d["quality"] = erp.erp_get(
            "Fabric Quality Evidence",
            fields=["name", "source_fabric_code", "inspection_result",
                    "detailed_metrics_extracted", "source_document"],
            limit=0,
        )
        # ── the shipment leg (2026-11-02) ──────────────────────────────────
        # `Garment Shipment Evidence` was retired; the customs leg now lives in
        # `Shipment Document Evidence` (one row per document) + `Freight Booking`.
        # erp_model.shipment_leg() groups those rows per shipment so a shipment
        # described by a declaration row AND a size-grid row is counted once.
        try:
            leg = erp_model.shipment_leg()
            d["shipments"] = leg.get("rows") or []
            d["shipment_groups"] = leg.get("groups") or []
            d["freight_bookings"] = leg.get("bookings") or []
        except Exception:
            d["shipments"], d["shipment_groups"], d["freight_bookings"] = [], [], []
        # `Production Daily Evidence` was retired with the old tracker ingest; the
        # shop floor is now PP Meeting → Cutting Lay → Production Card → WIP.
        d["production"] = []
        d["pp_meetings"] = erp.erp_get(
            "PP Meeting",
            fields=["name", "status", "sales_order", "style_no", "meeting_date",
                    "order_qty", "open_actions", "bulk_cutting_allowed", "pilot_run_closed"],
            limit=0,
        )
        # ── buyer side + pre-order (the Stage-1 model) ─────────────────────
        d["client_pos"] = erp.erp_get(
            "Client Purchase Order",
            fields=["name", "client_po_no", "order_ref", "order_ref_label", "order_ref_type",
                    "em_no", "po_date", "customer", "status",
                    "qty", "amount_usd", "style_no", "x_factory_date", "linked_sales_order"],
            limit=0,
        )
        d["buyer_packs"] = erp.erp_get(
            "Buyer Tech Pack",
            fields=["name", "status", "style_no", "customer", "pack_revision", "round",
                    "bom_line_count", "pom_line_count", "readiness", "buyer_decision",
                    "corrected_due", "style_file"],
            limit=0,
        )
        d["buyer_boms"] = erp.erp_get(
            "Buyer BOM",
            fields=["name", "status", "style_no", "pack", "line_count", "mapped_count",
                    "unmapped_count", "fabric_line_count", "generated_bom_count"],
            limit=0,
        )
        d["style_files"] = erp.erp_get(
            "Style File", fields=["name", "status", "style_no", "customer", "qty", "target_fob"],
            limit=0,
        )
        d["cost_sheets"] = erp.erp_get(
            "Cost Sheet",
            fields=["name", "status", "style_no", "customer", "order_qty", "total_fob",
                    "avg_margin_pct", "gate_ok", "gate_notes", "pack_stale", "docstatus"],
            limit=0,
        )
        d["consumption_cards"] = erp.erp_get(
            "Consumption Card",
            fields=["name", "style_no", "status", "docstatus", "weighted_consumption",
                    "total_fabric_qty"],
            limit=0,
        )
        d["quotations"] = erp.erp_get(
            "Quotation",
            fields=["name", "party_name", "workflow_state", "docstatus", "grand_total",
                    "transaction_date", "valid_till", "currency"],
            limit=0,
        )
        # Which quotations were actually converted? A Sales Order carries the
        # quotation it came from (`custom_quotation`), and that — not the
        # Quotation's own `status` (which stays "Draft" until submit) — is the
        # honest test for "still in play".
        d["quotation_refs"] = {
            r.get("custom_quotation") for r in
            (erp.erp_get("Sales Order", fields=["name", "custom_quotation"], limit=0) or [])
            if r.get("custom_quotation")
        }
        d["sales_contracts"] = erp.erp_get(
            "Sales Contract", fields=["name", "customer", "docstatus"], limit=0,
        )
        d["allowance_bands"] = erp.erp_get(
            "Contract Allowance Band",
            fields=["name", "band_from", "band_to", "tolerance_pct", "applies_to",
                    "customer", "active"],
            limit=0,
        )
        d["quality_inspections"] = erp.erp_get(
            "Quality Inspection",
            fields=["name", "status", "docstatus", "item_code", "inspection_type"],
            limit=0,
        )
        d["gaps"] = erp.erp_get(
            "Migration Data Gap",
            fields=["name", "gap_key", "process_area", "missing_information",
                    "status", "affected_records", "recommended_request_to_cortex"],
            limit=0,
        )
        d["item_prices"] = erp.erp_count("Item Price")
    except Exception as e:  # defensive — must never escape
        d["error"] = str(e)[:300]
    return d, status


# ────────────────────────────────────────────────────────────────────────────
# Derived live facts
# ────────────────────────────────────────────────────────────────────────────

def _facts(d: dict) -> dict:
    """Derived live facts. One place, so the KPI tiles, the charts and the
    recommendations can never disagree about what the ERP says."""
    sos = [s for s in d.get("sales_orders", []) if isinstance(s, dict)]
    boms = [b for b in d.get("boms", []) if isinstance(b, dict)]
    items = [i for i in d.get("items", []) if isinstance(i, dict)]
    shipments = [s for s in d.get("shipments", []) if isinstance(s, dict)]
    groups = [g for g in d.get("shipment_groups", []) if isinstance(g, dict)]
    quality = [q for q in d.get("quality", []) if isinstance(q, dict)]
    gaps = [g for g in d.get("gaps", []) if isinstance(g, dict)]
    mrs = [m for m in d.get("material_requests", []) if isinstance(m, dict)]
    invoices = [s for s in d.get("sales_invoices", []) if isinstance(s, dict)]

    so_names = [s.get("name") for s in sos if s.get("name")]

    # ── orders: "open" means not yet delivered, not "every submitted order" ──
    open_sos = [s for s in sos if _num(s.get("per_delivered")) < 100]
    order_book = round(sum(_num(s.get("grand_total")) for s in open_sos), 2)
    order_book_all = round(sum(_num(s.get("grand_total")) for s in sos), 2)
    units = sum(_num(i.get("qty")) for s in open_sos for i in (s.get("items") or []))
    delivery_dates = sorted([s.get("delivery_date") for s in open_sos if s.get("delivery_date")])
    months = sorted({dd[:7] for dd in delivery_dates})

    # ── BOM coverage: DISTINCT finished-garment items that have a BOM ──────
    # (counting BOM documents against variants gave 115% — a variant can carry
    # more than one BOM revision, so the numerator must be distinct items)
    fg_variants = [i for i in items
                   if i.get("variant_of") and (i.get("item_group") or "") == "Finished Garments"]
    if not fg_variants:
        fg_variants = [i for i in items if i.get("variant_of")]
    variant_names = {i.get("name") for i in fg_variants}
    bom_items = {b.get("item") for b in boms if b.get("item")}
    covered_items = variant_names & bom_items
    variants_total = len(variant_names)
    bom_total = len(covered_items)
    coverage_pct = round(bom_total / variants_total * 100) if variants_total else 0

    draft_mrs = [m for m in mrs if (m.get("status") or "").lower() == "draft"]
    open_gaps = [g for g in gaps if (g.get("status") or "").lower() != "resolved"]
    si_total = round(sum(_num(s.get("grand_total")) for s in invoices), 2)
    not_extracted = [q for q in quality
                     if "not conclusively" in (q.get("inspection_result") or "").lower()]
    fails = [q for q in quality if (q.get("inspection_result") or "").strip().lower() == "fail"]

    # ── shipment leg: per GROUP, never per evidence row ───────────────────
    sent_pcs = sum(_num(g.get("shipped")) for g in groups)
    sent_planned = sum(_num(g.get("ordered")) for g in groups)
    captured = [g for g in groups if g.get("qty_captured")]
    # judged from the contract band inside erp_model.shipment_leg() — the string is
    # a consequence, not the source (RULES 01 #109)
    allowance_flags = [g for g in groups if g.get("allowance_verdict") == "Over"]
    allowance_unconfirmed = [g for g in groups if g.get("allowance_verdict") == "UNCONFIRMED"
                             and g.get("qty_captured")]
    docs_missing = [g for g in groups if g.get("missing")]
    unlinked_rows = [r for r in shipments
                     if not r.get("sales_order") and not r.get("client_purchase_order")]

    # ── receivables ───────────────────────────────────────────────────────
    open_inv = [s for s in invoices if _num(s.get("outstanding_amount")) > 0.5]
    overdue_inv = []
    today = _today_iso()
    for s in open_inv:
        due = s.get("due_date") or s.get("posting_date")
        if due and str(due) < today:
            overdue_inv.append(s)

    # ── buyer side (Stage 1) ──────────────────────────────────────────────
    cpos = [c for c in d.get("client_pos", []) if isinstance(c, dict)]
    packs = [p for p in d.get("buyer_packs", []) if isinstance(p, dict)]
    bboms = [b for b in d.get("buyer_boms", []) if isinstance(b, dict)]
    cost_sheets = [c for c in d.get("cost_sheets", []) if isinstance(c, dict)]
    quotes = [q for q in d.get("quotations", []) if isinstance(q, dict)]
    trims = [t for t in d.get("trim_requisitions", []) if isinstance(t, dict)]
    fabrics = [f for f in d.get("fabric_requisitions", []) if isinstance(f, dict)]
    pp = [p for p in d.get("pp_meetings", []) if isinstance(p, dict)]
    qis = [q for q in d.get("quality_inspections", []) if isinstance(q, dict)]

    cpo_linked = [c for c in cpos if c.get("linked_sales_order")]
    packs_not_ready = [p for p in packs
                       if "not ready" in str(p.get("readiness") or "").lower()
                       or str(p.get("status") or "").lower() in ("superseded", "cancelled")]
    bbom_unmapped = [b for b in bboms if _num(b.get("unmapped_count")) > 0]
    cost_blocked = [c for c in cost_sheets
                    if str(c.get("status") or "").lower() == "draft"
                    and not _num(c.get("gate_ok"))]
    cost_stale = [c for c in cost_sheets if _num(c.get("pack_stale"))]
    converted = d.get("quotation_refs") or set()
    quotes_open = [q for q in quotes
                   if str(q.get("docstatus")) == "0"
                   and q.get("name") not in converted
                   and str(q.get("workflow_state") or "").lower()
                   in ("draft", "pending approval", "approved", "sent", "")]
    quotes_expired = [q for q in quotes_open
                      if q.get("valid_till") and str(q.get("valid_till")) < today]
    reqs_no_mr = [r for r in (trims + fabrics)
                  if str(r.get("docstatus")) == "1" and not r.get("material_request")]
    pp_open = [p for p in pp if _num(p.get("open_actions")) > 0
               or not _num(p.get("bulk_cutting_allowed"))]
    qis_open = [q for q in qis if str(q.get("docstatus")) == "0"]

    so_item_codes = sorted({(i.get("item_code") or "")
                            for s in sos for i in (s.get("items") or []) if i.get("item_code")})

    return {
        "sos": sos, "so_names": so_names, "months": months, "delivery_dates": delivery_dates,
        "earliest_delivery": delivery_dates[0] if delivery_dates else None,
        "latest_delivery": delivery_dates[-1] if delivery_dates else None,
        "open_sos": open_sos, "open_orders": len(open_sos),
        "order_book": order_book, "order_book_po": order_book, "order_book_so": order_book,
        "order_book_all": order_book_all,
        "units": units,
        "customers": sorted({s.get("customer") for s in sos if s.get("customer")}),
        "companies": sorted({s.get("company") for s in sos if s.get("company")}),
        "boms": boms, "bom_total": bom_total, "bom_docs": len(boms),
        "variants_total": variants_total, "coverage_pct": coverage_pct,
        "fabric_rolls": int(d.get("fabric_rolls") or 0),
        "trim_reqs": int(d.get("trim_reqs") or 0),
        "mrs": mrs, "draft_mrs": draft_mrs,
        "purchase_orders": d.get("purchase_orders") or [],
        "purchase_receipts": d.get("purchase_receipts") or [],
        "delivery_notes": int(d.get("delivery_notes") or 0),
        "invoices": invoices, "si_total": si_total,
        "open_invoices": open_inv, "overdue_invoices": overdue_inv,
        "receivable_usd": round(sum(_num(s.get("outstanding_amount")) for s in open_inv), 2),
        "overdue_usd": round(sum(_num(s.get("outstanding_amount")) for s in overdue_inv), 2),
        "payment_entries": int(d.get("payment_entries") or 0),
        "work_orders": d.get("work_orders") or [],
        "job_cards": int(d.get("job_cards") or 0),
        "quality": quality, "not_extracted": not_extracted, "fails": fails,
        "shipments": shipments, "shipment_groups": groups,
        "shipment_rows": len(shipments),
        "sent_pcs": int(sent_pcs), "sent_planned": int(sent_planned),
        "shipments_captured": len(captured),
        "allowance_flags": allowance_flags, "allowance_unconfirmed": allowance_unconfirmed,
        "docs_missing": docs_missing,
        "unlinked_shipment_rows": unlinked_rows,
        "variances": [_num(g.get("variance_qty")) for g in groups],
        "nonzero_var": [_num(g.get("variance_qty")) for g in groups if _num(g.get("variance_qty"))],
        "production": d.get("production") or [],
        "pp_meetings": pp, "pp_open": pp_open,
        "gaps": gaps, "open_gaps": open_gaps,
        "item_prices": int(d.get("item_prices") or 0),
        "so_item_codes": so_item_codes,
        # buyer side
        "client_pos": cpos, "cpo_count": len(cpos), "cpo_linked": cpo_linked,
        "cpo_usd": round(sum(_num(c.get("amount_usd")) for c in cpos), 2),
        "cpo_qty": int(sum(_num(c.get("qty")) for c in cpos)),
        "buyer_packs": packs, "packs_not_ready": packs_not_ready,
        "buyer_boms": bboms, "bbom_unmapped": bbom_unmapped,
        "style_files": d.get("style_files") or [],
        "cost_sheets": cost_sheets, "cost_blocked": cost_blocked, "cost_stale": cost_stale,
        "quotations": quotes, "quotes_open": quotes_open, "quotes_expired": quotes_expired,
        "quotes_converted": sorted(converted),
        "trim_requisitions": trims, "fabric_requisitions": fabrics,
        "requisitions": trims + fabrics, "reqs_no_mr": reqs_no_mr,
        "consumption_cards": d.get("consumption_cards") or [],
        "quality_inspections": qis, "qis_open": qis_open,
    }


def _quality_style(f: dict, so_item_codes) -> Optional[str]:
    """Find the live style that uses a failing fabric code (e.g. S84)."""
    code = (f.get("source_fabric_code") or "").strip()
    if not code:
        return None
    for item in so_item_codes:
        if f"-{code}-" in item:
            return _style_of_item(item)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Risk + recommendation derivation now lives in rulebook.py (the generic,
# config-driven engine). It is bound to _build_risks / _build_recommendations
# by the overrides near the function registry below. (The old hardcoded copies
# were removed — dead/shadowed code.)
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
# KPIs + charts
# ────────────────────────────────────────────────────────────────────────────

def _kpis(d: dict) -> list:
    """The executive tiles — every one of them a live ERP number.

    Ordered along the order's own chain (pre-order → order → buying → floor →
    shipment → money), so the strip reads left to right like the process.
    """
    f = _facts(d)
    open_orders = f["open_orders"]
    earliest = f["earliest_delivery"] or "—"
    avg_units = round(f["units"] / open_orders) if open_orders else 0

    packs_not_ready = len(f["packs_not_ready"])
    quotes_open = len(f["quotes_open"])
    cost_blocked = len(f["cost_blocked"])
    reqs_no_mr = len(f["reqs_no_mr"])
    pp_open = len(f["pp_open"])
    docs_missing = len(f["docs_missing"])
    overdue = len(f["overdue_invoices"])
    open_gaps = len(f["open_gaps"])

    return [
        # ── the order ─────────────────────────────────────────────────────
        {"key": "open_orders", "label": "Open customer orders", "value": f"{open_orders}",
         "unit": "", "tone": "neutral",
         "hint": (f"next due {earliest}" if open_orders else "none awaiting delivery"),
         "tooltip": ("Sales Orders in KOGO ERP that are submitted and not yet fully delivered "
                     "(per_delivered < 100). A delivered order leaves this count.")},
        {"key": "order_book", "label": "Order book value", "value": f"{f['order_book']:,.0f}",
         "unit": "USD", "tone": "positive",
         "hint": f"across {open_orders} open order{'s' if open_orders != 1 else ''}"
                 + (f" · all orders {f['order_book_all']:,.0f}" if f["order_book_all"] > f["order_book"] + 1 else ""),
         "tooltip": ("Combined value of the OPEN Sales Orders (grand total, USD) — the order book. "
                     "Delivered orders and cancelled/amended predecessors are excluded.")},
        {"key": "units_on_order", "label": "Garments on order", "value": f"{int(f['units']):,}",
         "unit": "pcs", "tone": "neutral",
         "hint": f"avg {avg_units:,} pcs per order" if open_orders else "—",
         "tooltip": "Total garments across the open sales orders (sum of order lines)."},
        {"key": "buyer_book", "label": "Buyer POs on file", "value": f"{f['cpo_count']}",
         "unit": "", "tone": "neutral",
         "hint": f"USD {f['cpo_usd']:,.0f} · {len(f['cpo_linked'])} linked to an order",
         "tooltip": ("Client Purchase Orders the buyer actually issued (the paper that starts an order). "
                     "A PO with no linked Sales Order is demand the ERP has not turned into an order yet.")},

        # ── the pre-order / buyer model ───────────────────────────────────
        {"key": "buyer_pack", "label": "Buyer packs", "value": f"{len(f['buyer_packs'])}",
         "unit": "", "tone": "warning" if packs_not_ready else "positive",
         "hint": (f"{packs_not_ready} not ready to build a BOM" if packs_not_ready
                  else "all packs usable"),
         "tooltip": ("Buyer Tech Packs on file, one per revision. The pack is the customer-side source "
                     "of style, BOM lines and POM columns; a pack that is not ready blocks the BOM.")},
        {"key": "quotations", "label": "Quotations in play", "value": f"{quotes_open}",
         "unit": "", "tone": "warning" if len(f["quotes_expired"]) else "neutral",
         "hint": (f"{len(f['quotes_expired'])} past validity" if f["quotes_expired"]
                  else f"of {len(f['quotations'])} ever raised"),
         "tooltip": ("Quotations still inside the negotiation workflow (Draft · Pending Approval · "
                     "Approved · Sent). A quotation past its validity date cannot be accepted as-is.")},
        {"key": "cost_gate", "label": "Cost sheets blocked", "value": f"{cost_blocked}",
         "unit": "", "tone": "critical" if cost_blocked else "positive",
         "hint": (f"of {len(f['cost_sheets'])} cost sheets · {len(f['cost_stale'])} on a moved pack"
                  if f["cost_sheets"] else "no cost sheet raised yet"),
         "tooltip": ("Cost Sheets whose gate is closed (no margin floor / missing rate) or that were "
                     "costed against a buyer pack that has since moved. A blocked cost sheet cannot price.")},
        {"key": "bom_coverage", "label": "BOM coverage (variants)", "value": f"{f['coverage_pct']}",
         "unit": "%", "tone": "warning" if f["coverage_pct"] < 100 else "positive",
         "hint": f"{f['bom_total']} of {f['variants_total']} garment variants · {f['bom_docs']} BOMs",
         "tooltip": ("Share of the finished-garment variants that have a Bill of Materials. "
                     "Counted as DISTINCT items with a BOM, so several BOMs on one size "
                     "can never push the figure over 100%.")},

        # ── buying ────────────────────────────────────────────────────────
        {"key": "fabric_rolls", "label": "Fabric rolls received", "value": f"{f['fabric_rolls']:,}",
         "unit": "rolls", "tone": "positive",
         "hint": "received into the fabric store",
         "tooltip": "Fabric rolls recorded in the fabric store (Fabric Roll)."},
        {"key": "requisitions", "label": "Requisitions without cover", "value": f"{reqs_no_mr}",
         "unit": "", "tone": "critical" if reqs_no_mr else "positive",
         "hint": (f"of {len(f['requisitions'])} fabric + trim requisitions"
                  if f["requisitions"] else "no requisition raised"),
         "tooltip": ("Submitted Cortex fabric/trim requisitions that carry no Material Request yet — "
                     "the demand exists but purchasing has not been asked to buy.")},
        {"key": "trim_mr_draft", "label": "Material requests (draft)", "value": f"{len(f['draft_mrs'])}",
         "unit": "", "tone": "warning" if f["draft_mrs"] else "positive",
         "hint": f"of {len(f['mrs'])} material requests",
         "tooltip": "Material Requests still in Draft — not yet raised to a supplier as an order."},

        # ── the floor ─────────────────────────────────────────────────────
        {"key": "floor_gate", "label": "PP gates open", "value": f"{pp_open}",
         "unit": "", "tone": "critical" if pp_open else "positive",
         "hint": (f"of {len(f['pp_meetings'])} PP meetings · bulk cutting held"
                  if pp_open else f"{len(f['pp_meetings'])} PP meeting(s) closed"),
         "tooltip": ("Pre-production meetings with actions still open, or where the gate has not "
                     "released bulk cutting. The floor cannot cut until the PP gate closes.")},

        # ── shipment ──────────────────────────────────────────────────────
        {"key": "shipments", "label": "Shipped (declared)", "value": f"{f['sent_pcs']:,}",
         "unit": "pcs", "tone": "neutral",
         "hint": (f"{len(f['shipment_groups'])} shipment groups · {f['shipment_rows']} evidence rows"),
         "tooltip": ("Quantity actually shipped, read from Shipment Document Evidence and counted once "
                     "per shipment group (the customs declaration row and the size-grid row describe "
                     "the same cartons).")},
        {"key": "shipment_docs", "label": "Shipment document gaps", "value": f"{docs_missing}",
         "unit": "", "tone": "critical" if docs_missing else "positive",
         "hint": (f"{len(f['unlinked_shipment_rows'])} evidence rows with no shipment group"
                  if f["unlinked_shipment_rows"] else "every group has its document set"),
         "tooltip": ("Shipment groups missing a Customs Declaration or a Bill of Lading / Air Waybill, "
                     "plus evidence rows that name neither a shipment group nor an order.")},

        # ── money + data ──────────────────────────────────────────────────
        {"key": "receivables", "label": "Receivables overdue", "value": f"{overdue}",
         "unit": "", "tone": "critical" if overdue else "positive",
         "hint": (f"USD {f['overdue_usd']:,.0f} of USD {f['receivable_usd']:,.0f} open"
                  if f["open_invoices"] else "nothing outstanding"),
         "tooltip": "Submitted Sales Invoices with an outstanding balance whose due date has passed."},
        {"key": "delivery_notes", "label": "Delivery notes raised", "value": f"{f['delivery_notes']}",
         "unit": "", "tone": "neutral",
         "hint": f"for {open_orders} open order{'' if open_orders == 1 else 's'}",
         "tooltip": "Delivery Notes raised and not cancelled — the goods-movement document that "
                    "shipment and invoicing hang off."},
        {"key": "open_gaps", "label": "Open data gaps", "value": f"{open_gaps}",
         "unit": "", "tone": "critical" if open_gaps else "positive",
         "hint": f"of {len(f['gaps'])} recorded migration gaps",
         "tooltip": "Migration data gaps still awaiting evidence from Cortex."},
    ]


def _charts(d: dict) -> dict:
    f = _facts(d)

    month_counts = {}
    for so in f["sos"]:
        dd = so.get("delivery_date")
        if dd:
            month_counts[dd[:7]] = month_counts.get(dd[:7], 0) + 1
    orders_at_risk = [{"x": m, "y": month_counts[m]} for m in sorted(month_counts)]

    material_readiness = [
        {"x": _style_of_item(b.get("item")), "y": round(_num(b.get("total_sam")), 2)}
        for b in f["boms"] if b.get("item")
    ]

    # "Ordered · factory packed · sent" (per style)
    #   ordered       = the LIVE Sales Order quantity per style — the PO/order
    #                   quantity, i.e. the same basis as the Order book (ERP)
    #   actual/packed = the FACTORY packed quantity from the production tracker,
    #                   from the report whose PACKED column is a genuine packed
    #                   figure. INTERNAL and UNVERIFIED — never the commercial figure.
    #   sent          = the AUTHORITATIVE shipped quantity, from the final packing
    #                   list / commercial invoice (Garment Shipment Evidence).
    ordered: dict = {}
    for so in f["sos"]:
        for it in (so.get("items") or []):
            st = _style_of_item(it.get("item_code") or "")
            if st:
                ordered[st] = ordered.get(st, 0.0) + _num(it.get("qty"))
    produced: dict = {}
    for row in _packed_production(d):
        st = _norm_style(row.get("style_no") or "", ordered)
        if st:
            produced[st] = produced.get(st, 0.0) + _num(row.get("source_total_packed"))
    # sent = the AUTHORITATIVE shipped figure, from the final packing list /
    # commercial invoice (Garment Shipment Evidence), by style.
    # sent — per shipment GROUP (a group can be described by several evidence
    # rows; summing the rows double-counts the same cartons), by style.
    sent: dict = {}
    for g in f["shipment_groups"]:
        st = _norm_style(g.get("style") or "", ordered)
        if st:
            sent[st] = sent.get(st, 0.0) + _num(g.get("shipped"))
    keys = sorted(set(ordered) | set(produced) | set(sent))
    prod_plan_actual = [{"x": k,
                         "planned": int(ordered.get(k, 0.0)),
                         "actual": int(produced.get(k, 0.0)),
                         "sent": int(sent.get(k, 0.0))} for k in keys]

    q = {}
    for row in f["quality"]:
        code = row.get("source_fabric_code") or "unknown"
        res = (row.get("inspection_result") or "").lower()
        e = q.setdefault(code, {"x": code, "pass": 0, "fail": 0, "not_extracted": 0})
        if res == "pass":
            e["pass"] += 1
        elif res == "fail":
            e["fail"] += 1
        else:
            e["not_extracted"] += 1
    quality_trends = [q[k] for k in sorted(q)]

    # shipment readiness: ordered vs shipped per shipment group (one bar per group,
    # not per document row — a declaration row and its bill-of-lading row are the
    # same cartons).
    ship = {}
    for g in f["shipment_groups"]:
        key = g.get("style") or g.get("sales_order") or g.get("group") or "unknown"
        s = ship.setdefault(key, {"x": key, "planned": 0.0, "actual": 0.0})
        s["planned"] += _num(g.get("ordered"))
        s["actual"] += _num(g.get("shipped"))
    shipment_readiness = [
        {"x": v["x"], "planned": int(v["planned"]), "actual": int(v["actual"])}
        for v in sorted(ship.values(), key=lambda r: r["x"])
    ]

    order_margin = [
        {"x": _style_of_item(b.get("item")),
         "expected": round(_num(b.get("op_cm_usd")), 4),
         "current": round(_num(b.get("op_total_operation_cost_usd")), 4)}
        for b in f["boms"] if b.get("item")
    ]

    # Sourcing pipeline: received vs ordered schedule per supplier (on-time %).
    pos_by_supplier = {}
    for p in f["purchase_orders"]:
        if str(p.get("docstatus")) == "2":
            continue
        pos_by_supplier.setdefault(p.get("supplier"), []).append(p)
    stats = {}
    for pr in f["purchase_receipts"]:
        sup = pr.get("supplier")
        acc = stats.setdefault(sup, {"on_time": 0, "total": 0})
        acc["total"] += 1
        cands = pos_by_supplier.get(sup) or []
        match = None
        if cands:
            match = min(cands, key=lambda p: abs(_num(p.get("grand_total")) - _num(pr.get("grand_total"))))
        sched = (match or {}).get("schedule_date")
        posted = pr.get("posting_date")
        if not sched or (posted and posted <= sched):
            acc["on_time"] += 1
    supplier_delivery = []
    for sup in sorted(stats, key=lambda s: (s is None, s or "")):
        acc = stats[sup]
        pct = round(100.0 * acc["on_time"] / acc["total"]) if acc["total"] else 0
        supplier_delivery.append({"x": sup or "Unknown", "otel": pct, "y": pct})

    return {
        "orders_at_risk": orders_at_risk,
        "material_readiness": material_readiness,
        "prod_plan_actual": prod_plan_actual,
        "quality_trends": quality_trends,
        "shipment_readiness": shipment_readiness,
        "order_margin": order_margin,
        "supplier_delivery": supplier_delivery,
    }


def _command_suggestions(d: dict) -> list:
    f = _facts(d)
    missing = max(f["variants_total"] - f["bom_total"], 0)
    suggestions = [
        f"Which orders are due in {f['months'][0]}?" if f["months"] else "Which orders are due soon?",
        f"How many BOMs are missing? ({missing} of {f['variants_total']} variants)",
        "What is blocking shipment?",
        "Show the biggest data gap",
        f"How many fabric rolls are in stock? ({f['fabric_rolls']:,})",
    ]
    return suggestions


# ────────────────────────────────────────────────────────────────────────────
# State sync (derive -> upsert -> overlay)
# ────────────────────────────────────────────────────────────────────────────

def _sync(db: Session) -> dict:
    """Read live ERP, upsert risk/action state, and return the working context."""
    _ensure_db()
    d, status = _snapshot()
    live = bool(status.get("connected"))

    if live:
        try:
            built_risks = _build_risks(d)
            live_risk_keys = {r["risk_key"] for r in built_risks}
            # recommendations are only kept for risks that still exist live
            built_recs = [r for r in _build_recommendations(d)
                          if r["risk_key"] in live_risk_keys]
            for risk in built_risks:
                _upsert_risk(db, risk)
            for rec in built_recs:
                _upsert_action(db, rec)
            # PRUNE state rows whose live-derived key no longer exists (e.g. a
            # resolved risk that dropped out of _build_risks) so the dashboard
            # never shows a stale card after the ERP moves on. A risk/action is
            # KEPT if the action performed a real ERP write — otherwise the
            # write could never be rolled back.
            live_action_keys = {r["action_key"] for r in built_recs}
            all_actions = db.query(ActionStateModel).all()
            stale = [r for r in db.query(RiskStateModel).all()
                     if r.risk_key not in live_risk_keys]
            for r in stale:
                acts = [a for a in all_actions if a.risk_key == r.risk_key]
                if any((a.write_status or "") in ("created", "submitted") for a in acts):
                    continue  # keep the pair so the ERP write stays reversible
                for a in acts:
                    db.delete(a)
                db.delete(r)
            for a in all_actions:
                if a.action_key not in live_action_keys and (a.write_status or "") not in ("created", "submitted"):
                    db.delete(a)
            db.commit()
        except Exception:
            db.rollback()

    risk_rows = db.query(RiskStateModel).order_by(RiskStateModel.id).all()
    risk_ids = {r.risk_key: r.id for r in risk_rows}
    action_rows = db.query(ActionStateModel).order_by(ActionStateModel.id).all()

    # Active view: only OPEN risks are shown. A fixed (resolved) or dismissed
    # (rejected) risk leaves the board. Executed actions stay visible so the
    # ERP write remains rollback-able; rejected actions are hidden.
    risks = [r.to_dict() for r in risk_rows if (r.status or "open") == "open"]
    recs = [_action_dict(db, a) for a in action_rows if (a.approval_status or "") != "rejected"]

    return {"snapshot": d, "status": status, "live": live,
            "risks": risks, "recs": recs, "risk_ids": risk_ids}


def _upsert_risk(db: Session, risk: dict) -> RiskStateModel:
    row = db.query(RiskStateModel).filter(RiskStateModel.risk_key == risk["risk_key"]).first()
    if not row:
        row = RiskStateModel(risk_key=risk["risk_key"], status="open")
        db.add(row)
    row.risk_type = risk.get("risk_type") or ""
    row.severity = risk.get("severity") or "warning"
    row.title = risk.get("title") or ""
    row.payload = json.dumps({
        k: v for k, v in risk.items()
        if k not in ("risk_key", "risk_type", "severity", "title", "status")
    })
    db.commit()
    db.refresh(row)
    return row


def _upsert_action(db: Session, rec: dict) -> ActionStateModel:
    row = db.query(ActionStateModel).filter(ActionStateModel.action_key == rec["action_key"]).first()
    if not row:
        row = ActionStateModel(action_key=rec["action_key"], approval_status="pending")
        db.add(row)
    row.risk_key = rec.get("risk_key") or ""
    row.payload = json.dumps({
        "risk_title": _risk_title_for(db, rec.get("risk_key")),
        "action": rec.get("action"),
        "expected_impact": rec.get("expected_impact"),
        "responsible_team": rec.get("responsible_team"),
        "priority": rec.get("priority"),
    })
    db.commit()
    db.refresh(row)
    return row


def _risk_title_for(db: Session, risk_key: Optional[str]) -> str:
    if not risk_key:
        return ""
    row = db.query(RiskStateModel).filter(RiskStateModel.risk_key == risk_key).first()
    return row.title if row else ""


def _log(db, action_type, action_name, description, actor="Ops Manager", risk_title=None, approved=None):
    entry = AuditLogModel(
        action_type=action_type,
        action_name=action_name,
        description=description,
        actor=actor,
        risk_title=risk_title,
        approved=approved,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ────────────────────────────────────────────────────────────────────────────
# Order mapping
# ────────────────────────────────────────────────────────────────────────────

def _map_order(so: dict, today: str, by_so: dict = None, by_style: dict = None,
               ship_by_so: dict = None, ship_by_style: dict = None) -> dict:
    items = so.get("items") or []
    qty = int(sum(_num(i.get("qty")) for i in items))
    item_codes = sorted({(i.get("item_code") or "") for i in items if i.get("item_code")})
    styles = sorted({_style_of_item(c) for c in item_codes if c})
    delivery = so.get("delivery_date")
    status = "Overdue" if (delivery and delivery < today) else (so.get("status") or "Open")

    terms_text = _strip_html(so.get("terms"))
    source_terms = (so.get("custom_source_terms") or "").strip()
    planned, packed, packed_source = _order_packed(so.get("name"), styles, by_so or {}, by_style or {})
    packed_pct = int(round(packed / planned * 100)) if planned else 0
    # "sent" = the AUTHORITATIVE shipped figure (final packing list / commercial
    # invoice). The factory's packed figure above is internal and unverified.
    sent, sent_source = _order_shipped(so.get("name"), styles,
                                       ship_by_so or {}, ship_by_style or {})
    sent_pct = int(round(sent / qty * 100)) if qty else 0
    return {
        "id": so.get("name"),
        "order_number": so.get("name"),
        "buyer_name": so.get("customer"),
        "style": ", ".join(styles),
        "styles": styles,
        "item_codes": item_codes,
        "quantity": qty,
        "ship_date": delivery,
        "delivery_date": delivery,
        "status": status,
        "expected_margin_pct": None,
        "current_margin_pct": None,
        "created_at": so.get("transaction_date"),
        "updated_at": so.get("transaction_date"),
        # additive live fields
        "po_no": so.get("po_no"),
        "transaction_date": so.get("transaction_date"),
        "grand_total": _num(so.get("grand_total")),
        "per_delivered": _num(so.get("per_delivered")),
        "currency": so.get("currency"),
        "company": so.get("company"),
        "items_note": f"{len(items)} line(s) · {qty:,} pcs",
        # ── terms & conditions (per order, straight off the live Sales Order) ──
        "incoterm": so.get("incoterm") or "",
        "source_terms": source_terms,
        "payment_terms": so.get("payment_terms_template") or "",
        "advance_payment_status": so.get("advance_payment_status") or "",
        "terms_text": terms_text[:4000],
        "has_terms": bool(terms_text or source_terms),
        # ── source exception (photo sample, etc.) ──
        "source_exception": so.get("source_exception") or "",
        "is_sample": "sample" in (so.get("source_exception") or "").lower(),
        # ── order (PO) basis vs invoiced (shipped) basis ──
        "po_qty": int(so.get("po_qty") or qty),
        "so_qty": int(so.get("so_qty") or qty),
        "rate_usd": _num(so.get("rate_usd")),
        "order_basis_usd": _num(so.get("order_basis_usd") or so.get("grand_total")),
        "so_basis_usd": _num(so.get("so_basis_usd") or so.get("grand_total")),
        # ── ordered vs packed (FACTORY evidence — internal, unverified) ──
        "planned_qty": int(planned),
        "packed_qty": int(packed),
        "packed_pct": packed_pct,
        # "sales_order" = exact (production evidence names the order)
        # "style"       = estimated from styles only (may be shared between orders)
        "packed_source": packed_source,
        "packed_exact": packed_source == "sales_order",
        # ── ordered vs sent — the AUTHORITATIVE shipped figure, taken from the
        #    final packing list / commercial invoice (Garment Shipment Evidence),
        #    NOT from the factory's packed claim. ──
        "sent_qty": int(sent),
        "sent_pct": sent_pct,
        # "sales_order" = exact (a shipment names this order)
        # "style"       = estimated from styles only; "none" = no shipment evidence
        "sent_source": sent_source,
        "sent_exact": sent_source == "sales_order",
    }


def _order_rows(ctx: dict, search_query: str = "", limit: int = 50, offset: int = 0):
    today = _today_iso()
    snap = ctx["snapshot"]
    by_so, by_style = _so_production_index(snap)
    ship_by_so, ship_by_style = _shipment_indexes(snap)
    rows = [_map_order(so, today, by_so, by_style, ship_by_so, ship_by_style)
            for so in snap.get("sales_orders", [])]
    if search_query:
        needle = search_query.lower()
        rows = [r for r in rows if needle in json.dumps(r, default=str).lower()]
    total = len(rows)
    page = rows[offset:offset + limit] if limit else rows[offset:]
    return page, total


# ────────────────────────────────────────────────────────────────────────────
# Read functions
# ────────────────────────────────────────────────────────────────────────────

# ── Inbound-mail bridge (TEMPORARY) ─────────────────────────────────────────
# The KOGO middleware snapshots the callable function list at PUBLISH time, so a
# newly-added backend function is not callable via the project API until the app
# is re-published. The Inbox UI needs these inbound-mail functions; until the
# project is re-published it reaches them through the already-published
# `get_dashboard` with an `inbox_action` param (same return shape as the target).
# This is additive — a normal get_dashboard call (no inbox_action) is unchanged.
# Once re-published, the UI can call the dedicated functions directly and this
# block can be deleted.
_BRIDGE_ACTIONS = {
    "sync_inbox", "get_inbox", "get_inbox_summary", "get_mail_message",
    "dismiss_mail", "get_order_changes", "decide_order_change",
    "rollback_order_change",
    "submit_in_erp", "rollback_action",
    # Everything else that is in FUNCTIONS but frozen out of the platform allowlist
    # (it only refreshes on a re-publish). Bridging keeps the app fully functional
    # without one — remove these once the project is re-published.
    "get_recommendations", "get_erp_preview", "get_ai_next_steps", "run_monitor",
    # the ERP-model census + the shipment leg (2026-11-02) — callable through the
    # bridge until the project is re-published.
    "get_erp_model", "get_shipment_leg",
    # the WIP plan as a Gantt / calendar (2026-11-03) — bridged until the project is re-published
    "get_wip_plan", "get_wip_thread", "get_wip_analytics",
    # the planner's four actions on a plan: discuss · finalise · adjust · reject
    "wip_comment", "wip_finalise", "wip_adjust", "wip_reject",
    # the Plan tab's one write: the dates a planner settled on, applied in one go (2026-11-03)
    "wip_apply_plan",
    # intake (mail -> process), 2026-11-03
    "get_intake_queue", "get_intake", "get_intake_summary", "understand_intake",
    "simulate_intake", "approve_intake", "reject_intake", "edit_intake",
    "rollback_intake", "create_intake_ack", "dismiss_intake", "sync_intake_mail",
    "get_intake_document",
    # the chain (2026-11-03): the conversation, the reply, the pack it delivers
    "get_mail_chain", "send_chain_reply", "ingest_chain_pack", "set_intake_customer",
    "get_intake_options", "reopen_intake",
    # the buyer-enquiry register (2026-11-03)
    "get_buyer_inquiries", "get_buyer_inquiry", "update_buyer_inquiry", "sync_buyer_inquiries",
}


def get_dashboard(db: Session, inbox_action: str = "", bridge_action: str = "", **kwargs) -> dict:
    action = bridge_action or inbox_action
    if action:
        fn = FUNCTIONS.get(action)
        if action in _BRIDGE_ACTIONS and fn:
            return fn(db=db, **kwargs)
        return {"error": f"unknown bridge action '{action}'", "live": False,
                "source": SOURCE}
    ctx = _sync(db)
    audit = [a.to_dict() for a in
             db.query(AuditLogModel).order_by(desc(AuditLogModel.timestamp)).limit(40).all()]

    if not ctx["live"]:
        d = ctx["snapshot"]
        return {
            "kpis": [], "risks": [], "recommendations": [], "audit_log": audit,
            "buyer_orders": [], "charts": {k: [] for k in
                ("orders_at_risk", "material_readiness", "prod_plan_actual", "quality_trends",
                 "shipment_readiness", "order_margin", "supplier_delivery")},
            "factories": [], "date_options": [], "command_suggestions": [], "demo": False,
            "error": d.get("error"),
            "write_mode": writes.current_mode(),
            **_meta(ctx),
        }

    try:
        _monitor.maybe_run(db)                  # throttled proactive scan + push alerts
    except Exception:
        pass
    _ai.attach_to_dashboard(db, ctx["risks"])   # cached AI next-steps (no LLM call)
    f = _facts(ctx["snapshot"])
    rows, _total = _order_rows(ctx, limit=0)
    return {
        "kpis": _kpis(ctx["snapshot"]),
        "risks": ctx["risks"],
        "recommendations": ctx["recs"],
        "risk_summary": _rulebook.summarize(ctx["risks"]),
        "forecast": _forecast.build(),
        "migration_gaps": [{"gap_key": g.get("gap_key"), "process_area": g.get("process_area"),
                            "status": g.get("status"), "missing": g.get("missing_information")}
                           for g in _rulebook.live_facts().get("mdg", [])],
        "audit_log": audit,
        "buyer_orders": rows,
        "charts": _charts(ctx["snapshot"]),
        "factories": f["companies"],
        "date_options": f["months"],
        "command_suggestions": _command_suggestions(ctx["snapshot"]),
        # ── what the ERP actually holds today (2026-11-02) ─────────────────
        # The census is the honest answer to "is the dashboard reading the ERP
        # as it is?" — per process stage, which objects exist and how many rows
        # they carry, including the objects that are built but still empty.
        "erp_model": _census(),
        "shipment_leg": _shipment_leg_block(f),
        "demo": False,
        "write_mode": writes.current_mode(),
        **_meta(ctx),
    }


def get_buyer_orders(db: Session, search_query: str = "", limit: int = 50, offset: int = 0) -> dict:
    ctx = _sync(db)
    if not ctx["live"]:
        return {"buyer_orders": [], "total": 0, "total_count": 0, "offset": offset,
                "limit": limit, **_meta(ctx)}
    rows, total = _order_rows(ctx, search_query, limit, offset)
    return {"buyer_orders": rows, "total": len(rows), "total_count": total,
            "offset": offset, "limit": limit, **_meta(ctx)}


def get_risks(db: Session, search_query: str = "", limit: int = 50, offset: int = 0) -> dict:
    ctx = _sync(db)
    risks = ctx["risks"] if ctx["live"] else []
    if search_query:
        needle = search_query.lower()
        risks = [r for r in risks if needle in (r.get("title") or "").lower()
                 or needle in (r.get("risk_type") or "").lower()]
    page = risks[offset:offset + limit] if limit else risks[offset:]
    return {"risks": page, "total": len(page), "total_count": len(risks),
            "offset": offset, "limit": limit, **_meta(ctx)}


def get_recommendations(db: Session, search_query: str = "", limit: int = 50, offset: int = 0) -> dict:
    ctx = _sync(db)
    recs = ctx["recs"] if ctx["live"] else []
    if search_query:
        needle = search_query.lower()
        recs = [r for r in recs if needle in (r.get("action") or "").lower()
                or needle in (r.get("risk_title") or "").lower()]
    page = recs[offset:offset + limit] if limit else recs[offset:]
    return {"recommendations": page, "total": len(page), "total_count": len(recs),
            "offset": offset, "limit": limit, **_meta(ctx)}


def get_audit_log(db: Session, search_query: str = "", limit: int = 50, offset: int = 0) -> dict:
    _ensure_db()
    q = db.query(AuditLogModel)
    if search_query:
        q = q.filter(AuditLogModel.description.ilike(f"%{search_query}%"))
    total = q.count()
    rows = q.order_by(desc(AuditLogModel.timestamp)).offset(offset).limit(limit).all()
    status = erp.erp_status()
    return {
        "audit_log": [r.to_dict() for r in rows], "total": len(rows), "total_count": total,
        "offset": offset, "limit": limit,
        "live": bool(status.get("connected")), "source": SOURCE,
        "generated_at": _now_iso(), "connection": status,
    }


# ────────────────────────────────────────────────────────────────────────────
# Action previews — PREVIEW ONLY (no ERP write). The real, mode-gated ERP write
# lives in execute_action / run_action → _perform_write → writes.py.
# ────────────────────────────────────────────────────────────────────────────

# Flag for genuine preview/prompt responses (a preview never writes to the ERP).
READ_ONLY = {"erp_write": False, "mode": "read-only"}

_EMAIL_SLUGS = {
    "email_buyer_delivery", "email_supplier_trims", "email_buyer_statement",
    "request_test_rows", "request_bom_evidence", "request_evidence",
    "request_variance_approval",
}


def _channel_for(action_key: str, action_text: str, risk_title: str) -> str:
    slug = (action_key or "").split("::")[-1]
    if slug in _EMAIL_SLUGS:
        return "email"
    a = f"{action_text or ''} {risk_title or ''}".lower()
    if any(k in a for k in ("email", "notify", "ask cortex", "request from cortex")):
        return "email"
    return "erp"


def _not_found(action_id, db: Optional[Session] = None) -> dict:
    status = erp.erp_status()
    return {"error": f"Action {action_id} not found",
            "live": bool(status.get("connected")), "source": SOURCE,
            "generated_at": _now_iso(), "connection": status}


def _find_action(db: Session, action_id):
    _ensure_db()
    try:
        action_id = int(action_id)
    except Exception:
        return None
    return db.query(ActionStateModel).filter(ActionStateModel.id == action_id).first()


def _dt_slug(dt: str) -> str:
    """Frappe route slug for a DocType: 'Payment Request' -> 'payment-request'.

    Kept as a thin alias of :func:`erp.doctype_slug` so every caller shares one rule; nothing new should call this.
    """
    return erp.doctype_slug(dt)


def _erp_links(doctype: str, doc: str = "", count: int = 1) -> dict:
    """Direct ERP links so the UI can PIVOT the user into the ERP to finish (add details / submit).

    The address itself is built by :func:`erp.url_for` — the one place in this app that knows how an ERP page is
    spelled — so a screen never assembles a path and a change of desk route cannot leave an old link behind. A batch
    (>1 record) or an unknown record opens the LIST, which is where the person will find the record they mean.
    """
    if not doctype:
        return {}
    out = {"erp_doctype": doctype, "erp_list_url": erp.list_url(doctype)}
    out["erp_url"] = erp.list_url(doctype) if (count > 1 or not doc) else erp.doc_url(doctype, doc)
    return {k: v for k, v in out.items() if v}


def _action_dict(db: Session, row: ActionStateModel) -> dict:
    d = row.to_dict()
    rid = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
    d["risk_id"] = rid.id if rid else None
    try:
        n = len(json.loads(row.result_docs or "[]"))
    except Exception:
        n = 0
    d.update(_erp_links(row.result_doctype or "", row.result_doc or "", n))
    return d


def _risk_for_action(db: Session, row: ActionStateModel) -> dict:
    rr = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
    return rr.to_dict() if rr else {}


def _live_ctx(db: Session) -> dict:
    """Light context for previews: snapshot facts + buyer/supplier/company names.

    Cached briefly so repeated previews (e.g. a polling loop) do not re-read ~20
    doctypes and hydrate every Sales Order child table on each call.
    """
    now = time.monotonic()
    cached = _LIVE_CTX_CACHE["ctx"]
    if cached is not None and (now - _LIVE_CTX_CACHE["t"]) < _LIVE_CTX_TTL:
        return cached
    d, status = _snapshot()
    f = _facts(d)
    ctx = {"snapshot": d, "status": status, "live": bool(status.get("connected")), "facts": f}
    _LIVE_CTX_CACHE["ctx"] = ctx
    _LIVE_CTX_CACHE["t"] = now
    return ctx


def _email_preview(db: Session, row: ActionStateModel, ctx: dict, risk: dict) -> dict:
    """Build a professional, context-grounded email draft for the action.

    Generation lives in ``email_engine``: the communication intent is derived from
    the live context (not from an action slug), every value in the draft comes from
    a fact sheet built off the live ERP records, and the draft is checked by the
    grounding validator before it is returned. Nothing is ever sent, and no internal
    product branding appears inside the email.

    ``email_engine`` blocks (returns ``email: None`` + ``blocked``) when the ERP is
    unavailable, the recipient party is ambiguous, there is nothing to write about,
    or a total would span currencies.
    """
    f = ctx["facts"]
    action = row.modified_text or (json.loads(row.payload or "{}").get("action") or "")
    gen = email_engine.generate_email(f, risk, action, live=bool(ctx.get("live")))

    if gen.get("blocked"):
        b = gen["blocked"]
        return {
            "action_id": row.id,
            "channel": "email",
            "blocked": True,
            "blocked_reason": b["code"],
            "blocked_message": b["message"],
            "blocked_detail": b.get("detail") or [],
            "intent": b["message"],
            "comm_type": gen["intent"],
            "policy_version": gen["policy_version"],
            "grounding": gen["grounding"],
            **READ_ONLY,
        }

    to = gen["email"]["to"]
    return {
        "action_id": row.id,
        "channel": "email",
        "email": gen["email"],
        "intent": f"Send this email to {to}.",
        "comm_type": gen["intent"],
        "party_status": gen.get("party_status"),
        "policy_version": gen["policy_version"],
        "grounding": gen["grounding"],
        **READ_ONLY,
    }


def _erp_record(row: ActionStateModel, risk: dict, ctx: dict) -> dict:
    f = ctx["facts"]
    slug = (row.action_key or "").split("::")[-1]
    company = f["companies"][0] if f["companies"] else None
    today = _today_iso()
    so_name = f["so_names"][0] if f["so_names"] else None
    buyer = f["customers"][0] if f["customers"] else None
    bom_name = next((b.get("name") for b in f["boms"] if b.get("name")), None)
    variant = next((i.get("item") for i in f["boms"] if i.get("item")), None) or (
        f["so_item_codes"][0] if f["so_item_codes"] else None)
    trim_mr = next((m.get("name") for m in f["draft_mrs"] if m.get("name")), None)

    if slug == "create_boms":
        return {"doctype": "BOM", "fields": {
            "item": variant, "bom_type": "Manufacturing", "quantity": 1,
            "company": company, "is_active": 1,
            "remarks": f"{risk.get('style')} — {len(f['boms'])} of {f['variants_total']} variants have a BOM",
        }}
    if slug in ("request_bom_evidence",):
        return {"doctype": "Material Request", "fields": {
            "material_request_type": "Purchase", "company": company,
            "transaction_date": today, "schedule_date": risk.get("required_date") or today,
            "remarks": f"Per-size BOM evidence required — {risk.get('style')}",
        }}
    if slug == "raise_delivery_notes":
        return {"doctype": "Delivery Note", "fields": {
            "customer": buyer, "company": company, "posting_date": today,
            "sales_order": so_name,
            "remarks": f"{len(f['sos'])} orders To Deliver; {f['delivery_notes']} delivery notes exist",
        }}
    if slug in ("reinspection_fabric", "reinspection_s84", "request_test_rows"):
        failed = f["fails"][0] if f["fails"] else {}
        return {"doctype": "Quality Inspection", "fields": {
            "inspection_type": "Incoming", "reference_type": "Item",
            "item_code": variant,
            "report_date": today, "status": "Not Started",
            "sample_size": int(_num(failed.get("detailed_metrics_extracted")) or 1),
            "remarks": (f"Fabric code {failed.get('source_fabric_code') or risk.get('material')} "
                        f"marked {failed.get('inspection_result') or risk.get('defect_rate')}; "
                        f"{len(f['not_extracted'])} of {len(f['quality'])} packs not conclusively extracted"),
        }}
    if slug in ("review_shipment_variance", "request_variance_approval"):
        worst = max(f["shipments"],
                    key=lambda s: abs(_num(s.get("shipment_variance_qty")))) if f["shipments"] else {}
        # The write path raises a TASK (investigation), not a shipment document.
        return {"doctype": "Task", "fields": {
            "subject": f"Review shipment variance — {worst.get('name') or ''}".strip(),
            "priority": "High", "status": "Open", "exp_start_date": today,
            "description": (f"{len(f['shipments'])} records differ from order qty; worst "
                            f"{worst.get('item')} shipped {int(_num(worst.get('shipped_qty'))):,} vs "
                            f"ordered {int(_num(worst.get('sales_order_qty'))):,} pcs"),
        }}
    if slug == "close_quality_inspection":
        return {"doctype": "Quality Inspection", "fields": {
            "inspection_type": risk.get("inspection_stage") or "Incoming",
            "report_date": today,
            "remarks": risk.get("title"),
        }}
    if slug == "raise_trim_mrs":
        return {"doctype": "Material Request", "fields": {
            "material_request_type": "Purchase", "company": company,
            "transaction_date": today, "schedule_date": today,
            "remarks": f"Fabric requisition — {risk.get('style')} short {risk.get('required_qty')}",
        }}
    if slug in ("raise_work_orders", "register_bom_sizewise"):
        main_so = f["sos"][0] if f["sos"] else {}
        order_qty = int(sum(_num(i.get("qty")) for i in (main_so.get("items") or [])))
        return {"doctype": "Work Order", "fields": {
            "production_item": variant, "bom_no": bom_name,
            "qty": order_qty or None,
            "company": company, "planned_start_date": today, "status": "Draft",
            "remarks": (f"Only the test work order exists "
                        f"({f['work_orders'][0].get('name') if f['work_orders'] else 'none'}) "
                        f"for {len(f['sos'])} live orders"),
        }}
    if slug in ("submit_trim_mrs", "email_supplier_trims"):
        return {"doctype": "Material Request", "fields": {
            "material_request_type": "Purchase", "company": company,
            "transaction_date": today, "schedule_date": risk.get("required_date") or today,
            "custom_trim_requisition": trim_mr,
            "remarks": (f"{len(f['draft_mrs'])} trim Material Requests are Draft — "
                        f"no RFQ or Purchase Order raised"),
        }}
    if slug == "create_item_prices":
        return {"doctype": "Item Price", "fields": {
            "item_code": variant, "price_list": config.SELLING_PRICE_LIST,
            "price_list_rate": None, "currency": config.DEFAULT_CURRENCY,
            "remarks": f"{f['item_prices']} Item Price records exist — no selling price master",
        }}
    if slug in ("review_receivables", "email_buyer_statement"):
        return {"doctype": "Payment Entry", "fields": {
            "payment_type": "Receive", "party_type": "Customer", "party": buyer,
            "company": company, "posting_date": today,
            "paid_amount": round(f["si_total"], 2),
            "remarks": (f"{len(f['invoices'])} Overdue Sales Invoices (USD {f['si_total']:,.2f}), "
                        f"{f['payment_entries']} Payment Entries"),
        }}
    if slug == "request_evidence":
        # The write path raises a TASK asking for the missing evidence.
        return {"doctype": "Task", "fields": {
            "subject": f"Request missing trim specifications ({len(f['trim_exceptions'])} unmapped)",
            "priority": "High", "status": "Open", "exp_start_date": today,
            "remarks": (f"{len(f['open_gaps'])} open migration data gaps await Cortex evidence "
                        f"across {len({g.get('process_area') for g in f['open_gaps']})} process areas"),
        }}
    if slug == "assign_data_owners":
        return {"doctype": "Task", "fields": {
            "subject": f"Close {len(f['open_gaps'])} open migration data gaps",
            "priority": "High", "status": "Open", "exp_start_date": today,
            "description": "; ".join(sorted({g.get("process_area") for g in f["open_gaps"] if g.get("process_area")})[:6]) or None,
        }}
    # Fallback — still a real ERPNext doctype.
    return {"doctype": "Material Request", "fields": {
        "material_request_type": "Purchase", "company": company,
        "transaction_date": today, "schedule_date": risk.get("required_date") or today,
        "remarks": risk.get("title"),
    }}


def get_email_preview(db: Session, action_id: int) -> dict:
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    ctx = _live_ctx(db)
    risk = _risk_for_action(db, row)
    out = _email_preview(db, row, ctx, risk)
    out.update({"live": ctx["live"], "source": SOURCE,
                "generated_at": _now_iso(), "connection": ctx["status"]})
    return out


def get_erp_preview(db: Session, action_id: int) -> dict:
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    ctx = _live_ctx(db)
    risk = _risk_for_action(db, row)
    action = row.modified_text or (json.loads(row.payload or "{}").get("action") or "")
    record = _erp_record(row, risk, ctx)
    plan = writes.preview_write(row, {**ctx, "row": row})
    return {
        "action_id": row.id,
        "channel": "erp",
        "record": record,
        "write": plan,
        "inputs": plan.get("inputs") or {"fields": [], "values": {}, "missing": []},
        "intent": f"Cortex OS would draft a {record['doctype']} record: {action}",
        "live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx["status"],
        **READ_ONLY,
    }


def preview_action(db: Session, action_id: int) -> dict:
    """Auto-detect the channel (email vs erp) and return the matching preview."""
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    ctx = _live_ctx(db)
    risk = _risk_for_action(db, row)
    action = row.modified_text or (json.loads(row.payload or "{}").get("action") or "")
    channel = _channel_for(row.action_key, action, risk.get("title") or "")
    out = (_email_preview(db, row, ctx, risk) if channel == "email"
           else get_erp_preview(db, action_id))
    out.setdefault("action_id", row.id)
    out.update({"live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
                "connection": ctx["status"], **READ_ONLY})
    return out


# ────────────────────────────────────────────────────────────────────────────
# Decision overlay (local state + audit only — never the ERP)
# ────────────────────────────────────────────────────────────────────────────

def decide_action(db: Session, action_id: int, decision: str) -> dict:
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    decision = (decision or "").lower()
    if decision not in ("approve", "reject"):
        status = erp.erp_status()
        return {"error": "decision must be 'approve' or 'reject'",
                "live": bool(status.get("connected")), "source": SOURCE,
                "generated_at": _now_iso(), "connection": status}
    row.approval_status = "approved" if decision == "approve" else "rejected"
    db.commit()
    db.refresh(row)
    rec = _action_dict(db, row)
    # A rejection is a real decision: dismiss the risk so it (and its action)
    # leaves the active dashboard instead of silently staying on screen.
    if decision == "reject":
        rr = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
        if rr:
            rr.status = "dismissed"
            db.commit()
    _log(db, "approval", "Action approved" if decision == "approve" else "Action rejected",
         f"{rec['action']} — {decision} by Ops Manager", risk_title=rec["risk_title"],
         approved=decision)
    ctx = _live_ctx(db)
    return {
        "recommendation": rec, "decision": decision,
        "note": ("Action approved — it is now executable (creates a draft in the ERP)."
                 if decision == "approve" else
                 "Action rejected — the risk has been dismissed and removed from the active list."),
        "audit": [a.to_dict() for a in db.query(AuditLogModel)
                  .order_by(desc(AuditLogModel.timestamp)).limit(40).all()],
        "live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx["status"],
        "erp_write": False, "mode": writes.current_mode(),
    }


def modify_action(db: Session, action_id: int, new_text: str) -> dict:
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    row.modified_text = new_text
    row.approval_status = "modified"
    db.commit()
    db.refresh(row)
    rec = _action_dict(db, row)
    _log(db, "modify", "Action modified", f"Action updated to: {new_text}",
         risk_title=rec["risk_title"])
    ctx = _live_ctx(db)
    return {
        "recommendation": rec,
        "audit": [a.to_dict() for a in db.query(AuditLogModel)
                  .order_by(desc(AuditLogModel.timestamp)).limit(40).all()],
        "live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx["status"],
        "erp_write": False, "mode": writes.current_mode(),
    }


def _perform_write(db: Session, row: ActionStateModel, ctx: dict, inputs: Optional[dict] = None) -> dict:
    """Run the real (mode-gated) ERP write for an action and persist the outcome.

    Idempotent and drafts-only — see ``writes.py``. Never resolves the risk unless
    the ERP record was actually created."""
    risk = _risk_for_action(db, row)
    result = writes.execute(row, {
        "db": db,                       # one write envelope: per-record audit_log rows
        "actor": "Ops Manager",
        "facts": ctx["facts"],
        "risk": risk,
        "row": row,
        "inputs": inputs or {},
        "action": row.modified_text or (json.loads(row.payload or "{}").get("action") or ""),
    })
    status = result.get("status")
    if status == "created":
        row.result_doctype = result.get("doctype")
        prev = []
        if row.result_docs:
            try:
                prev = json.loads(row.result_docs) or []
            except Exception:
                prev = []
        merged = list(dict.fromkeys(prev + (result.get("docs") or [])))
        row.result_docs = json.dumps(merged)
        row.result_doc = merged[0] if merged else result.get("doc")
        row.write_op = result.get("op") or "create"
        row.write_status = "created"
        row.write_error = ("; ".join(result.get("errors") or [])) or None
        row.approval_status = "executed"
        row.executed_at = datetime.now()
    elif (row.write_status or "") in ("created", "submitted") and row.result_doc:
        # A re-run must NEVER downgrade a successful write: the ERP record still
        # exists, and losing the marker would also lose the rollback link.
        pass
    elif status == "already_done":
        row.write_status = "already_done"
        row.write_error = result.get("reason")
    elif status == "failed":
        row.write_status = "failed"
        row.write_error = result.get("reason")
    else:
        row.write_status = "blocked"
        row.write_error = result.get("reason")
    db.commit()
    db.refresh(row)
    # a write changes the ERP — drop the cached preview snapshot AND the
    # detection engine's fact cache so the next read reflects the change.
    _LIVE_CTX_CACHE["ctx"] = None
    try:
        _rulebook.invalidate()
    except Exception:
        pass
    return result


def execute_action(db: Session, action_id: int, inputs: Optional[dict] = None) -> dict:
    """Execute an approved action — performs a REAL ERP write (drafts only)."""
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    if row.approval_status not in ("approved", "executed"):
        status = erp.erp_status()
        return {"error": "Action must be approved before it can be executed",
                "recommendation": _action_dict(db, row),
                "live": bool(status.get("connected")), "source": SOURCE,
                "generated_at": _now_iso(), "connection": status,
                "write_mode": writes.current_mode(),
                "erp_write": False, "mode": writes.current_mode()}

    ctx = _live_ctx(db)
    result = _perform_write(db, row, ctx, inputs)
    rec = _action_dict(db, row)
    created = result.get("status") == "created"

    if created:
        risk = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
        if risk:
            risk.status = "resolved"
            db.commit()
        _log(db, "execute", "Action executed",
             f"Created {result.get('doctype')} {result.get('doc')} — {rec['action']}",
             risk_title=rec["risk_title"])
    else:
        _log(db, "execute", "Action not executed",
             f"{result.get('status')}: {result.get('reason')} — {rec['action']}",
             risk_title=rec["risk_title"])

    ctx2 = _sync(db)
    out = {
        "recommendation": rec,
        "write": result,
        "risks": ctx2["risks"],
        "dashboard": get_dashboard(db),
        "audit": [a.to_dict() for a in db.query(AuditLogModel)
                  .order_by(desc(AuditLogModel.timestamp)).limit(40).all()],
        "erp_write": bool(created),
        "mode": writes.current_mode(),
        "live": ctx2["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx2["status"],
    }
    if not created:
        out["error"] = result.get("reason") or "the ERP write was not performed"
        out["note"] = f"Nothing was written to the ERP ({result.get('status')})."
    else:
        out["note"] = f"Created {result.get('doctype')} {result.get('doc')} in the ERP (draft)."
    return out


def rollback_action(db: Session, action_id: int) -> dict:
    """Delete the ERP record this action created and reopen its risk."""
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    title = _risk_title_for(db, row.risk_key)
    result = writes.rollback(row)
    if result.get("status") == "rolled_back":
        doc = f"{result.get('doctype')} [{', '.join(result.get('docs') or [])}]"
        row.write_status = "rolled_back"
        row.result_doc = None
        row.result_docs = None
        row.result_doctype = None
        row.write_op = None
        row.approval_status = "approved"
        row.executed_at = None
        db.commit()
        risk = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
        if risk:
            risk.status = "open"
            db.commit()
        _log(db, "rollback", "Action rolled back", f"Deleted {doc}", risk_title=title)
    ctx = _live_ctx(db)
    return {
        "rollback": result,
        "recommendation": _action_dict(db, row),
        "audit": [a.to_dict() for a in db.query(AuditLogModel)
                  .order_by(desc(AuditLogModel.timestamp)).limit(40).all()],
        "erp_write": False,
        "mode": writes.current_mode(),
        "live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx["status"],
    }


# ────────────────────────────────────────────────────────────────────────────
# Submit-in-ERP — confirm (docstatus 0 -> 1) the draft(s) an action created.
# The Tower only ever CREATES drafts; this is the explicit human step that
# confirms them in the ERP. Idempotent (already-submitted docs are skipped).
# ────────────────────────────────────────────────────────────────────────────
def submit_in_erp(db: Session, action_id: int = 0, all: int = 0) -> dict:
    _ensure_db()
    q = db.query(ActionStateModel)
    if action_id:
        rows = q.filter(ActionStateModel.id == int(action_id)).all()
    elif all:
        rows = q.filter(ActionStateModel.write_status == "created").all()
    else:
        return {"ok": False, "error": "action_id or all required", "submitted": [],
                "skipped": [], "errors": [], "count": 0, "live": True,
                "source": SOURCE, "write_mode": writes.current_mode()}

    submitted, skipped, errors, repairs = [], [], [], []
    doctypes = set()
    for row in rows:
        try:
            names = json.loads(row.result_docs or "[]") or []
        except Exception:
            names = []
        if not names and row.result_doc:
            names = [row.result_doc]
        doctype = row.result_doctype
        if not doctype or not names:
            skipped.append({"action_id": row.id, "reason": "this action created no draft"})
            continue
        doctypes.add(doctype)
        for name in names:
            doc = erp.erp_doc(doctype, name) or {}
            if not doc:
                # A companion record of a DIFFERENT doctype (e.g. the finished-goods
                # stock receipt the builder already submitted). Resolve it by name.
                alt = next((c for c in ("Stock Entry", "Material Request", "Payment Request",
                                        "Task", "Quality Inspection", "Work Order", "BOM")
                            if erp.erp_doc(c, name)), None)
                if alt:
                    doctypes.add(alt)
                    d2 = erp.erp_doc(alt, name) or {}
                    if str(d2.get("docstatus")) == "1":
                        skipped.append(name)
                    else:
                        rep = writes.submit_with_repair(alt, name, d2.get("company"))
                        if rep["ok"]:
                            submitted.append(name)
                        else:
                            errors.append(f"{name}: {rep['error']}")
                        repairs.extend(rep["repaired"])
                    continue
                errors.append(f"{name}: document not found")
                continue
            if str(doc.get("docstatus")) == "1":
                skipped.append(name)
                continue
            rep = writes.submit_with_repair(doctype, name, doc.get("company"))
            if rep["ok"]:
                submitted.append(name)
            else:
                errors.append(f"{name}: {rep['error']}")
            repairs.extend(rep["repaired"])
        if submitted:
            row.write_status = "submitted"
        db.commit()

    _log(db, "execute", "submit_in_erp",
         f"Submitted {len(submitted)} record(s) to the ERP" + (f"; errors: {errors}" if errors else ""))
    return {"ok": bool(submitted), "doctype": ", ".join(sorted(doctypes)) or None,
            "submitted": submitted, "skipped": skipped, "errors": errors,
            "repaired": repairs,
            "count": len(submitted), "write_mode": writes.current_mode(),
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def run_action(db: Session, action_id: int, inputs: Optional[dict] = None) -> dict:
    """End-to-end execute: intent + data used + the REAL ERP write result."""
    row = _find_action(db, action_id)
    if not row:
        return _not_found(action_id, db)
    ctx = _live_ctx(db)
    risk = _risk_for_action(db, row)
    payload = json.loads(row.payload or "{}")
    action = row.modified_text or payload.get("action") or ""
    channel = _channel_for(row.action_key, action, risk.get("title") or "")
    f = ctx["facts"]

    data_used = {
        "action_id": row.id,
        "action_key": row.action_key,
        "risk": risk or None,
        "action": action,
        "expected_impact": payload.get("expected_impact"),
        "responsible_team": payload.get("responsible_team"),
        "priority": payload.get("priority"),
        "channel": channel,
        "live_evidence": {
            "sales_orders": len(f["sos"]),
            "order_book_usd": f["order_book"],
            "bom_coverage": f"{f['bom_total']}/{f['variants_total']}",
            "fabric_rolls": f["fabric_rolls"],
            "delivery_notes": f["delivery_notes"],
            "draft_trim_mrs": len(f["draft_mrs"]),
            "open_data_gaps": len(f["open_gaps"]),
        },
    }

    result = _perform_write(db, row, ctx, inputs)
    created = result.get("status") == "created"

    if created:
        rr = db.query(RiskStateModel).filter(RiskStateModel.risk_key == row.risk_key).first()
        if rr:
            rr.status = "resolved"
            db.commit()
        _log(db, "execute", "Action executed (run)",
             f"Created {result.get('doctype')} {result.get('doc')} — {action}",
             risk_title=risk.get("title"))
    else:
        _log(db, "execute", "Action not executed (run)",
             f"{result.get('status')}: {result.get('reason')} — {action}",
             risk_title=risk.get("title"))

    return {
        "intent": f"Execute: {action}",
        "data_used": data_used,
        "write": result,
        "result": ({"status": "success", "channel": channel,
                    "note": f"Created {result.get('doctype')} {result.get('doc')} in the ERP (draft)."}
                   if created else
                   {"status": result.get("status"), "channel": channel,
                    "note": result.get("reason"), "error": result.get("reason")}),
        "recommendation": _action_dict(db, row),
        "erp_write": bool(created),
        # Direct ERP link to the record just created, so the UI can send the user
        # straight there to do the final confirmation (draft -> submitted).
        **(_erp_links(result.get("doctype") or "", result.get("doc") or "",
                      len(result.get("docs") or [])) if created else {}),
        "mode": writes.current_mode(),
        "live": ctx["live"], "source": SOURCE, "generated_at": _now_iso(),
        "connection": ctx["status"],
    }


# ────────────────────────────────────────────────────────────────────────────
# Ask KOGO — deterministic analysis over live ERP numbers
# ────────────────────────────────────────────────────────────────────────────

# RETIRED — the long-prompt ask path was replaced by the chat-module (see CHAT MODULE block).
# Kept for reference only; renamed so it can never bind the public name `ask_kogo`.
def _ask_kogo_legacy(db: Session, question: str = "", context: dict = None) -> dict:
    ctx = _live_ctx(db)
    f = ctx["facts"]
    q = (question or "").lower()

    if not ctx["live"]:
        return {
            "answer": ("I can't reach KOGO ERP right now, so I have no live numbers to analyse. "
                       "Check the ERP connection and ask again — the dashboard will show live "
                       "orders, BOM coverage, data gaps and shipments once the link is back."),
            "related": [],
            "live": False, "source": SOURCE, "generated_at": _now_iso(),
            "connection": ctx["status"],
        }

    def _match(*keys):
        return any(k in q for k in keys)

    missing = max(f["variants_total"] - f["bom_total"], 0)
    risk_rows = db.query(RiskStateModel).order_by(RiskStateModel.id).all()
    open_titles = [r.title for r in risk_rows if r.status == "open"]
    related = open_titles[:5]

    def _reply(text, rel=None):
        return {"answer": text, "related": rel if rel is not None else related,
                "live": True, "source": SOURCE, "generated_at": _now_iso(),
                "connection": ctx["status"]}

    # Order book / orders by month / at risk / due
    if _match("order", "due", "q1", "q2", "book", "at risk", "buyer"):
        per_month = ", ".join(
            f"{m}: {sum(1 for s in f['sos'] if (s.get('delivery_date') or '').startswith(m))}"
            for m in f["months"]
        )
        return _reply(
            f"There are {len(f['sos'])} open Sales Orders worth USD {f['order_book']:,.2f} "
            f"({int(f['units']):,} pcs) for {f['customers'][0] if f['customers'] else 'the buyer'}, "
            f"to be delivered {f['earliest_delivery']} → {f['latest_delivery']}. "
            f"Orders by delivery month — {per_month}. "
            f"Every order is still 'To Deliver' with {f['delivery_notes']} Delivery Notes raised and "
            f"{f['payment_entries']} Payment Entries, so the entire book is operationally open.",
            [r.title for r in risk_rows if r.risk_key in ("NO_DELIVERY_NOTES", "NO_PAYMENT_ENTRY")],
        )

    # BOM / variants / coverage
    if _match("bom", "variant", "coverage", "size", "missing"):
        return _reply(
            f"Only {f['bom_total']} of {f['variants_total']} finished-garment variants have a BOM — "
            f"{missing} are missing ({f['coverage_pct']}% coverage), and all {f['bom_total']} existing "
            f"BOMs are Size S only. Sourcing evidence: {f['fabric_rolls']:,} fabric rolls in stock and "
            f"{f['trim_reqs']} trim requisitions, but {len(f['draft_mrs'])} Material Requests are still "
            f"Draft with no RFQ or Purchase Order raised.",
            [r.title for r in risk_rows if r.risk_key in ("BOM_COVERAGE", "TRIM_MR_DRAFT")],
        )

    # Shipment / blocking
    if _match("ship", "block", "delivery note", "dispatch", "variance"):
        ship_via = sorted({s.get("ship_via") for s in f["shipments"] if s.get("ship_via")})
        return _reply(
            f"Shipment is blocked by paperwork: {len(f['sos'])} orders are 'To Deliver' but "
            f"{f['delivery_notes']} Delivery Notes exist. On top of that, all {len(f['shipments'])} "
            f"shipment records differ from their order quantity ("
            f"{len(f['nonzero_var'])} non-zero variances). Recorded ship-via modes: "
            f"{', '.join(ship_via) if ship_via else 'none'}. "
            f"Highest-priority fix: raise the Delivery Notes and get the variance approved.",
            [r.title for r in risk_rows if r.risk_key in ("NO_DELIVERY_NOTES", "SHIPMENT_VARIANCE")],
        )

    # Data gaps
    if _match("gap", "migration", "evidence", "cortex"):
        top = f["open_gaps"][0] if f["open_gaps"] else {}
        areas = sorted({g.get("process_area") for g in f["open_gaps"] if g.get("process_area")})
        return _reply(
            f"{len(f['gaps'])} migration data gaps are recorded and {len(f['open_gaps'])} are awaiting "
            f"Cortex evidence across {len(areas)} process areas ({', '.join(areas[:6])}… ). "
            f"Biggest single gap: {top.get('gap_key')} — {top.get('missing_information')} "
            f"Affects: {str(top.get('affected_records') or '').rstrip('.')}.",
            [r.title for r in risk_rows if r.risk_key == "MDG_OPEN"],
        )

    # Quality
    if _match("quality", "fabric", "fail", "inspection", "defect"):
        fails = ", ".join(f"{q['source_fabric_code']} ({q['inspection_result']})" for q in f["quality"])
        return _reply(
            f"{len(f['quality'])} fabric quality packs were recorded. Results: "
            f"{len(f['fails'])} FAIL, "
            f"{len([q for q in f['quality'] if (q.get('inspection_result') or '').lower() == 'pass'])} pass, "
            f"{len(f['not_extracted'])} not conclusively extracted. Detail — {fails}. "
            f"The FAIL is on fabric {(f['fails'][0].get('source_fabric_code') if f['fails'] else 'n/a')}, "
            f"used by a live style, so it must be re-inspected before shipment.",
            [r.title for r in risk_rows if r.risk_key == "FABRIC_QUALITY_FAIL"],
        )

    # Margin / cost / finance
    if _match("margin", "cost", "finance", "receivable", "payment", "invoice", "price"):
        cm = [b for b in f["boms"] if _num(b.get("op_cm_usd"))]
        over = [b for b in cm if _num(b.get("op_total_operation_cost_usd")) > _num(b.get("op_cm_usd"))]
        return _reply(
            f"Margin control is limited by missing masters: {f['item_prices']} Item Price records exist, "
            f"so selling prices and payment terms cannot be verified. {len(f['invoices'])} Sales Invoices "
            f"(USD {f['si_total']:,.2f}) are posted and Overdue with {f['payment_entries']} Payment Entries. "
            f"Across {len(cm)} BOMed styles, cut-and-make cost is USD {sum(_num(b.get('op_cm_usd')) for b in cm):,.2f} "
            f"versus an achieved operation cost of "
            f"USD {sum(_num(b.get('op_total_operation_cost_usd')) for b in cm):,.2f} "
            f"({len(over)} style(s) already over the cut-and-make target).",
            [r.title for r in risk_rows if r.risk_key in ("NO_ITEM_PRICE", "NO_PAYMENT_ENTRY")],
        )

    # Sourcing / supplier / purchase
    if _match("sourc", "supplier", "purchase", "receipt", "rfq", "po "):
        pos = [p for p in f["purchase_orders"] if str(p.get("docstatus")) != "2"]
        suppliers = sorted({p.get("supplier") for p in pos if p.get("supplier")})
        return _reply(
            f"Sourcing pipeline: {len(pos)} submitted Purchase Orders and {len(f['purchase_receipts'])} "
            f"Purchase Receipts across {len(suppliers)} suppliers ({', '.join(suppliers)}). "
            f"However {len(f['draft_mrs'])} of {len(f['mrs'])} Material Requests are still Draft and "
            f"{f['trim_reqs']} trim requisitions are unactioned, so no new RFQ or PO covers the trim demand "
            f"for the {len(f['sos'])} live orders.",
            [r.title for r in risk_rows if r.risk_key == "TRIM_MR_DRAFT"],
        )

    # Management brief
    if _match("brief", "summary", "management", "overview", "status"):
        return _reply(
            f"Live management brief — {len(f['sos'])} open Sales Orders, order book "
            f"USD {f['order_book']:,.2f} ({int(f['units']):,} pcs), delivery window "
            f"{f['earliest_delivery']} → {f['latest_delivery']}. "
            f"BOM coverage {f['bom_total']}/{f['variants_total']} variants ({f['coverage_pct']}%), "
            f"all Size S only. {f['fabric_rolls']:,} fabric rolls in stock, but "
            f"{len(f['draft_mrs'])} trim Material Requests are Draft, {f['delivery_notes']} Delivery Notes "
            f"exist and {len(f['open_gaps'])} migration data gaps await Cortex evidence. "
            f"Quality: {len(f['fails'])} fabric pack FAIL, {len(f['not_extracted'])} inconclusive. "
            f"Finance: {len(f['invoices'])} invoices (USD {f['si_total']:,.2f}) unpaid, {f['payment_entries']} "
            f"Payment Entries. Focus: BOM coverage, Delivery Notes, and the trim Material Requests.",
            related,
        )

    # Default — overall live posture
    return _reply(
        f"I read {len(f['sos'])} open Sales Orders worth USD {f['order_book']:,.2f} from KOGO ERP. "
        f"The three critical issues are: (1) BOM coverage is {f['bom_total']}/{f['variants_total']} "
        f"variants ({f['coverage_pct']}%), (2) {len(f['sos'])} orders are 'To Deliver' with "
        f"{f['delivery_notes']} Delivery Notes raised, and (3) fabric pack "
        f"{(f['fails'][0].get('source_fabric_code') if f['fails'] else 'n/a')} FAILED quality with "
        f"{len(f['not_extracted'])} packs not conclusively extracted. "
        f"{len(f['open_gaps'])} migration data gaps remain open. "
        f"Ask me about orders, BOMs, shipments, quality, sourcing, finance or data gaps for detail.",
        related,
    )


# ────────────────────────────────────────────────────────────────────────────
# Registry + CLI
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
# Fabric & Price Intelligence
#
# Joins FOUR live ERP sources onto one row per STYLE and applies explicit
# detection rules:
#   consumption : BOM Item.stock_qty        (the ERP master)
#                 Internal Costing Evidence.avg_consumption_yard  (quoted)
#                 Client Purchase Order Evidence.fabric_yield_yd (buyer PO)
#   buying rate : Purchase Order Item.rate  (USD, per the PO's own UOM)
#   selling     : Sales Order Item.rate + Client Purchase Order Evidence.unit_price_usd
#   cost build  : Internal Costing Evidence (fabric/cm/trim/wash/overhead/…)
#
# Everything is normalised to YARD for consumption and USD/YARD for rate, so a
# unit mix-up surfaces as a flag instead of a wrong number.
# ────────────────────────────────────────────────────────────────────────────

FAB_PREFIX = "FAB-"
M_PER_YD = 1.0 / 0.9144          # 1 metre = 1.0936133 yard

CONS_WARN_PCT = 5.0              # consumption spread  -> warning
CONS_CRIT_PCT = 15.0             # consumption spread  -> critical
RATE_WARN_PCT = 5.0              # buying rate vs quoted rate -> warning
MARGIN_WARN_PCT = 15.0           # gross margin floor


def _to_yard(qty, uom):
    """Normalise a quantity to YARD. Returns ``(yards, known_uom)``."""
    u = (uom or "").strip().lower()
    if u.startswith(("yard", "yd")):
        return _num(qty), True
    if u.startswith("met"):
        return _num(qty) * M_PER_YD, True
    return _num(qty), False


def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _r2(v):
    return None if v is None else round(v, 2)


def _r4(v):
    return None if v is None else round(v, 4)


def _flag(style, ftype, severity, title, detail, impact=None):
    return {"style": style, "type": ftype, "severity": severity, "title": title,
            "detail": detail, "impact_usd": _r2(impact)}


def get_fabric_intelligence(db: Session) -> dict:
    """Fabric consumption vs ordered qty vs cost vs price — one live row per style.

    Read-only. Degrades to empty rows + ``live: false`` when the ERP is down.
    """
    _ensure_db()
    ctx = _snapshot()
    d, status = ctx if isinstance(ctx, tuple) else (ctx, erp.erp_status())
    meta = _meta({"live": bool((status or {}).get("connected")),
                  "status": status or {"connected": False, "base": "", "error": "erp_unavailable"}})

    if not d.get("sales_orders"):
        out = {"summary": {}, "rows": [], "flags": [], "charts": {}, "live": False}
        out.update(meta)
        if d.get("error"):
            out["error"] = d["error"]
        return out

    # ---- variant (FG item) -> style template ---------------------------------
    variant_style = {}
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("variant_of"):
            variant_style[it["name"]] = it["variant_of"]

    # ---- 1. orders: qty + selling price per style ----------------------------
    style_order = {}
    for so in d.get("sales_orders") or []:
        for i in so.get("items") or []:
            code = str(i.get("item_code") or "")
            style = variant_style.get(code) or _style_of_item(code)
            if not style:
                continue
            row = style_order.setdefault(style, {"qty": 0.0, "value": 0.0, "so": [], "pos": []})
            q = _num(i.get("qty"))
            row["qty"] += q
            row["value"] += _num(i.get("amount")) or (q * _num(i.get("rate")))
            if so.get("name") not in row["so"]:
                row["so"].append(so.get("name"))
            if so.get("po_no") and so.get("po_no") not in row["pos"]:
                row["pos"].append(so.get("po_no"))

    # ---- 2. BOM fabric consumption (ERP master) ------------------------------
    bom_cons = {}          # style -> [ {fabric, yard, metre, uom, bom} ]
    for b in d.get("boms") or []:
        if not isinstance(b, dict) or _num(b.get("docstatus")) != 1:
            continue
        style = _style_of_item(b.get("item"))
        doc = erp.erp_doc("BOM", b.get("name"))
        for i in doc.get("items") or []:
            code = str(i.get("item_code") or "")
            if not code.startswith(FAB_PREFIX):
                continue
            yard_from_qty, uom_ok = _to_yard(i.get("qty"), i.get("uom"))
            yard_stock, _ = _to_yard(i.get("stock_qty"), i.get("stock_uom"))
            bom_cons.setdefault(style, []).append({
                "fabric": code,
                "yard": yard_from_qty if uom_ok else yard_stock,
                "metre": _num(i.get("stock_qty")),
                "uom": i.get("uom"),
                "stock_uom": i.get("stock_uom"),
                "bom": b.get("name"),
            })

    # ---- 3. Internal Costing Evidence (quoted consumption + cost build) ------
    costing = {}           # style -> dict
    costing_row = erp.erp_get("Internal Costing Evidence",
                              fields=["name", "source_sheet"], limit=0)
    for rec in costing_row:
        doc = erp.erp_doc("Internal Costing Evidence", rec.get("name"))
        fallback = None
        for line in doc.get("lines") or []:
            style = line.get("style_no") or None
            desc = str(line.get("source_description") or "")
            if not style:
                # lining / component rows carry no style — keep as fallback
                if fallback is None:
                    fallback = line
                continue
            c = costing.setdefault(style, {"ice": rec.get("name"), "lines": []})
            c["lines"].append(line)
        if fallback is not None:
            for style, c in costing.items():
                if c.get("ice") == rec.get("name") and not c.get("lining"):
                    c["lining"] = fallback

    # ---- 4. Client Purchase Order Evidence (buyer yield + allowed price) -----
    client_po = {}
    for x in erp.erp_get("Client Purchase Order Evidence",
                         fields=["name", "po_number", "style_no", "order_qty", "unit_price_usd",
                                 "fabric_price_usd", "fabric_yield_yd", "fabric_content",
                                 "fabric_gsm", "fabric_vendor_ref"], limit=0):
        style = x.get("style_no")
        if not style:
            continue
        r = client_po.setdefault(style, {"po_numbers": [], "qty": 0, "unit_price_usd": None,
                                         "fabric_price_usd": None, "yield_yd": None,
                                         "gsm": None, "vendor": None, "content": None})
        r["po_numbers"].append(x.get("po_number"))
        r["qty"] += int(_num(x.get("order_qty")))
        if x.get("unit_price_usd") is not None:
            r["unit_price_usd"] = _num(x.get("unit_price_usd"))
        if x.get("fabric_price_usd") is not None:
            r["fabric_price_usd"] = _num(x.get("fabric_price_usd"))
        if _num(x.get("fabric_yield_yd")) > 0:
            r["yield_yd"] = _num(x.get("fabric_yield_yd"))
        r["gsm"] = x.get("fabric_gsm") or r["gsm"]
        r["vendor"] = x.get("fabric_vendor_ref") or r["vendor"]
        r["content"] = x.get("fabric_content") or r["content"]

    # ---- 5. Purchase Orders: actual buying rate per fabric -------------------
    buy = {}               # fabric item -> {usd_per_yd, usd_per_m, uom, po, supplier}
    for po in d.get("purchase_orders") or []:
        if not isinstance(po, dict) or _num(po.get("docstatus")) != 1:
            continue
        doc = erp.erp_doc("Purchase Order", po.get("name"))
        for i in doc.get("items") or []:
            code = str(i.get("item_code") or "")
            if not code.startswith(FAB_PREFIX):
                continue
            rate = _num(i.get("rate"))
            uom = (i.get("uom") or "").strip().lower()
            if rate <= 0:
                continue
            per_yd = rate / M_PER_YD if uom.startswith("met") else rate
            per_m = rate * M_PER_YD if uom.startswith(("yard", "yd")) else rate
            prev = buy.get(code)
            # keep the most recent / largest purchase as the reference
            if prev is None or _num(i.get("qty")) > prev.get("qty", 0):
                buy[code] = {"usd_per_yd": per_yd, "usd_per_m": per_m, "uom": i.get("uom"),
                             "qty": _num(i.get("qty")), "po": po.get("name"),
                             "supplier": po.get("supplier")}

    # ---- 6. build one intelligence row per style -----------------------------
    rows, flags = [], []
    styles = sorted(set(list(style_order) + list(bom_cons) + list(costing) + list(client_po)))

    for style in styles:
        order = style_order.get(style) or {}
        order_qty = _num(order.get("qty"))
        order_value = _num(order.get("value"))
        sell_price = (order_value / order_qty) if order_qty else None

        bom_lines = bom_cons.get(style) or []
        shell = max(bom_lines, key=lambda x: _num(x.get("yard"))) if bom_lines else None
        cons_bom = _num(shell.get("yard")) if shell else None
        req_unit_m = sum(_num(l.get("metre")) for l in bom_lines) if bom_lines else None
        fabric_item = shell.get("fabric") if shell else None

        ice = costing.get(style) or {}
        ice_lines = ice.get("lines") or []
        ice_main = None
        for l in ice_lines:
            if "lining" not in str(l.get("source_description") or "").lower():
                ice_main = l
                break
        ice_main = ice_main or (ice_lines[0] if ice_lines else None)
        cons_cost = _num(ice_main.get("avg_consumption_yard")) if ice_main else None
        cons_cost_3pct = _num(ice_main.get("avg_consumption_plus_3pct_yard")) if ice_main else None
        quote_rate_yd = _num(ice_main.get("source_fabric_usd_per_yard")) if ice_main else None
        desc = (ice_main or {}).get("source_description")

        cpo = client_po.get(style) or {}
        cons_cpo = _num(cpo.get("yield_yd")) if cpo.get("yield_yd") else None
        po_price = cpo.get("unit_price_usd")
        allowed_fabric_usd = cpo.get("fabric_price_usd")

        b = buy.get(fabric_item) if fabric_item else None
        buy_yd = b.get("usd_per_yd") if b else None
        buy_m = b.get("usd_per_m") if b else None

        # ---- consumption consensus & spread ---------------------------------
        avail = [(n, v) for n, v in (("bom", cons_bom), ("costing", cons_cost), ("client_po", cons_cpo))
                 if v and v > 0]
        consensus = _median([v for _, v in avail])
        spread = None
        if consensus and len(avail) >= 2:
            spread = (max(v for _, v in avail) - min(v for _, v in avail)) / consensus * 100.0

        # ---- cost build-up (per garment, USD) --------------------------------
        g = lambda k: _num((ice_main or {}).get(k))
        cm, trim, wash = g("source_cm_usd"), g("source_trim_usd"), g("source_wash_usd")
        addl = g("source_additional_usd")
        overhead, reject = g("source_overhead_usd"), g("source_rejection_usd")
        finance, deprec = g("source_finance_usd"), g("source_depreciation_usd")
        ice_total_cost = g("source_actual_cost_usd")
        ice_quoted_price = g("source_confirmed_or_quoted_price_usd")

        fabric_at_bom = (cons_bom * buy_yd) if (cons_bom and buy_yd) else None
        fabric_at_costing = (cons_cost * buy_yd) if (cons_cost and buy_yd) else None
        fabric_at_allowed = allowed_fabric_usd
        conversion = cm + trim + wash + addl
        bom_basis_cost = (fabric_at_bom + conversion + overhead + reject + finance + deprec) \
            if fabric_at_bom is not None else None
        costing_basis_cost = (fabric_at_costing + conversion + overhead + reject + finance + deprec) \
            if fabric_at_costing is not None else None
        ref_cost = ice_total_cost or costing_basis_cost or bom_basis_cost

        margin_usd = (sell_price - ref_cost) if (sell_price is not None and ref_cost) else None
        margin_pct = (margin_usd / sell_price * 100.0) if (margin_usd is not None and sell_price) else None

        exposure = (req_unit_m * order_qty * buy_m) if (req_unit_m and buy_m and order_qty) else None
        cons_gap_cost = None
        if spread is not None and consensus and order_qty and buy_yd:
            hi = max(v for _, v in avail)
            cons_gap_cost = (hi - consensus) * order_qty * buy_yd

        # ---- detection rules -------------------------------------------------
        f = []
        if not bom_lines:
            f.append(_flag(style, "missing_bom", "critical", "No BOM fabric line",
                           "The style has no bill of materials, so no fabric requirement can be derived."))
        if not ice_lines:
            f.append(_flag(style, "missing_costing", "warning", "No internal costing",
                           "No INTERNAL COSTING.xlsx row for this style — cost cannot be verified."))
        if fabric_item and not b:
            f.append(_flag(style, "no_buy_rate", "warning", "Fabric never purchased",
                           f"{fabric_item} has no submitted purchase order, so the real buying rate is unknown."))
        if spread is not None and spread > CONS_WARN_PCT:
            sev = "critical" if spread > CONS_CRIT_PCT else "warning"
            f.append(_flag(style, "consumption_conflict", sev, f"Consumption sources disagree by {spread:.1f}%",
                           " / ".join(f"{n} {v:.3f} yd" for n, v in avail) +
                           f" — consensus {consensus:.3f} yd.", cons_gap_cost))
        if buy_yd and quote_rate_yd and quote_rate_yd > 0:
            drift = (buy_yd - quote_rate_yd) / quote_rate_yd * 100.0
            if abs(drift) > RATE_WARN_PCT:
                f.append(_flag(style, "rate_drift", "warning",
                               f"Fabric price moved {drift:+.1f}% vs quote",
                               f"Quoted ${quote_rate_yd:.2f}/yd, bought at ${buy_yd:.2f}/yd.",
                               (buy_yd - quote_rate_yd) * _num(consensus) * order_qty if consensus else None))
        if margin_usd is not None and margin_usd < 0:
            f.append(_flag(style, "price_below_cost", "critical", "Selling price below cost",
                           f"Sells at ${sell_price:.2f} but costs ${ref_cost:.2f} — losing ${-margin_usd:.2f}/pc.",
                           margin_usd * order_qty))
        elif margin_pct is not None and margin_pct < MARGIN_WARN_PCT:
            f.append(_flag(style, "thin_margin", "warning", f"Thin margin {margin_pct:.1f}%",
                           f"Sells at ${sell_price:.2f}, costs ${ref_cost:.2f}."))
        if po_price is not None and sell_price is not None and abs(po_price - sell_price) > 0.01:
            f.append(_flag(style, "po_vs_so_price", "info", "Client PO price ≠ Sales Order price",
                           f"PO ${po_price:.2f} vs SO ${sell_price:.2f} (revision — see COM-04)."))
        if shell and (shell.get("uom") or "").lower().startswith("yard") and b and \
                (b.get("uom") or "").lower().startswith("met"):
            f.append(_flag(style, "uom_mix", "info", "BOM in yard, purchase in metre",
                           "Consumption is normalised to yard; the buying rate is converted from metre."))

        flags.extend(f)
        verdict = "ok"
        if any(x["severity"] == "critical" for x in f):
            verdict = "alert"
        elif any(x["severity"] == "warning" for x in f):
            verdict = "watch"

        rows.append({
            "style": style,
            "description": desc,
            "fabric_item": fabric_item,
            "fabric_content": cpo.get("content"),
            "gsm": cpo.get("gsm"),
            "vendor": cpo.get("vendor"),
            "order_qty_pcs": round(order_qty) if order_qty else None,
            "order_value_usd": _r2(order_value),
            "sell_price_usd": _r2(sell_price),
            "client_po_price_usd": _r2(po_price),
            "client_po_numbers": cpo.get("po_numbers") or order.get("pos") or [],
            "sales_orders": order.get("so") or [],
            "consumption_yd": {
                "bom": _r4(cons_bom),
                "costing": _r4(cons_cost),
                "costing_with_3pct": _r4(cons_cost_3pct),
                "client_po": _r4(cons_cpo),
                "consensus": _r4(consensus),
                "spread_pct": _r2(spread),
                "sources": len(avail),
            },
            "required_m_unit": {
                "bom": _r2(req_unit_m),
                "costing": _r2(cons_cost * M_PER_YD) if cons_cost else None,
            },
            "required_m_total": {
                "bom": _r2(req_unit_m * order_qty) if (req_unit_m and order_qty) else None,
                "costing": _r2(cons_cost * M_PER_YD * order_qty) if (cons_cost and order_qty) else None,
                "with_3pct": _r2(cons_cost_3pct * M_PER_YD * order_qty) if (cons_cost_3pct and order_qty) else None,
            },
            "fabric_cost_total_usd": _r2(exposure),
            "rate_usd": {
                "buy_per_yd": _r4(buy_yd),
                "buy_per_m": _r4(buy_m),
                "buy_uom": (b or {}).get("uom"),
                "po": (b or {}).get("po"),
                "supplier": (b or {}).get("supplier"),
                "quoted_per_yd": _r4(quote_rate_yd) if quote_rate_yd else None,
                "allowed_per_garment": _r2(allowed_fabric_usd),
            },
            "cost_usd": {
                "fabric_bom_basis": _r2(fabric_at_bom),
                "fabric_costing_basis": _r2(fabric_at_costing),
                "cm": _r2(cm), "trim": _r2(trim), "wash": _r2(wash), "additional": _r2(addl),
                "overhead": _r2(overhead), "rejection": _r2(reject),
                "finance": _r2(finance), "depreciation": _r2(deprec),
                "bom_basis_total": _r2(bom_basis_cost),
                "costing_basis_total": _r2(costing_basis_cost),
                "costing_actual": _r2(ice_total_cost) if ice_total_cost else None,
                "costing_quoted_price": _r2(ice_quoted_price) if ice_quoted_price else None,
                "reference": _r2(ref_cost),
            },
            "margin_usd": _r2(margin_usd),
            "margin_pct": _r2(margin_pct),
            "fabric_exposure_usd": _r2(exposure),
            "consumption_gap_usd": _r2(cons_gap_cost),
            "flags": [x["type"] for x in f],
            "verdict": verdict,
        })

    # ---- 7. aggregate ---------------------------------------------------------
    def _sum(key):
        return sum(_num(r.get(key)) for r in rows)

    total_qty = _sum("order_qty_pcs")
    total_value = _sum("order_value_usd")
    flagged = [r for r in rows if r["verdict"] != "ok"]
    summary = {
        "styles": len(rows),
        "order_qty_pcs": round(total_qty),
        "order_value_usd": _r2(total_value),
        "styles_ok": len(rows) - len(flagged),
        "styles_watch": len([r for r in rows if r["verdict"] == "watch"]),
        "styles_alert": len([r for r in rows if r["verdict"] == "alert"]),
        "consumption_conflicts": len([r for r in rows if "consumption_conflict" in r["flags"]]),
        "rate_drifts": len([r for r in rows if "rate_drift" in r["flags"]]),
        "price_below_cost": len([r for r in rows if "price_below_cost" in r["flags"]]),
        "missing_data": len([r for r in rows if {"missing_bom", "missing_costing", "no_buy_rate"} & set(r["flags"])]),
        "fabric_exposure_usd": _r2(_sum("fabric_exposure_usd")),
        "cost_of_goods_usd": _r2(sum(_num(r["cost_usd"].get("reference")) * _num(r["order_qty_pcs"])
                                     for r in rows)),
        "blended_margin_pct": _r2((total_value - sum(
            _num(r["cost_usd"].get("reference")) * _num(r["order_qty_pcs"]) for r in rows)) / total_value * 100.0)
        if total_value else None,
    }

    charts = {
        "consumption_sources": [
            {"x": r["style"],
             "bom": _num(r["consumption_yd"].get("bom")),
             "costing": _num(r["consumption_yd"].get("costing")),
             "client_po": _num(r["consumption_yd"].get("client_po"))}
            for r in rows if r["consumption_yd"].get("bom") or r["consumption_yd"].get("costing")
        ],
        "cost_vs_price": [
            {"x": r["style"],
             "cost": _num(r["cost_usd"].get("reference")),
             "price": _num(r["sell_price_usd"])}
            for r in rows if r.get("sell_price_usd")
        ],
        "fabric_value_by_style": [
            {"x": r["style"], "y": _num(r["fabric_exposure_usd"])}
            for r in rows if r.get("fabric_exposure_usd")
        ],
        "flags_by_type": _flags_by_type(flags),
    }

    out = {"summary": summary, "rows": rows, "flags": flags, "charts": charts,
           "meta": {"consumption_warn_pct": CONS_WARN_PCT, "consumption_crit_pct": CONS_CRIT_PCT,
                    "rate_warn_pct": RATE_WARN_PCT, "margin_warn_pct": MARGIN_WARN_PCT,
                    "yard_per_metre": round(M_PER_YD, 6)}}
    out.update(meta)
    return out


def _flags_by_type(flags):
    counts = {}
    for f in flags:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    label = {"missing_bom": "No BOM", "missing_costing": "No costing", "no_buy_rate": "Not purchased",
             "consumption_conflict": "Consumption conflict", "rate_drift": "Price moved",
             "price_below_cost": "Below cost", "thin_margin": "Thin margin",
             "po_vs_so_price": "PO vs SO price", "uom_mix": "Unit mix"}
    return [{"x": label.get(k, k), "y": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


# ────────────────────────────────────────────────────────────────────────────
# Email connector (P1) — SMTP settings + human-approved outbound queue
#
# Additive. SMTP never runs in the browser: these functions are the only path
# from an approved draft to a real message, and every draft body still comes
# from ``email_engine`` (grounded + validated). No existing function is changed.
# ────────────────────────────────────────────────────────────────────────────

_MAIL_DEFAULTS = {
    "id": None,
    "enabled": 0,
    "email_account": "",
    "from_name": config.MAIL_FROM_NAME,
    "smtp_host": config.SMTP_HOST,
    "smtp_port": config.SMTP_PORT,
    "use_tls": 1,
    "password_set": False,
    "updated_at": None,
}


def _mail_settings_row(db: Session):
    """Return the single logical mail_settings row (or None if never saved)."""
    _ensure_db()
    return db.query(MailSettingsModel).order_by(MailSettingsModel.id.asc()).first()


def _draft_action_text(row: ActionStateModel) -> str:
    try:
        return row.modified_text or (json.loads(row.payload or "{}").get("action") or "")
    except Exception:
        return row.modified_text or ""


def _resolve_recipient_email(db: Session, party_display: str) -> str:
    """Resolve a party *display* name (e.g. ``"Bella Dahl"``, ``"Cortex"``) to
    a real email address held on the live ERP.

    ``email_engine`` sets the recipient to the party's display name, which is not
    a routable address. This helper closes that gap without inventing a new HTTP
    layer — it reuses the existing ``erp.erp_get`` read helper:

    * a value that already contains ``@`` is returned unchanged;
    * otherwise the ERP is queried for a ``Customer`` (``name`` -> ``email_id``)
      and then a ``Contact`` whose ``name`` contains the display name
      case-insensitively; the first non-empty ``email_id`` wins;
    * ``""`` when nothing matches.
    """
    val = (party_display or "").strip()
    if not val:
        return ""
    if "@" in val:
        return val
    needle = val.lower()

    def _match(doctype: str) -> str:
        for row in erp.erp_get(doctype, fields=["name", "email_id"], limit=0):
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            email = (row.get("email_id") or "").strip()
            if email and needle in name.lower():
                return email
        return ""

    return _match("Customer") or _match("Contact") or ""


def _looks_like_email(addr: str) -> bool:
    """True when ``addr`` contains ``@`` with a dot in the domain part."""
    addr = (addr or "").strip()
    local, sep, domain = addr.partition("@")
    return bool(sep and local and "." in domain and not domain.startswith(".")
                and not domain.endswith("."))


MAIL_PASSWORD_UNREADABLE = ("The saved mail password can no longer be unlocked — the project was moved or "
                            "re-uploaded and its encryption key changed. Open Outbound mail → Settings and "
                            "enter the Gmail app password again; nothing else needs to change.")


def get_mail_settings(db: Session) -> dict:
    """Return the outbound SMTP configuration. The password is never included."""
    row = _mail_settings_row(db)
    if row is None:
        return {"settings": dict(_MAIL_DEFAULTS), "connected": False}
    settings = row.to_dict()
    connected = bool(settings.get("enabled") and settings.get("email_account")
                     and settings.get("password_set") and settings.get("password_readable", True))
    out = {"settings": settings, "connected": connected}
    if settings.get("password_set") and not settings.get("password_readable", True):
        out["problem"] = "password_unreadable"
        out["message"] = MAIL_PASSWORD_UNREADABLE
    return out


def save_mail_settings(db: Session, email_account: str, from_name: Optional[str] = None,
                       smtp_host: str = config.SMTP_HOST, smtp_port: int = config.SMTP_PORT,
                       use_tls: int = 1, password: Optional[str] = None,
                       enabled: int = 1) -> dict:
    """Create or update the SMTP settings row.

    The ``password`` is only overwritten when a non-empty value is passed, so the
    frontend can re-save the other fields without re-sending the secret.
    """
    _ensure_db()
    row = _mail_settings_row(db)
    if row is None:
        row = MailSettingsModel(email_account=email_account or "")
        db.add(row)
        db.flush()
    row.email_account = email_account or ""
    if from_name is not None:
        row.from_name = from_name
    row.smtp_host = smtp_host or config.SMTP_HOST
    try:
        row.smtp_port = int(smtp_port or config.SMTP_PORT)
    except Exception:
        row.smtp_port = config.SMTP_PORT
    row.use_tls = 1 if int(use_tls or 0) else 0
    row.enabled = 1 if int(enabled or 0) else 0
    if password:
        import secret_store as _secrets
        row.password = _secrets.enc(password)      # sealed at rest (D-125)
    db.commit()
    db.refresh(row)
    return {"ok": True, "settings": row.to_dict()}


def test_mail_settings(db: Session, to: Optional[str] = None) -> dict:
    """Send a short test email to ``to`` (defaults to the configured account)."""
    row = _mail_settings_row(db)
    target = to or (row.email_account if row else "")
    if row is None or not row.email_account or not row.password:
        return {"ok": False, "error": "Mail is not configured yet.", "to": target or ""}
    import secret_store as _secrets
    settings = {
        "email_account": row.email_account,
        "from_name": row.from_name,
        "smtp_host": row.smtp_host,
        "smtp_port": row.smtp_port,
        "use_tls": row.use_tls,
        "password": "",
    }
    try:
        settings["password"] = _secrets.dec(row.password)
    except _secrets.SecretUnreadable:
        return {"ok": False, "error": MAIL_PASSWORD_UNREADABLE, "password_unreadable": True, "to": target or ""}
    result = mailer.send_via_smtp(
        settings, target,
        "Cortex Control Tower \u2014 SMTP test",
        "This is a test message confirming your outbound mail settings.\n",
        row.from_name or "",
    )
    return {"ok": bool(result.get("ok")), "error": result.get("error") or "",
            "to": target or ""}


def create_email_draft(db: Session, action_id: int, subject: Optional[str] = None,
                       body: Optional[str] = None, to_email: Optional[str] = None) -> dict:
    """Generate (via ``email_engine``) and store an email draft for approval.

    Mirrors :func:`_email_preview` exactly — same live context, same engine call,
    same blocked path. If the engine blocks, nothing is stored and the block
    reason is returned.

    The engine's recipient is a party *display* name; the stored ``to_email`` is
    resolved to a real address via :func:`_resolve_recipient_email` (Customer,
    then Contact), falling back to any explicit ``to_email`` and finally to the
    raw display name so nothing is lost.
    """
    _ensure_db()
    row = _find_action(db, action_id)
    if not row:
        return {"ok": False, "draft": None, "blocked": False,
                "blocked_reason": "action_not_found"}

    ctx = _live_ctx(db)
    risk = _risk_for_action(db, row)
    gen = email_engine.generate_email(
        ctx["facts"], risk, _draft_action_text(row), live=bool(ctx.get("live")))

    if gen.get("blocked"):
        return {"ok": False, "draft": None, "blocked": True,
                "blocked_reason": gen["blocked"].get("code")}

    email = gen.get("email") or {}
    sheet = gen.get("fact_sheet") or {}
    check = gen.get("grounding") or {}
    subj = subject if subject is not None else (email.get("subject") or "")
    bod = body if body is not None else (email.get("body") or "")

    key = f"{row.action_key}:{hashlib.sha1(f'{subj}{bod}'.encode('utf-8')).hexdigest()}"
    existing = db.query(EmailDraftModel).filter(
        EmailDraftModel.idempotency_key == key).first()
    if existing:
        return {"ok": True, "draft": existing.to_dict(), "blocked": False,
                "blocked_reason": ""}

    settings = _mail_settings_row(db)
    from_name = (settings.from_name if settings is not None else "") or ""
    raw_to = email.get("to") or ""
    resolved_to = to_email or _resolve_recipient_email(db, raw_to) or raw_to
    draft = EmailDraftModel(
        action_id=row.id,
        action_key=row.action_key or "",
        intent=gen.get("intent") or "",
        to_email=resolved_to,
        from_name=from_name,
        subject=subj,
        body=bod,
        fact_sheet=json.dumps(sheet, default=str),
        status="draft",
        grounding_ok=1 if check.get("ok") else 0,
        grounding_unsourced=json.dumps(check.get("unsourced") or [], default=str),
        policy_version=gen.get("policy_version") or "",
        edited=1 if (subject is not None or body is not None or to_email is not None) else 0,
        idempotency_key=key,
        message_id="",
        error=None,
        decided_by="Ops Manager",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"ok": True, "draft": draft.to_dict(), "blocked": False, "blocked_reason": ""}


def get_email_drafts(db: Session, status: str = "draft") -> dict:
    """List stored email drafts, newest first. ``status="all"`` returns all."""
    _ensure_db()
    q = db.query(EmailDraftModel)
    if status and status != "all":
        q = q.filter(EmailDraftModel.status == status)
    rows = q.order_by(desc(EmailDraftModel.created_at), desc(EmailDraftModel.id)).all()
    return {"drafts": [r.to_dict() for r in rows]}


def approve_and_send_email(db: Session, draft_id: int, subject: Optional[str] = None,
                           body: Optional[str] = None, to_email: Optional[str] = None,
                           actor: str = "Ops Manager", confirm: int = 0) -> dict:
    """Approve a draft and send it over SMTP — REQUIRES explicit confirmation.

    GUARDRAIL: nothing leaves over SMTP unless the caller passes ``confirm=1``.
    The UI only does so after the operator confirms the recipient, so no email
    (to anyone, including the operator) can be sent without a human decision.

    Optional edits are applied first, then the (possibly edited) message is
    re-validated with ``email_engine.validate_grounding`` against the stored fact
    sheet — an ungrounded message is refused. The final recipient is
    ``to_email or draft.to_email`` and must look like an email address
    (contains ``@`` with a dot after it); otherwise ``invalid_recipient`` is
    returned and nothing is sent. When ``to_email`` is supplied it is persisted
    on the draft (``edited=1``). A row already in ``sent`` status is returned
    unchanged (idempotent). Every decision is written to ``audit_log``.
    """
    _ensure_db()
    try:
        draft_id = int(draft_id)
    except Exception:
        return {"ok": False, "status": "not_found", "message_id": "",
                "error": "not_found", "draft": None}

    draft = db.query(EmailDraftModel).filter(EmailDraftModel.id == draft_id).first()
    if not draft:
        return {"ok": False, "status": "not_found", "message_id": "",
                "error": "not_found", "draft": None}

    # Idempotent — never re-send a row that already went out.
    if draft.status == "sent":
        return {"ok": True, "status": "sent", "message_id": draft.message_id or "",
                "error": None, "draft": draft.to_dict()}

    # ── HARD GUARDRAIL — no confirmation, no send. Nothing is edited or sent. ──
    if not confirm:
        _log(db, "email", "send_blocked_no_confirmation",
             f"Send of draft #{draft_id} blocked — explicit confirmation not provided",
             actor=actor, risk_title=(draft.subject or "")[:120])
        return {"ok": False, "status": "confirmation_required", "message_id": "",
                "error": "confirmation_required", "confirmation_required": True,
                "to_email": (to_email or draft.to_email or ""),
                "subject": (subject if subject is not None else draft.subject),
                "message": ("No email is sent without an explicit confirmation — "
                            "review the recipient and resend with confirm=1."),
                "draft": draft.to_dict()}

    if subject is not None and subject != draft.subject:
        draft.subject = subject
        draft.edited = 1
    if body is not None and body != draft.body:
        draft.body = body
        draft.edited = 1

    # Resolve + validate the final recipient BEFORE anything can send. An invalid
    # recipient is refused outright (nothing sent, nothing persisted).
    final_to = (to_email or draft.to_email or "").strip()
    if not _looks_like_email(final_to):
        return {"ok": False, "status": draft.status, "message_id": draft.message_id or "",
                "error": "invalid_recipient", "draft": draft.to_dict()}
    if to_email is not None:
        draft.to_email = final_to
        draft.edited = 1

    try:
        sheet = json.loads(draft.fact_sheet) if draft.fact_sheet else {}
    except Exception:
        sheet = {}
    check = email_engine.validate_grounding(
        {"subject": draft.subject or "", "body": draft.body or ""}, sheet)
    if not check.get("ok"):
        draft.grounding_ok = 0
        draft.grounding_unsourced = json.dumps(check.get("unsourced") or [], default=str)
        draft.decided_at = datetime.now()
        draft.decided_by = actor or "Ops Manager"
        db.commit()
        db.refresh(draft)
        return {"ok": False, "status": draft.status, "message_id": draft.message_id or "",
                "error": "ungrounded", "draft": draft.to_dict()}

    draft.grounding_ok = 1
    draft.grounding_unsourced = json.dumps([])

    settings = _mail_settings_row(db)
    if settings is None or not settings.email_account or not settings.password:
        draft.status = "failed"
        draft.error = "Mail is not configured yet."
        draft.decided_at = datetime.now()
        draft.decided_by = actor or "Ops Manager"
        db.commit()
        db.refresh(draft)
        _log(db, "email", "approve_and_send_email",
             f"Send refused for draft #{draft.id}: mail not configured.",
             actor=actor or "Ops Manager", approved="failed")
        return {"ok": False, "status": "failed", "message_id": "",
                "error": draft.error, "draft": draft.to_dict()}

    import secret_store as _secrets
    settings_dict = {
        "email_account": settings.email_account,
        "from_name": settings.from_name,
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "use_tls": settings.use_tls,
        "password": "",
    }
    try:
        settings_dict["password"] = _secrets.dec(settings.password)
    except _secrets.SecretUnreadable:
        return {"ok": False, "status": "failed", "message_id": "", "error": MAIL_PASSWORD_UNREADABLE,
                "password_unreadable": True, "draft": draft.to_dict()}
    result = mailer.send_via_smtp(
        settings_dict, final_to, draft.subject or "", draft.body or "",
        draft.from_name or settings.from_name or "")

    draft.decided_at = datetime.now()
    draft.decided_by = actor or "Ops Manager"
    if result.get("ok"):
        draft.status = "sent"
        draft.message_id = result.get("message_id") or ""
        draft.error = None
        draft.sent_at = datetime.now()
        db.commit()
        db.refresh(draft)
        _log(db, "email", "approve_and_send_email",
             f"Email sent to {final_to} (draft #{draft.id}, {draft.message_id}).",
             actor=actor or "Ops Manager", approved="yes")
        return {"ok": True, "status": "sent", "message_id": draft.message_id or "",
                "error": None, "draft": draft.to_dict()}

    draft.status = "failed"
    draft.error = result.get("error") or "send failed"
    db.commit()
    db.refresh(draft)
    _log(db, "email", "approve_and_send_email",
         f"Email to {final_to} failed: {draft.error}",
         actor=actor or "Ops Manager", approved="no")
    return {"ok": False, "status": "failed", "message_id": "",
            "error": draft.error, "draft": draft.to_dict()}


def reject_email_draft(db: Session, draft_id: int, reason: str = "") -> dict:
    """Reject a draft (never sends). Writes an ``audit_log`` row."""
    _ensure_db()
    try:
        draft_id = int(draft_id)
    except Exception:
        return {"ok": False, "draft": None}
    draft = db.query(EmailDraftModel).filter(EmailDraftModel.id == draft_id).first()
    if not draft or draft.status == "sent":
        return {"ok": False, "draft": draft.to_dict() if draft else None}
    draft.status = "rejected"
    draft.error = reason or draft.error
    draft.decided_at = datetime.now()
    draft.decided_by = "Ops Manager"
    db.commit()
    db.refresh(draft)
    _log(db, "email", "reject_email_draft",
         f"Email draft #{draft.id} rejected" + (f": {reason}" if reason else ""),
         approved="no")
    return {"ok": True, "draft": draft.to_dict()}


def delete_email_draft(db: Session, draft_id: int) -> dict:
    """Delete a draft. Refuses when the row has already been sent."""
    _ensure_db()
    try:
        draft_id = int(draft_id)
    except Exception:
        return {"ok": False, "error": "not_found"}
    draft = db.query(EmailDraftModel).filter(EmailDraftModel.id == draft_id).first()
    if not draft:
        return {"ok": False, "error": "not_found"}
    if draft.status == "sent":
        return {"ok": False, "error": "already_sent"}
    db.delete(draft)
    db.commit()
    return {"ok": True}


# ────────────────────────────────────────────────────────────────────────────
# Inbound mail (P2) — mailbox → understood inbox → order-change flags
#
# Read-only: this never writes to the ERP on its own. Understanding is purely
# deterministic (no OCR, by client decision). Any change to an order becomes a
# flagged row a human decides on.
# ────────────────────────────────────────────────────────────────────────────

# Which inbound types create a decision item, and how urgent they are.
_CHANGE_TYPES = {
    inbound.CLASS_NEW_ORDER: "new_order",
    inbound.CLASS_AMENDMENT: "order_amendment",
    inbound.CLASS_INVOICE: "invoice",
    inbound.CLASS_REMITTANCE: "remittance",
    inbound.CLASS_QUERY: "query",
}
_SEVERITY = {
    inbound.CLASS_AMENDMENT: "critical",
    inbound.CLASS_INVOICE: "warning",
    inbound.CLASS_QUERY: "warning",
    inbound.CLASS_NEW_ORDER: "info",
    inbound.CLASS_REMITTANCE: "info",
}


def _mailbox_settings(db: Session) -> dict:
    """Settings dict for the IMAP client (includes the stored password)."""
    row = _mail_settings_row(db)
    if not row:
        return {"email_account": "", "password": "", "imap_host": config.IMAP_HOST,
                "imap_port": config.IMAP_PORT, "smtp_host": config.SMTP_HOST, "smtp_port": config.SMTP_PORT,
                "enabled": 0, "from_name": ""}
    import secret_store as _secrets
    try:
        pw, pw_err = (_secrets.dec(row.password) or ""), ""
    except _secrets.SecretUnreadable:
        pw, pw_err = "", "password_unreadable"
    return {
        "password_error": pw_err,
        "email_account": row.email_account or "",
        "password": pw,
        "imap_host": config.IMAP_HOST,
        "imap_port": config.IMAP_PORT,
        "smtp_host": row.smtp_host or config.SMTP_HOST,
        "smtp_port": int(row.smtp_port or config.SMTP_PORT),
        "enabled": int(row.enabled or 0),
        "from_name": row.from_name or "",
    }


_SEV_STYLE = {
    "critical": {"label": "ACT NOW", "rail": "#dc2626", "bg": "#fee2e2", "ink": "#991b1b"},
    "warning": {"label": "REVIEW", "rail": "#d97706", "bg": "#fef3c7", "ink": "#92400e"},
    "info": {"label": "FOR INFO", "rail": "#0f766e", "bg": "#ccfbf1", "ink": "#115e59"},
}


def _notify_text(changes: list[dict], total_mail: int) -> str:
    """Plain-text fallback (for clients that do not render HTML)."""
    n = len(changes)
    out = [f"CORTEX CONTROL TOWER", f"{n} item{'s' if n != 1 else ''} need your decision", ""]
    for i, c in enumerate(changes[:15], 1):
        sev = (c.get("severity") or "info").upper()
        body = c.get("title") or ""
        if " — " in body:
            body = body.split(" — ", 1)[1]
        out.append(f"{i}. [{sev}] {body}")
        meta = []
        if c.get("so_name"):
            meta.append(f"Order {c['so_name']}")
        if c.get("po_no"):
            meta.append(f"PO {c['po_no']}")
        if c.get("customer"):
            meta.append(str(c["customer"]))
        if meta:
            out.append("   " + " · ".join(meta))
        steps = c.get("next_steps") or []
        if steps:
            out.append("   Next steps:")
            for st in steps[:3]:
                out.append(f"     - {st}")
        out.append("")
    out.append("Open the Cortex Control Tower > Inbox to approve or dismiss.")
    return "\n".join(out)


def _notify_html(changes: list[dict], total_mail: int) -> str:
    """Formatted HTML alert. Inline styles + tables only (email-client safe)."""
    import html as _html

    n = len(changes)
    rows = []
    for c in changes[:15]:
        st = _SEV_STYLE.get(c.get("severity") or "info", _SEV_STYLE["info"])
        title = c.get("title") or ""
        if " — " in title:
            title = title.split(" — ", 1)[1]
        from_addr = c.get("from_addr") or ""
        meta = []
        if c.get("so_name"):
            meta.append(("Order", c["so_name"]))
        if c.get("po_no"):
            meta.append(("PO", c["po_no"]))
        if c.get("customer"):
            meta.append(("Customer", c["customer"]))
        meta_html = "".join(
            f'<span style="display:inline-block;background:#f1f5f9;color:#334155;font-size:11.5px;'
            f'padding:3px 9px;border-radius:6px;margin:0 6px 6px 0;">'
            f'<b style="color:#0f172a;">{_html.escape(k)}</b>&nbsp;{_html.escape(str(v))}</span>'
            for k, v in meta
        )
        steps = c.get("next_steps") or []
        steps_html = ""
        if steps:
            lis = "".join(
                f'<li style="margin:0 0 4px 0;">{_html.escape(str(s))}</li>' for s in steps[:4]
            )
            steps_html = (
                f'<div style="margin-top:12px;">'
                f'<div style="font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#64748b;margin-bottom:5px;">Next steps</div>'
                f'<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.55;color:#334155;">{lis}</ul>'
                f'</div>'
            )
        rows.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border:1px solid #e2e8f0;border-left:4px solid {st["rail"]};border-radius:10px;margin:0 0 12px 0;">'
            f'<tr><td style="padding:14px 16px;">'
            f'<span style="display:inline-block;background:{st["bg"]};color:{st["ink"]};font-size:10.5px;font-weight:800;'
            f'letter-spacing:.06em;padding:3px 9px;border-radius:999px;">{st["label"]}</span>'
            f'<div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.4;margin-top:9px;">{_html.escape(title)}</div>'
            + (f'<div style="font-size:12.5px;color:#64748b;margin-top:3px;">From {_html.escape(from_addr)}</div>' if from_addr else '')
            + (f'<div style="margin-top:10px;">{meta_html}</div>' if meta_html else '')
            + steps_html
            + '</td></tr></table>'
        )

    headline = f"{n} item{'s' if n != 1 else ''} need your decision"
    return (
        '<div style="background:#eef2f7;padding:26px 12px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">'
        '<table role="presentation" width="620" cellpadding="0" cellspacing="0" '
        'style="width:620px;max-width:620px;background:#ffffff;border:1px solid #dbe3ec;border-radius:14px;overflow:hidden;">'
        # header
        '<tr><td style="background:#0f2a4a;padding:20px 24px;">'
        '<div style="color:#93c0e8;font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;">Cortex Control Tower</div>'
        f'<div style="color:#ffffff;font-size:20px;font-weight:700;margin-top:6px;">{headline}</div>'
        f'<div style="color:#c7d7e8;font-size:12.5px;margin-top:5px;">Read from your inbox · {total_mail} message(s) processed · nothing is applied to the ERP until you approve it</div>'
        '</td></tr>'
        # body
        f'<tr><td style="padding:20px 24px 6px 24px;">{"".join(rows)}</td></tr>'
        # cta
        '<tr><td style="padding:6px 24px 22px 24px;">'
        '<div style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:10px;padding:13px 16px;font-size:13px;color:#334155;">'
        'Open the <b>Cortex Control Tower</b> and go to the <b>Inbox</b> tab to review each item. Everything stays a draft until you approve it.'
        '</div></td></tr>'
        # footer
        '<tr><td style="padding:14px 24px;background:#f7f9fc;border-top:1px solid #e6ecf3;color:#64748b;font-size:11.5px;">'
        'Automated message from the Cortex Control Tower. You receive this because this mailbox is connected to the Tower.'
        '</td></tr>'
        '</table></td></tr></table></div>'
    )


def _notify_inbox(db: Session, new_changes: list[dict], new_mail: int) -> dict:
    """Send the operator a formatted heads-up. Best-effort; never raises.

    GUARDRAIL: automatic notification emails are OFF unless the operator enables
    them (app_kv `email_auto_notify` = "1"). Default = no send.
    """
    _kv = db.query(KVModel).filter(KVModel.key == "email_auto_notify").first()
    if not _kv or str(_kv.value) != "1":
        return {"ok": False, "error": "auto_notify_disabled"}
    s = _mailbox_settings(db)
    if not (s.get("email_account") and s.get("password")) or not new_changes:
        return {"ok": False, "error": "notify_skipped"}
    n = len(new_changes)
    res = mailer.send_via_smtp(
        {"smtp_host": s.get("smtp_host") or config.SMTP_HOST, "smtp_port": s.get("smtp_port") or config.SMTP_PORT,
         "use_tls": 1, "email_account": s["email_account"], "password": s["password"]},
        to_email=s["email_account"],
        subject=f"Cortex Tower - {n} item{'s' if n != 1 else ''} need your decision",
        body=_notify_text(new_changes, new_mail),
        html=_notify_html(new_changes, new_mail),
        from_name=s.get("from_name") or "Cortex Control Tower",
    )
    return res



def _kv_set(db, key: str, value: str) -> None:
    """One row in ``app_kv``. Never raises."""
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(KVModel(key=key, value=str(value)))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _kv_get(db, key: str, default: str = "") -> str:
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        return row.value if row and row.value is not None else default
    except Exception:
        return default


def _set_error(msg) -> None:
    """Record a background failure where an operator can find it (stderr of the function call).
    It was called on two error paths but never defined, so the error path itself raised NameError."""
    import sys as _sys
    print(json.dumps({"warning": str(msg)[:500]}), file=_sys.stderr)


def _stamp_sync(db, subsystem: str) -> None:
    """Record that this subsystem actually talked to the mailbox, and when."""
    _kv_set(db, f"last_sync:{subsystem}", datetime.now().isoformat(timespec="seconds"))


def _freshness(db, *subsystems: str) -> dict:
    """``{"mail": {"at": iso, "ago": "4 min ago", "stale": bool}, …}`` — read, never guessed.

    Nothing in this app runs on a clock (the WIP heartbeat was removed on the owner's
    instruction, 2026-11-03), so a screen must be able to say *when* it last reached the
    mailbox. A number with no timestamp is a number you cannot trust (2026-11-04, D-126).
    """
    out = {}
    now = datetime.now()
    for name in subsystems:
        raw = _kv_get(db, f"last_sync:{name}", "")
        entry = {"at": raw or None, "ago": "never", "stale": True, "minutes": None}
        if raw:
            try:
                when = datetime.fromisoformat(raw)
                mins = max(int((now - when).total_seconds() // 60), 0)
                entry.update({"minutes": mins, "stale": mins > 60,
                              "ago": ("just now" if mins < 1 else
                                      f"{mins} min ago" if mins < 90 else
                                      f"{mins // 60} h ago")})
            except Exception:
                pass
        out[name] = entry
    return out


def sync_inbox(db: Session, limit: int = 50, notify: int = 0, full: int = 0) -> dict:
    """Fetch new mail, understand it and flag any order-affecting items.

    Idempotent: messages already stored (by IMAP UID) are skipped.
    """
    _ensure_db()
    s = _mailbox_settings(db)
    if s.get("password_error") == "password_unreadable":
        return {"ok": False, "error": "password_unreadable", "message": MAIL_PASSWORD_UNREADABLE,
                "password_unreadable": True, **READ_ONLY}
    if not s.get("email_account") or not s.get("password"):
        return {"ok": False, "error": "mailbox_not_configured",
                "message": "No mailbox is set up yet. Open Outbound mail → Settings, enter the Gmail address and its app password.",
                **READ_ONLY}

    known = {u for (u,) in db.query(MailMessageModel.uid).all()}
    since_uid = None
    if known:
        try:
            since_uid = max(int(u) for u in known if str(u).isdigit())
        except Exception:
            since_uid = None

    # DRAIN the mailbox, newest mail included. The old single call took the first
    # `limit` messages above the high-water mark and stopped, so a burst of junk
    # (bounces, security alerts) hid the one real PO for weeks (2026-11-03).
    fetched_msgs: list[dict] = []
    scanned, remaining = 0, 0
    batches = 0
    while batches < 6:
        res = inbound.fetch_inbox(s, known, limit=int(limit), since_uid=since_uid, full=bool(full))
        if not res.get("ok"):
            if batches == 0:
                return {"ok": False, "error": res.get("error"), "fetched": 0, "flagged": 0,
                        **READ_ONLY}
            break
        batch = res.get("messages") or []
        scanned += int(res.get("scanned") or 0)
        remaining = int(res.get("remaining") or 0)
        fetched_msgs.extend(batch)
        for m in batch:                        # advance the high-water mark inside the loop
            known.add(str(m.get("uid")))
            try:
                since_uid = max(int(since_uid or 0), int(m.get("uid")))
            except Exception:
                pass
        batches += 1
        if not batch or remaining <= 0:
            break
    res = {"ok": True, "messages": fetched_msgs, "scanned": scanned, "remaining": remaining}

    # the live order book is read only when there is mail to match against it: the inbox polls every two minutes and
    # an empty poll must not cost an ERP read (2026-11-07)
    sos = ((_live_ctx(db).get("facts") or {}).get("sos") or []) if res.get("messages") else []
    created_mail, new_changes = 0, []
    self_addr = (s.get("email_account") or "").lower()

    for m in res.get("messages") or []:
        # Never re-ingest our own notification mail (subject-prefixed by _notify_inbox),
        # otherwise the Tower's heads-up loops back as a "change".
        is_own_alert = (m.get("from_addr") == self_addr and
                        (m.get("subject") or "").startswith(("Cortex Tower -", "Cortex Tower —")))
        is_system_noise = inbound.is_noise(m.get("subject"), m.get("from_addr"), m.get("body_text"))
        cls = inbound.classify(m.get("subject"), m.get("body_text"), m.get("attachments"))
        po_refs = inbound.extract_po_refs(m.get("subject"), m.get("body_text"), m.get("attachments"))
        matched = inbound.match_orders(po_refs, sos)
        steps = inbound.next_steps(cls["classification"], matched, po_refs)

        row = MailMessageModel(
            uid=m["uid"], message_id=m.get("message_id"), thread_id=m.get("thread_id"),
            from_name=m.get("from_name"), from_addr=m.get("from_addr"), to_addr=m.get("to_addr"),
            subject=m.get("subject"), snippet=m.get("snippet"), body_text=m.get("body_text"),
            received_at=m.get("received_at"), has_attachments=m.get("has_attachments"),
            # metadata only: the bytes live as one file each under data/mail/<id>/, not base64 inside this row
            attachments=json.dumps([{k: v for k, v in a.items() if k != "data"} for a in (m.get("attachments") or [])]),
            classification=cls["classification"], confidence=int(cls["confidence"]),
            reasons=json.dumps(cls["reasons"]), po_refs=json.dumps(po_refs),
            matched_orders=json.dumps(matched),
            status="ignored" if (is_own_alert or is_system_noise) else "new",
            gm_thrid=m.get("gm_thrid") or None, in_reply_to=(m.get("in_reply_to") or "")[:300] or None,
            cc_addr=(m.get("cc_addr") or "")[:600] or None, direction="in",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created_mail += 1

        if is_own_alert or is_system_noise:
            continue

        # ── intake: read the attachments, understand the document, open a run ──
        stored = []
        try:
            for att in (m.get("attachments") or []):
                if "data" in att or (att.get("mime") or "").startswith(("application/", "image/", "text/")) \
                        or att.get("too_large"):
                    stored.append(_store_attachment(db, row, att))
        except Exception as e:
            row.needs_ocr = 1 if "ocr" in str(e).lower() else 0
            db.commit()
        # ── intake: ONE RUN PER DOCUMENT ──────────────────────────────────────
        if stored or cls["classification"] in INTAKE_CLASSES or row.chain_id:
            try:
                made = _open_document_runs(db, row, stored, use_llm=False)
                if made:
                    row.route = made[-1].route
                    row.intake_status = made[-1].status
                    row.parse_ok = 1 if all(r.status == "understood" for r in made) else 0
                row.document_count = len(made)
                db.commit()
            except Exception as e:
                row.intake_status = "error"
                db.commit()
                _set_error(f"intake: {e}")
        ctype = _CHANGE_TYPES.get(cls["classification"])
        if not ctype:
            continue
        sev = _SEVERITY.get(cls["classification"], "info")
        if ctype == "new_order" and matched:
            sev = "warning"
        title = f"{inbound.CLASS_LABEL[cls['classification']]} — {m.get('from_name') or m.get('from_addr')}: {(m.get('subject') or '(no subject)')[:120]}"
        ch = OrderChangeModel(
            mail_id=row.id, change_type=ctype, title=title[:400],
            summary=(m.get("snippet") or "")[:1000], from_addr=m.get("from_addr"),
            so_name=(matched[0].get("so") if matched else None),
            po_no=(matched[0].get("po_no") if matched else (po_refs[0] if po_refs else None)),
            customer=(matched[0].get("customer") if matched else None),
            severity=sev, next_steps=json.dumps(steps), status="pending",
        )
        db.add(ch)
        db.commit()
        db.refresh(ch)
        new_changes.append(ch.to_dict())

    notif = {"ok": False, "error": "notify_off"}
    if int(notify or 0) and new_changes:
        notif = _notify_inbox(db, new_changes, created_mail)

    if created_mail or new_changes:
        db.add(AuditLogModel(
            action_type="inbox", action_name="sync_inbox",
            description=f"Synced {created_mail} new mail; {len(new_changes)} item(s) flagged",
            actor="System", approved=None))
        db.commit()

    _stamp_sync(db, "mail")
    if created_mail:
        _stamp_sync(db, "intake")

    return {"ok": True, "fetched": created_mail, "flagged": len(new_changes),
            "scanned": scanned, "remaining": remaining, "batches": batches,
            "notified": bool(notif.get("ok")), "notify_error": notif.get("error") or "",
            "freshness": _freshness(db, "mail", "intake"), **READ_ONLY}


def get_inbox(db: Session, classification: str = "", status: str = "", limit: int = 100) -> dict:
    """The understood inbox, newest first."""
    _ensure_db()
    q = db.query(MailMessageModel)
    if not status:
        q = q.filter(MailMessageModel.status != "ignored")
    if classification:
        q = q.filter(MailMessageModel.classification == classification)
    if status:
        q = q.filter(MailMessageModel.status == status)
    rows = q.order_by(desc(MailMessageModel.id)).limit(int(limit)).all()
    return {"messages": [r.to_dict() for r in rows], **READ_ONLY}


def get_mail_message(db: Session, mail_id: int) -> dict:
    """One inbound message in full; marks it read."""
    _ensure_db()
    row = db.query(MailMessageModel).filter(MailMessageModel.id == int(mail_id)).first()
    if not row:
        return {"message": None, **READ_ONLY}
    if row.status == "new":
        row.status = "read"
        db.commit()
    return {"message": row.to_dict(), **READ_ONLY}


def dismiss_mail(db: Session, mail_id: int) -> dict:
    _ensure_db()
    try:
        mail_id = int(mail_id)
    except Exception:
        return {"ok": False, "error": "not_found"}
    row = db.query(MailMessageModel).filter(MailMessageModel.id == mail_id).first()
    if not row:
        # Say WHY: a bare {"ok": false} left the UI with nothing to show (2026-11-06).
        return {"ok": False, "error": "not_found"}
    row.status = "dismissed"
    db.commit()
    return {"ok": True, "message": row.to_dict()}


def _change_fallback_doctype(change_type: str) -> str:
    return {
        "new_order": "Sales Order", "order_amendment": "Sales Order",
        "invoice": "Purchase Invoice", "remittance": "Payment Entry",
    }.get(change_type or "", "Sales Order")


def _change_is_open(ch) -> bool:
    """True while the decision still needs finishing (incomplete ERP write)."""
    if ch.status != "pending":
        return False
    return bool(ch.result_note)   # a note on a still-pending row = an attempt that did not finish


def _enrich_change(ch) -> dict:
    """Add the ERP pivot links + 'needs action' so the UI can hold the item open."""
    d = ch.to_dict()
    if ch.result_doctype and ch.result_doc:
        links = _erp_links(ch.result_doctype, ch.result_doc, 1)
    else:
        links = _erp_links(_change_fallback_doctype(ch.change_type), "", 2)
    d.update(links)
    d["needs_action"] = _change_is_open(ch)
    return d


def get_order_changes(db: Session, status: str = "pending") -> dict:
    """Flagged inbound items (new orders, amendments, invoices…) awaiting a decision."""
    _ensure_db()
    q = db.query(OrderChangeModel)
    if status and status != "all":
        q = q.filter(OrderChangeModel.status == status)
    rows = q.order_by(desc(OrderChangeModel.id)).limit(200).all()
    return {"changes": [_enrich_change(r) for r in rows], **READ_ONLY}


# Change types with no document of their own get a tracked ERP Task instead.
_CHANGE_TASK = {
    "order_amendment": ("Apply buyer PO revision", "Sales"),
    "invoice": ("Enter supplier invoice", "Accounts"),
    "remittance": ("Record customer payment", "Accounts"),
    "query": ("Answer buyer query", "Customer Service"),
    "other": ("Handle inbound mail", "Operations"),
}


def _task_for_change(subject: str, description: str):
    """Return (task_name, created). Idempotent on the subject."""
    rows = erp.erp_get("Task", fields=["name"], filters=[["subject", "=", subject]], limit=1)
    if rows:
        return rows[0].get("name"), False
    try:
        ok, doc, _err, _n = _intake_exec.create_checked("Task", {
            "doctype": "Task", "subject": subject[:140], "priority": "High", "status": "Open",
            "exp_start_date": date.today().isoformat(), "description": description,
        })
    except Exception:
        ok, doc = False, {}
    return (doc.get("name") if ok and doc.get("name") else None), bool(ok and doc.get("name"))


_AMT_RE = re.compile(r"(?:USD|US\$|\$)\s*([\d][\d,]*\.?\d*)", re.I)
_DAYS_RE = re.compile(r"(\d{1,3})\s*days?", re.I)
_INVNO_RE = re.compile(r"\b(INV[-\s]?[A-Z0-9-]{3,})\b", re.I)
_FROMTO_NUM = re.compile(r"from\s*([\d,]{2,})\s*to\s*([\d,]{2,})", re.I)
_FROMTO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})[^\d]{1,40}?(\d{4}-\d{2}-\d{2})")


def _ensure_supplier_for_change(mail, ch: OrderChangeModel):
    """Return (supplier_name, created, error). Creates the vendor when it is new."""
    name = _derive_buyer_name(mail, ch)
    rows = erp.erp_get("Supplier", fields=["name"], limit=0) or []
    for s in rows:
        if (s.get("name") or "").lower() == name.lower():
            return s["name"], False, None
    groups = [g.get("name") for g in (erp.erp_get("Supplier Group", fields=["name", "is_group"], limit=0) or [])
              if g.get("name") and not g.get("is_group")]
    blob = f"{ch.summary or ''} {ch.title or ''}".lower()
    pref = ["Fabric Mills"] if "fabric" in blob else ["Services", "Local"]
    payload = {"doctype": "Supplier", "supplier_name": name, "supplier_type": "Company",
               "supplier_group": _pick(groups, pref, groups[0] if groups else "Services")}
    email = _derive_buyer_email(mail, ch)
    if email:
        payload["email_id"] = email
    try:
        ok, doc, err, _n = _intake_exec.create_checked("Supplier", payload)
    except Exception as e:
        ok, doc, err = False, {}, f"{type(e).__name__}: {e}"
    if ok and doc.get("name"):
        return doc["name"], True, None
    return "", False, err or "supplier create failed"


UNALLOCATED_ITEM = "UNALLOCATED-EXPENSE"


def _ensure_unallocated_item():
    """A clearly-flagged non-stock line item used to book a supplier bill whose
    coding is not yet known. Return (item_code, created)."""
    if erp.erp_doc("Item", UNALLOCATED_ITEM):
        return UNALLOCATED_ITEM, False
    try:
        ok, doc, _e = _intake_exec.create_checked("Item", {
            "doctype": "Item", "item_code": UNALLOCATED_ITEM, "item_name": "Unallocated expense (to code)",
            "item_group": "Products", "stock_uom": "Nos", "is_stock_item": 0, "is_purchase_item": 1,
            "description": ("Auto-created by Cortex OS to book an inbound supplier invoice before its "
                            "expense coding is known. Re-code the line before submitting."),
        })
    except Exception:
        ok, doc = False, {}
    return (doc.get("name") if ok and doc.get("name") else None), bool(ok and doc.get("name"))


def _expense_defaults(company: str):
    acc = next((a.get("name") for a in (erp.erp_get(
        "Account", fields=["name"], filters=[["company", "=", company], ["root_type", "=", "Expense"],
                                             ["is_group", "=", 0]], limit=0) or []) if a.get("name")), None)
    cc = next((c.get("name") for c in (erp.erp_get(
        "Cost Center", fields=["name"], filters=[["company", "=", company], ["is_group", "=", 0]],
        limit=0) or []) if c.get("name")), None)
    return acc, cc


def _payable_account(company: str, currency: str):
    """The Liability account that MATCHES the bill currency.

    ERPNext refuses a document whose currency differs from its party account, so a
    USD bill needs a USD payable (this site has 'Creditors USD - CTXHK').
    """
    accs = erp.erp_get("Account", fields=["name", "account_currency", "root_type"],
                       filters=[["company", "=", company], ["root_type", "=", "Liability"],
                                ["is_group", "=", 0]], limit=0) or []
    cands = [a["name"] for a in accs
             if (a.get("account_currency") or "").upper() == (currency or "").upper()]
    if not cands:
        return None
    pref = [c for c in cands if "creditor" in c.lower() or "payable" in c.lower()]
    return (pref or cands)[0]


def _handle_invoice_change(db: Session, ch: OrderChangeModel, mail) -> tuple:
    """Supplier invoice -> auto-create the Supplier + a DRAFT Purchase Invoice."""
    supplier, created_sup, serr = _ensure_supplier_for_change(mail, ch)
    if not supplier:
        return [], f"could not resolve or create the Supplier ({serr or 'unknown error'})"
    blob = f"{ch.title or ''} {ch.summary or ''} {getattr(mail, 'body_text', '') or ''}"
    inv_m = _INVNO_RE.search(blob)
    amt_m = _AMT_RE.search(blob)
    days_m = _DAYS_RE.search(blob)
    from datetime import timedelta as _td
    today = date.today()
    amount = float(amt_m.group(1).replace(",", "")) if amt_m else 0.0
    due = (today + _td(days=int(days_m.group(1)))).isoformat() if days_m else today.isoformat()
    company = _pick([c.get("name") for c in (erp.erp_get("Company", fields=["name"], limit=0) or [])],
                    ["CORTEX FASHION (HK) LIMITED"], "")
    item, created_item = _ensure_unallocated_item()
    refs = []
    if created_sup:
        refs.append({"doctype": "Supplier", "name": supplier})
    if created_item:
        refs.append({"doctype": "Item", "name": item})
    bits = [f"Supplier '{supplier}'" + (" created" if created_sup else " matched")]
    if item and amount > 0:
        acc, cc = _expense_defaults(company)
        line = {"item_code": item, "qty": 1, "rate": amount, "amount": amount,
                "description": f"Inbound supplier invoice {(inv_m.group(1) if inv_m else '')} — code before submitting"}
        if acc:
            line["expense_account"] = acc
        if cc:
            line["cost_center"] = cc
        payload = {"doctype": "Purchase Invoice", "supplier": supplier, "company": company,
                   "currency": "USD", "posting_date": today.isoformat(), "due_date": due,
                   "bill_no": (inv_m.group(1) if inv_m else ""), "items": [line]}
        # a USD bill must post to a USD payable account
        pay_acct = _payable_account(company, "USD")
        if pay_acct:
            payload["credit_to"] = pay_acct
        try:
            ok, doc, err, _n = _intake_exec.create_checked("Purchase Invoice", payload)
        except Exception as e:
            ok, doc, err = False, {}, f"{type(e).__name__}: {e}"
        if ok and doc.get("name"):
            refs.append({"doctype": "Purchase Invoice", "name": doc["name"]})
            bits.append(f"draft Purchase Invoice {doc['name']} (USD {amount:,.2f}, due {due})")
        else:
            bits.append(f"draft Purchase Invoice failed ({err or 'unknown'})")
    else:
        bits.append("no amount found in the mail — raise the bill manually")
    return refs, "; ".join(bits)


def _amendment_deltas(ch: OrderChangeModel, mail) -> str:
    """Turn a revised-PO mail into precise change instructions."""
    blob = f"{ch.title or ''}\n{ch.summary or ''}\n{getattr(mail, 'body_text', '') or ''}"
    out, seen = [], set()
    for a, b in _FROMTO_NUM.findall(blob):
        txt = f"quantity {a} -> {b} pcs"
        if txt not in seen:
            seen.add(txt); out.append(txt)
    for a, b in _FROMTO_DATE.findall(blob)[:1]:
        txt = f"delivery {a} -> {b}"
        if txt not in seen:
            seen.add(txt); out.append(txt)
    for line in (getattr(mail, "body_text", "") or "").splitlines():
        s = line.strip()
        if any(k in s.lower() for k in ("revised", "increased", "decreased", "moved", "change", "supersede")):
            if s and s not in seen:
                seen.add(s); out.append(s)
    return "; ".join(out[:6]) or "see the email for the requested change"


def _handle_other_change(db: Session, ch: OrderChangeModel):
    """Order amendments / invoices / remittances / queries: raise a TRACKED ERP Task
    (and link the related record when we can find one). Returns (refs, note)."""
    label, team = _CHANGE_TASK.get(ch.change_type, ("Handle inbound item", "Operations"))
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == ch.mail_id).first()
    # 1) Supplier invoice -> Supplier + draft Purchase Invoice
    if ch.change_type == "invoice":
        try:
            refs, note = _handle_invoice_change(db, ch, mail)
        except Exception as e:
            refs, note = [], f"{type(e).__name__}: {e}"
        if refs:
            return refs, note
        label = "Enter supplier invoice"
    ref = ch.po_no or ch.so_name or (ch.title or "")[:60]
    subject = f"{label} — {ref} [{team}]"
    detail = _amendment_deltas(ch, mail) if ch.change_type == "order_amendment" else ""
    desc = (f"Cortex Control Tower: inbound {ch.change_type}.\n\n{ch.summary or ch.title}\n"
            + (f"\nRequested change: {detail}\n" if detail else "")
            + f"\nFrom: {ch.from_addr or 'unknown'}")
    # point at the related record when the mail names one we can resolve
    target_dt = target_doc = None
    if ch.po_no:
        for so in (erp.erp_get("Sales Order", fields=["name", "po_no", "docstatus"], limit=0) or []):
            if str(so.get("po_no") or "") == str(ch.po_no):
                target_dt, target_doc = "Sales Order", so["name"]
                break
    tid, created = _task_for_change(subject, desc)
    refs = []
    if target_dt and target_doc:
        refs.append({"doctype": target_dt, "name": target_doc})
    if tid:
        refs.append({"doctype": "Task", "name": tid})
    bits = []
    if target_dt:
        bits.append(f"linked {target_dt} {target_doc}")
    if detail:
        bits.append(f"change: {detail}")
    bits.append(f"raised Task {tid}" if created else (f"Task {tid} already open" if tid else "could not raise a Task"))
    return refs, "; ".join(bits)


def rollback_order_change(db: Session, change_id: int, actor: str = "Ops Manager") -> dict:
    """Undo an approved inbound item: delete everything it created in the ERP and
    put the item back in the queue as pending.

    Deletes in REVERSE creation order (Sales Order -> Item -> Customer) so links
    never block the removal. Never raises.
    """
    _ensure_db()
    ch = db.query(OrderChangeModel).filter(OrderChangeModel.id == int(change_id)).first()
    if not ch:
        return {"ok": False, "error": "not_found"}
    try:
        refs = json.loads(ch.result_refs or "[]") or []
    except Exception:
        refs = []
    # fall back to the single recorded result when the refs list is absent
    if not refs and ch.result_doctype and ch.result_doc:
        refs = [{"doctype": ch.result_doctype, "name": ch.result_doc}]

    removed, failed = [], []
    for ref in reversed(refs):
        dt, nm = ref.get("doctype"), ref.get("name")
        if not dt or not nm:
            continue
        try:
            if erp.erp_doc(dt, nm):
                ok, err = erp.erp_delete(dt, nm)
                (removed if ok else failed).append(
                    f"{dt} {nm}" if ok else f"{dt} {nm}: {err}")
            else:
                removed.append(f"{dt} {nm} (already gone)")
        except Exception as e:
            failed.append(f"{dt} {nm}: {type(e).__name__}")

    ch.status = "pending"
    ch.result_doctype = None
    ch.result_doc = None
    ch.result_refs = None
    ch.result_note = None
    ch.decided_at = None
    ch.decided_by = None
    ch.customer = None
    db.add(AuditLogModel(
        action_type="inbox", action_name="rollback_order_change",
        description=(f"rolled back inbound {ch.change_type}: {ch.title}"
                     + (f" — removed {', '.join(removed)}" if removed else "")
                     + (f"; failed {', '.join(failed)}" if failed else "")),
        actor=actor, approved="no", risk_title=ch.title))
    db.commit()
    db.refresh(ch)
    return {"ok": True, "change": _enrich_change(ch),
            "removed": removed, "failed": failed,
            "note": ("Rolled back — " + ", ".join(removed)) if removed else "nothing was created to roll back"}


def get_inbox_summary(db: Session) -> dict:
    """Counts for the dashboard header."""
    _ensure_db()
    msgs = db.query(MailMessageModel).filter(MailMessageModel.status != "ignored").all()
    changes = db.query(OrderChangeModel).all()
    by_class: dict = {}
    for m in msgs:
        by_class[m.classification] = by_class.get(m.classification, 0) + 1
    return {
        "total_mail": len(msgs),
        "unread": sum(1 for m in msgs if m.status == "new"),
        "by_classification": [
            {"key": k, "label": inbound.CLASS_LABEL.get(k, k), "count": v}
            for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])
        ],
        "pending_changes": sum(1 for c in changes if c.status == "pending"),
        "critical": sum(1 for c in changes if c.status == "pending" and c.severity == "critical"),
        "freshness": _freshness(db, "mail"),
        **READ_ONLY,
    }


def _resolve_customer_for_change(db: Session, ch: OrderChangeModel) -> str:
    """Find an ERP Customer for a flagged mail: by email match, then fuzzy name."""
    if ch.customer:
        return ch.customer
    addr = (ch.from_addr or "").lower()
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == ch.mail_id).first()
    sender_name = (mail.from_name if mail else "") or ""
    try:
        customers = erp.erp_get("Customer", fields=["name", "email_id"], limit=500) or []
    except Exception:
        customers = []
    for c in customers:
        if addr and (c.get("email_id") or "").lower() == addr:
            return c.get("name")
    needle = sender_name.lower().strip()
    if needle:
        for c in customers:
            if needle and (needle in (c.get("name") or "").lower() or (c.get("name") or "").lower() in needle):
                return c.get("name")
    return ""


# ── Buyer auto-provisioning (so an approval never dead-ends on "create it manually") ──
_ROLE_WORDS = re.compile(
    r"\b(purchasing|purchase|procurement|buying|sourcing|import|imports|order desk|orders?|"
    r"accounts?( payable)?|a/?p|billing|finance|sales|admin(istration)?|team|department|dept|"
    r"logistics|operations?|ops|supply chain)\b", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ITEM_RE = re.compile(r"\b([A-Z]{1,3}\d{2,5}(?:-[A-Z0-9]+){1,5})\b")
_QTY_RE = re.compile(r"([\d][\d,]{0,8})\s*(?:pcs|pieces|units|nos)\b", re.I)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


JOINER = " "


def _derive_buyer_name(mail, ch: OrderChangeModel) -> str:
    """'Nordic Retail AB Purchasing' -> 'Nordic Retail AB' (role words stripped)."""
    raw = (getattr(mail, "from_name", "") or "").strip()
    if "<" in raw:
        raw = raw.split("<")[0].strip()
    cleaned = _ROLE_WORDS.sub(JOINER, raw)
    cleaned = re.sub(r"[\s,;:-]{2,}", " ", cleaned).strip(" ,;:-<>")
    if len(cleaned) >= 3:
        return cleaned[:140]
    # fall back to the email domain
    addr = _derive_buyer_email(mail, ch)
    if "@" in addr:
        dom = addr.split("@", 1)[1].split(".")[0]
        if len(dom) >= 3:
            return dom.replace("-", " ").title()[:140]
    return raw[:140] or "Unknown buyer"


def _derive_buyer_email(mail, ch: OrderChangeModel) -> str:
    """Prefer a real buyer address found in the body over the relay/sender."""
    blob = f"{getattr(mail, 'body_text', '') or ''} {getattr(mail, 'snippet', '') or ''} {ch.summary or ''}"
    found = _EMAIL_RE.findall(blob)
    real = [e for e in found if not re.search(r"(gmail\.com|no-?reply|postmaster|mailer-daemon)", e, re.I)]
    if real:
        return real[0][:140]
    return (getattr(mail, "from_addr", "") or "")[:140]


def _pick(options, preferred, default):
    names = [o for o in options if o]
    for p in preferred:
        if p in names:
            return p
    return names[0] if names else default


def _ensure_item_for_line(code: str, ch: OrderChangeModel):
    """Return (item_code, created). Creates a clearly-flagged provisional master
    so an inbound order never dead-ends on a missing Item."""
    if erp.erp_doc("Item", code):
        return code, False
    po = f"PO {ch.po_no}" if ch.po_no else (ch.title or "inbound order")
    payload = {
        "doctype": "Item", "item_code": code, "item_name": code,
        "item_group": "Finished Garments", "stock_uom": "Nos",
        "is_stock_item": 1, "is_sales_item": 1,
        "description": (f"Provisional master auto-created by Cortex OS from inbound {po}. "
                        f"Verify style, fabric, colour and UOM before manufacturing."),
    }
    try:
        ok, doc, err, _n = _intake_exec.create_checked("Item", payload)
    except Exception as e:
        ok, doc, err = False, {}, f"{type(e).__name__}: {e}"
    if ok and doc.get("name"):
        return doc["name"], True
    return None, False


def _parse_order_lines(ch: OrderChangeModel):
    """Pull item / qty / delivery date out of the mail text so the draft Sales Order
    is actually usable. Missing item masters are created provisionally.

    Returns (lines, created_item_codes)."""
    blob = f"{ch.title or ''} {ch.summary or ''}"
    date_m = _DATE_RE.search(blob)
    qty_m = _QTY_RE.search(blob)
    qty = float(qty_m.group(1).replace(",", "")) if qty_m else None
    items, created, skipped, seen = [], [], [], set()
    for code in _ITEM_RE.findall(blob):
        if code in seen:
            continue
        seen.add(code)
        existing = erp.erp_doc("Item", code)
        # A TEMPLATE cannot sit on a transaction line (ERPNext rejects it).
        if existing and existing.get("has_variants"):
            skipped.append(code)
            continue
        item_code, was_created = _ensure_item_for_line(code, ch)
        if not item_code:
            continue
        if was_created:
            created.append(item_code)
        line = {"item_code": item_code}
        if qty:
            line["qty"] = qty
        if date_m:
            line["delivery_date"] = date_m.group(1)
        items.append(line)
    return items, created, skipped


def _ensure_customer_for_change(db: Session, ch: OrderChangeModel):
    """Return (customer_name, created, error). Creates the buyer when it is new."""
    existing = _resolve_customer_for_change(db, ch)
    if existing:
        return existing, False, None
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == ch.mail_id).first()
    name = _derive_buyer_name(mail, ch)
    email = _derive_buyer_email(mail, ch)
    groups = [g.get("name") for g in (erp.erp_get("Customer Group", fields=["name", "is_group"], limit=0) or [])
              if g.get("name") and not g.get("is_group")]
    terr = [t.get("name") for t in (erp.erp_get("Territory", fields=["name", "is_group"], limit=0) or [])
            if t.get("name") and not t.get("is_group")]
    payload = {
        "doctype": "Customer", "customer_name": name, "customer_type": "Company",
        "customer_group": _pick(groups, ["Apparel Buyers", "Commercial"], "Commercial"),
        "territory": _pick(terr, ["Rest Of The World"], "Rest Of The World"),
    }
    if email:
        payload["email_id"] = email
    try:
        ok, doc, err, _n = _intake_exec.create_checked("Customer", payload)
    except Exception as e:
        ok, doc, err = False, {}, f"{type(e).__name__}: {e}"
    if ok and doc.get("name"):
        return doc["name"], True, None
    return "", False, err or "customer create failed"


def decide_order_change(db: Session, change_id: int, decision: str,
                        note: str = "", actor: str = "Ops Manager") -> dict:
    """Approve or dismiss a flagged inbound item.

    Approving a **new order** attempts a real, drafts-only ERP write (a draft
    Sales Order) and records exactly what happened. Nothing is submitted.
    """
    _ensure_db()
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "dismiss"):
        return {"ok": False, "error": "decision must be 'approve' or 'dismiss'"}
    ch = db.query(OrderChangeModel).filter(OrderChangeModel.id == int(change_id)).first()
    if not ch:
        return {"ok": False, "error": "not_found"}
    if ch.status != "pending":
        # already decided — still return the FULL enriched shape so the UI keeps the
        # Open-in-ERP link and the roll-back affordance.
        return {"ok": True, "change": _enrich_change(ch), "note": "already_decided"}

    ch.decided_at = datetime.now()
    ch.decided_by = actor

    if decision == "dismiss":
        ch.status = "dismissed"
        ch.result_note = note or "dismissed by operator"
    else:
        # A decision is only COMPLETE when the ERP work actually happened. If the
        # write could not finish, the row stays pending so the item never vanishes
        # from the queue — the operator finishes it in the ERP and approves again.
        ch.status = "approved"
        # One mail must never produce two orders. If the intake agent has already
        # read this mail, the intake card owns the decision — point there instead
        # of creating a second, header-only Sales Order from the change queue.
        if ch.change_type == "new_order":
            try:
                run = (db.query(IntakeRunModel)
                       .filter(IntakeRunModel.mail_id == ch.mail_id)
                       .order_by(desc(IntakeRunModel.id)).first())
            except Exception:
                run = None
            if run and run.status == "approved":
                refs = json.loads(run.created_refs or "[]")
                first = next((r for r in refs if r.get("doctype") == "Client Purchase Order"), None)
                ch.result_doctype = first["doctype"] if first else "Intake"
                ch.result_doc = first["name"] if first else f"intake #{run.id}"
                ch.result_note = (f"already handled by Order intake #{run.id} — "
                                  f"{', '.join(r['doctype'] + ' ' + r['name'] for r in refs) or 'no records'}")
                db.commit()
                return {"ok": True, "change": _enrich_change(ch), "note": ch.result_note}
            if run and run.status in ("understood", "simulated"):
                ch.status = "pending"
                ch.result_note = (f"this mail is in Order intake #{run.id} — approve it there; "
                                  f"the intake creates the Client PO and the order in one step")
                db.commit()
                return {"ok": True, "change": _enrich_change(ch), "note": ch.result_note}
        if ch.change_type == "new_order":
            if not writes.mode_allows("draft"):
                ch.result_note = f"approved; ERP write mode '{writes.current_mode()}' does not allow draft creation"
            else:
                customer, created_cust, cerr = _ensure_customer_for_change(db, ch)
                if not customer:
                    ch.status = "pending"      # keep it in the queue — needs a human in the ERP
                    ch.result_note = (f"could not resolve or create the Customer "
                                      f"({cerr or 'unknown error'}) — add it in the ERP, then approve again")
                else:
                    ch.customer = customer
                    # Duplicate guard: if this PO is already in the ERP it is not a NEW
                    # order — point at the existing Sales Order instead of cloning it.
                    if ch.po_no:
                        dupe = next((s for s in (erp.erp_get("Sales Order", fields=["name", "po_no"], limit=0) or [])
                                     if str(s.get("po_no") or "") == str(ch.po_no)), None)
                        if dupe:
                            ch.status = "pending"
                            ch.result_doctype, ch.result_doc = "Sales Order", dupe["name"]
                            ch.result_refs = json.dumps([{"doctype": "Sales Order", "name": dupe["name"]}])
                            ch.result_note = (f"PO {ch.po_no} already exists as Sales Order {dupe['name']} — "
                                              f"this is not a new order; review it there, then dismiss this item")
                            db.commit()
                            return {"ok": True, "change": _enrich_change(ch),
                                    "note": ch.result_note}
                    lines, new_items, skipped_tpl = _parse_order_lines(ch)
                    # Everything this approval creates, so it can be rolled back.
                    refs = []
                    if created_cust:
                        refs.append({"doctype": "Customer", "name": customer})
                    for it in new_items:
                        refs.append({"doctype": "Item", "name": it})
                    ch.result_refs = json.dumps(refs)
                    today = date.today().isoformat()
                    company = _pick([c.get("name") for c in (erp.erp_get("Company", fields=["name"], limit=0) or [])],
                                    ["CORTEX FASHION (HK) LIMITED"], "")
                    # ERPNext refuses to save a stock line without a source warehouse.
                    fg_wh = next((w.get("name") for w in (erp.erp_get(
                        "Warehouse", fields=["name"],
                        filters=[["company", "=", company], ["is_group", "=", 0]], limit=0) or [])
                        if "finished" in (w.get("name") or "").lower()), None)
                    payload = {
                        "customer": customer,
                        "company": company,
                        "currency": "USD",
                        "po_no": ch.po_no or "",
                        "transaction_date": today,
                        "delivery_date": lines[0].get("delivery_date", today) if lines else today,
                        "custom_from_mail": ch.id,
                    }
                    if fg_wh:
                        payload["set_warehouse"] = fg_wh
                    if lines:
                        payload["items"] = lines
                    try:
                        ok, doc, err, _n = _intake_exec.create_checked("Sales Order", payload)
                    except Exception as e:
                        ok, doc, err = False, {}, f"{type(e).__name__}: {e}"
                    if ok and doc.get("name"):
                        ch.result_doctype = "Sales Order"
                        ch.result_doc = doc["name"]
                        refs.append({"doctype": "Sales Order", "name": doc["name"]})
                        ch.result_refs = json.dumps(refs)
                        bits = []
                        if created_cust:
                            bits.append(f"created Customer '{customer}'")
                        if new_items:
                            bits.append(f"created provisional item(s) {', '.join(new_items)}")
                        bits.append(f"draft Sales Order {doc['name']}")
                        if skipped_tpl:
                            bits.append(f"size not chosen for template {', '.join(skipped_tpl)} — pick a variant")
                        if not lines:
                            bits.append("header only — no item line found in the mail")
                        ch.result_note = "approved; " + " + ".join(bits)
                    else:
                        # The ERP write did not finish -> the item stays OPEN so it does
                        # not vanish; the operator completes it in the ERP and retries.
                        ch.status = "pending"
                        if created_cust:
                            ch.result_doctype = "Customer"
                            ch.result_doc = customer
                        ch.result_note = (
                            f"needs ERP input — {err or 'unknown error'}. "
                            f"{'Customer created; ' if created_cust else ''}"
                            f"finish it in the ERP, then approve again.")
        else:
            # Amendment / invoice / remittance / query: raise a TRACKED task (and link
            # the related record). The item STAYS in the queue until it is dismissed.
            refs = []
            try:
                refs, bits = _handle_other_change(db, ch)
            except Exception as e:
                bits = f"{type(e).__name__}: {e}"
            ch.status = "pending"
            ch.result_refs = json.dumps(refs) if refs else None
            if refs:
                first = refs[-1]                      # the Task is last
                ch.result_doctype, ch.result_doc = first["doctype"], first["name"]
            ch.result_note = (f"{bits} — handle it in the ERP, then dismiss this item"
                              if refs else
                              f"could not act automatically ({bits}) — handle it in the ERP")

    db.add(AuditLogModel(
        action_type="inbox", action_name="decide_order_change",
        description=f"{decision}d inbound {ch.change_type}: {ch.title}",
        actor=actor, approved=("yes" if decision == "approve" else "no"), risk_title=ch.title))
    db.commit()
    db.refresh(ch)
    change = _enrich_change(ch)
    out = {"ok": True, "change": change}
    if change.get("needs_action"):
        out["note"] = ("Still open — finish it in the ERP, then approve again. "
                       + (ch.result_note or ""))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# CHAT MODULE — Kogo Agent Chat Functions
# ═══════════════════════════════════════════════════════════════════════════

# Import config values from config.py. These are the ONLY source for IDs/paths.
# The JWT is NEVER imported here — it is read from the USER_JWT_TOKEN env var at
# runtime inside _chat_headers(). (See Pre-Flight: all 6 names below must exist
# in config.py, or STOP and report — do not fabricate.)
from config import (
    AGENT_ID as CFG_AGENT_ID,
    DEPLOYMENT_ID as CFG_DEPLOYMENT_ID,
    USER_ID as CFG_USER_ID,
    CHAT_API_PATH as CFG_CHAT_API_PATH,
    API_PATH as CFG_API_PATH,
    SWARM_ID as CFG_SWARM_ID,
)

CHAT_MODULE_CHAT_API_PATH = CFG_CHAT_API_PATH  # from env CHAT_API_PATH
CHAT_MODULE_USER_ID = CFG_USER_ID
CHAT_MODULE_DEPLOYMENT_ID = CFG_DEPLOYMENT_ID  # from env DEPLOYMENT_ID (the deployment id)
# SWARM_ID: empty string means "no workspace" (direct agent context).
# Also guard against the legacy "null" string sentinel from old configs.
CHAT_MODULE_SWARM_ID = CFG_SWARM_ID if CFG_SWARM_ID and CFG_SWARM_ID != "null" else None
# AGENT_ID / DEPLOYMENT_ID / SWARM_ID are ALWAYS distinct ids — never equal.
CHAT_MODULE_AGENT_ID = CFG_AGENT_ID  # from env AGENT_ID (the agent's own id)
# API_PATH from env is the GraphQL gateway URL (ends with /gateway).
# Derive base (without /gateway) for api_path response field.
CHAT_MODULE_BASE = CFG_API_PATH[:-len("/gateway")] if CFG_API_PATH.endswith("/gateway") else CFG_API_PATH
CHAT_MODULE_API_PATH = CFG_API_PATH if CFG_API_PATH.endswith("/gateway") else f"{CFG_API_PATH}/gateway"


def _chat_headers() -> dict:
    return {
        "Authorization": os.environ.get("USER_JWT_TOKEN", ""),  # runtime only
        "Content-Type": "application/json",
    }


def clean_boat_reply(raw: str) -> str:
    if not raw: return ""
    text = raw
    for tag in ["starttime", "endtime", "icon", "loader", "summary", "file"]:
        text = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", text, flags=re.DOTALL)
    # Strip the model's private reasoning block — it must NEVER reach the user.
    # 1) the paired <think>…</think> block; 2) an unterminated <think…> at the tail
    # (mid-stream); 3) any orphan/closing tag left behind.
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think\b.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d{13}", "", text)
    text = re.sub(r"fa-(?:regular|solid) fa-[\w-]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {3,}", " ", text)
    return text.strip()


def get_chat_config(db: Session) -> dict:
    # All values from config.py. Fail loud if the module is not configured —
    # never hand the frontend an empty chat_api_path (would build a hostless URL).
    if not CHAT_MODULE_CHAT_API_PATH or not CHAT_MODULE_API_PATH:
        return {"error": "chat module not configured: missing CHAT_API_PATH"}
    if not CHAT_MODULE_DEPLOYMENT_ID and not CHAT_MODULE_SWARM_ID:
        return {"error": "chat module not configured: missing DEPLOYMENT_ID and SWARM_ID"}
    return {
        "api_path": CHAT_MODULE_BASE,
        "chat_api_path": CHAT_MODULE_CHAT_API_PATH,
        "user_id": CHAT_MODULE_USER_ID,
        "deployment_id": CHAT_MODULE_DEPLOYMENT_ID,
        "swarm_id": CHAT_MODULE_SWARM_ID,
        "agent_id": CHAT_MODULE_AGENT_ID,
        "token": os.environ.get("USER_JWT_TOKEN", ""),  # runtime only
        "agent_name": "",
        "agent_icon": "",
    }


def create_room(db: Session) -> dict:
    """Create a user room via the Kogo GraphQL gateway. Must be called before any chat interaction."""
    # FIXED CONTRACT: GraphQL operation "register_user_room" — verbatim, never renamed/invented.
    payload = {
        "query": (
            "mutation Register_user_room($sender: ID) {\n"
            "  register_user_room(sender: $sender) {\n"
            "    _id\n"
            "  }\n"
            "}"
        ),
        "variables": {"sender": CHAT_MODULE_USER_ID},
    }
    try:
        resp = requests.post(CHAT_MODULE_API_PATH, json=payload, headers=_chat_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        room_data = (data.get("data") or {}).get("register_user_room")
        if room_data is None:
            return {"error": "No data returned from register_user_room", "raw": data}
        return {"room_id": room_data["_id"]}
    except requests.exceptions.RequestException as e:
        return {"error": f"Room creation failed: {e}"}
    except (KeyError, TypeError) as e:
        return {"error": f"Unexpected room creation response: {e}"}


def send_message(
    db: Session,
    message: str,
    thread_id: Optional[str] = None,
    deployment_id: str = "",
    swarm_id: Optional[str] = None,
) -> dict:
    """Send a user message to the agent via SSE streaming. Backend accumulates the full stream."""
    dep_id = deployment_id or CHAT_MODULE_DEPLOYMENT_ID
    # swarm_id "null" sentinel (see config import block) is normalized to None.
    swm_id = swarm_id if swarm_id is not None else (CHAT_MODULE_SWARM_ID if CHAT_MODULE_SWARM_ID and CHAT_MODULE_SWARM_ID != "null" else None)

    # Fail loud — never POST a hostless URL or an empty deployment_id.
    if not CHAT_MODULE_CHAT_API_PATH:
        return {"error": "chat module not configured: missing CHAT_API_PATH"}
    if not dep_id and not swm_id:
        return {"error": "chat module not configured: missing DEPLOYMENT_ID and SWARM_ID"}

    # FIXED CONTRACT: endpoint path "deployment_stream_kogo_os_stream" — verbatim,
    # never altered, abbreviated, or invented.
    url = f"{CHAT_MODULE_CHAT_API_PATH}/deployment_stream_kogo_os_stream"
    payload = {
        "sender": CHAT_MODULE_USER_ID,
        "guest_sender": None,
        "guest_name": None,
        "thread_id": thread_id,
        "message": message,
        "deployment_id": dep_id,
        "kogo_swarm_id": swm_id,
    }

    created_thread_id = None
    boatReply = ""
    repliedAgent = None
    chat_id = None
    chat_ref_id = None
    cardContent = None

    try:
        with requests.post(url, json=payload, headers=_chat_headers(), stream=True, timeout=120) as resp:
            resp.raise_for_status()
            # The SSE endpoint is text/event-stream with no charset, so requests would
            # otherwise default to ISO-8859-1 and mangle every UTF-8 char (em dashes,
            # emoji) into Latin-1 mojibake. Force UTF-8 before iterating the stream.
            resp.encoding = "utf-8"
            buffer = ""
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if not chunk:
                    continue
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", errors="replace")
                buffer += chunk
                while "\n\n" in buffer:
                    event_raw, buffer = buffer.split("\n\n", 1)
                    data_str = None
                    for line in event_raw.split("\n"):
                        if line.startswith("data:"):
                            data_str = line[len("data:"):].strip()
                            break
                    if not data_str:
                        continue
                    try:
                        event_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    event_type = event_data.get("type", "")
                    inner = event_data.get("data", {})
                    if event_type == "streaming":
                        if inner.get("boatReply"):
                            boatReply += inner["boatReply"]
                        if created_thread_id is None and inner.get("created_thread_id"):
                            created_thread_id = inner["created_thread_id"]
                        if repliedAgent is None and inner.get("repliedAgent"):
                            repliedAgent = inner["repliedAgent"]
                        if not cardContent and inner.get("cardContent"):
                            cardContent = inner["cardContent"]
                    elif event_type == "final":
                        if inner.get("boatReply"):
                            boatReply = inner["boatReply"]
                        if inner.get("created_thread_id"):
                            created_thread_id = inner["created_thread_id"]
                        if inner.get("repliedAgent"):
                            repliedAgent = inner["repliedAgent"]
                        if inner.get("chat_id"):
                            chat_id = inner["chat_id"]
                        if inner.get("chat_ref_id"):
                            chat_ref_id = inner["chat_ref_id"]
                        if inner.get("cardContent"):
                            cardContent = inner["cardContent"]

        result = {
            "created_thread_id": created_thread_id,
            "boatReply": boatReply,
            "message": clean_boat_reply(boatReply),
            "repliedAgent": repliedAgent,
            "chat_id": chat_id,
            "cardContent": cardContent if cardContent else None,
        }
        if chat_ref_id:
            result["chat_ref_id"] = chat_ref_id
        return result
    except requests.exceptions.RequestException as e:
        return {"error": f"Message send failed: {e}"}
    except Exception as e:
        return {"error": f"Stream processing error: {e}"}


def fetch_threads(db: Session, room_id: str) -> dict:
    """Fetch the chat thread list for a room.

    ⭐ FIXED CONTRACT — thread scoping has TWO cases. Pick the case by whether a SWARM_ID
    exists, and send EXACTLY the keys listed for that case (nothing more, nothing less):

      • WORKSPACE / SWARM context  (CHAT_MODULE_SWARM_ID is set):
            { "isKogoSwramThread": True,  "roomId": <room_id>, "swarmId": <SWARM_ID> }
        → do NOT send deploymentId.
      • DIRECT AGENT context       (CHAT_MODULE_SWARM_ID is None / empty):
            { "isKogoSwramThread": False, "roomId": <room_id>, "deploymentId": <DEPLOYMENT_ID> }
        → do NOT send swarmId.

    ⚠️ The GraphQL argument is literally spelled `is_kogo_swram_thread` — note "swram", NOT
       "swarm". This is the server's real (misspelled) field name; copy it verbatim and NEVER
       "fix" the spelling, or the query fails. Same for the variable `$isKogoSwramThread`.
    """
    # Branch strictly on SWARM_ID presence — this is what decides swarm vs agent threads.
    if CHAT_MODULE_SWARM_ID:
        variables: dict = {
            "roomId": room_id,
            "isKogoSwramThread": True,
            "swarmId": CHAT_MODULE_SWARM_ID,
        }
    else:
        variables = {
            "roomId": room_id,
            "isKogoSwramThread": False,
            "deploymentId": CHAT_MODULE_DEPLOYMENT_ID or None,
        }
    # FIXED CONTRACT: operation "getChatThreadList_kogoos", the arg name
    # "is_kogo_swram_thread" (real server typo), and the response field names — all verbatim.
    # The query declares all branch variables; the unused one is simply null for that case.
    payload = {
        "query": (
            "query GetChatThreadList_kogoos($roomId: ID!, $isKogoSwramThread: Boolean, $swarmId: ID, $deploymentId: ID) {\n"
            "  getChatThreadList_kogoos(room_id: $roomId, is_kogo_swram_thread: $isKogoSwramThread, swarm_id: $swarmId, deployment_id: $deploymentId) {\n"
            "    _id\n    title\n    summary\n    deployment_id\n    kogo_swarm_id\n"
            "    last_chat_time\n    dateCategory\n    unread_count\n    agent_category_id\n    job_type\n"
            "  }\n}"
        ),
        "variables": variables,
    }
    try:
        resp = requests.post(CHAT_MODULE_API_PATH, json=payload, headers=_chat_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        threads = (data.get("data") or {}).get("getChatThreadList_kogoos")
        if threads is None:
            return {"threads": [], "error": "No data returned from getChatThreadList_kogoos", "raw": data}
        return {"threads": threads}
    except requests.exceptions.RequestException as e:
        return {"error": f"Fetch threads failed: {e}"}
    except (KeyError, TypeError) as e:
        return {"error": f"Unexpected threads response: {e}"}


def fetch_chat_history(db: Session, thread_id: str) -> dict:
    """Fetch full chat history for a specific thread."""
    # FIXED CONTRACT: GraphQL operation "kogoos_getChatsAndLogs" and its response
    # field names (incl. card_data { card_content { item_info } }) — verbatim, never
    # renamed/invented.
    payload = {
        "query": (
            "query Kogoos_getChatsAndLogs($thread_id: ID!) {\n"
            "  kogoos_getChatsAndLogs(thread_id: $thread_id) {\n"
            "    logs { _id message thread_id timestamp type vendor_id }\n"
            "    schedule_info { first_run last_run runs_at next_run }\n"
            "    thread { _id summary title agent_category_id last_chat_time kogo_swarm_id }\n"
            "    chats { _id sent_at agent { icon name } card_data { _id card_content { item_info } card_description card_icon card_type } message translated_message chat_ref_id isHumanReply user { _id first_name last_name email } file_datas { file_type file_extension file_name file_path } likeStatus likeFeedback is_msg_read }\n"
            "    deployment_details { _id deployment_name icon }\n"
            "    videoChatData { audio_recording_path created_at end_time meeting_url start_time thread_id call_duration }\n"
            "    ticket_ids\n"
            "  }\n}"
        ),
        "variables": {"thread_id": thread_id},
    }
    try:
        resp = requests.post(CHAT_MODULE_API_PATH, json=payload, headers=_chat_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result_data = (data.get("data") or {}).get("kogoos_getChatsAndLogs")
        if result_data is None:
            return {"chats": [], "thread": {}, "deployment_details": {}, "logs": [], "error": "No data returned", "raw": data}
        return {
            "chats": result_data.get("chats", []),
            "thread": result_data.get("thread", {}),
            "deployment_details": result_data.get("deployment_details", {}),
            "logs": result_data.get("logs", []),
            "schedule_info": result_data.get("schedule_info"),
            "videoChatData": result_data.get("videoChatData", []),
            "ticket_ids": result_data.get("ticket_ids", []),
        }
    except requests.exceptions.RequestException as e:
        return {"error": f"Fetch chat history failed: {e}"}
    except (KeyError, TypeError) as e:
        return {"error": f"Unexpected chat history response: {e}"}


# ── Ask KOGO — retired-invoker shim ─────────────────────
# The long-prompt grounded-copilot path (copilot.py) was replaced by the streaming
# chat module above. An OLDER cached frontend may still call `ask_kogo`; this shim
# answers with an actionable pointer instead of leaving the button dead.
# Remove once no legacy client remains.
def ask_kogo(db: Session, question: str = "", context: dict = None) -> dict:
    return {
        "answer": ("**Ask KOGO is now a full chat.** Close and reopen the app "
                   "(hard-refresh with Ctrl/Cmd+Shift+R) to load the new streaming chat, "
                   "then use the \u2728 Ask KOGO button."),
        "related": [],
        "grounded": True,
        "evidence_sections": [],
        "retired": True,
        "live": True, "source": SOURCE, "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# INTAKE — mail → understanding → ERP drafts (see docs/INTAKE_PLAN_EMAIL_TO_PROCESS.md)
#
# Every function here is additive. The only one that writes to the ERP is
# `approve_intake`, and it writes drafts only (intake_exec.execute).
# ═══════════════════════════════════════════════════════════════════════════

import base64 as _b64
import hashlib as _hashlib

import docread as _docread
import intake as _intake
import intake_exec as _intake_exec
import chain as _chain
import inquiry as _inquiry
import pack_ingest as _pack_ingest
from models import (IntakeEditModel, IntakeRunModel, MailAttachmentModel, MailChainModel,
                    BuyerInquiryModel)

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
MAIL_DIR = os.path.join(BACKEND_DIR, "data", "mail")


def _resolve_stored_path(path: str) -> str:
    """Rebuild an absolute path from what is in the DB.

    The same project is executed from a different mount on the platform, so an
    absolute path written by one runtime is dead in the other (2026-11-03). Only
    the part below ``backend/`` is stored, and it is resolved here.
    """
    if not path:
        return ""
    p = str(path)
    if os.path.isabs(p):
        if "/backend/" in p:
            p = p.split("/backend/", 1)[1]
        elif os.path.exists(p):
            return p
        else:
            return ""
    return os.path.join(BACKEND_DIR, p)

# mails that can start a process even without an attachment
INTAKE_CLASSES = {inbound.CLASS_NEW_ORDER, inbound.CLASS_AMENDMENT, inbound.CLASS_QUERY,
                  inbound.CLASS_INVOICE, inbound.CLASS_REMITTANCE}


def _intake_dir(*parts) -> str:
    path = os.path.join(MAIL_DIR, *[str(p) for p in parts])
    os.makedirs(os.path.dirname(path) if parts else MAIL_DIR, exist_ok=True)
    return path


def _store_attachment(db: Session, mail: MailMessageModel, att: dict) -> Optional[MailAttachmentModel]:
    """Decode, hash, store and READ one attachment. Returns its row."""
    raw = b""
    if att.get("data"):
        try:
            raw = _b64.b64decode(att["data"])
        except Exception:
            raw = b""
    sha = _hashlib.sha256(raw).hexdigest() if raw else ""
    row = MailAttachmentModel(
        mail_id=mail.id, filename=(att.get("filename") or "")[:400],
        mime=(att.get("mime") or "")[:120], size=len(raw) or int(att.get("size") or 0),
        sha256=sha, ok=0, needs_ocr=0, chars=0, pages=0,
    )
    if raw:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (att.get("filename") or "attachment"))[:120]
        path = _intake_dir(mail.id, f"{sha[:12]}_{safe}")
        try:
            with open(path, "wb") as fh:
                fh.write(raw)
            row.path = os.path.relpath(path, BACKEND_DIR)   # portable across mounts
        except Exception as e:
            row.error = f"store_failed: {e}"
    elif att.get("too_large"):
        row.error = (f"too_large — {int(att.get('size') or 0) / 1048576:.1f} MB is over the {config.MAX_ATTACHMENT_MB} MB "
                     f"limit this mailbox keeps, so it was not read. Ask for a smaller file, or upload it on the deal.")
    else:
        row.error = "attachment_bytes_missing"

    if raw:
        try:
            res = _docread.read_attachment(att.get("filename") or "", att.get("mime") or "", raw)
        except Exception as e:                      # docread never raises, but be safe
            res = {"ok": False, "text": "", "parser": "", "pages": 0, "chars": 0,
                   "needs_ocr": False, "error": f"{type(e).__name__}: {e}"}
        row.ok = 1 if res.get("ok") else 0
        row.parser = (res.get("parser") or "")[:40]
        row.pages = int(res.get("pages") or 0)
        row.chars = int(res.get("chars") or 0)
        row.needs_ocr = 1 if res.get("needs_ocr") else 0
        row.text = res.get("text") or ""
        try:
            row.layout = json.dumps(res.get("layout") or [])
        except Exception:
            row.layout = "[]"
        if not res.get("ok"):
            row.error = (res.get("error") or "unreadable")[:300]
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mail_text(mail: MailMessageModel) -> str:
    """The best available 'paper' text: attachment text first, then the body."""
    return (mail.body_text or "").strip()


def _open_document_runs(db: Session, mail: MailMessageModel, attachments: list,
                        use_llm: bool = False) -> list:
    """Open ONE intake run per document a mail carries.

    A buyer put three POs and three BOMs in one mail. Reading "the biggest attachment" made
    one card about one PDF and dropped two orders and every BOM without a word (2026-11-03).
    An order is a document, so each order-like file gets its own run and its own card; the
    pack documents (BOM / tech pack) ride together on one card, because they are evidence
    for the styles rather than orders.
    """
    readable = [a for a in (attachments or []) if a.ok and a.text and a.chars >= 120]
    order_docs, pack_docs = [], []
    for a in readable:
        kind = _intake.doc_kind(a.text or "", a.filename or "")
        if _intake.is_order_document(kind):
            order_docs.append(a)
        elif kind in ("bom", "tech_pack"):
            pack_docs.append(a)
    made = []
    # one pack card per conversation: the same three BOMs arrived twice (a forward and a
    # re-send), and two cards offering the same ingest is noise, not information
    if pack_docs:
        want = {a.sha256 for a in pack_docs if a.sha256}
        if want and mail.chain_id:
            for other in (db.query(IntakeRunModel)
                          .filter(IntakeRunModel.chain_id == mail.chain_id,
                                  IntakeRunModel.status != "rejected",
                                  IntakeRunModel.route == "chain_reply")
                          .all()):
                try:
                    of = json.loads(other.facts or "{}")
                except Exception:
                    continue
                have = {d.get("sha") for d in (of.get("_pack_documents") or []) if d.get("sha")}
                if want and want <= have:
                    pack_docs = []      # already on the queue for this thread
                    break
    for doc in order_docs:
        run = _understand_mail(db, mail, attachments, use_llm=use_llm, attachment_id=doc.id)
        if run:
            made.append(run)
    if pack_docs:
        run = _understand_mail(db, mail, attachments, use_llm=use_llm,
                               attachment_id=pack_docs[0].id)
        if run:
            made.append(run)
    if not made:
        # body-only mail: a question, a confirmation, a one-line reply
        run = _understand_mail(db, mail, attachments, use_llm=use_llm)
        if run:
            made.append(run)
    return made


def _understand_mail(db: Session, mail: MailMessageModel, attachments: list,
                     use_llm: bool = False, run_id_hint: Optional[int] = None,
                     attachment_id: Optional[int] = None) -> Optional[IntakeRunModel]:
    """Extract → gates → match → plan, and store ONE run for ONE document.

    ``attachment_id`` picks the document this run is about. Without it the biggest readable
    attachment is used — which is how a mail carrying **three POs and three BOMs** produced
    a single card for whichever PDF happened to be largest, and dropped the other five
    documents on the floor (2026-11-03). The caller now opens one run per document.
    """
    readable = [a for a in (attachments or []) if a.ok and a.text and a.chars >= 120]
    if attachment_id:
        primary = next((a for a in readable if a.id == int(attachment_id)), None)
        if primary is None:
            primary = next((a for a in (attachments or []) if a.id == int(attachment_id)), None)
    else:
        primary = max(readable, key=lambda a: a.chars) if readable else None
    doc_text = (primary.text or "") if primary is not None else ""

    # Every document in the mail, classified — so the card can say what came with it even
    # though this run is about one of them.
    documents = []
    for a in (attachments or []):
        if not (a.ok and a.text and a.chars >= 120):
            documents.append({"attachment_id": a.id, "filename": a.filename or "",
                              "kind": "unreadable", "chars": a.chars or 0,
                              "needs_ocr": bool(a.needs_ocr)})
            continue
        kind = _intake.doc_kind(a.text or "", a.filename or "")
        documents.append({"attachment_id": a.id, "filename": a.filename or "",
                          "kind": kind, "chars": a.chars or 0,
                          "sha": a.sha256 or "",
                          "order": _intake.is_order_document(kind)})

    layout = []
    if primary is not None and getattr(primary, "layout", None):
        try:
            layout = json.loads(primary.layout)
        except Exception:
            layout = []
    facts = _intake.extract_deterministic(doc_text, subject=mail.subject or "",
                                          body=mail.body_text or "",
                                          from_name=mail.from_name or "",
                                          from_addr=mail.from_addr or "",
                                          layout=layout)
    extractors_used = "deterministic"
    if use_llm and (doc_text or mail.body_text):
        # A model call that fails must be VISIBLE. It used to be swallowed, so a
        # weak pattern read looked exactly like a good one (2026-11-03).
        try:
            llm = _intake.extract_with_llm(db, doc_text, subject=mail.subject or "",
                                           body=mail.body_text or "")
            if llm:
                facts = _intake.merge(facts, llm)
                extractors_used = "deterministic+llm"
                facts.setdefault("extractors", [])
                if "llm" not in facts["extractors"]:
                    facts["extractors"].append("llm")
            else:
                extractors_used = "deterministic (model returned nothing)"
        except Exception as ex:                                        # noqa: BLE001
            extractors_used = f"deterministic (model failed: {type(ex).__name__})"
    facts["_provenance"] = extractors_used
    # A re-read must never silently undo a human correction: the operator's edits
    # are re-applied on top of whatever the readers produced.
    if run_id_hint:
        try:
            for ed in (db.query(IntakeEditModel)
                       .filter(IntakeEditModel.run_id == int(run_id_hint))
                       .order_by(IntakeEditModel.id).all()):
                try:
                    val = json.loads(ed.corrected) if ed.corrected else None
                except Exception:
                    val = ed.corrected
                if ed.field.startswith("lines."):
                    parts = ed.field.split(".")
                    facts["lines"][int(parts[1])][parts[2]] = val
                else:
                    node = facts
                    parts = ed.field.split(".")
                    for p in parts[:-1]:
                        node = node.setdefault(p, {})
                    node[parts[-1]] = val
                facts.setdefault("confidence", {})[ed.field] = 0.99
        except Exception:
            pass
    facts = _intake.check_arithmetic(facts)
    facts["_message_id"] = mail.message_id or f"uid:{mail.uid}"

    # The buyer names their file after the order: "HL93312 PO71242 C9533-U71-725 PO.pdf".
    # When the paper itself did not yield a number, the name is evidence — not a guess, and
    # not something to be invented. Without it a real order sits blocked on "no PO number"
    # until a person types it (2026-11-03).
    if primary is not None and not (facts.get("po") or {}).get("number"):
        hit = re.search(r"\b(?:po|p\.?\s?o\.?)[\s_\-.#:]*([0-9]{3,8})\b",
                        primary.filename or "", re.I)
        if hit:
            facts.setdefault("po", {})["number"] = hit.group(1)
            facts.setdefault("po_source", "filename")
            facts.setdefault("confidence", {})["po.number"] = 0.6

    # Which conversation is this? Found BEFORE worthiness, because a one-line reply
    # ("pack attached") only matters because of the thread it answers.
    chain_row = None
    try:
        chain_row = _chain.find(db, references=mail.thread_id, own_id=mail.message_id)
    except Exception:                                                # noqa: BLE001
        chain_row = None
    chain_live = bool(_chain.context(db, chain_row.id).get("live")) if chain_row is not None else False

    # A card is only opened for mail that actually carries a business document.
    # Without this, every newsletter with a logo attachment becomes an "intake".
    if not _is_intake_worthy(facts, mail, primary, chain_live=chain_live):
        if chain_row is not None:      # keep the thread's timeline whole, card or no card
            try:
                _chain.attach(db, mail)
            except Exception:                                        # noqa: BLE001
                pass
        return None
    facts["_attachment"] = (primary.filename if primary is not None else "")
    facts["_attachment_kind"] = _intake.doc_kind(
        (primary.text or "") if primary is not None else "",
        (primary.filename or "") if primary is not None else "")
    facts["_documents"] = documents
    # The pack documents this mail carries — one ingest step each, never "the biggest one".
    # Only on the card whose OWN document is not an order: a PO card is about the PO, and the
    # pack card is about the packs, otherwise three PO cards would each offer to ingest the
    # same three BOMs (2026-11-03).
    own_kind = facts.get("_attachment_kind") or "other"
    facts["_pack_documents"] = [] if _intake.is_order_document(own_kind) else [
        {"attachment_id": d["attachment_id"], "filename": d["filename"],
         "kind": d["kind"], "chars": d["chars"], "sha": d.get("sha")}
        for d in documents if d["kind"] in ("bom", "tech_pack")]
    # what the planner needs about the DOCUMENT, not just its name: an ingest step needs
    # the row id (to resolve the file), and "is this a pack?" is answered by its contents
    facts["_attachment_id"] = primary.id if primary is not None else None
    facts["_attachment_name"] = (primary.filename if primary is not None else "")
    facts["_pack_words"] = _intake_exec.pack_words(
        primary.filename if primary is not None else "",
        primary.mime if primary is not None else "", primary.text if primary is not None else "")

    # Every style code the mail names — one enquiry can ask about three, and the register
    # (and the Opportunity's line table) needs all of them, not just the first (2026-11-03).
    try:
        facts["styles"] = _inquiry.styles_for_mail(
            mail.subject or "", mail.body_text or "",
            (primary.text if primary is not None else "")[:40000])
    except Exception:
        facts["styles"] = []

    matches = _intake.match(db, facts)

    # ── the chain ────────────────────────────────────────────────────────────
    # A conversation already under way answers for itself: its buyer and its style are
    # known, so a one-line reply ("pack attached, go ahead") still belongs to the deal.
    try:
        chain_row = _chain.attach(db, mail)
        if chain_row is not None:
            ctx = _chain.context(db, chain_row.id)
            matches["chain"] = ctx
            if chain_row.customer and not matches.get("customer"):
                matches["customer"] = chain_row.customer
            if chain_row.customer_name:
                matches["chain_customer_name"] = chain_row.customer_name
            if chain_row.style_code and not (facts.get("style") or {}).get("code"):
                facts.setdefault("style", {})["code"] = chain_row.style_code
            if chain_row.buyer_name and not (facts.get("buyer") or {}).get("name"):
                facts.setdefault("buyer", {})["name"] = chain_row.buyer_name
    except Exception as ex:                                          # noqa: BLE001
        matches["chain_error"] = f"{type(ex).__name__}: {ex}"

    # The ERP's Customer name wins over whatever the model read off a page heading. One PO
    # PDF opens with "SAMPLE REQUIREMENTS: S/1 REQUIRED", and that became the buyer's name,
    # the Project name and the register line (2026-11-03). The raw read is kept beside it.
    if matches.get("customer") and not matches.get("po_other_buyer") \
            and not matches.get("customer_candidates"):
        buyer_node = facts.setdefault("buyer", {})
        if (buyer_node.get("name") or "") != matches["customer"]:
            if buyer_node.get("name"):
                buyer_node["name_as_read"] = buyer_node["name"]
            buyer_node["name"] = matches["customer"]

    # what is already on file for this PO (for the revision diff / duplicate guard)
    if matches.get("po_existing"):
        try:
            cpo = erp.erp_doc("Client Purchase Order", matches["po_existing"]) or {}
            matches["po_existing_detail"] = {"total_qty": cpo.get("total_qty") or cpo.get("qty"),
                                             "ship_date": cpo.get("ship_date"),
                                             "currency": cpo.get("currency")}
        except Exception:
            pass
    # a scan is a blocker the operator must see, not a footnote
    if primary is not None and primary.needs_ocr:
        matches.setdefault("blocking", []).append("document_is_a_scan_needs_ocr")

    # The revision diff needs the earlier reading of the SAME PO — from an earlier
    # intake run of a plain purchase order, because the CPO may not exist yet (the
    # first mail of a new-PO + revision pair). Direction matters: a revision looks
    # back at the order, never the other way round.
    if (facts.get("po") or {}).get("number") and facts.get("document_type") == "po_revision":
        core = _intake.po_core(facts["po"]["number"])
        prev = None
        for other in (db.query(IntakeRunModel)
                      .filter(IntakeRunModel.id != (run_id_hint or -1))
                      .order_by(desc(IntakeRunModel.id)).limit(80).all()):
            try:
                of = json.loads(other.facts or "{}")
            except Exception:
                continue
            if (of.get("document_type") == "purchase_order"
                    and _intake.po_core((of.get("po") or {}).get("number") or "") == core):
                prev = of
                break
        if prev:
            matches["previous_run"] = {
                "total_qty": (prev.get("commercial") or {}).get("total_qty"),
                "ship_date": prev.get("ship_date"),
                "currency": (prev.get("commercial") or {}).get("currency"),
            }
            if not matches.get("po_existing_detail"):
                matches["po_existing_detail"] = matches["previous_run"]

    # a second plain PO for a number already read is a duplicate warning
    if (facts.get("po") or {}).get("number") and facts.get("document_type") == "purchase_order":
        core = _intake.po_core(facts["po"]["number"])
        for other in (db.query(IntakeRunModel)
                      .filter(IntakeRunModel.id != (run_id_hint or -1),
                              IntakeRunModel.status != "rejected")
                      .order_by(desc(IntakeRunModel.id)).limit(80).all()):
            try:
                of = json.loads(other.facts or "{}")
            except Exception:
                continue
            if (of.get("document_type") == "purchase_order"
                    and _intake.po_core((of.get("po") or {}).get("number") or "") == core):
                matches.setdefault("warnings", []).append(
                    f"PO {facts['po']['number']} was already read in intake #{other.id} — check this is not a duplicate")
                break

    route = _intake.route(facts, matches)
    plan = _intake_exec.build_plan(facts, matches)

    source_key = f"mail:{(mail.message_id or mail.uid)}:{(primary.sha256 if primary is not None else 'body')[:32]}"
    run = db.query(IntakeRunModel).filter(IntakeRunModel.source_key == source_key).first()
    if not run:
        run = IntakeRunModel(source_key=source_key, mail_id=mail.id,
                             attachment_id=(primary.id if primary is not None else None))
        db.add(run)
    run.route = route
    run.chain_id = mail.chain_id or (matches.get("chain") or {}).get("id")
    run.document_type = facts.get("document_type") or "other"
    run.facts = json.dumps(facts, default=str)
    run.matches = json.dumps(matches, default=str)
    run.plan = json.dumps(plan, default=str)
    run.confidence = json.dumps(facts.get("confidence") or {})
    run.missing = json.dumps(facts.get("missing") or [])
    run.blocking = json.dumps(sorted(set((facts.get("missing") or []) + (matches.get("blocking") or []))))
    run.extractor = "+".join(facts.get("extractors") or []) or (facts.get("_provenance") or "")
    if (facts.get("_provenance") or "").startswith("deterministic (model"):
        run.extractor += " | " + facts["_provenance"]
    run.summary = _intake_summary_line(facts, matches)
    if run.status in (None, "", "new"):
        run.status = "understood"
    db.commit()
    db.refresh(run)
    return run


def _is_intake_worthy(facts: dict, mail: MailMessageModel, primary, chain_live: bool = False) -> bool:
    """Does this mail carry a document we should open a card for?"""
    dt = (facts.get("document_type") or "other").lower()
    if dt in ("purchase_order", "po_revision", "enquiry", "invoice", "remittance"):
        return True
    if (facts.get("po") or {}).get("number"):
        return True
    c = facts.get("commercial") or {}
    if c.get("total_qty") and (c.get("rate") or facts.get("lines")):
        return True
    # A reply inside a live conversation is worth a card even with no order words in it:
    # "tech pack attached" is the most useful mail of the whole deal and it reads as
    # nothing on its own. Only an attachment or a question earns the card — a bare
    # "thanks" does not.
    if chain_live and (primary is not None or (facts.get("asks") or [])):
        return True
    # a readable document that talks like an order, even if the classifier missed it
    text = ((primary.text if primary is not None else "") or mail.body_text or "").lower()
    if primary is not None and primary.ok:
        orderish = ("purchase order" in text or "p.o." in text or "po no" in text or " po " in text)
        if orderish and ("qty" in text or "quantity" in text or "pieces" in text):
            return True
    if (mail.classification or "") in ("new_order", "order_amendment") and (
            c.get("total_qty") or (facts.get("buyer") or {}).get("name")):
        return True
    return False


def _intake_summary_line(facts: dict, matches: dict) -> str:
    c = facts.get("commercial") or {}
    bits = []
    buyer = (facts.get("buyer") or {}).get("name") or "unknown buyer"
    bits.append(buyer)
    if (facts.get("po") or {}).get("number"):
        bits.append((facts["po"].get("number") or ""))
    if c.get("total_qty"):
        bits.append(f"{c['total_qty']:,} pcs")
    if c.get("rate"):
        bits.append(f"{c.get('currency') or ''} {c['rate']:,.2f}".strip())
    if facts.get("ship_date"):
        bits.append(f"ships {facts['ship_date']}")
    if matches.get("customer") and matches["customer"] != buyer:
        bits.append(f"→ {matches['customer']}")
    return " · ".join(bits)[:300]


def _intake_payload(db: Session, run: IntakeRunModel, with_plan: bool = True) -> dict:
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
    atts = db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == run.mail_id).all()
    out = run.to_dict(full=with_plan)
    facts = json.loads(run.facts or "{}")
    # the conversation this run belongs to, so the panel can offer the reply and the pack
    try:
        row = _chain.newest_for_run(db, run)
        if row is not None:
            ctx = _chain.context(db, row.id)
            out["chain"] = {**ctx, "subject": row.subject or "",
                            "buyer_email": row.buyer_email or "",
                            "reply_to": row.buyer_email or "",
                            "reply_subject": _reply_subject(row.subject or ""),
                            "timeline_count": len(_chain.timeline(db, row))}
        else:
            out["chain"] = None
    except Exception as e:                                            # noqa: BLE001
        out["chain"] = None
        out["chain_error"] = f"{type(e).__name__}: {e}"
    edits = []
    try:
        edits = [e.field for e in db.query(IntakeEditModel).filter(IntakeEditModel.run_id == run.id).all()]
    except Exception:
        edits = []
    out["dates"] = _intake_dates(facts, mail, edits)
    out["provenance"] = facts.get("_provenance") or out.get("extractor") or ""
    out["readers"] = facts.get("extractors") or []
    out["pages"] = []
    for a in atts:
        if a.layout:
            try:
                out["pages"] = _intake.render_pages(json.loads(a.layout))
            except Exception:
                out["pages"] = []
            break
    best = max(atts, key=lambda a: a.chars or 0) if atts else None
    out["document"] = {
        "filename": best.filename if best else "",
        "mime": best.mime if best else "",
        "parser": best.parser if best else "",
        "pages": best.pages if best else 0,
        "chars": best.chars if best else 0,
        "size": best.size if best else 0,
        "needs_ocr": bool(best.needs_ocr) if best else False,
        "error": (best.error or "") if best else "",
        "has_pdf": bool(best and (best.size or 0) <= 1_500_000 and best.path
                        and (best.mime or "") == "application/pdf"
                        and os.path.exists(_resolve_stored_path(best.path))),
    }
    out.update({
        "mail": {
            "id": mail.id if mail else None,
            "subject": mail.subject if mail else "",
            "from_name": mail.from_name if mail else "",
            "from_addr": mail.from_addr if mail else "",
            "received_at": mail.received_at if mail else "",
            "body_text": (mail.body_text or "")[:6000] if mail else "",
        },
        "attachments": [
            {**a.to_dict(), "text_preview": (a.text or "")[:6000],
             "text_chars": a.chars or 0}
            for a in atts
        ],
    })
    return out


def sync_intake_mail(db: Session, mail_id: int, use_llm: int = 0) -> dict:
    """(Re-)read ONE stored mail: fetch its attachments now, then open an intake run.

    Needed for mail that arrived before intake existed — the row is already in
    ``mail_message`` with no attachment bytes. Re-fetching one message is cheap;
    it never touches the ERP.
    """
    _ensure_db()
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == int(mail_id)).first()
    if not mail:
        return {"ok": False, "error": "not_found"}
    s = _mailbox_settings(db)
    stored = db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == mail.id).all()
    if not stored:
        res = inbound.fetch_one(s, mail.uid)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "fetch_failed"}
        msg = res.get("message") or {}
        kept = []
        for att in (msg.get("attachments") or []):
            if att.get("too_large"):
                continue
            if "data" in att:
                kept.append(_store_attachment(db, mail, att))
        stored = kept
    existing = None
    try:
        existing = (db.query(IntakeRunModel)
                    .filter(IntakeRunModel.mail_id == mail.id)
                    .order_by(desc(IntakeRunModel.id)).first())
    except Exception:
        existing = None
    # a mail read one at a time still has to join its conversation
    if not mail.chain_id:
        try:
            _chain.attach(db, mail)
        except Exception as e:                                        # noqa: BLE001
            _set_error(f"chain: {type(e).__name__}: {e}")
    run = _understand_mail(db, mail, stored, use_llm=bool(use_llm),
                           run_id_hint=(existing.id if existing else None),
                           attachment_id=(existing.attachment_id if existing else None))
    if run:
        mail.route = run.route
        mail.intake_status = run.status
        mail.parse_ok = 1
        db.commit()
    _stamp_sync(db, "intake")
    return {"ok": bool(run), "run": _intake_payload(db, run) if run else None,
            "freshness": _freshness(db, "mail", "intake"),
            "attachments": [a.to_dict() for a in stored]}


def _pdf_data_url(att, cap: int = 1_500_000) -> str:
    """The original file, inline, so the operator sees the customer's own sheet."""
    try:
        if not att or (att.size or 0) > cap or (att.mime or "") != "application/pdf" or not att.path:
            return ""
        real = _resolve_stored_path(att.path)
        if not real or not os.path.exists(real):
            return ""
        with open(real, "rb") as fh:
            raw = fh.read()
        return "data:application/pdf;base64," + _b64.b64encode(raw).decode("ascii")
    except Exception:
        return ""


def get_intake_document(db: Session, run_id: int) -> dict:
    """The original file, on demand. Kept out of ``get_intake`` so the card stays light."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    att = (db.query(MailAttachmentModel)
           .filter(MailAttachmentModel.mail_id == run.mail_id)
           .order_by(desc(MailAttachmentModel.chars)).first())
    if not att:
        return {"ok": False, "error": "no_attachment"}
    url = _pdf_data_url(att)
    if not url:
        return {"ok": False, "error": "not_embeddable", "filename": att.filename}
    return {"ok": True, "filename": att.filename, "mime": att.mime,
            "data_url": url, "live": True, "source": SOURCE}


def _intake_dates(facts: dict, mail, edited: list) -> dict:
    """Every date the decision needs, side by side — and which one a human moved."""
    from datetime import date as _date

    def _d(v):
        try:
            return _date.fromisoformat(str(v)[:10])
        except Exception:
            return None

    po_date = _d((facts.get("po") or {}).get("date"))
    ship = _d(facts.get("ship_date"))
    lead = facts.get("lead_time_days")
    today = _date.today()
    return {
        "received": (mail.received_at if mail else "") or "",
        "po_date": po_date.isoformat() if po_date else "",
        "ship_date": ship.isoformat() if ship else "",
        "lead_time_days": lead if isinstance(lead, int) else None,
        "po_to_ship_days": ((ship - po_date).days if (po_date and ship) else None),
        "days_to_ship": ((ship - today).days if ship else None),
        "ship_in_past": bool(ship and ship < today),
        "edited": sorted({e for e in (edited or []) if e in
                          ("po.date", "ship_date", "commercial.rate", "commercial.total_qty",
                           "commercial.currency", "po.number", "buyer.name")}),
    }


def get_intake_summary(db: Session) -> dict:
    """Counts for the badge: what is waiting, what is blocked, what went through."""
    _ensure_db()
    # a breadcrumb: proves the running UI actually asked for intake (so "the tab
    # is missing" can be told apart from "the bundle is old" without guessing)
    try:
        row = db.query(KVModel).filter(KVModel.key == "ui_intake_hits").first()
        if row:
            row.value = str(int(row.value or 0) + 1)
        else:
            db.add(KVModel(key="ui_intake_hits", value="1"))
        db.commit()
    except Exception:
        db.rollback()
    rows = db.query(IntakeRunModel).all()
    def n(st):
        return sum(1 for r in rows if (r.status or "") == st)
    ready = 0
    for r in rows:
        if (r.status or "") in ("understood", "simulated"):
            try:
                plan = json.loads(r.plan or "[]")
            except Exception:
                plan = []
            if plan and all(s.get("status") != "blocked" for s in plan if s.get("kind") != "task"):
                ready += 1
    hits = 0
    try:
        row = db.query(KVModel).filter(KVModel.key == "ui_intake_hits").first()
        hits = int(row.value or 0) if row else 0
    except Exception:
        hits = 0
    return {"total": len(rows), "understood": n("understood"), "approved": n("approved"),
            "rejected": n("rejected"), "blocked": n("blocked"), "simulated": n("simulated"),
            "ready_to_approve": ready, "ui_hits": hits,
            "freshness": _freshness(db, "mail", "intake"),
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def get_intake_queue(db: Session, status: str = "", limit: int = 50, group: int = 1) -> dict:
    """The intake queue — **one card per mail THREAD**, with the documents inside it.

    It used to be one card per document. A single buyer reply carrying three POs and three
    BOMs became six cards for one conversation, and the queue read as six unrelated deals
    (2026-11-03). A merchandiser thinks in conversations, so the card is the conversation
    and the documents are its lines: open the thread, then open the document you want.

    ``group=0`` returns the flat one-row-per-document list (kept for callers that want it).
    """
    _ensure_db()
    q = db.query(IntakeRunModel)
    if status:
        q = q.filter(IntakeRunModel.status == status)
    rows = q.order_by(desc(IntakeRunModel.id)).limit(int(limit or 50)).all()

    flat = []
    for r in rows:
        mail = db.query(MailMessageModel).filter(MailMessageModel.id == r.mail_id).first()
        att = None
        if r.attachment_id:
            att = (db.query(MailAttachmentModel)
                   .filter(MailAttachmentModel.id == r.attachment_id).first())
        chain_row = None
        try:
            chain_row = _chain.newest_for_run(db, r)
        except Exception:
            chain_row = None
        try:
            plan = json.loads(r.plan or "[]")
        except Exception:
            plan = []
        flat.append({**r.to_dict(),
                     "run_id": r.id,
                     "subject": (mail.subject if mail else "")[:200],
                     "from_addr": mail.from_addr if mail else "",
                     "received_at": mail.received_at if mail else "",
                     "document": (att.filename if att else "")[:200],
                     "document_count": int(getattr(mail, "document_count", 0) or 0),
                     "blocked": len([s for s in plan if s.get("status") == "blocked"]),
                     "ready": len([s for s in plan if s.get("status") != "blocked"]),
                     "chain_id": chain_row.id if chain_row is not None else None,
                     "chain_subject": (chain_row.subject or "")[:160] if chain_row is not None else "",
                     "chain_mails": int(chain_row.reply_count or 0) if chain_row is not None else 0,
                     "chain_customer": (chain_row.customer_name or chain_row.customer or ""
                                        if chain_row is not None else ""),
                     # the name the buyer uses, from the mail itself — survives the ERP link
                     "chain_buyer_name": ((chain_row.buyer_name or "")
                                          if chain_row is not None else "")})
    if not int(group or 0):
        return {"ok": True, "items": flat, "threads": [], "count": len(flat),
                "live": True, "source": SOURCE, "generated_at": _now_iso()}

    # ── group by conversation ───────────────────────────────────────────────
    groups: dict = {}
    for item in flat:
        key = f"chain:{item['chain_id']}" if item.get("chain_id") else f"run:{item['run_id']}"
        g = groups.setdefault(key, {
            "key": key, "chain_id": item.get("chain_id"),
            "subject": item.get("chain_subject") or item.get("subject") or "",
            "buyer": item.get("chain_customer") or item.get("chain_buyer_name") or "",
            "email": item.get("from_addr") or "",
            "mails": item.get("chain_mails") or 1,
            "documents": [],
            "first_at": item.get("received_at") or "",
            "last_at": item.get("received_at") or "",
        })
        g["documents"].append(item)
        if not g["buyer"] and item.get("recipient"):
            g["buyer"] = item["recipient"]
        at = item.get("received_at") or ""
        if at and (not g["first_at"] or at < g["first_at"]):
            g["first_at"] = at
        if at and at > g["last_at"]:
            g["last_at"] = at

    threads = []
    for g in groups.values():
        docs = g["documents"]
        counts = {
            "documents": len(docs),
            "waiting": len([d for d in docs if d["status"] in ("understood", "new", "simulated")]),
            "approved": len([d for d in docs if d["status"] == "approved"]),
            "rejected": len([d for d in docs if d["status"] == "rejected"]),
            "blocked_steps": sum(int(d.get("blocked") or 0) for d in docs
                                 if d["status"] in ("understood", "new", "simulated")),
        }
        g["counts"] = counts
        g["documents"] = sorted(docs, key=lambda d: (0 if d["route"] == "new_order" else 1, d["run_id"]))
        threads.append(g)
    threads.sort(key=lambda t: (t.get("last_at") or ""), reverse=True)
    return {"ok": True, "items": flat, "threads": threads, "count": len(threads),
            "documents": len(flat), "live": True, "source": SOURCE,
            "generated_at": _now_iso()}


def get_intake(db: Session, run_id: int, enrich: int = 1) -> dict:
    """One intake in full: the paper, the facts, the matches, the plan, the reply.

    ``enrich=1`` (default) lets the model read the document the first time a card
    is opened, when the deterministic pass alone produced the record. Real client
    PO layouts (EMJ's dense two-column sheet) do not survive a pattern reader, so
    the first look is worth the few seconds; the result is cached on the run.
    """
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"run": None, "error": "not_found", "live": True, "source": SOURCE}
    if enrich and run.status not in ("approved", "rejected") and "llm" not in (run.extractor or ""):
        atts = db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == run.mail_id).all()
        mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
        has_text = any((a.ok and (a.chars or 0) >= 200) for a in atts)
        if mail and has_text and run.route in ("new_order", "revision", "enquiry"):
            try:
                refreshed = _understand_mail(db, mail, atts, use_llm=True,
                                             run_id_hint=run.id,
                                             attachment_id=run.attachment_id)
                if refreshed:
                    run = refreshed
            except Exception:
                pass
    data = _intake_payload(db, run)
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    try:
        data["ack"] = _intake_exec.ack_draft(facts, matches, json.loads(run.created_refs or "[]"))
    except Exception as e:
        data["ack"] = {"subject": "", "body": "", "grounding": {"ok": False, "unsourced": [str(e)]}}
    data["edits"] = [e.to_dict() for e in
                     db.query(IntakeEditModel).filter(IntakeEditModel.run_id == run.id).all()]
    data["live"] = True
    data["source"] = SOURCE
    data["generated_at"] = _now_iso()
    return data


def understand_intake(db: Session, run_id: int, use_llm: int = 1) -> dict:
    """Re-read the document (optionally with the model) and rebuild the plan."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status in ("approved",):
        return {"ok": False, "error": "already_approved"}
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
    if not mail:
        return {"ok": False, "error": "mail_missing"}
    atts = db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == mail.id).all()
    run.status = "new"
    db.commit()
    run = _understand_mail(db, mail, atts, use_llm=bool(use_llm), run_id_hint=run.id,
                           attachment_id=run.attachment_id)
    return {"ok": True, "run": _intake_payload(db, run)}


def simulate_intake(db: Session, run_id: int) -> dict:
    """Dry run: show the exact ERP payloads. Writes nothing, anywhere."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    # show the plan that WILL run, not the one stored when the card was read
    plan, _notes = _intake_exec.rebuilt_plan(facts, matches)
    if plan:
        run.plan = json.dumps(plan, default=str)
        run.matches = json.dumps(matches, default=str)
    else:
        plan = json.loads(run.plan or "[]")
    if run.status in ("understood", "new", "simulated"):
        run.status = "simulated"
    db.commit()
    return {"ok": True, "simulated": True, "erp_write": False,
            "route": run.route,
            "steps": plan,
            "blocked": [s for s in plan if s.get("status") == "blocked"],
            "ready": [s for s in plan if s.get("status") != "blocked"],
            "ack": _intake_exec.ack_draft(facts, matches, []),
            "note": "Simulation only — nothing was written to the ERP.",
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


# ── review → confirm → write (2026-11-07) ──────────────────────────────────
# A person must SEE every value that will be written, be able to change any of them, and then
# confirm that exact plan. `intake_review` returns the plan with a hash; `approve_intake` refuses
# when the plan changed since that review (an edit, a re-read, a new mail) or when a step is blocked
# and the person did not explicitly accept that the blocked steps are skipped.

def _plan_overrides(db: Session, run_id: int) -> dict:
    row = db.query(KVModel).filter(KVModel.key == f"intake_plan_edits:{int(run_id)}").first()
    try:
        return json.loads(row.value) if row and row.value else {}
    except Exception:
        return {}


def _save_plan_overrides(db: Session, run_id: int, data: dict) -> None:
    key = f"intake_plan_edits:{int(run_id)}"
    row = db.query(KVModel).filter(KVModel.key == key).first()
    if row:
        row.value = json.dumps(data, default=str)
    else:
        db.add(KVModel(key=key, value=json.dumps(data, default=str)))
    db.commit()


def _set_path(node, path: str, value):
    """Set ``a.b.0.c`` inside dicts/lists. Raises on a path that does not exist (beyond the leaf)."""
    parts = [p for p in str(path).split(".") if p != ""]
    for i, p in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(node, list):
            node = node[int(p)]
        else:
            if p not in node or node[p] is None:
                node[p] = [] if nxt.isdigit() else {}
            node = node[p]
    leaf = parts[-1]
    if isinstance(node, list):
        node[int(leaf)] = value
    else:
        node[leaf] = value


def _apply_overrides(plan: list, overrides: dict) -> list:
    """Re-apply a person's edits to a freshly built plan. ``{step_key: {path: value}}``."""
    for st in plan:
        edits = (overrides or {}).get(st.get("key")) or {}
        if not edits or st.get("status") in ("blocked", "skipped"):
            continue
        payload = st.setdefault("payload", {})
        for path, value in edits.items():
            try:
                _set_path(payload, path, value)
                st.setdefault("edited", []).append(path)
            except Exception:
                st.setdefault("edit_errors", []).append(path)
    return plan


def _review_hash(facts: dict, plan: list) -> str:
    core = [{k: s.get(k) for k in ("key", "doctype", "status", "kind", "payload")} for s in plan]
    blob = json.dumps({"facts": facts, "plan": core}, sort_keys=True, default=str)
    return _hashlib.sha256(blob.encode()).hexdigest()[:24]


def _reviewed_plan(db: Session, run) -> tuple:
    """``(plan, facts, matches, notes)`` — rebuilt against the ERP now, with the person's edits applied."""
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    plan, notes = _intake_exec.rebuilt_plan(facts, matches)
    if not plan:
        plan = json.loads(run.plan or "[]")
    plan = _apply_overrides(plan, _plan_overrides(db, run.id))
    return plan, facts, matches, notes


def intake_review_core(db: Session, run_id: int) -> dict:
    """Everything approval would write, value by value, plus a hash that approval must quote back."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    plan, facts, matches, notes = _reviewed_plan(db, run)
    run.plan = json.dumps(plan, default=str)
    run.matches = json.dumps(matches, default=str)
    db.commit()
    blocked = [{"key": s.get("key"), "label": s.get("label"), "reason": s.get("reason") or ""}
               for s in plan if s.get("status") == "blocked"]
    return {"ok": True, "run_id": run.id, "status": run.status, "route": run.route, "steps": plan,
            "blocked": blocked, "skipped": [s.get("label") for s in plan if s.get("status") == "skipped"],
            "missing": json.loads(run.missing or "[]"), "warnings": json.loads(run.blocking or "[]"),
            "review_hash": _review_hash(facts, plan), "notes": notes,
            # the dropdowns: currencies come with the plan (small list); customers are searched
            # on demand through get_intake_options so a site with 4,000 buyers stays quick
            "options": {"currency": _erp_currency_options()},
            "buyer": {"name": (facts.get("buyer") or {}).get("name") or "",
                      "email": (facts.get("buyer") or {}).get("email") or "",
                      "customer": matches.get("customer") or "",
                      "candidates": matches.get("customer_candidates") or []},
            "write_mode": writes.current_mode(), "erp_write": False,
            "note": "Review only — nothing has been written to the ERP."}


def intake_plan_edit_core(db: Session, run_id: int, step_key: str, field: str, value, actor: str = "") -> dict:
    """Change one value the plan will write (``field`` is a path inside that step's payload, e.g.
    ``items.0.qty``). Stored per run and re-applied whenever the plan is rebuilt."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": False, "error": "already_approved"}
    if not step_key or not field:
        return {"ok": False, "error": "step_key and field are required"}
    if field.split(".")[0] in ("doctype", "name", "owner", "docstatus", "naming_series"):
        return {"ok": False, "error": f"{field} cannot be changed here"}
    ov = _plan_overrides(db, run.id)
    if value is None:
        (ov.get(step_key) or {}).pop(field, None)
    else:
        ov.setdefault(step_key, {})[field] = value
    # Renaming the buyer here is the same act as renaming them on the Customer step (2026-11-07):
    # the card says "correct buyer.name, then re-plan", and the field a person naturally reaches
    # for is `customer_name` on the Opportunity. One edit, both places, and the plan is rebuilt.
    note = ""
    if field.split(".")[-1] == "customer_name" and isinstance(value, str) and value.strip():
        try:
            facts = json.loads(run.facts or "{}")
            nm = " ".join(value.split())[:140]
            buyer = facts.get("buyer") or {}
            buyer["name"] = nm
            facts["buyer"] = buyer
            run.facts = json.dumps(facts, default=str)
            note = (f'The buyer is now "{nm}" — the Customer step will use that name.')
        except Exception:
            pass
    _save_plan_overrides(db, run.id, ov)
    _log(db, "intake", "intake_plan_edit", f"Intake #{run.id}: {step_key}.{field} set before approval",
         actor=actor or "Ops Manager")
    out = intake_review_core(db, run.id)
    if note:
        out["note"] = note
    return out


def _pipeline_writer(db: Session, principal: dict, run_id: int):
    """A create function for intake_exec that goes through the ONE guarded write pipeline."""
    import pipeline as _pipeline

    def write(doctype: str, payload: dict):
        data = {k: v for k, v in (payload or {}).items() if k != "doctype"}
        fp = _hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]
        out = _pipeline.execute(db, principal, {"op": "insert", "doctype": doctype, "data": data,
                                                "idem_key": f"intake-{run_id}-{doctype}-{fp}"})
        if out.get("ok"):
            return True, (out.get("doc") or {}), ""
        if out.get("needs_approval"):
            return False, {}, f"held for a manager's approval (#{out.get('approval_id')})"
        return False, {}, out.get("error") or "refused by the tower's rules"
    return write


def approve_intake(db: Session, run_id: int, actor: str = "Ops Manager", note: str = "",
                   review_hash: str = "", accept_blocked: int = 0, principal: Optional[dict] = None) -> dict:
    """Approve one reviewed intake → create the ERP drafts.

    Refused unless ``review_hash`` matches the plan as it is NOW (so what was reviewed is what is
    written), and unless blocked steps are explicitly accepted with ``accept_blocked=1``.
    """
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": True, "status": "approved", "already": True,
                "refs": json.loads(run.created_refs or "[]"), "note": run.result_note}
    if run.status == "rejected":
        return {"ok": False, "error": "already_rejected"}
    if not writes.mode_allows("draft"):
        return {"ok": False, "error": f"write_mode_{writes.current_mode()}_blocks_drafts"}

    plan, facts, matches_now, _notes = _reviewed_plan(db, run)
    current = _review_hash(facts, plan)
    if not review_hash:
        return {"ok": False, "needs_review": True, "review_hash": current,
                "error": "Review the plan first — every value that will be written is shown there."}
    if review_hash != current:
        return {"ok": False, "needs_review": True, "review_hash": current,
                "error": "The plan changed since you reviewed it (an edit, a re-read or a change in the ERP). Review it again."}
    blocked = [s for s in plan if s.get("status") == "blocked"]
    if blocked and not int(accept_blocked or 0):
        return {"ok": False, "needs_review": True, "review_hash": current,
                "blocked": [{"key": s.get("key"), "label": s.get("label"), "reason": s.get("reason")} for s in blocked],
                "error": f"{len(blocked)} step(s) are blocked. Fix them, or confirm that the rest is created without them."}
    if not [s for s in plan if s.get("status") not in ("blocked", "skipped")]:
        return {"ok": False, "error": "Nothing in this plan can be created yet — every step is blocked."}

    # the executor runs THIS plan (rebuild=False) against the matches it was built from
    run.plan = json.dumps(plan, default=str)
    run.matches = json.dumps(matches_now, default=str)
    db.commit()
    use_pipeline = principal is not None and config.INTAKE_WRITE_PATH != "direct"
    if use_pipeline:
        _intake_exec.set_writer(_pipeline_writer(db, principal, run.id))
    try:
        res = _intake_exec.execute(db, run, actor=actor, rebuild=False)
    finally:
        _intake_exec.set_writer(None)
    if note:
        run.result_note = ((run.result_note or "") + f"\n{note}")[:4000]
        db.commit()
    _log(db, "intake", "approve_intake",
         f"Intake #{run.id} ({run.route}) → {res.get('status')}: "
         f"{', '.join(r['doctype'] + ' ' + r['name'] for r in (res.get('refs') or [])) or 'nothing created'}"
         + (" [through the guarded pipeline]" if use_pipeline else ""),
         actor=actor, risk_title=(run.summary or "")[:120])
    return {**res, "run": run.to_dict(), "write_path": "pipeline" if use_pipeline else "direct",
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def reject_intake(db: Session, run_id: int, reason: str = "", actor: str = "Ops Manager") -> dict:
    """Reject an intake. The reason is kept — it is the classifier's training signal."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": False, "error": "already_approved — roll it back instead"}
    run.status = "rejected"
    run.result_note = reason or "rejected by operator"
    run.decided_by = actor
    run.decided_at = datetime.now()
    db.commit()
    _log(db, "intake", "reject_intake", f"Intake #{run.id} rejected: {reason[:160]}", actor=actor)
    return {"ok": True, "run": run.to_dict()}


def edit_intake(db: Session, run_id: int, field: str, value, actor: str = "Ops Manager") -> dict:
    """Correct one field before approval, and re-plan. The edit is stored."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": False, "error": "already_approved"}
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    before = _intake._get(facts, field)
    if field.startswith("lines."):
        parts = field.split(".")
        try:
            idx = int(parts[1]); key = parts[2]
            facts["lines"][idx][key] = value
        except Exception:
            return {"ok": False, "error": "bad_line_path"}
    else:
        try:
            node = facts
            parts = field.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            # Shape-preserving write (2026-11-06). ``style`` and friends are STRUCTURED nodes
            # ({"code": ..., "description": ...}); writing a bare string over one of them made
            # intake.match() crash with "'str' object has no attribute 'get'" on the next line.
            cur = node.get(parts[-1])
            if isinstance(cur, dict) and not isinstance(value, dict):
                if "code" in cur or parts[-1] == "style":
                    cur["code"] = value
                else:
                    cur["value"] = value
            else:
                node[parts[-1]] = value
        except Exception:
            return {"ok": False, "error": "bad_field_path"}
    facts.setdefault("confidence", {})[field] = 0.99
    facts = _intake.check_arithmetic(facts)
    matches = _intake.match(db, facts)
    plan = _intake_exec.build_plan(facts, matches)
    run.facts = json.dumps(facts, default=str)
    run.matches = json.dumps(matches, default=str)
    run.plan = json.dumps(plan, default=str)
    run.confidence = json.dumps(facts.get("confidence") or {})
    run.missing = json.dumps(facts.get("missing") or [])
    run.status = "understood"
    run.summary = _intake_summary_line(facts, matches)
    db.add(IntakeEditModel(run_id=run.id, field=field, original=json.dumps(before, default=str)[:4000],
                           corrected=json.dumps(value, default=str)[:4000], actor=actor))
    db.commit()
    _log(db, "intake", "edit_intake", f"Intake #{run.id}: {field} corrected", actor=actor)
    return {"ok": True, "run": _intake_payload(db, run)}


def rollback_intake(db: Session, run_id: int, actor: str = "Ops Manager") -> dict:
    """Delete what this approval created (drafts only), newest first."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    refs = json.loads(run.created_refs or "[]")
    if not refs:
        return {"ok": False, "error": "nothing_created"}
    res = _intake_exec.rollback(refs)
    if res.get("ok"):
        run.status = "understood"
        run.created_refs = "[]"
        run.result_note = ((run.result_note or "") + "\nrolled back").strip()
        db.commit()
    _log(db, "intake", "rollback_intake",
         f"Intake #{run.id} rollback: {len(res.get('deleted') or [])} deleted, "
         f"{len(res.get('kept') or [])} kept", actor=actor)
    return {**res, "run": run.to_dict()}


def create_intake_ack(db: Session, run_id: int, actor: str = "Ops Manager") -> dict:
    """Draft the buyer's acknowledgement from the facts — never sent from here."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    ack = _intake_exec.ack_draft(facts, matches, json.loads(run.created_refs or "[]"),
                                 sender_name=config.MAIL_FROM_NAME)
    to_email = ((facts.get("buyer") or {}).get("email")
                or (mail.from_addr if mail else "") or "")
    draft = EmailDraftModel(
        action_key=f"intake:{run.id}",
        intent="order_acknowledgement",
        to_email=to_email,
        from_name=config.MAIL_FROM_NAME,
        subject=ack.get("subject") or "",
        body=ack.get("body") or "",
        fact_sheet=json.dumps({"facts": _intake_exec._flat_facts(facts),
                               "records": json.loads(run.created_refs or "[]")}, default=str),
        status="draft",
        grounding_ok=1 if (ack.get("grounding") or {}).get("ok") else 0,
        grounding_unsourced=json.dumps((ack.get("grounding") or {}).get("unsourced") or []),
        policy_version=email_engine.POLICY_VERSION,
        idempotency_key=f"intake:{run.id}:{_hashlib.sha1((ack.get('body') or '').encode()).hexdigest()[:16]}",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    _log(db, "intake", "create_intake_ack", f"Intake #{run.id}: acknowledgement drafted", actor=actor)
    return {"ok": True, "draft": draft.to_dict(),
            "grounding": ack.get("grounding"), "live": True, "source": SOURCE}


# ────────────────────────────────────────────────────────────────────────────
# The chain — reply from the Tower, follow the thread, ingest the pack
# ────────────────────────────────────────────────────────────────────────────

def _chain_row(db: Session, chain_id: int = 0, run_id: int = 0) -> Optional[MailChainModel]:
    """The chain, by id or by any of its runs."""
    if chain_id:
        return db.query(MailChainModel).filter(MailChainModel.id == int(chain_id)).first()
    if run_id:
        run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
        if run is not None:
            return _chain.newest_for_run(db, run)
    return None


def _reply_subject(base: str) -> str:
    """'Re: ' + the buyer's subject EXACTLY, however odd their subject is.

    Two hard-won rules, both from 2026-11-03:

    * **Collapse every line break.** A raw `\r\n` in a header makes `msg["Subject"] = …`
      raise before the socket opens, and the send died silently.
    * **Never otherwise rewrite it.** This buyer's mail really is titled
      `SUBJECT: Enquiry - Summer 2027 - …`, so stripping the literal "SUBJECT:" looked
      tidy — and it broke the thread: a mail client groups a conversation on the subject
      as well as on `References`, and a changed subject sends the reply into a new
      conversation. Only real reply prefixes (Re:/AW:/FWD:) are removed, so replying twice
      does not give `Re: Re: Re:`.
    """
    text = re.sub(r"\s+", " ", (base or "")).strip()
    while True:
        m = re.match(r"(?i)^(re|aw|fw|fwd)\s*:\s*", text)
        if not m:
            break
        text = text[m.end():].strip()
    return f"Re: {text}" if text else ""


# An ordered list is MARKUP, not figures: "1. 30% deposit" made the token "1." look like a
# number that was not on the record (2026-11-03, the first real reply through the Tower).
_LIST_MARK = re.compile(r"(?m)(^|[:;]\s|\n)([ \t]*)(?:\d{1,2}[.)]|\(\d{1,2}\))[ \t]+")
# a token that is only "1." is a list marker however it was written
_ORDINAL = re.compile(r"^\d{1,2}\.$")


def _strip_list_markers(text: str) -> str:
    return _LIST_MARK.sub(lambda m: m.group(1), text or "")


def _chain_sheet(db: Session, chain: MailChainModel) -> dict:
    """What a reply may quote from: the chain's reading AND the ERP records it points at.

    The intake facts alone were too narrow to be useful — a merchandiser answering an
    enquiry quotes the Opportunity, the last quotation, the cost sheet and the price we
    last sold the style at, and every one of those numbers was "not on the record" even
    though the record is exactly where it came from (2026-11-03).
    """
    run = (db.query(IntakeRunModel)
           .filter(IntakeRunModel.chain_id == chain.id, IntakeRunModel.status == "approved")
           .order_by(desc(IntakeRunModel.id)).first())
    if run is None:
        run = (db.query(IntakeRunModel)
               .filter(IntakeRunModel.chain_id == chain.id)
               .order_by(desc(IntakeRunModel.id)).first())
    facts, refs = {}, []
    if run is not None:
        try:
            facts = json.loads(run.facts or "{}")
        except Exception:
            facts = {}
        try:
            refs = json.loads(run.created_refs or "[]")
        except Exception:
            refs = []
    sheet = {"facts": _intake_exec._flat_facts(facts) if facts else {}, "records": refs,
             "erp": {}}

    def _doc(key, doctype, name):
        if not name:
            return
        try:
            got = erp.erp_doc(doctype, name)
            if got:
                sheet["erp"][key] = got
        except Exception:
            pass

    # the records this conversation produced or points at
    _doc("opportunity", "Opportunity", chain.opportunity)
    _doc("sales_order", "Sales Order", chain.sales_order)
    _doc("client_po", "Client Purchase Order", chain.client_po)

    # the styles asked about, and what the ERP holds for them
    styles = []
    try:
        rows = json.loads(facts.get("styles") or "[]")
        styles = [s for s in rows if s][:6]
    except Exception:
        styles = []
    for style in styles:
        try:
            for cs in erp.erp_get("Cost Sheet",
                                  fields=["name", "buyer_style_ref", "total_fob", "locked_fob",
                                          "currency", "valid_till", "delivery_date", "status"],
                                  filters=[["buyer_style_ref", "=", style]], limit=1) or []:
                _doc(f"cost_sheet:{style}", "Cost Sheet", cs.get("name"))
        except Exception:
            pass

    # the last offer we made this buyer — a re-quote should not disagree with it
    if chain.customer:
        try:
            last = erp.erp_get("Quotation",
                               fields=["name", "party_name", "transaction_date", "grand_total",
                                       "currency", "status"],
                               filters=[["party_name", "=", chain.customer]],
                               order="creation desc", limit=1) or []
            if last:
                _doc("last_quotation", "Quotation", last[0].get("name"))
        except Exception:
            pass
    return sheet


def get_mail_chain(db: Session, chain_id: int = 0, run_id: int = 0) -> dict:
    """The whole conversation: every mail in, every reply out, and what it produced.

    This is the answer to "where did this enquiry go?" — the timeline is read from the
    two places mail actually lives (``mail_message`` in, ``email_draft`` out), never
    reconstructed from a subject line.
    """
    _ensure_db()
    row = _chain_row(db, chain_id, run_id)
    if row is None:
        return {"ok": False, "error": "chain_not_found"}
    runs = (db.query(IntakeRunModel)
            .filter(IntakeRunModel.chain_id == row.id)
            .order_by(IntakeRunModel.id).all())
    hdrs = _chain.reply_headers(db, row)
    chain_dict = row.to_dict()
    pointers = _verified_pointers(chain_dict, _CHAIN_POINTERS)
    return {
        "ok": True,
        "chain": chain_dict,
        "pointers": pointers,
        "stale": pointers["missing"],
        "timeline": _chain.timeline(db, row),
        "runs": [{**r.to_dict(), "summary": r.summary} for r in runs],
        "reply_to": row.buyer_email or "",
        "reply_subject": _reply_subject(row.subject),
        "reply_headers": hdrs,
        "in_thread": bool(hdrs.get("in_reply_to")),
        "live": True, "source": SOURCE, "generated_at": _now_iso(),
    }


def send_chain_reply(db: Session, chain_id: int = 0, run_id: int = 0, subject: str = "",
                     body: str = "", confirm: int = 0, enforce_grounding: int = 0,
                     actor: str = "Ops Manager") -> dict:
    """Answer the buyer from the Tower, inside the buyer's own thread.

    Two guardrails, and one of them is only a warning — deliberately:

    * ``confirm=1`` is required before SMTP is touched — the UI sends it only after the
      operator has read the recipient and the text.
    * **grounding INFORMS, it does not block.** The reply is written by a human quoting a
      price that does not exist in any record yet (a quotation he is creating), so refusing
      it would refuse the normal case: the first real reply through the Tower came back with
      seventeen figures "not on the record", every one of them his (2026-11-03). The
      unsourced tokens are returned, shown before sending, and stored on the draft
      (``grounding_ok=0`` + the list) so the record says what was never sourced.
      ``enforce_grounding=1`` restores the wall for callers that want it.
    * **Naming the platform in a buyer email is refused, always** — that is not a figure to
      review, it is a mistake.

    The send carries ``In-Reply-To`` + ``References``, so the buyer's answer comes back
    into this same chain and never starts a second deal.
    """
    _ensure_db()
    row = _chain_row(db, chain_id, run_id)
    if row is None:
        return {"ok": False, "error": "chain_not_found"}
    to_email = (row.buyer_email or "").strip()
    if not _looks_like_email(to_email):
        return {"ok": False, "error": "no_buyer_address",
                "message": "this chain has no buyer email address to answer"}
    subj = re.sub(r"\s+", " ", (subject or "").strip() or _reply_subject(row.subject)).strip()
    text = body or ""
    if not text.strip():
        return {"ok": False, "error": "empty_body"}

    sheet = _chain_sheet(db, row)
    # ordered-list markers are markup; the engine must not read "1." as a figure
    check = email_engine.validate_grounding(
        {"subject": _strip_list_markers(subj), "body": _strip_list_markers(text)}, sheet)
    ungrounded = [u for u in (check.get("unsourced") or []) if not _ORDINAL.match(str(u))]
    named_platform = [u for u in ungrounded if str(u).startswith("forbidden:")]
    if named_platform:
        return {"ok": False, "error": "names_the_platform", "unsourced": ungrounded,
                "message": ("a buyer email may not name " +
                            ", ".join(u.split(":", 1)[1] for u in named_platform) +
                            " — remove it and send again")}
    if ungrounded and int(enforce_grounding or 0):
        return {"ok": False, "error": "ungrounded", "unsourced": ungrounded,
                "message": ("these numbers are not on the record: " + ", ".join(ungrounded) +
                            " — take them from the costing sheet, or send it anyway")}

    hdrs = _chain.reply_headers(db, row)
    settings = _mail_settings_row(db)
    from_name = (settings.from_name if settings is not None else "") or config.MAIL_FROM_NAME
    key = f"chain:{row.id}:{_hashlib.sha1((subj + text).encode('utf-8')).hexdigest()[:16]}"
    draft = db.query(EmailDraftModel).filter(EmailDraftModel.idempotency_key == key).first()
    if draft is not None and draft.status == "sent":
        return {"ok": True, "status": "sent", "already": True,
                "message_id": draft.message_id or "", "draft": draft.to_dict(),
                "chain": row.to_dict()}
    if draft is None:
        draft = EmailDraftModel(
            action_key=f"chain:{row.id}", intent="buyer_reply", to_email=to_email,
            from_name=from_name, subject=subj, body=text,
            fact_sheet=json.dumps(sheet, default=str), status="draft",
            grounding_ok=0 if ungrounded else 1,
            grounding_unsourced=json.dumps(ungrounded),
            policy_version=email_engine.POLICY_VERSION,
            idempotency_key=key, chain_id=row.id,
            in_reply_to=(hdrs.get("in_reply_to") or "")[:300],
            references=(hdrs.get("references") or ""),
            decided_by=actor or "Ops Manager",
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)

    if not int(confirm or 0):
        return {"ok": True, "status": "confirmation_required", "confirmation_required": True,
                "draft": draft.to_dict(), "to": to_email, "subject": subj,
                "unsourced": ungrounded, "in_thread": bool(hdrs.get("in_reply_to")),
                "message": "no email leaves without an explicit confirmation"}

    if settings is None or not settings.email_account or not settings.password:
        draft.status = "failed"
        draft.error = "Mail is not configured yet."
        db.commit()
        return {"ok": False, "error": draft.error, "draft": draft.to_dict()}

    import secret_store as _secrets2
    try:
        _chain_pw = _secrets2.dec(settings.password)
    except _secrets2.SecretUnreadable:
        return {"ok": False, "error": MAIL_PASSWORD_UNREADABLE, "password_unreadable": True}
    result = mailer.send_via_smtp(
        {"email_account": settings.email_account, "from_name": settings.from_name,
         "smtp_host": settings.smtp_host, "smtp_port": settings.smtp_port,
         "use_tls": settings.use_tls, "password": _chain_pw},
        to_email, subj, text, draft.from_name or from_name,
        in_reply_to=hdrs.get("in_reply_to") or "", references=hdrs.get("references") or "")

    draft.decided_at = datetime.now()
    draft.decided_by = actor or "Ops Manager"
    if result.get("ok"):
        draft.status = "sent"
        draft.message_id = (result.get("message_id") or "")[:200]
        draft.sent_at = datetime.now()
        draft.error = None
        db.commit()
        _chain.note_outbound(db, row, draft.message_id)
        _log(db, "chain", "send_chain_reply",
             (f"Replied to {to_email} in chain #{row.id} ({'threaded' if hdrs.get('in_reply_to') else 'new thread'})"
              + (f" — {len(ungrounded)} figure(s) not on the record, written by the operator: "
                 + ", ".join(ungrounded[:20]) if ungrounded else "")),
             actor=actor or "Ops Manager", approved="yes")
        return {"ok": True, "status": "sent", "message_id": draft.message_id,
                "draft": draft.to_dict(), "chain": row.to_dict(), "in_thread": True,
                "unsourced": ungrounded}

    draft.status = "failed"
    draft.error = result.get("error") or "send failed"
    db.commit()
    _log(db, "chain", "send_chain_reply", f"Reply to {to_email} failed: {draft.error}",
         actor=actor or "Ops Manager", approved="no")
    return {"ok": False, "status": "failed", "error": draft.error, "draft": draft.to_dict()}


def ingest_chain_pack(db: Session, run_id: int, apply: int = 1,
                      actor: str = "Ops Manager") -> dict:
    """Read the pack in this conversation into the ERP (Buyer Tech Pack + one BOM per size).

    The heavy lifting is the phase-A builder, called through ``pack_ingest``; this
    function resolves the file, refuses politely when it cannot, and records the result
    on the chain and on the run so the next person sees what came from where.
    """
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    att = None
    if run.attachment_id:
        att = db.query(MailAttachmentModel).filter(MailAttachmentModel.id == run.attachment_id).first()
    if att is None:
        att = (db.query(MailAttachmentModel)
               .filter(MailAttachmentModel.mail_id == run.mail_id)
               .order_by(desc(MailAttachmentModel.chars)).first())
    if att is None:
        return {"ok": False, "error": "no_attachment",
                "note": "this mail carries no file — nothing to ingest"}
    row = _chain.newest_for_run(db, run)
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    customer = ((row.customer if row else "") or matches.get("customer") or "")
    already = ((json.loads(row.ingested or "{}") or {}).get("_packs") or []) if row else []
    job = {
        "path": _pack_ingest.resolve_path(att.path or ""),
        "filename": att.filename or "",
        "customer": customer,
        "style_code": ((facts.get("style") or {}).get("code") or (row.style_code if row else "") or ""),
        "opportunity": ((row.opportunity if row else "") or (matches.get("chain") or {}).get("opportunity") or ""),
        "already": already,
    }
    res = _pack_ingest.ingest(job, apply=bool(int(apply or 0)))
    refs = res.get("refs") or []
    if refs:
        try:
            existing = json.loads(run.created_refs or "[]")
        except Exception:
            existing = []
        have = {(r.get("doctype"), r.get("name")) for r in existing}
        for r in refs:
            if (r.get("doctype"), r.get("name")) not in have:
                existing.append({**r, "step": "pack"})
        run.created_refs = json.dumps(existing)
        run.result_note = ((run.result_note or "") + "\n" + (res.get("note") or ""))[:4000]
        if row is not None:
            for r in refs:
                _chain.link(db, row, r.get("doctype") or "", r.get("name") or "")
        db.commit()
    _log(db, "chain", "ingest_chain_pack",
         f"Pack ingest on intake #{run.id}: " + (
             ", ".join(f"{r['doctype']} {r['name']}" for r in refs) or (res.get("note") or "nothing")[:180]),
         actor=actor or "Ops Manager", approved="yes" if res.get("ok") else "no")
    return {"ok": bool(res.get("ok")), "refs": refs, "note": res.get("note") or "",
            "run": run.to_dict(), "chain": row.to_dict() if row else None,
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def set_intake_customer(db: Session, run_id: int, customer: str = "", create: int = 0, name: str = "",
                        actor: str = "Ops Manager") -> dict:
    """Decide the buyer before approval: link the existing Customer, or say "create a new one".

    The gate this unblocks is real — intake refuses to create a Customer that reads 60-85 %
    like one already on file, because two Customers for one buyer is how one order becomes
    two. The human answers here, and the plan is rebuilt.

    ``name`` (2026-11-07) is the third answer and the one the review sheet needs: the buyer
    name on the mail was junk (a mail-client display name such as "temporary"), so a person
    types the real company and *that* becomes ``buyer.name`` — the field the Customer step is
    built from. Without it, correcting the name meant editing the card and re-reading the mail.
    """
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": False, "error": "already_approved"}
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    note = ""
    if customer:
        found = erp.erp_get("Customer", fields=["name", "customer_name"],
                            filters=[["name", "=", customer]], limit=1) or []
        if not found:
            return {"ok": False, "error": "customer_not_found", "customer": customer}
        matches["customer"] = found[0]["name"]
        matches["customer_candidates"] = []
        matches["warnings"] = [w for w in (matches.get("warnings") or [])
                               if "not certain" not in w and "does not exist" not in w]
    elif (name or "").strip():
        # typed by a person: this IS the buyer name, so it replaces what the mail said
        nm = " ".join((name or "").split())[:140]
        if len(nm) < 2:
            return {"ok": False, "error": "name_too_short",
                    "note": "Type the company name as it should appear in the ERP."}
        buyer = facts.get("buyer") or {}
        buyer["name"] = nm
        buyer["contact"] = buyer.get("contact") if _looks_like_company_name(buyer.get("contact")) else nm
        facts["buyer"] = buyer
        matches["customer"] = None
        matches["customer_candidates"] = []
        matches["customer_created"] = False
        matches["warnings"] = [w for w in (matches.get("warnings") or [])
                               if "not certain" not in w and "will be created on approval" not in w]
        problem = _intake_exec.buyer_name_problem(nm)
        note = (f'Heads up: the Customer step will still stop on "{nm}" — {problem}'
                if problem else f'A new Customer "{nm}" will be created on approval.')
    elif int(create or 0):
        matches["customer"] = None
        matches["customer_candidates"] = []
        matches["warnings"] = [w for w in (matches.get("warnings") or []) if "not certain" not in w]
    else:
        return {"ok": False, "error": "nothing_to_do"}
    run.facts = json.dumps(facts, default=str)
    run.matches = json.dumps(matches, default=str)
    run.plan = json.dumps(_intake_exec.build_plan(facts, matches), default=str)
    db.commit()
    db.refresh(run)
    _log(db, "intake", "set_intake_customer",
         f"Intake #{run.id}: buyer set to {matches.get('customer') or (facts.get('buyer') or {}).get('name') or 'create a new Customer'}",
         actor=actor or "Ops Manager")
    return {"ok": True, "note": note, "run": _intake_payload(db, run),
            "review": intake_review_core(db, run.id)}


def _looks_like_company_name(value) -> bool:
    """Cheap guard for the contact field when a person types the buyer name."""
    text = str(value or "").strip()
    return bool(text) and any(c.isalpha() for c in text) and text.lower() not in ("temporary", "none", "unknown")


# ── the lists behind the review sheet's dropdowns (2026-11-07) ─────────────
# The sheet used to show plain text boxes for `currency` and the buyer, so a person had to know
# the ERP's currency codes by heart and could not pick an existing Customer at all. These read
# the lists out of the ERP itself; nothing is hard-coded and nothing is cached to disk.
_OPTIONS_CACHE: dict = {}
_OPTIONS_TTL = 600          # 10 minutes — currencies change once a year, not once a minute


def _erp_currency_options() -> list:
    import time as _time
    hit = _OPTIONS_CACHE.get("currency")
    if hit and (_time.time() - hit[0]) < _OPTIONS_TTL:
        return hit[1]
    rows = erp.erp_get("Currency", fields=["name", "enabled"],
                       filters=[["enabled", "=", 1]], limit=0, order="name asc") or []
    out = [{"value": r.get("name"), "label": r.get("name")} for r in rows if r.get("name")]
    if not out:                                   # ERP unreadable — the plan default still has to work
        out = [{"value": config.DEFAULT_CURRENCY, "label": config.DEFAULT_CURRENCY, "fallback": True}]
    _OPTIONS_CACHE["currency"] = (_time.time(), out)
    return out


def _erp_customer_options(q: str = "", limit: int = 20) -> list:
    """Customers matching ``q`` (name or customer_name). Empty ``q`` = the most recent ones."""
    lim = max(1, min(int(limit or 20), 50))
    needle = (q or "").strip()
    rows: list = []
    if needle:
        like = [needle, f"%{needle}%"]
        for flt in ([["customer_name", "like", like[1]]], [["name", "like", like[1]]]):
            got = erp.erp_get("Customer", fields=["name", "customer_name"], filters=flt, limit=lim) or []
            seen = {r.get("name") for r in rows}
            rows += [r for r in got if r.get("name") not in seen]
            if len(rows) >= lim:
                break
    else:
        rows = erp.erp_get("Customer", fields=["name", "customer_name"], limit=lim,
                           order="modified desc") or []
    out = []
    for r in rows[:lim]:
        nm = r.get("name") or ""
        label = (r.get("customer_name") or "").strip()
        out.append({"value": nm,
                    "label": label if label and label != nm else nm,
                    "hint": nm if label and label != nm else ""})
    return out


def get_intake_options(db: Session, kind: str = "currency", q: str = "", limit: int = 20, **_) -> dict:
    """The choices for one dropdown in the review sheet, read live from the ERP.

    ``kind``: ``currency`` (enabled currencies), ``customer`` (search by name/customer_name),
    ``customer_group`` / ``territory`` (the non-group leaves a Customer may carry).
    """
    k = (kind or "currency").strip().lower()
    try:
        if k in ("currency", "currencies"):
            opts = _erp_currency_options()
        elif k in ("customer", "customers"):
            opts = _erp_customer_options(q, limit)
        elif k in ("customer_group", "customer_groups"):
            rows = erp.erp_get("Customer Group", fields=["name", "is_group"], limit=0, order="name asc") or []
            opts = [{"value": r["name"], "label": r["name"]} for r in rows
                    if r.get("name") and not r.get("is_group")]
        elif k in ("territory", "territories"):
            rows = erp.erp_get("Territory", fields=["name", "is_group"], limit=0, order="name asc") or []
            opts = [{"value": r["name"], "label": r["name"]} for r in rows
                    if r.get("name") and not r.get("is_group")]
        else:
            return {"ok": False, "error": f"unknown list '{kind}'"}
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "error": str(e)[:180], "options": []}
    return {"ok": True, "kind": k, "options": opts, "count": len(opts),
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def reopen_intake(db: Session, run_id: int, actor: str = "Ops Manager") -> dict:
    """Put a run back to ``understood`` so it can be approved again — only when nothing
    but to-dos were created.

    The one case this exists for: an approval whose every ERP step was blocked, so the
    only trace it left was a Task (2026-11-03, the HARBOR & LANE enquiry). Reopening is
    only safe while the run created no order, PO, style or project — re-approving a run
    that DID create one would create a second one, and ``source_key`` cannot stop that
    because the run row already exists.
    """
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status != "approved":
        return {"ok": False, "error": "not_approved", "status": run.status}
    try:
        refs = json.loads(run.created_refs or "[]")
    except Exception:
        refs = []
    real = [r for r in refs if (r.get("doctype") or "") != "Task"]
    if real:
        return {"ok": False, "error": "has_erp_records",
                "note": "this approval created " + ", ".join(f"{r['doctype']} {r['name']}" for r in real)
                        + " — roll it back first, then it can be reopened",
                "refs": real}
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    row = _chain.newest_for_run(db, run)
    if row is not None:
        matches["chain"] = _chain.context(db, row.id)
        if row.customer and not matches.get("customer"):
            matches["customer"] = row.customer
    run.matches = json.dumps(matches, default=str)
    run.route = _intake.route(facts, matches)
    run.plan = json.dumps(_intake_exec.build_plan(facts, matches), default=str)
    run.status = "understood"
    run.result_note = ((run.result_note or "") + "\nreopened for a re-plan")[:4000]
    db.commit()
    db.refresh(run)
    _log(db, "intake", "reopen_intake",
         f"Intake #{run.id} reopened and re-planned ({run.route}) — it had created nothing but a Task",
         actor=actor or "Ops Manager")
    return {"ok": True, "run": _intake_payload(db, run)}


# ────────────────────────────────────────────────────────────────────────────
# Buyer enquiries — the register an enquiry sits in (2026-11-03)
# ────────────────────────────────────────────────────────────────────────────

def _inquiry_text(db: Session, run, mail) -> str:
    """Everything the buyer wrote, for the style codes — attachments included."""
    bits = [(mail.subject if mail else "") or "", (mail.body_text if mail else "") or ""]
    for att in (db.query(MailAttachmentModel)
                .filter(MailAttachmentModel.mail_id == (mail.id if mail else -1)).all()):
        if att.text:
            bits.append(att.text[:20000])
    return "\n".join(bits)


def sync_buyer_inquiries(db: Session, refresh: int = 0) -> dict:
    """Import every enquiry the intake has read into the register. Idempotent, ERP-read only."""
    _ensure_db()
    res = _inquiry.sync(db, text_for=lambda run, mail: _inquiry_text(db, run, mail),
                        styles_for=lambda mail, text: _inquiry.styles_for_mail(
                            (mail.subject if mail else "") or "",
                            (mail.body_text if mail else "") or "",
                            text))
    rows = _inquiry.open_rows(db)
    return {**res, "count": len(rows), "summary": _inquiry.summary(rows),
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def _verified_pointers(row: dict, pairs: list) -> dict:
    """Mark which of a row's ERP pointers still resolve.

    ``mail_chain`` and ``buyer_inquiry`` both store names (``opportunity``, ``client_po``,
    ``customer``…). Those are pointers, not facts, and nothing used to re-check them — so a
    record deleted in the ERP kept being shown as if it existed (2026-11-04, D-123).

    Returns ``{"verified": [...], "missing": [...], "unavailable": [...], "state": {…}}``
    so a screen can say *deleted in ERP* instead of printing a dead name.
    """
    out = {"verified": [], "missing": [], "unavailable": [], "state": {}}
    for field, doctype in (pairs or []):
        name = (row or {}).get(field)
        if not name:
            continue
        res = erp.erp_doc_checked(doctype, name)
        state = "found" if res.state == erp.FOUND else (
            "missing" if res.state == erp.MISSING else "unavailable")
        out["state"][field] = state
        if state == "found":
            out["verified"].append(field)
        elif state == "missing":
            out["missing"].append(field)
        else:
            out["unavailable"].append(field)
    return out


_CHAIN_POINTERS = [("customer", "Customer"), ("opportunity", "Opportunity"),
                   ("client_po", "Client Purchase Order"), ("sales_order", "Sales Order")]
_INQUIRY_POINTERS = [("customer", "Customer"), ("opportunity", "Opportunity")]


def get_buyer_inquiries(db: Session, status: str = "", refresh: int = 0) -> dict:
    """The buyer-enquiry register: where an enquiry sits after the card is closed.

    One row per enquiry, with every style the buyer named and what the ERP already knows
    about it — *made before* (with the price we last sold it at), *costed*, *on file* or
    *new*. The history is read live from `Sales Order` lines, `Cost Sheet`, `Item Price`,
    `BOM` and `Buyer Tech Pack`; `refresh=1` re-reads it for every row.
    """
    _ensure_db()
    _inquiry.sync(db, text_for=lambda run, mail: _inquiry_text(db, run, mail),
                  styles_for=lambda mail, text: _inquiry.styles_for_mail(
                      (mail.subject if mail else "") or "",
                      (mail.body_text if mail else "") or "", text))
    if int(refresh or 0):
        for row in _inquiry.open_rows(db):
            _inquiry.refresh_history(db, row, text=_inquiry_text(
                db, None, db.query(MailMessageModel).filter(
                    MailMessageModel.id == row.mail_id).first()))
    rows = _inquiry.open_rows(db)
    if status and status != "all":
        rows = [r for r in rows if (r.status or "new") == status]
    items = []
    for r in rows:
        item = r.to_dict()
        item["pointers"] = _verified_pointers(item, _INQUIRY_POINTERS)
        if item["pointers"]["missing"]:
            item["stale"] = [f"{f}" for f in item["pointers"]["missing"]]
        items.append(item)
    return {"ok": True, "items": items, "count": len(items),
            "summary": _inquiry.summary(_inquiry.open_rows(db)),
            "live": True, "source": SOURCE, "generated_at": _now_iso()}


def get_buyer_inquiry(db: Session, inquiry_id: int, refresh: int = 0) -> dict:
    """One enquiry in full: the ask, the styles, and the evidence behind each verdict."""
    _ensure_db()
    row = db.query(BuyerInquiryModel).filter(BuyerInquiryModel.id == int(inquiry_id)).first()
    if not row:
        return {"ok": False, "error": "not_found"}
    if int(refresh or 0):
        mail = db.query(MailMessageModel).filter(MailMessageModel.id == row.mail_id).first()
        _inquiry.refresh_history(db, row, text=_inquiry_text(db, None, mail))
        db.refresh(row)
    out = row.to_dict()
    out["run"] = None
    if row.run_id:
        run = db.query(IntakeRunModel).filter(IntakeRunModel.id == row.run_id).first()
        out["run"] = run.to_dict() if run else None
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == row.mail_id).first()
    out["mail"] = ({"subject": mail.subject or "", "from_addr": mail.from_addr or "",
                     "from_name": mail.from_name or "", "received_at": mail.received_at or "",
                     "body_text": (mail.body_text or "")[:6000]} if mail else {})
    chain_row = _chain_row(db, row.chain_id or 0, row.run_id or 0)
    out["chain"] = chain_row.to_dict() if chain_row is not None else None
    return {"ok": True, **out, "live": True, "source": SOURCE, "generated_at": _now_iso()}


def update_buyer_inquiry(db: Session, inquiry_id: int, status: str = "", note: str = "",
                         actor: str = "Ops Manager") -> dict:
    """Move an enquiry along: ``new`` → ``costing`` → ``quoted`` → ``won`` | ``lost``.

    The register is the only place that says where an enquiry stands, so the change is
    written to the audit log with who made it.
    """
    _ensure_db()
    allowed = {"new", "costing", "quoted", "won", "lost", "dismissed"}
    row = db.query(BuyerInquiryModel).filter(BuyerInquiryModel.id == int(inquiry_id)).first()
    if not row:
        return {"ok": False, "error": "not_found"}
    if status and status not in allowed:
        return {"ok": False, "error": "bad_status", "allowed": sorted(allowed)}
    if status:
        row.status = status
    if note:
        row.note = (((row.note or "") + "\n" + note).strip())[:4000]
    db.commit()
    db.refresh(row)
    _log(db, "inquiry", "update_buyer_inquiry",
         f"Buyer enquiry #{row.id} ({row.buyer_name or 'buyer'} · {', '.join(row.to_dict()['styles']) or 'no style'})"
         f" → {row.status}" + (f": {note[:120]}" if note else ""),
         actor=actor or "Ops Manager")
    return {"ok": True, "inquiry": row.to_dict()}


def dismiss_intake(db: Session, run_id: int, actor: str = "Ops Manager") -> dict:
    """Hide a run that is not an order at all (kept, never deleted)."""
    _ensure_db()
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == int(run_id)).first()
    if not run:
        return {"ok": False, "error": "not_found"}
    if run.status == "approved":
        return {"ok": False, "error": "already_approved"}
    run.status = "rejected"
    run.result_note = "dismissed — not an order"
    run.decided_by = actor
    db.commit()
    return {"ok": True, "run": run.to_dict()}


FUNCTIONS = {
    "get_dashboard": get_dashboard,
    "ask_kogo": ask_kogo,   # retired-shim: pointer only, NOT the long-prompt path
    "get_buyer_orders": get_buyer_orders,
    "get_risks": get_risks,
    "get_recommendations": get_recommendations,
    "get_audit_log": get_audit_log,
    "get_fabric_intelligence": get_fabric_intelligence,
    "get_email_preview": get_email_preview,
    "get_erp_preview": get_erp_preview,
    "preview_action": preview_action,
    "decide_action": decide_action,
    "modify_action": modify_action,
    "execute_action": execute_action,
    "rollback_action": rollback_action,
    "run_action": run_action,
    # Email connector (P1)
    "get_mail_settings": get_mail_settings,
    "save_mail_settings": save_mail_settings,
    "test_mail_settings": test_mail_settings,
    "create_email_draft": create_email_draft,
    "get_email_drafts": get_email_drafts,
    "approve_and_send_email": approve_and_send_email,
    "reject_email_draft": reject_email_draft,
    "delete_email_draft": delete_email_draft,
    # Inbound mail (P2)
    "sync_inbox": sync_inbox,
    "get_inbox": get_inbox,
    "get_mail_message": get_mail_message,
    "get_inbox_summary": get_inbox_summary,
    "dismiss_mail": dismiss_mail,
    "get_order_changes": get_order_changes,
    # Intake (mail -> process) — P0..P3, 2026-11-03
    "sync_inbox": sync_inbox,
    "get_intake_queue": get_intake_queue,
    "get_intake": get_intake,
    "get_intake_summary": get_intake_summary,
    "understand_intake": understand_intake,
    "simulate_intake": simulate_intake,
    "approve_intake": approve_intake,
    "reject_intake": reject_intake,
    "edit_intake": edit_intake,
    "rollback_intake": rollback_intake,
    "create_intake_ack": create_intake_ack,
    "get_intake_document": get_intake_document,
    "dismiss_intake": dismiss_intake,
    "sync_intake_mail": sync_intake_mail,
    # the chain: reply from the Tower, follow the thread, ingest the pack (2026-11-03)
    "get_mail_chain": get_mail_chain,
    "send_chain_reply": send_chain_reply,
    "ingest_chain_pack": ingest_chain_pack,
    "set_intake_customer": set_intake_customer,
    "get_intake_options": get_intake_options,
    "reopen_intake": reopen_intake,
    # the buyer-enquiry register (2026-11-03)
    "get_buyer_inquiries": get_buyer_inquiries,
    "get_buyer_inquiry": get_buyer_inquiry,
    "update_buyer_inquiry": update_buyer_inquiry,
    "sync_buyer_inquiries": sync_buyer_inquiries,
    "decide_order_change": decide_order_change,
    "rollback_order_change": rollback_order_change,
    # Chat module
    "get_chat_config": get_chat_config,
    "create_room": create_room,
    "send_message": send_message,
    "fetch_threads": fetch_threads,
    "fetch_chat_history": fetch_chat_history,
}


# ────────────────────────────────────────────────────────────────────────────
# ERP model coverage (erp_model.py) — "what is actually in the ERP"
# ────────────────────────────────────────────────────────────────────────────

def _census() -> dict:
    """Stage-by-stage census of the Cortex process objects. Never raises."""
    try:
        return erp_model.census()
    except Exception as e:
        return {"error": str(e)[:200], "stages": [], "totals": {}}


def _shipment_leg_block(f: dict) -> dict:
    """The customs leg as the dashboard now reads it (grouped, counted once)."""
    return {
        "groups": f["shipment_groups"],
        "evidence_rows": f["shipment_rows"],
        "shipped_pcs": f["sent_pcs"],
        "ordered_pcs": f["sent_planned"],
        "groups_with_qty": f["shipments_captured"],
        "allowance_flags": [g.get("group") for g in f["allowance_flags"]],
        "allowance_unconfirmed": [g.get("group") for g in f.get("allowance_unconfirmed", [])],
        "groups_missing_documents": [g.get("group") for g in f["docs_missing"]],
        "unlinked_rows": [r.get("name") for r in f["unlinked_shipment_rows"]],
    }


def get_erp_model(db: Session) -> dict:
    """The ERP model census: every Cortex process object, by stage, with counts.

    Answers "is this dashboard reading the ERP as it is?" — including the objects
    that are built but still hold no rows.
    """
    status = erp.erp_status()
    return {"erp_model": _census(),
            "live": bool(status.get("connected")), "source": SOURCE,
            "generated_at": _now_iso(), "connection": status}


_RETIRED_WIP = {"retired": True, "ok": False, "live": False, "lanes": [], "orders": [], "queue": [],
                "reason": "The Cortex WIP screen is retired on a site that has the Arinox layer. Production is read from the Production Card and the Production Movement ledger: "
                          "open the Production board (production_board_get) or the Order page."}
def _wip_retired():
    """ORDER_TO_SHIP_PLAN section 3 rule 6: the old Cortex WIP readers stay in the code behind `erp_profile` = cortex_evidence; on a site with the Arinox layer
    they answer `retired` and the new reader (`production_board_get`) is used. No state is kept between calls; an unreadable ERP never retires anything."""
    try:
        import deals as _deals
        import order_flow as _of
        prof = _of.erp_profile(_deals._be())
    except Exception:                                       # noqa: BLE001
        return None
    return {**_RETIRED_WIP, "source": SOURCE, "generated_at": _now_iso(), "erp_profile": "arinox"} if prof == "arinox" else None


def get_wip_plan(db: Session, refresh: bool = False, **kwargs) -> dict:
    """The WIP as a drawing: one lane per (order, SKU) with its 13 milestones on a time axis, plus a
    month-by-month calendar of every drop-dead.

    364 milestone rows is not readable as a table — this returns the same records positioned as bars
    (`lanes[].bars[]`, each with `start`/`end`/`status`) and as calendar chips (`calendar.chips[]`), so the
    frontend draws instead of tabulating. Read-only; `refresh=true` bypasses the 90 s cache.
    """
    r = _wip_retired()
    if r:
        return r
    return wip_plan.build(force=bool(refresh))


def get_wip_analytics(db: Session, refresh: bool = False, **kwargs) -> dict:
    """Every non-Gantt WIP chart in one read: stages · ageing · output vs plan · SAM · rejects · completion ·
    shortage · the reconciliation. Each section carries its own `basis`; nothing is cached across calls."""
    import time as _t
    r = _wip_retired()
    if r:
        return r
    t0 = _t.time()
    plan = wip_plan.build(force=bool(refresh))
    a = wip_analytics.build_all(plan["orders"], plan["lanes"], date.today())
    return {**a, "live": plan["live"], "source": SOURCE, "generated_at": _now_iso(),
            "read_ms": int((_t.time() - t0) * 1000), "connection": plan.get("connection"),
            "write_mode": plan.get("write_mode"), "working_days": plan.get("working_days"),
            "issues": plan.get("issues"), "policy": plan.get("policy")}


def get_wip_thread(db: Session, wip: str = "", **kwargs) -> dict:
    """The discussion on one WIP — the `Comment` rows on the ERP record, newest first."""
    r = _wip_retired()
    if r:
        return {**r, "wip": wip, "thread": []}
    if not wip:
        return {"wip": None, "thread": [], "live": False, "source": SOURCE, "generated_at": _now_iso()}
    try:
        rows = wip_actions.thread(wip)
    except Exception as ex:                                        # noqa: BLE001
        return {"wip": wip, "thread": [], "error": str(ex)[:200], "live": False,
                "source": SOURCE, "generated_at": _now_iso()}
    return {"wip": wip, "thread": rows, "live": True, "source": SOURCE, "generated_at": _now_iso()}


def _wip_do(action, db, **kwargs):
    """One shape for the four planner actions: never a 500, always a sentence."""
    r = _wip_retired()
    if r:
        return {"ok": False, "refused": True, "reason": r["reason"], "retired": True, "live": False, "source": SOURCE, "generated_at": _now_iso()}
    if not str(kwargs.get("wip") or "").strip():
        # An empty name used to reach the ERP and come back as " could not be read from the ERP"
        # (leading space, no subject) — say the actual thing that is missing (2026-11-06).
        return {"ok": False, "refused": True, "reason": "Pick a WIP first.", "live": True, "source": SOURCE,
                "generated_at": _now_iso()}
    try:
        out = action(**kwargs)
        wip_plan._cache.update(t=0.0, v=None)               # a write invalidates the plan cache
        return {**out, "live": True, "source": SOURCE, "generated_at": _now_iso()}
    except wip_actions.Refused as ex:
        return {"ok": False, "refused": True, "reason": str(ex), "live": True, "source": SOURCE,
                "generated_at": _now_iso()}
    except Exception as ex:                                        # noqa: BLE001
        return {"ok": False, "error": str(ex)[:300], "live": True, "source": SOURCE,
                "generated_at": _now_iso()}


def wip_finalise(db: Session, wip: str = "", note: str = "", **kwargs) -> dict:
    """Draft → Planned: the planner accepts the proposed plan. Mode-gated (ERP_WRITE_MODE)."""
    return _wip_do(wip_actions.finalise, db, wip=wip, note=note)


def wip_adjust(db: Session, wip: str = "", plant: str = "", ship_date: str = "", pcd: str = "",
               note: str = "", **kwargs) -> dict:
    """Re-baseline: new ship date / plant, every OPEN gate shifted by the delta, actuals untouched."""
    return _wip_do(wip_actions.adjust, db, wip=wip, plant=plant or None, ship_date=ship_date or None,
                   pcd=pcd or None, note=note)


def wip_reject(db: Session, wip: str = "", reason: str = "", **kwargs) -> dict:
    """A proposal that will not be planned → Superseded, with the reason on the record."""
    return _wip_do(wip_actions.reject, db, wip=wip, reason=reason)


def wip_apply_plan(db: Session, wip: str = "", changes: str = "", ship_date: str = "", note: str = "",
                   **kwargs) -> dict:
    """**Write the dates the planner settled on.** `changes` = `Gate=YYYY-MM-DD;Gate2=YYYY-MM-DD`.

    This is the only write that the Plan tab uses. The `+` / `−` buttons move dates in the browser (instant,
    no ERP round-trip, no half-applied plan); pressing **Save** sends the whole set here once, and this either
    writes all of it or refuses before touching anything. A gate whose rows are already `Done` is never moved —
    an actual is history, and a re-plan may not rewrite what happened.
    """
    return _wip_do(wip_actions.apply_plan, db, wip=wip, changes=changes, ship_date=ship_date, note=note)


def wip_comment(db: Session, wip: str = "", text: str = "", **kwargs) -> dict:
    """The discussion: a Comment on the WIP, visible in the Tower and on the ERP form."""
    return _wip_do(wip_actions.comment, db, wip=wip, text=text)


def get_shipment_leg(db: Session) -> dict:
    """Shipment groups with their documents, declared quantity and variance."""
    ctx = _sync(db)
    if not ctx["live"]:
        return {"groups": [], "live": False, "source": SOURCE,
                "generated_at": _now_iso(), "connection": ctx.get("status")}
    f = _facts(ctx["snapshot"])
    return {"shipment_leg": _shipment_leg_block(f), **_meta(ctx)}


FUNCTIONS["get_erp_model"] = get_erp_model
FUNCTIONS["get_wip_plan"] = get_wip_plan
FUNCTIONS["get_wip_thread"] = get_wip_thread
FUNCTIONS["get_wip_analytics"] = get_wip_analytics
FUNCTIONS["wip_finalise"] = wip_finalise
FUNCTIONS["wip_adjust"] = wip_adjust
FUNCTIONS["wip_reject"] = wip_reject
FUNCTIONS["wip_comment"] = wip_comment
FUNCTIONS["wip_apply_plan"] = wip_apply_plan
FUNCTIONS["get_shipment_leg"] = get_shipment_leg


# ────────────────────────────────────────────────────────────────────────────
# Phase 1 — generic, live, config-driven detection engine (rulebook.py)
#
# These overrides replace the earlier hard-coded, aggregate-only risk and
# recommendation builders. They are defined last so they win at import time.
# The engine reads the ERP live (read-only) and derives one risk per offending
# record, with threshold-computed severity. See rulebook.py + rulebook.json.
# ────────────────────────────────────────────────────────────────────────────
import rulebook as _rulebook

# Keep the frontend's known risk-type vocabulary while the engine uses richer
# internal categories — so no frontend bundle rebuild is required.
_RISK_TYPE_MAP = {
    "supplier_risk": "fabric_shortage",
    "compliance_risk": "shipment_risk",
    "logistics_risk": "shipment_risk",
    "cash_risk": "margin_risk",
}


def _build_risks(d: dict) -> list:  # noqa: ARG001 — signature kept for _sync
    out = []
    for r in _rulebook.build_risks():
        r = dict(r)
        r["risk_key"] = r.pop("key", r.get("risk_key"))
        r["risk_type"] = _RISK_TYPE_MAP.get(r.get("risk_type"), r.get("risk_type"))
        r.pop("extra", None)          # action templates live on the recommendations
        out.append(r)
    return out


def _build_recommendations(d: dict) -> list:  # noqa: ARG001
    return _rulebook.build_recommendations()


def risk_summary(db: Session) -> dict:
    """Live danger/warning roll-up — drives the 'all clear' state."""
    return _rulebook.summarize(_rulebook.build_risks())


# ── Phase 3: grounded AI next-step layer (ai_nextsteps.py) ──────────────────
import ai_nextsteps as _ai
import forecast as _forecast


def get_ai_next_steps(db: Session, risk_id: int = None, risk_key: str = None,
                      limit: int = 8, refresh: int = 0) -> dict:
    """Generate grounded next-step plans for one risk, or the top `limit` risks.

    Uses the live engine's evidence pack; validates every number against it and
    caches the result (invalidated when the live evidence changes). Falls back to
    the deterministic action if the model is unavailable.
    """
    keys = None
    if risk_key:
        keys = [risk_key]
    elif risk_id is not None:
        row = db.query(RiskStateModel).filter(RiskStateModel.id == int(risk_id)).first()
        if row:
            keys = [row.risk_key]
    res = _ai.generate(db, risk_keys=keys, limit=int(limit or 8), refresh=bool(refresh))
    return {**res, "live": True, "source": SOURCE, "generated_at": _now_iso(),
            "write_mode": writes.current_mode()}


FUNCTIONS["get_ai_next_steps"] = get_ai_next_steps


# ── Phase 2: proactive monitor + push alerts (monitor.py) ───────────────────
import monitor as _monitor


def run_monitor(db: Session, notify: int = 0, force: int = 0) -> dict:
    """Scan live risks and push an alert for new/escalated criticals.

    Called on a schedule (and, throttled, from get_dashboard). Seeds a baseline
    on first run; alerts only on new or escalating criticals thereafter.
    """
    res = _monitor.run(db, notify=bool(notify), force=bool(force))
    return {**res, "live": True, "source": SOURCE, "write_mode": writes.current_mode()}


FUNCTIONS["run_monitor"] = run_monitor


FUNCTIONS["submit_in_erp"] = submit_in_erp


# ════════════════════════════════════════════════════════════════════════════
# Cortex TnA Calendar — merged INTO the Control Tower project (2026-10-08)
#
# The TnA planner / calendar experience now ships inside this app. Its backend
# lives in the self-contained ``tna_app`` subpackage: its own SQLite overlay
# store (``tna_app/data/``), its own live-ERP reader and its own plan engine.
#
# Every TnA function is re-exposed here, wrapped so it runs against the TNA
# session (the Control Tower has a different schema, so we must not hand it the
# Tower ``db``). Three names collide with Control Tower functions, so the TnA
# variants publish under a ``tna_`` prefix:
#     get_audit_log   → tna_get_audit_log
#     run_action      → tna_run_action
#     rollback_action → tna_rollback_action
# ════════════════════════════════════════════════════════════════════════════

TNA_FUNCTIONS: dict = {}
TNA_NAME_ALIASES = {
    "get_audit_log": "tna_get_audit_log",
    "run_action": "tna_run_action",
    "rollback_action": "tna_rollback_action",
}


def _make_tna_wrapper(fn):
    """Wrap a TnA function so it uses the TNA session, not the Tower's."""
    def _wrapper(db: Session = None, **kwargs) -> dict:  # noqa: ARG001 — db is intentionally ignored
        from tna_app.database import get_session, init_db
        init_db()
        session = get_session()
        try:
            return fn(db=session, **kwargs)
        finally:
            session.close()
    _wrapper.__name__ = getattr(fn, "__name__", "tna_fn")
    _wrapper.__doc__ = getattr(fn, "__doc__", None)
    return _wrapper


try:
    from tna_app import functions as _tna_functions
    for _name, _fn in _tna_functions.FUNCTIONS.items():
        _public = TNA_NAME_ALIASES.get(_name, _name)
        TNA_FUNCTIONS[_public] = _make_tna_wrapper(_fn)
        FUNCTIONS[_public] = TNA_FUNCTIONS[_public]
except Exception as _tna_exc:  # never break the Control Tower if the TnA module is unavailable
    import sys as _sys
    print(json.dumps({"warning": "tna_app unavailable", "error": str(_tna_exc)}), file=_sys.stderr)


def call_function(name: str, db: Session, **kwargs) -> dict:
    func = FUNCTIONS.get(name)
    if not func:
        raise ValueError(f"Function '{name}' not found. Available: {list(FUNCTIONS.keys())}")
    return func(db=db, **kwargs)


# ════════════════════════════════════════════════════════════════════════════
# Arinox layer (2026-11-06): identity, guardrails, the Tower Script Runtime, two-way sync, any-format inquiries.
# See cortex_api.py and CORTEX_TOWER_PLAN.md. Added last so nothing above is changed.
# ════════════════════════════════════════════════════════════════════════════
import cortex_api as _cx
_cx.bind_legacy(globals())

#: functions that WRITE (to the ERP, to mail, or to decisions). Require a signed-in person who holds a tower role;
#: the verified identity — never the client's ``actor`` parameter — is what gets audited.
_LEGACY_WRITES = {
    "decide_action", "modify_action", "execute_action", "run_action", "run_monitor", "create_email_draft", "approve_and_send_email",
    "reject_email_draft", "delete_email_draft", "approve_intake", "reject_intake", "edit_intake", "create_intake_ack",
    "send_chain_reply", "ingest_chain_pack", "set_intake_customer", "dismiss_intake", "dismiss_mail", "update_buyer_inquiry",
    "wip_finalise", "wip_adjust", "wip_reject", "wip_comment", "wip_apply_plan", "save_mail_settings", "test_mail_settings",
    "tna_run_action", "decide_order_change",
}
#: undoing things is a manager's call
_LEGACY_MANAGER = {"rollback_action", "rollback_intake", "rollback_order_change", "submit_in_erp", "tna_rollback_action", "reopen_intake"}


def _legacy_guard(name, fn):
    import inspect
    try:
        has_actor = "actor" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        has_actor = False
    needs_role = name in _LEGACY_WRITES or name in _LEGACY_MANAGER

    def guarded_fn(db, **kwargs):
        import cx_users, guardrails
        try:
            me = cx_users.require(db, **kwargs)
        except PermissionError as e:
            return {"ok": False, "error": str(e), "auth": False}
        kwargs.pop("_app_token", None)
        if needs_role:
            allowed = set(guardrails.ALL_POWER) if name in _LEGACY_MANAGER else set(guardrails.ROLES)
            if not set(me["roles"]) & allowed:
                return {"ok": False, "error": "Your role does not allow this action. Ask a manager.", "denied": True}
        if has_actor:
            kwargs["actor"] = me["name"] or me["email"]         # never trust a client-supplied actor
        else:
            kwargs.pop("actor", None)
        return fn(db=db, **kwargs)
    guarded_fn.__name__ = getattr(fn, "__name__", name)
    guarded_fn.__doc__ = getattr(fn, "__doc__", "")
    return guarded_fn


for _name in list(FUNCTIONS):
    if _name in _cx.PUBLIC or _name in _cx.FUNCTIONS:
        continue
    FUNCTIONS[_name] = _legacy_guard(_name, FUNCTIONS[_name])
FUNCTIONS.update(_cx.FUNCTIONS)
_BRIDGE_ACTIONS.update(_cx.FUNCTIONS.keys())
# the workspace (2026-11-07): one inbox as conversations, deals from inquiry to Sales Order, customers, dashboard
import deal_api as _deal_api  # noqa: E402
FUNCTIONS.update(_deal_api.FUNCTIONS)
_BRIDGE_ACTIONS.update(_deal_api.FUNCTIONS.keys())
# the post-order half (2026-11-09): one Order page per Sales Order
import order_api as _order_api  # noqa: E402
FUNCTIONS.update(_order_api.FUNCTIONS)
_BRIDGE_ACTIONS.update(_order_api.FUNCTIONS.keys())
# steps 4 to 7 of the Order page (S4 samples and PP, S5 materials, S6 cut and sew + production board, S7 subcontract and finish)
import order_samples as _order_samples  # noqa: E402
import order_materials as _order_materials  # noqa: E402
import order_cutsew as _order_cutsew  # noqa: E402
import order_subcontract as _order_subcontract  # noqa: E402
# steps 8 to 10 (S8 pack and inspect, S9 ship wizard, S10 invoice, collect and close)
import order_pack as _order_pack  # noqa: E402
import order_ship as _order_ship  # noqa: E402
import order_invoice as _order_invoice  # noqa: E402
for _m in (_order_samples, _order_materials, _order_cutsew, _order_subcontract, _order_pack, _order_ship, _order_invoice):
    FUNCTIONS.update(_m.FUNCTIONS)
    _BRIDGE_ACTIONS.update(_m.FUNCTIONS.keys())


if __name__ == "__main__":
    import sys
    from database import get_session, init_db

    init_db()

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python functions.py <function_name> [json_params]"}))
        sys.exit(1)

    func_name = sys.argv[1]
    params = {}
    if len(sys.argv) > 2:
        try:
            params = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON params: {e}"}))
            sys.exit(1)

    db = get_session()
    try:
        func = FUNCTIONS.get(func_name)
        if not func:
            print(json.dumps({"error": f"Function '{func_name}' not found. Available: {list(FUNCTIONS.keys())}"}))
            sys.exit(1)
        result = func(db=db, **params)
        print(json.dumps(result, default=str))
    except Exception as e:
        db.rollback()
        print(json.dumps({"error": str(e), "function": func_name, "params": params}))
        sys.exit(1)
    finally:
        db.close()
