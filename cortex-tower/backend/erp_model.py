"""Cortex Operations Control Tower — the ERP model census.

The dashboard used to describe an October-2026 slice of the ERP: 18 doctypes, four
of which (`Garment Shipment Evidence`, `Production Daily Evidence`,
`Trim Requisition Evidence`, `Fabric Requisition Evidence`) have since been retired
and now hold **zero** rows, so those panels read empty while the ERP holds real
data under the newer objects (`Shipment Document Evidence`, `Cortex Trim
Requisition`, `Cortex Fabric Requisition`, `PP Meeting`, ...).

This module is the single place that answers "what is actually in the ERP today".
It walks the Cortex process objects stage by stage and reports, per object:

    {doctype, purpose, count, populated, missing, status}

`status` is one of
    "populated" — the doctype exists and holds rows
    "empty"     — the doctype exists and holds no rows (built, not used yet)
    "missing"   — the doctype is not installed on this ERP

The census is a *read*: one `frappe.client.get_count` per object, cached briefly,
run on a small thread pool so the dashboard stays responsive.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import erp

CACHE_TTL = 120.0  # seconds
_cache: dict = {"t": 0.0, "v": None}

# ── the model, stage by stage ───────────────────────────────────────────────
# (stage_key, label, [(doctype, what the dashboard asks it for), ...])
STAGES = [
    ("pre_order", "Pre-order · buyer side", [
        ("Opportunity", "the enquiry"),
        ("Style File", "the style folder — one per style"),
        ("Buyer Tech Pack", "the buyer's pack, one per revision"),
        ("Buyer BOM", "the customer-side BOM, one per pack revision"),
        ("Item Mapping", "buyer code → our item"),
        ("Consumption Card", "CAD consumption + wastage per size"),
        ("Cost Sheet", "costed FOB, margin, gate"),
        ("Quotation", "the offer to the buyer"),
    ]),
    ("order", "Win the order", [
        ("Client Purchase Order", "the buyer's PO, as received"),
        ("Sales Contract", "the contract sheets"),
        ("Contract Allowance Band", "quantity allowance per order band"),
        ("Sales Order", "the order of record"),
        ("Project", "one per style/order folder"),
    ]),
    ("buying", "Buying · requisitions", [
        ("Cortex Fabric Requisition", "fabric demand per style"),
        ("Cortex Trim Requisition", "trim demand per style"),
        ("Material Request", "the request that reaches purchasing"),
        ("Purchase Order", "supplier orders"),
        ("Purchase Receipt", "goods received"),
        ("Supplier", "the vendor master"),
    ]),
    ("production", "Production · shop floor", [
        ("BOM", "bill of materials, one per size"),
        ("Work Order", "the manufacturing order"),
        ("Job Card", "operation-level work"),
        ("Cortex Marker", "the marker / lay plan"),
        ("Cutting Lay", "the lay (batch) released to cutting"),
        ("Production Card", "the bundle card on the floor"),
        ("PP Meeting", "pre-production meeting + gates"),
        ("Cortex WIP", "work in progress by stage"),
        ("Cortex End Line Audit", "end-of-line audit"),
        ("Stock Entry", "material issue / FG receipt"),
    ]),
    ("shipment", "Shipment · customs", [
        ("Freight Booking", "the booking, vessel and cut-off"),
        ("Shipment Document Evidence", "the customs basis + document set"),
        ("Delivery Note", "the goods-movement document"),
        ("Shipment", "the ERP shipment"),
    ]),
    ("quality", "Quality", [
        ("Quality Inspection", "inspection / AQL gate"),
        ("Fabric Quality Evidence", "fabric inspection sheets"),
        ("Fabric Inventory Variance", "physical vs system fabric"),
        ("Warehouse Report Evidence", "finished-goods stock counts"),
    ]),
    ("finance", "Finance", [
        ("Sales Invoice", "the commercial invoice"),
        ("Payment Entry", "receipts and payments"),
        ("Purchase Invoice", "supplier invoices"),
        ("Fabric Roll", "the fabric store"),
    ]),
    ("master", "Master data", [
        ("Item", "items + style variants"),
        ("Product Type", "product family master"),
        ("Cost Head", "costing heads"),
        ("Costing Parameter", "the rate card"),
    ]),
]

# Doctypes the dashboard must never read: retired, replaced by a newer object.
# Surfaced so the census reports the retirement instead of silently reading 0.
RETIRED = {
    "Garment Shipment Evidence": "Shipment Document Evidence",
    "Production Daily Evidence": "Cutting Lay / Production Card / PP Meeting",
    "Trim Requisition Evidence": "Cortex Trim Requisition",
    "Fabric Requisition Evidence": "Cortex Fabric Requisition",
}


def _count(doctype: str) -> int:
    try:
        return int(erp.erp_count(doctype) or 0)
    except Exception:
        return -1


def _installed() -> set:
    """The doctypes that exist on this ERP (one list read, cached by erp.py)."""
    try:
        rows = erp.erp_get("DocType", fields=["name"], limit=0) or []
        return {r.get("name") for r in rows if r.get("name")}
    except Exception:
        return set()


def census() -> dict:
    """Live census of the Cortex process objects. Never raises."""
    if _cache["v"] and (time.time() - _cache["t"]) < CACHE_TTL:
        return _cache["v"]

    installed = _installed()
    wanted = [(s[0], s[1], o) for s in STAGES for o in s[2]]

    with ThreadPoolExecutor(max_workers=12) as pool:
        counts = list(pool.map(lambda w: _count(w[2][0]), wanted))

    by_stage: dict = {}
    totals = {"objects": 0, "populated": 0, "empty": 0, "missing": 0, "rows": 0}
    for (stage_key, label, (doctype, purpose)), n in zip(wanted, counts):
        if doctype not in installed:
            status, n = "missing", 0
        elif n > 0:
            status = "populated"
        else:
            status = "empty"
            n = 0
        row = {"doctype": doctype, "purpose": purpose, "count": n, "status": status}
        st = by_stage.setdefault(stage_key, {"key": stage_key, "label": label,
                                             "objects": [], "populated": 0, "total": 0})
        st["objects"].append(row)
        st["total"] += 1
        st["populated"] += 1 if status == "populated" else 0
        totals["objects"] += 1
        totals["rows"] += n
        totals[{"populated": "populated", "empty": "empty", "missing": "missing"}[status]] += 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "KOGO ERP",
        "stages": [by_stage[s[0]] for s in STAGES if s[0] in by_stage],
        "totals": totals,
        "retired": [{"retired": k, "use": v} for k, v in RETIRED.items()],
    }
    _cache.update({"t": time.time(), "v": out})
    return out


def invalidate() -> None:
    _cache.update({"t": 0.0, "v": None})


# ── the shipment leg, read from the objects that exist today ────────────────
# `Shipment Document Evidence` (one row per document, customs basis) +
# `Freight Booking` (the booking/vessel) replaced the retired
# `Garment Shipment Evidence`. This reader turns them into the shape the
# dashboard already understands, so every panel keeps working on live data.
_SHIP_TTL = 60.0
_ship_cache: dict = {"t": 0.0, "v": None}

REQUIRED_DOCS = {"Customs Declaration", "Bill of Lading or Air Waybill"}
COMMERCIAL_DOCS = {"Commercial Invoice", "Packing List"}


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _band_pct(qty, bands) -> tuple:
    """``(tolerance_pct, source)`` for an order quantity — from the record.

    ``(None, reason)`` means **no band covers this quantity**: an answer, not a
    fallback. The caller must report UNCONFIRMED rather than invent a number.
    """
    q = _num(qty)
    if not q:
        return None, "no order quantity"
    rows = [b for b in (bands or [])
            if b.get("active", 1) and b.get("band_from") is not None and b.get("band_to") is not None
            and _num(b["band_from"]) <= q <= _num(b["band_to"])]
    if not rows:
        return None, f"no band covers {q:,.0f} pcs"
    return _num(rows[0].get("tolerance_pct")), (rows[0].get("name") or "band")


def _apply_allowance(groups) -> None:
    """Judge each shipment group against the contract band, in place."""
    try:
        bands = erp.erp_get("Contract Allowance Band",
                            fields=["name", "band_from", "band_to", "tolerance_pct",
                                    "customer", "active"], limit=0) or []
    except Exception:
        bands = []
    for g in groups:
        pct, src = _band_pct(g.get("ordered"), bands)
        g["allowance_pct"] = pct
        g["allowance_source"] = src
        g["allowance_stored"] = g.get("variance_status") or None
        if pct is None:
            g["allowance_verdict"] = "UNCONFIRMED"
            g["variance_status"] = "UNCONFIRMED - no allowance band for this quantity"
        else:
            over = abs(_num(g.get("variance_pct"))) > pct
            g["allowance_verdict"] = "Over" if over else "Within"
            g["variance_status"] = ("Over allowance - awaiting approval" if over
                                    else "Within allowance")


def shipment_leg() -> dict:
    """``{rows, groups, sent_by_so, sent_by_style, evidence}`` — live. Never raises."""
    if _ship_cache["v"] and (time.time() - _ship_cache["t"]) < _SHIP_TTL:
        return _ship_cache["v"]

    evidence = erp.erp_get(
        "Shipment Document Evidence",
        fields=["name", "shipment_group", "sales_order", "client_purchase_order", "customer_po_no",
                "customer_order_ref", "declaration_no", "declaration_qty",
                "declared_fob_value",
                "declared_value_currency", "variance_status", "etd", "eta", "evidence_status"],
        limit=0,
    ) or []
    cpos = erp.erp_get("Client Purchase Order",
                       fields=["name", "style_no", "qty", "amount_usd", "customer", "client_po_no"],
                       limit=0) or []
    bookings = erp.erp_get("Freight Booking",
                           fields=["name", "status", "mode", "booking_no", "sales_order",
                                   "client_purchase_order", "etd", "eta", "cartons", "cbm"],
                           limit=0) or []

    cpo_style = {c.get("name"): (c.get("style_no") or "") for c in cpos}
    cpo_qty = {c.get("name"): _num(c.get("qty")) for c in cpos}
    cpo_by_so = {}
    for b in bookings:
        if b.get("client_purchase_order") and b.get("sales_order"):
            cpo_by_so.setdefault(b["sales_order"], b["client_purchase_order"])
    for c in cpos:
        if c.get("name"):
            cpo_by_so.setdefault("", c["name"])

    rows, groups = [], {}
    for e in evidence:
        name = e.get("name")
        doc = erp.erp_doc("Shipment Document Evidence", name) or {}
        grid = [r for r in (doc.get("size_quantities") or []) if isinstance(r, dict)]
        docs = [f.get("document_type") for f in (doc.get("files") or []) if f.get("document_type")]

        grid_shipped = sum(_num(r.get("shipped_qty")) for r in grid)
        grid_ordered = sum(_num(r.get("ordered_qty")) for r in grid)
        grid_variance = sum(_num(r.get("variance_qty")) for r in grid)
        decl_qty = _num(e.get("declaration_qty"))
        shipped = grid_shipped or decl_qty
        cpo = (e.get("client_purchase_order") or "").strip()
        ordered = grid_ordered or cpo_qty.get(cpo) or 0.0
        variance = grid_variance or ((shipped - ordered) if ordered else 0.0)
        style = cpo_style.get(cpo) or ""

        # One shipment is described by SEVERAL evidence rows (a customs
        # declaration row, a bill-of-lading row, a size-grid row). Group them, and
        # take the group's quantity as a MAX — summing the rows double-counts the
        # same cartons (that is exactly how 1,520 pcs became 3,040).
        # the buyer's reference, whatever this buyer calls it — `customer_em_no` is the EM-era
        # column and is empty for every non-EMJ shipment (2026-11-03)
        gkey = (e.get("shipment_group") or cpo or e.get("customer_order_ref")
                or e.get("customer_po_no") or name)

        row = {
            "name": name,
            "sales_order": e.get("sales_order") or "",
            "item": style,
            "customer_po_no": e.get("customer_po_no") or "",
            "customer_order_ref": e.get("customer_order_ref") or "",
            "customer_order_ref": e.get("customer_order_ref") or e.get("customer_em_no") or "",
            "client_purchase_order": cpo,
            "shipment_group": e.get("shipment_group") or "",
            "declaration_no": e.get("declaration_no") or "",
            "declared_fob_value": _num(e.get("declared_fob_value")),
            "declared_value_currency": e.get("declared_value_currency") or "",
            "ordered_qty": ordered,
            "shipped_qty": shipped,
            "sales_order_qty": ordered,
            "shipment_variance_qty": variance,
            "variance_status": e.get("variance_status") or "",
            "etd": e.get("etd"),
            "eta": e.get("eta"),
            "documents": docs,
            "ship_via": "",
            "source_invoice_no": e.get("declaration_no") or "",
            "group": gkey,
            "qty_captured": bool(shipped),
        }
        for b in bookings:
            if row["sales_order"] and b.get("sales_order") == row["sales_order"]:
                row["ship_via"] = b.get("mode") or ""
                row["booking"] = b.get("name")
                row["etd"] = row["etd"] or b.get("etd")
                row["eta"] = row["eta"] or b.get("eta")
                break
        rows.append(row)

        g = groups.setdefault(gkey, {"group": gkey, "sales_order": "", "client_purchase_order": "",
                                     "rows": [], "documents": set(), "shipped": 0.0,
                                     "ordered": 0.0, "variance_status": "", "style": ""})
        g["rows"].append(name)
        g["documents"].update(docs)
        g["shipped"] = max(g["shipped"], shipped)
        g["ordered"] = max(g["ordered"], ordered)
        g["sales_order"] = g["sales_order"] or row["sales_order"]
        g["client_purchase_order"] = g["client_purchase_order"] or cpo
        g["style"] = g["style"] or style
        g["variance_status"] = g["variance_status"] or row["variance_status"]

    sent_by_so, sent_by_style = {}, {}
    for g in groups.values():
        if g["sales_order"]:
            sent_by_so[g["sales_order"]] = sent_by_so.get(g["sales_order"], 0.0) + g["shipped"]
        if g["style"]:
            sent_by_style[g["style"]] = sent_by_style.get(g["style"], 0.0) + g["shipped"]
        g["qty_captured"] = bool(g["shipped"])
        g["variance_qty"] = (g["shipped"] - g["ordered"]
                             if (g["ordered"] and g["qty_captured"]) else 0.0)
        g["variance_pct"] = (round(100.0 * g["variance_qty"] / g["ordered"], 2)
                             if (g["ordered"] and g["qty_captured"]) else 0.0)

    # The allowance is a RECORD (`Contract Allowance Band`), and this function is the
    # one place every page gets a shipment from — so it is judged here, once. The
    # evidence row's own stamp came from a runner that typed 3 % (RULES 01 #109);
    # it is kept as `allowance_stored` so a disagreement stays visible, never used.
    _apply_allowance(groups.values())

    out = {
        "rows": rows,
        "evidence": evidence,
        "bookings": bookings,
        "groups": [{**{k: v for k, v in g.items() if k != "documents"},
                    "documents": sorted(g["documents"]),
                    "missing": sorted(REQUIRED_DOCS - g["documents"]),
                    "commercial_missing": sorted(COMMERCIAL_DOCS - g["documents"])}
                   for g in groups.values()],
        "sent_by_so": sent_by_so,
        "sent_by_style": sent_by_style,
    }
    _ship_cache.update({"t": time.time(), "v": out})
    return out


def invalidate_shipments() -> None:
    _ship_cache.update({"t": 0.0, "v": None})
