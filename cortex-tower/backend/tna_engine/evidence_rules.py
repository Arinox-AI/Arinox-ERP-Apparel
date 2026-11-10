"""The evidence rule table (TNA plan section 8.1, D6): which Arinox document proves which milestone, which field carries the date and
what makes it count. DATA ONLY in T0/T1 (the readers that stamp actuals are slice T2); it lives here so the model, the vocabulary and
the scheduler already know every source, and so a contract test can prove each doctype and field exists on the ERP.

``code`` is an ERP ``TNA Milestone Type`` code (``vocab``). ``link`` says how a document is found for an order: ``sales_order`` (a field on
it), ``child:<Child>.<field>`` (a row links the order), ``via:<DocType>.<field>`` (another evidence document names it).
``complete`` is the completeness rule in words, ``status`` the docstatus that counts (1 = submitted, 0 or 1 = the doctype has no draft rule).
Nothing is derived from a draft unless the document type has no draft state (section 8.2).
"""

from __future__ import annotations

RULES = [
    # the 16 rows of section 8.1
    {"code": "ORDER_RECEIVED", "doctype": "Sales Order", "link": "name", "date": "transaction_date", "status": [1], "complete": "the order exists and is submitted"},
    {"code": "TECH_PACK_RECEIVED", "doctype": "Tech Pack", "link": "style_item", "date": "received_on", "status": [1], "complete": "submitted"},
    {"code": "BOM_RECEIVED", "doctype": "Tech Pack", "link": "style_item", "date": "received_on", "status": [0, 1], "complete": "at least one material row"},
    {"code": "MINI_MARKER", "doctype": "Cut Plan", "link": "sales_order", "date": "approved_on", "status": [0, 1], "complete": "exists"},
    {"code": "FR_RAISED", "doctype": "Fabric Requisition", "link": "child:Fabric Requisition Item.sales_order", "date": "fr_date", "status": [1], "complete": "submitted"},
    {"code": "FABRIC_BOOKED", "doctype": "Purchase Order", "link": "child:Purchase Order Item.sales_order", "date": "transaction_date", "status": [1], "complete": "submitted, for this order's style"},
    {"code": "FABRIC_IN_HOUSE", "doctype": "Purchase Receipt", "link": "child:Purchase Receipt Item.sales_order", "date": "posting_date", "status": [1], "complete": "submitted, quantity above zero"},
    {"code": "FABRIC_QC_PASSED", "doctype": "Fabric Inspection", "link": "via:Fabric Requisition.fabric_requisition", "date": "inspection_date", "status": [1], "complete": "the verdict is pass"},
    {"code": "FABRIC_ETD", "doctype": "Purchase Order", "link": "child:Purchase Order Item.sales_order", "date": "schedule_date", "status": [1], "complete": "the supplier's own date, never guessed"},
    {"code": "PP_MEETING", "doctype": "PP Meeting", "link": "sales_order", "date": "meeting_date", "status": [1], "complete": "exists"},
    {"code": "PCD", "doctype": "Production Card", "link": "sales_order", "date": "pcd", "status": [0, 1], "complete": "exists (the factory allocation's PCD is the plan; the card's PCD is the evidence)"},
    {"code": "BULK_FINISH", "doctype": "Daily Line Report", "link": "via:Production Card.production_card", "date": "report_date", "status": [1], "complete": "date of the last sewing output; without it a person confirms with a photo"},
    {"code": "PACK_FINISHED", "doctype": "Packing List", "link": "sales_order", "date": "packing_date", "status": [1], "complete": "submitted"},
    {"code": "FINAL_INSPECTION", "doctype": "Final Inspection", "link": "sales_order", "date": "inspection_date", "status": [1], "complete": "a result is recorded"},
    {"code": "ON_BOARD", "doctype": "Shipment", "link": "via:Packing List.shipment", "date": "pickup_date", "status": [1], "complete": "exists"},
    {"code": "IN_WAREHOUSE", "doctype": "Shipment", "link": "via:Packing List.shipment", "date": "pickup_date", "status": [1], "complete": "arrival recorded (a person confirms until the ERP carries the arrival date)"},
    # the other Arinox documents D6 names, so no document is left out
    {"code": "TR_RAISED", "doctype": "Trim Requisition", "link": "child:Trim Requisition Item.sales_order", "date": "tr_date", "status": [1], "complete": "submitted"},
    {"code": "TRIMS_IN_HOUSE", "doctype": "Purchase Receipt", "link": "child:Purchase Receipt Item.sales_order", "date": "posting_date", "status": [1], "complete": "submitted, trim items"},
    {"code": "TRIMS_QC_PASSED", "doctype": "Trim Inspection", "link": "via:Trim Requisition.trim_requisition", "date": "received_date", "status": [1], "complete": "the result is pass"},
    {"code": "LAB_DIP", "doctype": "Sample Approval", "link": "sales_order", "date": "approved_on", "status": [1], "complete": "type Lab Dip, status Approved"},
    {"code": "FIT", "doctype": "Sample Approval", "link": "sales_order", "date": "approved_on", "status": [1], "complete": "type Fit, status Approved"},
    {"code": "PP_GPT", "doctype": "Sample Approval", "link": "sales_order", "date": "approved_on", "status": [1], "complete": "type PP, status Approved"},
    {"code": "PILOT_RUN", "doctype": "Pilot Run", "link": "sales_order", "date": "approved_on", "status": [1], "complete": "status Approved"},
    {"code": "CUT_START", "doctype": "Cut Plan", "link": "sales_order", "date": "approved_on", "status": [1], "complete": "released"},
    {"code": "SEW_START", "doctype": "Daily Line Report", "link": "via:Production Card.production_card", "date": "report_date", "status": [1], "complete": "the first day with sewing output"},
    {"code": "QC_INLINE", "doctype": "Line QC Report", "link": "via:Production Card.production_card", "date": "report_date", "status": [1], "complete": "exists"},
    {"code": "QC_ENDLINE", "doctype": "Line QC Report", "link": "via:Production Card.production_card", "date": "report_date", "status": [1], "complete": "the last report of the order"},
    {"code": "PACKLIST", "doctype": "Packing List", "link": "sales_order", "date": "packing_date", "status": [1], "complete": "submitted"},
    {"code": "SHIP", "doctype": "Delivery Note", "link": "child:Delivery Note Item.against_sales_order", "date": "posting_date", "status": [1], "complete": "submitted"},
    {"code": "COMM_INVOICE", "doctype": "Sales Invoice", "link": "child:Sales Invoice Item.sales_order", "date": "posting_date", "status": [1], "complete": "submitted"},
]
#: every other milestone is manual by design and says so on its row: "recorded by a person" (section 8.1)
MANUAL = "Recorded by a person"
#: the winner rule (section 8.2): the earliest VALID document wins; a later one that differs by more than this many working days is a conflict
CONFLICT_TOLERANCE_WD = 2


