"""Context-driven email generation for the Cortex Control Tower.

Pipeline (see ``EMAIL_AUTOMATION_PLAN.md``)::

    build_fact_sheet() -> detect_intent() -> compose() -> validate_grounding()

Design rules
------------
* **No email body is hard-coded per action slug.** The communication *intent* is
  derived from the live context; the structure comes from an intent policy; every
  value in the email comes from the fact sheet built off the live ERP records.
* Nothing here sends mail. Nothing here writes to the ERP.
* No internal product branding ("KOGO", "Control Tower") appears inside an email.
* ``validate_grounding()`` re-reads the finished draft and rejects any number,
  date or reference that cannot be traced back to the fact sheet.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

import config

POLICY_VERSION = "comms-policy/2026-10-01.1"

# ── Intents ──────────────────────────────────────────────────────────────────
INTENT_DELIVERY = "delivery_plan"
INTENT_STATEMENT = "statement_of_account"
INTENT_RFQ = "request_for_quotation"
INTENT_DATA = "data_request"
INTENT_APPROVAL = "approval_request"
INTENT_GENERIC = "operations_followup"

AUDIENCE_BY_INTENT = {
    INTENT_DELIVERY: "buyer",
    INTENT_STATEMENT: "buyer",
    INTENT_RFQ: "supplier",
    INTENT_DATA: "internal",
    INTENT_APPROVAL: "buyer",
    INTENT_GENERIC: None,          # resolved from the context
}

ROLE_BY_INTENT = {
    INTENT_DELIVERY: "Customer Service",
    INTENT_STATEMENT: "Accounts Receivable",
    INTENT_RFQ: "Procurement",
    INTENT_DATA: "Data Governance",
    INTENT_APPROVAL: "Commercial",
    INTENT_GENERIC: "Operations",
}

# Sentences/words that must never appear in an outbound email.
FORBIDDEN_TEXT = ("KOGO", "kogo", "Control Tower", "control tower")

DEFAULT_COMPANY = config.DEFAULT_COMPANY
MAX_ROWS_INLINE = 10

# Words allowed in a draft even though they are not in the fact sheet.
_TOKEN_WHITELIST = {
    "USD", "EUR", "HKD", "VND", "GBP", "CNY", "pcs", "PC", "XS", "S", "M", "L",
    "XL", "XXL", "PO", "SO", "BOM", "RFQ", "TBC", "AWB", "B/L",
}


# ── Small formatting helpers ─────────────────────────────────────────────────
def _num(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _money(value, currency: str = "") -> str:
    return f"{currency or config.DEFAULT_CURRENCY} {_num(value):,.2f}"


def _int(value) -> str:
    return f"{int(_num(value)):,}"


def _signed_int(value) -> str:
    n = int(_num(value))
    return f"{n:+,}"


def _bullets(rows: list[str]) -> str:
    if not rows:
        return "  \u2022 (no matching records)"
    return "\n".join(f"  \u2022 {r}" for r in rows)


def _now_iso() -> str:
    return date.today().isoformat()


def _style_of_item(item_code: str) -> str:
    """`C2027-S84-304-MICTP-S` -> `C2027-S84-304` (drops colourway/size suffix)."""
    parts = (item_code or "").strip().split("-")
    if len(parts) >= 5:
        return "-".join(parts[:3])
    return item_code or ""


# ── Intent detection (from context, not from an action slug) ─────────────────
def detect_intent(f: dict, risk: dict, action: str) -> str:
    """Choose the communication intent.

    Primary signal is the *action* wording; the risk type is only a fallback.
    Internal risk *titles* are deliberately ignored — they are internal language
    and must never influence a customer-facing message.
    """
    text = (action or "").lower()
    rt = (risk.get("risk_type") or "").lower()

    if any(k in text for k in ("statement", "receivable", "payment reminder", "collection")):
        return INTENT_STATEMENT
    if any(k in text for k in ("quotation", "request for quote", "rfq")):
        return INTENT_RFQ
    if any(k in text for k in ("approve", "approval", "tolerance", "accept")):
        return INTENT_APPROVAL
    if any(k in text for k in ("evidence", "data request", "test result", "test row",
                               "bom consumption", "consumption", "per-size bom")):
        return INTENT_DATA
    if any(k in text for k in ("delivery plan", "delivery schedule", "delivery notice",
                               "shipment schedule", "shipping plan")):
        return INTENT_DELIVERY

    # fallback: the risk type
    if rt == "invoicing_risk":
        return INTENT_STATEMENT
    if rt == "fabric_shortage":
        return INTENT_RFQ
    if rt in ("data_quality", "quality_risk"):
        return INTENT_DATA
    if rt == "shipment_risk":
        return INTENT_DELIVERY
    if rt == "production_delay" and "bom" in text:
        return INTENT_DATA
    return INTENT_GENERIC


def _conflict(code: str, message: str, detail=None) -> dict:
    return {"code": code, "message": message, "detail": detail or []}


# ── Fact sheet ───────────────────────────────────────────────────────────────
def resolve_audience(f: dict, action: str, intent: str):
    """Return ``(audience, conflict)``.

    Never silently picks a party when more than one exists: an ambiguous party is
    a *conflict* that blocks generation rather than a guess.
    """
    buyers = sorted(
        {s.get("customer") for s in (f.get("sos") or []) if s.get("customer")}
        | {i.get("customer") for i in (f.get("invoices") or []) if i.get("customer")}
    )
    suppliers = sorted({p.get("supplier") for p in (f.get("purchase_orders") or []) if p.get("supplier")})
    text = (action or "").lower()
    kind = AUDIENCE_BY_INTENT.get(intent) or "internal"

    if kind == "buyer":
        if not buyers:
            return None, _conflict("no_buyer", "No customer is present on the live orders.")
        if len(buyers) == 1:
            return {"kind": "buyer", "display": buyers[0], "candidates": buyers}, None
        named = [b for b in buyers if b.lower() in text]
        if len(named) == 1:
            return {"kind": "buyer", "display": named[0], "candidates": buyers}, None
        return None, _conflict(
            "ambiguous_buyer",
            f"{len(buyers)} customers are in scope and the action does not name one.",
            buyers,
        )

    if kind == "supplier":
        if not suppliers:
            return None, _conflict("no_supplier", "No supplier is present on the live purchase orders.")
        if len(suppliers) == 1:
            # Single-sourced from purchase orders; a trim RFQ has no supplier mapping yet.
            return {"kind": "supplier", "display": suppliers[0],
                    "candidates": suppliers, "unconfirmed": True}, None
        named = [s for s in suppliers if s.lower() in text]
        if len(named) == 1:
            return {"kind": "supplier", "display": named[0], "candidates": suppliers}, None
        return None, _conflict(
            "ambiguous_supplier",
            f"{len(suppliers)} suppliers are in scope and the action does not name one.",
            suppliers,
        )

    return {"kind": "internal", "display": "Cortex", "candidates": []}, None


def build_fact_sheet(f: dict, risk: dict, action: str, intent: str, audience: dict) -> dict:
    """Turn the live ERP facts into a typed, provenance-tagged fact sheet."""
    company = (f.get("companies")[0] if f.get("companies") else None) or DEFAULT_COMPANY
    role = ROLE_BY_INTENT.get(intent, "Operations")

    orders = []
    for so in f.get("sos") or []:
        line_qty = sum(_num(i.get("qty")) for i in (so.get("items") or []))
        orders.append({
            "so": so.get("name"),
            "po": so.get("po_no"),
            "qty": int(line_qty),
            "delivery_date": so.get("delivery_date"),
            "value": _num(so.get("grand_total")),
            "currency": so.get("currency") or "USD",
        })

    # Receivables statement = OPEN invoices only, measured on outstanding_amount,
    # never on grand_total (which would overstate a partly-paid account).
    invoices = []
    for inv in f.get("invoices") or []:
        amount = _num(inv.get("grand_total"))
        outstanding = inv.get("outstanding_amount")
        if outstanding in (None, ""):
            outstanding = amount
        outstanding = _num(outstanding)
        if outstanding <= 0:
            continue
        status = (inv.get("status") or "").strip()
        invoices.append({
            "name": inv.get("name"),
            "posting_date": inv.get("posting_date"),
            "amount": amount,
            "outstanding": outstanding,
            "currency": inv.get("currency") or "USD",
            "status": status,
            "overdue": status.lower() == "overdue",
        })

    requisitions = [
        {
            "name": m.get("name"),
            "ref": m.get("custom_trim_requisition"),
            "required_by": m.get("schedule_date"),
        }
        for m in (f.get("draft_mrs") or f.get("mrs") or [])
    ]

    shipments = [
        {
            "so": s.get("sales_order") or s.get("source_invoice_no") or s.get("name"),
            "item": s.get("item"),
            "ordered": _num(s.get("sales_order_qty")),
            "shipped": _num(s.get("shipped_qty")),
            "variance": _num(s.get("shipment_variance_qty")),
        }
        for s in (f.get("shipments") or [])
    ]

    quality_packs = [
        {
            "name": q.get("name"),
            "fabric": q.get("source_fabric_code"),
            "result": q.get("inspection_result"),
            "document": q.get("source_document"),
        }
        for q in (f.get("not_extracted") or f.get("quality") or [])
    ]

    gaps = [
        {
            "name": g.get("name"),
            "key": g.get("gap_key") or g.get("name"),
            "area": g.get("process_area"),
            "detail": g.get("missing_information"),
        }
        for g in (f.get("open_gaps") or f.get("gaps") or [])
    ]

    styles = sorted({
        _style_of_item(b.get("item")) for b in (f.get("boms") or []) if b.get("item")
    })

    window = {
        "from": f.get("earliest_delivery"),
        "to": f.get("latest_delivery"),
    }
    window_text = (
        f"{window['from']} to {window['to']}" if window["from"] else "to be confirmed"
    )

    number = len(orders)
    outstanding_total = round(sum(i["outstanding"] for i in invoices), 2)
    currencies = sorted({i["currency"] for i in invoices})
    currency = currencies[0] if len(currencies) == 1 else None
    overdue_count = sum(1 for i in invoices if i["overdue"])
    return {
        "generated_at": _now_iso(),
        "as_at": _now_iso(),
        "intent": intent,
        "policy_version": POLICY_VERSION,
        "audience": audience,
        "currency": currency,
        "sender": {"company": company, "role": role},
        "party": {
            "kind": audience.get("kind"),
            "status": "unconfirmed" if audience.get("unconfirmed") else "confirmed",
            "candidates": audience.get("candidates", []),
        },
        "risk": {
            "title": risk.get("title"),
            "type": risk.get("risk_type"),
            "severity": risk.get("severity"),
        },
        "window": window,
        "window_text": window_text,
        "orders": orders,
        "invoices": invoices,
        "requisitions": requisitions,
        "shipments": shipments,
        "quality_packs": quality_packs,
        "gaps": gaps,
        "styles": styles,
        "totals": {
            "orders": number,
            "order_value": round(sum(o["value"] for o in orders), 2),
            "invoices": len(invoices),
            "outstanding": outstanding_total,
            "overdue": overdue_count,
            "currencies": len(currencies),
            "requisitions": len(requisitions),
            "shipments": len(shipments),
            "variance_count": len(f.get("nonzero_var") or []),
            "max_variance": max([abs(_num(v)) for v in (f.get("variances") or [])] or [0]),
            "quality_packs": len(quality_packs),
            "gaps": len(gaps),
            "bom_total": int(_num(f.get("bom_total"))),
            "variants_total": int(_num(f.get("variants_total"))),
            "coverage_pct": int(_num(f.get("coverage_pct"))),
            "bom_missing": max(
                int(_num(f.get("variants_total"))) - int(_num(f.get("bom_total"))), 0
            ),
            # derived, provenance-tagged overflow counts rendered as "and N more"
            "orders_overflow": max(len(orders) - MAX_ROWS_INLINE, 0),
            "invoices_overflow": max(len(invoices) - 12, 0),
            "requisitions_overflow": max(len(requisitions) - MAX_ROWS_INLINE, 0),
            "shipments_overflow": max(len(shipments) - MAX_ROWS_INLINE, 0),
            "quality_overflow": max(len(quality_packs) - MAX_ROWS_INLINE, 0),
            "gaps_overflow": max(len(gaps) - 12, 0),
        },
        "provenance": sorted({
            "Sales Order", "Sales Invoice" if invoices else "",
            "Material Request" if requisitions else "",
            "Garment Shipment Evidence" if shipments else "",
            "Fabric Quality Evidence" if quality_packs else "",
            "Migration Data Gap" if gaps else "",
        } - {""}),
    }


# ── Composition (every value comes from the fact sheet) ──────────────────────
def _greeting(sheet: dict) -> str:
    if sheet["audience"]["kind"] == "internal":
        return "Dear Cortex team,"
    return f"Dear {sheet['audience']['display']} team,"


def _signature(sheet: dict) -> str:
    s = sheet["sender"]
    return f"Kind regards,\n{s['role']}\n{s['company']}"


def _compose_delivery(sheet: dict, action: str = "") -> dict:
    orders = sheet["orders"]
    rows = [
        f"{o['so']} \u2014 PO {o['po'] or '\u2014'} \u2014 {_int(o['qty'])} pcs \u2014 "
        f"delivery {o['delivery_date'] or 'TBC'} \u2014 {_money(o['value'], o['currency'])}"
        for o in orders[:MAX_ROWS_INLINE]
    ]
    extra = len(orders) - len(rows)
    if extra > 0:
        rows.append(f"and {extra} further order(s) within the same delivery window")
    subject = (
        f"Delivery plan for {sheet['totals']['orders']} open order"
        f"{'s' if sheet['totals']['orders'] != 1 else ''} \u2014 window {sheet['window_text']}"
    )
    body = (
        f"{_greeting(sheet)}\n\n"
        f"Thank you for your continued business. Please see below our delivery plan for the "
        f"orders currently in production for you.\n\n"
        f"Orders in production: {sheet['totals']['orders']}\n"
        f"Total order value: {_money(sheet['totals']['order_value'])}\n"
        f"Delivery window: {sheet['window_text']}\n"
        f"Prepared on: {sheet['as_at']}\n\n"
        f"{_bullets(rows)}\n\n"
        f"We will confirm the final shipment dates and packing details for each order as it "
        f"approaches its delivery window, and will notify you promptly of any change. If any "
        f"order needs to be prioritised, please let us know and we will accommodate it wherever "
        f"the production schedule allows.\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": subject, "body": body}


def _compose_statement(sheet: dict, action: str = "") -> dict:
    cur = sheet["currency"] or "USD"
    invoices = sorted(sheet["invoices"], key=lambda i: i.get("posting_date") or "")
    rows = []
    for i in invoices[:12]:
        line = (
            f"{i['name']} \u2014 posted {i['posting_date'] or '\u2014'} \u2014 "
            f"invoice {_money(i['amount'], i['currency'])} \u2014 "
            f"outstanding {_money(i['outstanding'], i['currency'])}"
        )
        if i["overdue"]:
            line += " \u2014 overdue"
        rows.append(line)
    extra = len(invoices) - len(rows)
    if extra > 0:
        rows.append(f"and {extra} further invoice(s)")
    total = sheet["totals"]["outstanding"]
    overdue = sheet["totals"]["overdue"]
    overdue_line = ""
    if overdue:
        overdue_line = (
            f"Of these, {overdue} invoice{'s' if overdue != 1 else ''} "
            f"{'are' if overdue != 1 else 'is'} shown as overdue in our records. "
        )
    subject = f"Statement of account as at {sheet['as_at']} \u2014 {_money(total, cur)} outstanding"
    body = (
        f"{_greeting(sheet)}\n\n"
        f"Please find below a statement of your account as at {sheet['as_at']}, covering the "
        f"invoices currently outstanding in our records.\n\n"
        f"Outstanding invoices: {sheet['totals']['invoices']}\n"
        f"Total outstanding: {_money(total, cur)}\n\n"
        f"{_bullets(rows)}\n\n"
        f"{overdue_line}We would be grateful if you could arrange settlement, or share the "
        f"payment references if remittance has already been made, so that we can update our "
        f"records accordingly. Should you require supporting documents or a detailed "
        f"reconciliation, please let us know.\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": subject, "body": body}


def _compose_rfq(sheet: dict, action: str = "") -> dict:
    reqs = sheet["requisitions"]
    rows = [
        f"{r['name']} \u2014 {r['ref'] or 'trim requisition'} \u2014 "
        f"required by {r['required_by'] or 'TBC'}"
        for r in reqs[:MAX_ROWS_INLINE]
    ]
    extra = len(reqs) - len(rows)
    if extra > 0:
        rows.append(f"and {extra} further requisition(s)")
    subject = (
        f"Request for quotation \u2014 {sheet['totals']['requisitions']} trim requisition"
        f"{'s' if sheet['totals']['requisitions'] != 1 else ''}"
    )
    body = (
        f"{_greeting(sheet)}\n\n"
        f"We would like to request your quotation for the trim items required against the "
        f"requisitions listed below, which support our current production orders.\n\n"
        f"Requisitions for quotation: {sheet['totals']['requisitions']}\n"
        f"Required ahead of: {sheet['window_text']}\n\n"
        f"{_bullets(rows)}\n\n"
        f"Please quote your best unit prices, minimum order quantities and lead times, and "
        f"confirm the earliest delivery date you can commit to for each item. Kindly send your "
        f"quotation at your earliest convenience so that we can secure the material ahead of the "
        f"delivery window.\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": subject, "body": body}


def _compose_data(sheet: dict, action: str = "") -> dict:
    """Data request. Focus is chosen from the action context; values come from the sheet."""
    t = sheet["totals"]
    text = (action or "").lower()
    if "bom" in text or "consumption" in text:
        focus = "bom_consumption"
    elif "test" in text or "quality" in text or "inspection" in text:
        focus = "test_results"
    elif "gap" in text or "evidence" in text:
        focus = "evidence"
    elif sheet["quality_packs"]:
        focus = "test_results"
    elif t["variants_total"]:
        focus = "bom_consumption"
    else:
        focus = "evidence"

    if focus == "test_results":
        rows = [
            f"{q['name']} \u2014 fabric {q['fabric'] or '\u2014'} \u2014 "
            f"{q['result'] or 'result not stated'}"
            for q in sheet["quality_packs"][:MAX_ROWS_INLINE]
        ]
        extra = len(sheet["quality_packs"]) - len(rows)
        if extra > 0:
            rows.append(f"and {extra} further pack(s)")
        focus = "test_results"
        subject = (
            f"Data request \u2014 test results for {t['quality_packs']} fabric quality pack"
            f"{'s' if t['quality_packs'] != 1 else ''}"
        )
        intro = (
            "As part of closing the open items on our fabric inspection records, we require the "
            "machine-readable test results for the packs whose results could not be conclusively "
            "extracted."
        )
        metric = f"Records awaiting test data: {t['quality_packs']}"
        ask = (
            "Please provide the results in spreadsheet form \u2014 ideally one row per test, "
            "showing the test method, specification, actual value and pass/fail outcome. This "
            "will allow us to finalise the quality records and release the affected styles for "
            "production and shipment."
        )
    elif focus == "bom_consumption":
        missing = max(t["variants_total"] - t["bom_total"], 0)
        rows = [f"Style {s}" for s in sheet["styles"][:MAX_ROWS_INLINE]]
        focus = "bom_consumption"
        subject = (
            f"Data request \u2014 per-size BOM consumption ({missing} variants outstanding)"
        )
        intro = (
            "To complete the manufacturing data for our current orders, we require the per-size "
            "BOM (bill of materials) consumption for the finished-garment variants where only the "
            "Size S BOM is currently available."
        )
        metric = (
            f"Variants with a BOM: {t['bom_total']} of {t['variants_total']} "
            f"({t['coverage_pct']}%) — per-size BOMs still required: {missing}"
        )
        ask = (
            "For each style, please provide the graded fabric and trim consumption per size "
            "(XS, S, M, L, XL as applicable) together with the unit of measure, so that we can "
            "raise Work Orders and issue material for every size rather than only Size S."
        )
    else:
        rows = [
            f"{g['key']} \u2014 {g['area'] or 'General'}"
            for g in sheet["gaps"][:12]
        ]
        extra = len(sheet["gaps"]) - len(rows)
        if extra > 0:
            rows.append(f"and {extra} further item(s)")
        focus = "evidence"
        subject = (
            f"Data request \u2014 evidence for {t['gaps']} open migration item"
            f"{'s' if t['gaps'] != 1 else ''}"
        )
        intro = (
            "During our review of the migrated data we recorded a number of items for which the "
            "supporting evidence is still outstanding. We would appreciate your help in closing "
            "the following open items."
        )
        metric = f"Open items: {t['gaps']}"
        ask = (
            "For each item, please share the source document or a system extract that evidences "
            "the value or position recorded. Where an item cannot be evidenced, please confirm so "
            "that we can record it as out of scope rather than leaving it open."
        )

    rows_block = f"{_bullets(rows)}\n\n" if rows else ""
    body = (
        f"{_greeting(sheet)}\n\n"
        f"{intro}\n\n"
        f"{metric}\n\n"
        f"{rows_block}"
        f"{ask}\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": subject, "body": body, "focus": focus}


def _compose_approval(sheet: dict, action: str = "") -> dict:
    t = sheet["totals"]
    shipments = sorted(sheet["shipments"], key=lambda s: -abs(s["variance"]))
    rows = [
        f"{s['so']} \u2014 {s['item'] or '\u2014'} \u2014 ordered {_int(s['ordered'])} pcs \u2014 "
        f"shipped {_int(s['shipped'])} pcs \u2014 variance {_signed_int(s['variance'])} pcs"
        for s in shipments[:MAX_ROWS_INLINE]
    ]
    extra = len(shipments) - len(rows)
    if extra > 0:
        rows.append(f"and {extra} further shipment(s)")
    subject = (
        f"Approval required \u2014 shipment quantity variance (up to {_int(t['max_variance'])} pcs)"
    )
    body = (
        f"{_greeting(sheet)}\n\n"
        f"The shipments listed below show a difference between the ordered quantity and the "
        f"quantity shipped. We would like your confirmation of the acceptable tolerance before we "
        f"finalise the invoices and customs documentation.\n\n"
        f"Shipments with a variance: {t['variance_count']} of {t['shipments']}\n"
        f"Largest difference: {_int(t['max_variance'])} pcs\n\n"
        f"{_bullets(rows)}\n\n"
        f"Please confirm whether the shipped quantities are accepted as final, or whether an "
        f"adjustment is required. Once approved, we will proceed to invoice and dispatch on the "
        f"recorded quantities.\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": subject, "body": body}


def _compose_generic(sheet: dict, action: str = "", fallback_note: str = "") -> dict:
    """Neutral, always-grounded closing email.

    Deliberately echoes no internal risk wording, so no unsourced number or
    reference can leak into a customer-facing message.
    """
    note = f"\n\n{fallback_note}" if fallback_note else ""
    body = (
        f"{_greeting(sheet)}\n\n"
        f"We are writing regarding an open item on our operations register that requires your "
        f"attention. Kindly review the matter and revert with your confirmation or the requested "
        f"information so that we can progress this without delay."
        f"{note}\n\n"
        f"{_signature(sheet)}"
    )
    return {"subject": "Operations follow-up", "body": body}


_COMPOSERS = {
    INTENT_DELIVERY: _compose_delivery,
    INTENT_STATEMENT: _compose_statement,
    INTENT_RFQ: _compose_rfq,
    INTENT_DATA: _compose_data,
    INTENT_APPROVAL: _compose_approval,
}


def compose(sheet: dict, action: str = "", safe_mode: bool = False) -> dict:
    if safe_mode:
        # Minimal, provably-grounded fallback: uses only counts from the sheet.
        return _compose_generic(
            sheet, action,
            fallback_note="Some details were withheld pending verification.",
        )
    composer = _COMPOSERS.get(sheet["intent"])
    if composer:
        return composer(sheet, action)
    return _compose_generic(sheet, action)


# ── Grounding validator ──────────────────────────────────────────────────────
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# a number not embedded inside a code such as S84 / C2027-S84-304 / MFG-WO-2026-00001
_NUM_RE = re.compile(r"(?<![A-Za-z0-9-])\d[\d,]*\.?\d*")
# a full reference token, e.g. SAL-ORD-2026-00001, ACC-SINV-2026-00001, MDG-0
_REF_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")


def _iter_values(obj: Any):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_values(v)
    elif obj is not None:
        yield obj


def _norm_number(raw: str) -> str:
    s = raw.replace(",", "").rstrip(".")
    try:
        return f"{float(s):.6f}".rstrip("0").rstrip(".")
    except Exception:
        return s


def _allowed(sheet: dict) -> dict:
    numbers, dates, refs, names = set(), set(), set(), set()
    for v in _iter_values(sheet):
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            numbers.add(_norm_number(str(v)))
        elif isinstance(v, str):
            if _DATE_RE.fullmatch(v):
                dates.add(v)
                continue
            if _REF_RE.fullmatch(v):
                refs.add(v)
            n = _norm_number(v)
            if n and n.replace("-", "").isdigit():
                numbers.add(n)
            names.add(v.strip())
    # derived counts that appear in the sheet as lengths are already present;
    # add safe singular/plural arithmetic helpers
    numbers |= {"0"}
    return {"numbers": numbers, "dates": dates, "refs": refs, "names": names}


def validate_grounding(draft: dict, sheet: dict) -> dict:
    """Return {ok, unsourced} — anything in the draft not traceable to the sheet."""
    allowed = _allowed(sheet)
    text = f"{draft.get('subject', '')}\n{draft.get('body', '')}"
    unsourced: list[str] = []

    for bad in FORBIDDEN_TEXT:
        if bad in text:
            unsourced.append(f"forbidden:{bad}")

    for d in _DATE_RE.findall(text):
        if d not in allowed["dates"]:
            unsourced.append(d)
    text_no_dates = _DATE_RE.sub(" ", text)

    for n in _NUM_RE.findall(text_no_dates):
        if _norm_number(n) not in allowed["numbers"]:
            unsourced.append(n)

    for ref in _REF_RE.findall(text):
        if ref not in allowed["refs"] and ref not in _TOKEN_WHITELIST:
            unsourced.append(ref)

    unsourced = sorted(set(unsourced))
    return {"ok": not unsourced, "unsourced": unsourced, "policy_version": POLICY_VERSION}


# ── Top-level entry point ────────────────────────────────────────────────────
def _blocked(intent: str, code: str, message: str, detail=None) -> dict:
    return {
        "intent": intent,
        "policy_version": POLICY_VERSION,
        "blocked": {"code": code, "message": message, "detail": detail or []},
        "email": None,
        "grounding": {"ok": False, "unsourced": [], "policy_version": POLICY_VERSION},
    }


def generate_email(f: dict, risk: dict, action: str, live: bool = True) -> dict:
    """Context -> guardrails -> fact sheet -> intent -> draft -> grounded validation.

    A *blocked* result (``{"blocked": {...}, "email": None}``) is returned when the
    message must not be produced at all: the ERP is unavailable, the target party
    is ambiguous, there is nothing to write about, or a total spans currencies.
    """
    intent = detect_intent(f, risk, action)

    # G1 — never generate from an empty/degraded snapshot.
    if not live:
        return _blocked(intent, "erp_unavailable",
                        "Generation blocked: live ERP data is unavailable.")

    # G2 — never guess the recipient.
    audience, conflict = resolve_audience(f, action, intent)
    if conflict:
        return _blocked(intent, conflict["code"], conflict["message"], conflict["detail"])

    sheet = build_fact_sheet(f, risk, action, intent, audience)
    t = sheet["totals"]

    # G3 — there must be something real to write about.
    if intent == INTENT_DELIVERY and t["orders"] == 0:
        return _blocked(intent, "no_records", "Generation blocked: no live orders for a delivery plan.")
    if intent == INTENT_STATEMENT and t["invoices"] == 0:
        return _blocked(intent, "no_records", "Generation blocked: no outstanding invoices.")
    if intent == INTENT_RFQ and t["requisitions"] == 0:
        return _blocked(intent, "no_records", "Generation blocked: no open requisitions.")
    if intent == INTENT_APPROVAL and t["shipments"] == 0:
        return _blocked(intent, "no_records", "Generation blocked: no shipment variance records.")
    if intent == INTENT_DATA and not (sheet["quality_packs"] or sheet["gaps"]):
        return _blocked(intent, "no_records", "Generation blocked: no open data items.")

    # G4 — never total across currencies.
    if intent == INTENT_STATEMENT and t["currencies"] > 1:
        return _blocked(intent, "mixed_currency",
                        "Generation blocked: invoices span more than one currency and cannot be totalled.",
                        sheet["currency"] if sheet["currency"] else [
                            i["currency"] for i in sheet["invoices"]
                        ])

    draft = compose(sheet, action)
    check = validate_grounding(draft, sheet)

    if not check["ok"]:
        # Never ship an ungrounded draft — retry with a minimal grounded email.
        draft = compose(sheet, action, safe_mode=True)
        check = validate_grounding(draft, sheet)
        check["fell_back"] = True
        if not check["ok"]:
            return _blocked(intent, "ungrounded",
                            "Generation blocked: the draft could not be traced to the live records.",
                            check["unsourced"])

    return {
        "intent": intent,
        "policy_version": POLICY_VERSION,
        "blocked": None,
        "email": {
            "to": sheet["audience"]["display"],
            "from": f"{sheet['sender']['role']} \u2014 {sheet['sender']['company']}",
            "subject": draft["subject"],
            "body": draft["body"],
        },
        "party_status": sheet["party"]["status"],
        "grounding": check,
        "fact_sheet": sheet,
    }
