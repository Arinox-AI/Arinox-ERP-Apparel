"""Cortex Operations Control Tower — the process, read as records.

`Cortex Milestone Template` used to be 13 rows of invented offsets and carried no idea of a phase at all.
Since 2026-11-03 it is **29 gates in the client's 5 phases**, and every row says where its number came from
(`duration_source` = `measured` · `default` · `pinned` · `planner set`). This module is the only reader of that
master; nothing downstream re-types a gate name or an offset.

    chain()      the 29 gates, in process order, with phase, offset, duration, evidence doctype and provenance
    phases()     the same gates grouped 1…5, with each phase's span in days
    rank()       gate -> position in DATE order (1 = earliest). Not `sequence`: the client's phases are an
                 ownership order, and two of them overlap in time, so `sequence` cannot rank "how far along".
    suggest()    a proposed date per gate for an anchor date — anchor − offset_days, the whole plan, no writes
    slack()      the latest honest date per gate, walking back from the anchor

Read-only. Never raises: an unreachable ERP returns the fallback chain (the same 29 gates, offsets from
`build/planning_build/build_phases.py`) with `live: false`, so the Plan tab still draws.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import erp

TEMPLATE = "Cortex Milestone Template"
CACHE_TTL = 120.0
_cache: dict = {"t": 0.0, "v": None}

PHASE_NAME = {1: "Win the order", 2: "Plan & sample", 3: "Materials", 4: "Production", 5: "Exit"}

# Fallback only — mirrors build/planning_build/build_phases.py so the tab is never empty. Anything live wins.
_FALLBACK = [
    ("Inquiry Received", 1, 80, "Merchandising", 1, "Opportunity", "default"),
    ("Tech Pack Received", 1, 78, "Merchandising", 1, "Buyer Tech Pack", "default"),
    ("Buyer BOM Received", 1, 75, "Merchandising", 0, "Buyer BOM", "default"),
    ("Costing Issued", 1, 72, "Merchandising", 1, "Costing Sheet", "default"),
    ("Price Negotiated & Locked", 1, 68, "Merchandising", 1, "Quotation", "default"),
    ("Order Confirmed", 1, 64, "Merchandising", 1, "Sales Order", "default"),
    ("Production Plan & Capacity Slot", 2, 62, "Production Planner", 1, "Cortex WIP", "default"),
    ("Fit Samples 1-3", 2, 56, "Quality", 1, "Sample Request", "default"),
    ("PP Sample Approval", 2, 39, "Quality", 1, "Sample Request", "measured"),
    ("Bulk Standard Approved", 2, 37, "Quality", 0, "", "default"),
    ("Fabric Requisition Placed", 3, 60, "Fabric Purchase", 1, "Cortex Fabric Requisition", "default"),
    ("Trim Requisition Placed", 3, 58, "Trim Purchase", 1, "Cortex Trim Requisition", "default"),
    ("Purchase Order Placed", 3, 57, "Fabric Purchase", 1, "Purchase Order", "default"),
    ("Fabric Ready at Mill", 3, 55, "Fabric Purchase", 1, "", "measured"),
    ("Fabric ETD", 3, 50, "Fabric Purchase", 1, "Shipment Document Evidence", "measured"),
    ("Fabric In-House", 3, 34, "Fabric Purchase", 1, "Stock Entry", "measured"),
    ("Fabric Tested & Inspected", 3, 33, "Quality", 1, "Quality Inspection", "default"),
    ("Stock Entry Receipt", 3, 31, "Warehouse", 1, "Stock Entry", "default"),
    ("PP Meeting", 4, 36, "Production Planner", 1, "PP Meeting", "default"),
    ("Job Cards Issued", 4, 35, "Production Planner", 1, "Job Card", "default"),
    ("Cutting", 4, 30, "Production Planner", 1, "Work Order", "measured"),
    ("TOP Sample Approved", 4, 27, "Quality", 0, "Sample Request", "measured"),
    ("Sewing Complete", 4, 20, "Production Planner", 1, "Work Order", "default"),
    ("Washing", 4, 14, "Production Planner", 0, "Work Order", "default"),
    ("Final Check & Pack", 4, 6, "Quality", 1, "Quality Inspection", "default"),
    ("Buyer Final Inspection", 5, 3, "Quality", 1, "Quality Inspection", "default"),
    ("Ship", 5, 0, "Merchandising", 1, "Delivery Note", "pinned"),
    ("Payment Maturity", 5, -70, "Finance", 0, "Payment Entry", "measured"),
    ("Grievance Closed", 5, -80, "Merchandising", 0, "Issue", "default"),
]


def _fallback_chain() -> list[dict]:
    out = []
    for i, (name, phase, off, dept, crit, ev, src) in enumerate(_FALLBACK, start=1):
        out.append({"milestone": name, "sequence": i, "phase": phase,
                    "phase_name": PHASE_NAME.get(phase, ""), "offset_days": off, "duration_days": 0,
                    "department": dept, "critical": bool(crit), "evidence_doctype": ev or None,
                    "duration_source": src, "source_note": "", "active": True})
    return out


def _int(v, d=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def chain(force: bool = False) -> list[dict]:
    """The gate master. Cached 120 s — it changes when a planner edits a duration, not per request."""
    if not force and _cache["v"] and (time.time() - _cache["t"]) < CACHE_TTL:
        return _cache["v"]
    rows = erp.erp_get(TEMPLATE, fields=["name", "milestone", "sequence", "offset_days", "duration_days",
                                         "department", "critical", "active", "phase", "phase_name",
                                         "evidence_doctype", "duration_source", "source_note"],
                       filters=[["active", "=", 1]], limit=0, order="sequence asc")
    out = []
    for r in rows or []:
        out.append({
            "milestone": r.get("milestone") or r.get("name"),
            "sequence": _int(r.get("sequence")),
            "phase": _int(r.get("phase")) or 1,
            "phase_name": r.get("phase_name") or PHASE_NAME.get(_int(r.get("phase")) or 1, ""),
            "offset_days": _int(r.get("offset_days")),
            "duration_days": _int(r.get("duration_days")),
            "department": r.get("department"),
            "critical": bool(_int(r.get("critical"))),
            "evidence_doctype": r.get("evidence_doctype") or None,
            "duration_source": r.get("duration_source") or "default",
            "source_note": r.get("source_note") or "",
            "active": True,
        })
    out.sort(key=lambda g: g["sequence"])
    if not out:
        out = _fallback_chain()
    _cache.update(t=time.time(), v=out)
    return out


def phases(force: bool = False) -> list[dict]:
    """The five phases with their gates and their span in days (offset of the first gate − offset of the last)."""
    gates = chain(force)
    out = []
    for p in sorted({g["phase"] for g in gates}):
        mine = [g for g in gates if g["phase"] == p]
        offs = [g["offset_days"] for g in mine]
        out.append({"phase": p, "name": PHASE_NAME.get(p, mine[0]["phase_name"] or f"Phase {p}"),
                    "gates": [g["milestone"] for g in mine], "count": len(mine),
                    "first_offset": max(offs), "last_offset": min(offs),
                    "span_days": max(offs) - min(offs),
                    "days_before_delivery": max(offs)})
    return out


def rank(force: bool = False) -> dict:
    """gate -> its position in DATE order (1 = earliest). The client's `sequence` is the ownership order and
    two phases overlap in time, so `sequence` cannot answer 'how far along is this gate'."""
    gates = sorted(chain(force), key=lambda g: -g["offset_days"])
    return {g["milestone"]: i + 1 for i, g in enumerate(gates)}


def suggest(anchor: date, force: bool = False) -> list[dict]:
    """A proposed date per gate: anchor − offset_days. The anchor is the order's delivery date."""
    out = []
    for g in chain(force):
        out.append({**g, "suggested": (anchor - timedelta(days=g["offset_days"])).isoformat(),
                    "days_before_anchor": g["offset_days"]})
    return out


def slack(ship: date, open_gates: list[str], force: bool = False) -> dict:
    """The latest honest date per gate, walking back from the ship date with the gates' own durations."""
    by_name = {g["milestone"]: g for g in chain(force)}
    tail = 0
    out = {}
    for name in sorted(open_gates, key=lambda n: -(by_name.get(n, {}).get("offset_days") or 0)):
        g = by_name.get(name)
        if not g:
            continue
        latest = ship - timedelta(days=tail)
        out[name] = {"latest": latest.isoformat(), "duration_days": g["duration_days"]}
        tail += g["duration_days"]
    return out