def rule_for(code: str) -> list[dict]:
    return [r for r in RULES if r["code"] == code]


def doctypes() -> list[str]:
    return sorted({r["doctype"] for r in RULES})


def contract(be) -> dict:
    """The contract test against an ERP (TNA plan 13.3): every doctype the rules name exists and every field they read is on it.

    ``be`` is a backend with ``meta(doctype)``. Returns ``{missing_doctypes, missing_fields, ok}``; a missing doctype is a configuration
    error, never a silent skip (section 8.2).
    """
    missing_dt: list[str] = []
    missing_f: list[tuple] = []
    for dt in doctypes():
        try:
            fields = {f["fieldname"] for f in (be.meta(dt) or {}).get("fields", [])}
        except Exception:                                    # noqa: BLE001
            missing_dt.append(dt)
            continue
        if not fields:
            missing_dt.append(dt)
            continue
        for r in RULES:
            if r["doctype"] != dt:
                continue
            for f in (r["date"], r["link"] if "." not in r["link"] and ":" not in r["link"] and r["link"] != "name" else None):
                if f and f not in fields and f not in ("creation", "modified", "name"):
                    missing_f.append((dt, f))
    return {"missing_doctypes": missing_dt, "missing_fields": sorted(set(missing_f)), "ok": not missing_dt and not missing_f}


def health(be) -> dict:
    """Evidence sources at a glance: per document type whether it exists and how many documents it has (section 8.2 health check)."""
    out = []
    for dt in doctypes():
        try:
            n = be.count(dt, [["docstatus", "!=", 2]])
            out.append({"doctype": dt, "exists": True, "rows": n, "milestones": sorted({r["code"] for r in RULES if r["doctype"] == dt})})
        except Exception as e:                               # noqa: BLE001
            out.append({"doctype": dt, "exists": False, "rows": 0, "error": str(e)[:120], "milestones": sorted({r["code"] for r in RULES if r["doctype"] == dt})})
    return {"sources": out, "missing": [s["doctype"] for s in out if not s["exists"]], "empty": [s["doctype"] for s in out if s["exists"] and not s["rows"]]}
