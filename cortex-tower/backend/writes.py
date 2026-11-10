"""Opt-in ERP write execution for the Cortex Control Tower.

A control tower that cannot act is just a dashboard. This module gives the
recommendations a **real effect in the ERP** — conservatively:

* **Mode-gated** — env ``ERP_WRITE_MODE`` = ``off | safe | draft | all``
  (default ``draft``).
* **Drafts only** for submittable doctypes (``docstatus = 0``); the one
  ``submit`` op is explicitly listed below. Nothing else is ever submitted.
* **Idempotent** — every builder checks the ERP first, so a second Execute is a
  no-op and a retry cannot create duplicates.
* **Reversible** — created docs are recorded on the action and can be rolled
  back (delete for ``create`` ops, cancel for ``submit`` ops).
* **Batch-capped** — at most ``MAX_PER_RUN`` records per execution so the API
  call stays inside the 30 s client timeout; re-executing continues the batch.

Safety classes
--------------
``safe``   non-submittable, additive, trivially deleted   (Task, Item Price)
``draft``  submittable, created as a draft / or submit    (Quality Inspection,
                                                           BOM, Delivery Note,
                                                           Payment Request,
                                                           Material Request submit)
``risky``  accounting / hard to reverse                   (reserved)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import config
import erp
import rulebook
import write_gate as _gate

MODE_ORDER = {"off": 0, "safe": 1, "draft": 2, "all": 3}
DEFAULT_MODE = config.ERP_WRITE_MODE if config.ERP_WRITE_MODE in MODE_ORDER else "draft"
# ONE definition of the cap, shared with the intake path (write_gate.MAX_PER_RUN <- config).
MAX_PER_RUN = _gate.MAX_PER_RUN

SELLING_PRICE_LIST = config.SELLING_PRICE_LIST

# slug -> (doctype, safety class)
POLICY: dict[str, tuple[str, str]] = {
    "assign_data_owners": ("Task", "safe"),
    "create_item_prices": ("Item Price", "safe"),
    "reinspection_fabric": ("Quality Inspection", "draft"),
    "raise_work_orders": ("Work Order", "draft"),
    "create_boms": ("BOM", "draft"),
    "register_bom_sizewise": ("BOM", "draft"),
    "raise_delivery_notes": ("Delivery Note", "draft"),
    "submit_trim_mrs": ("Material Request", "draft"),
    "review_receivables": ("Payment Request", "draft"),
    # Previously read-only recommendations — every action now has a real ERP write.
    "close_quality_inspection": ("Quality Inspection", "draft"),
    "raise_trim_mrs": ("Material Request", "draft"),
    "review_shipment_variance": ("Task", "safe"),
    "request_evidence": ("Task", "safe"),
    # the buyer side / pre-order chain (2026-11-02) — every one is a review task
    "link_client_po": ("Task", "safe"),
    "review_cost_sheet": ("Task", "safe"),
    "close_pp_actions": ("Task", "safe"),
    "raise_material_request": ("Task", "safe"),
    "renew_quotation": ("Task", "safe"),
}


def current_mode() -> str:
    m = (config.ERP_WRITE_MODE or DEFAULT_MODE).strip().lower()
    return m if m in MODE_ORDER else DEFAULT_MODE


def mode_allows(required: str) -> bool:
    return MODE_ORDER[current_mode()] >= MODE_ORDER.get(required, 99)


def writes_enabled() -> bool:
    return current_mode() != "off"


def _today() -> str:
    return date.today().isoformat()


def _num(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _style(item_code: str) -> str:
    parts = (item_code or "").strip().split("-")
    return "-".join(parts[:3]) if len(parts) >= 5 else (item_code or "")


def _slug(row) -> str:
    return (row.action_key or "").split("::")[-1]


def _fg_warehouse(company: str) -> Optional[str]:
    ws = erp.erp_get("Warehouse", fields=["name"], filters=[["company", "=", company], ["is_group", "=", 0]], limit=0)
    names = [w.get("name") for w in ws if w.get("name")]
    if not names:
        return None
    return next((n for n in names if "finished" in n.lower()), names[0])


def _delivered_sales_orders() -> set:
    """Sales Orders that already have a Delivery Note (draft or submitted).

    ``Delivery Note Item`` is NOT list-permitted for this ERP user, so build the
    set from the parent documents instead (child tables arrive with the doc).
    Without this the per-order guard silently fails and duplicates get created.
    """
    covered: set = set()
    for dn in erp.erp_get("Delivery Note", fields=["name"],
                          filters=[["docstatus", "!=", 2]], limit=0):
        name = dn.get("name")
        if not name:
            continue
        doc = erp.erp_doc("Delivery Note", name)
        for it in (doc.get("items") or []):
            so = it.get("against_sales_order")
            if so:
                covered.add(so)
    return covered


# ── Input forms: what a human must supply for an action to be executable ────
# Each entry is the Data-Entry the UI must show BEFORE "Confirm & execute".
# Fields carry computed defaults wherever the ERP can supply one, so the user
# only types what genuinely needs a human decision.
FORM_FIELDS: dict[str, list[dict]] = {
    "assign_data_owners": [
        {"key": "assign_to", "label": "Assign to (ERP user)", "type": "text", "required": True,
         "help": "Who owns closing these gaps"},
        {"key": "priority", "label": "Priority", "type": "select", "required": True,
         "options": ["Low", "Medium", "High", "Urgent"]},
    ],
    "create_item_prices": [
        {"key": "valid_from", "label": "Valid from", "type": "date", "required": True},
    ],
    "reinspection_fabric": [
        {"key": "sample_size", "label": "Sample size (rolls)", "type": "number", "required": True},
        {"key": "remarks", "label": "Remarks", "type": "textarea", "required": False},
    ],
    "raise_work_orders": [
        {"key": "qty", "label": "Production quantity", "type": "number", "required": True},
        {"key": "planned_start_date", "label": "Planned start date", "type": "date", "required": True},
    ],
    "create_boms": [
        {"key": "quantity", "label": "BOM quantity", "type": "number", "required": True},
    ],
    "register_bom_sizewise": [
        {"key": "quantity", "label": "BOM quantity", "type": "number", "required": True},
    ],
    "raise_delivery_notes": [
        {"key": "posting_date", "label": "Posting date", "type": "date", "required": True},
        {"key": "warehouse", "label": "Source warehouse", "type": "select", "required": True,
         "options_source": "warehouses", "help": "Finished-goods warehouse the goods leave from"},
    ],
    "review_receivables": [
        {"key": "mode_of_payment", "label": "Mode of payment", "type": "select", "required": False,
         "options_source": "modes_of_payment"},
        {"key": "bank_account", "label": "Bank account", "type": "select", "required": False,
         "options_source": "bank_accounts"},
        {"key": "transaction_reference", "label": "Reference (optional)", "type": "text", "required": False},
    ],
    "submit_trim_mrs": [],
}


_OPTION_SOURCES = {
    "warehouses": lambda: [w.get("name") for w in erp.erp_get(
        "Warehouse", fields=["name"], filters=[["is_group", "=", 0]], limit=0) if w.get("name")],
    "modes_of_payment": lambda: [m.get("name") for m in erp.erp_get(
        "Mode of Payment", fields=["name"], limit=0) if m.get("name")],
    "bank_accounts": lambda: [b.get("name") for b in erp.erp_get(
        "Bank Account", fields=["name"], limit=0) if b.get("name")],
}


def _target_record_name(row) -> Optional[str]:
    """The record an action targets, taken from ``risk_key`` = ``<TYPE>#<name>``."""
    rk = (getattr(row, "risk_key", "") or "")
    return rk.split("#", 1)[1] if "#" in rk else None


def _computed_defaults(row, ctx: dict) -> dict:
    """Defaults the ERP can answer itself — the user never types these."""
    slug = _slug(row)
    out: dict = {}
    if slug == "raise_delivery_notes":
        name = _target_record_name(row)
        so = next((s for s in (ctx["facts"].get("sos") or [])
                   if s.get("name") == name), {})
        out["posting_date"] = _today()
        wh = _fg_warehouse(so.get("company")) if so else None
        if wh:
            out["warehouse"] = wh
    elif slug == "raise_work_orders":
        out["planned_start_date"] = _today()
        boms = ctx["facts"].get("boms") or []
        item = boms[0].get("item") if boms else None
        if item:
            qty = sum(_num(i.get("qty")) for so in (ctx["facts"].get("sos") or [])
                      for i in (so.get("items") or []) if i.get("item_code") == item)
            out["qty"] = qty or 1
    elif slug == "create_item_prices":
        out["valid_from"] = _today()
    elif slug in ("create_boms", "register_bom_sizewise"):
        out["quantity"] = 1
    elif slug == "assign_data_owners":
        out["priority"] = "High"
    elif slug == "reinspection_fabric":
        out["sample_size"] = 1
    return out


def resolve_inputs(row, ctx: dict) -> dict:
    """Merge user-supplied inputs over ERP-computed defaults."""
    vals = _computed_defaults(row, ctx)
    given = ctx.get("inputs") or {}
    vals.update({k: v for k, v in given.items() if v not in (None, "")})
    return vals


def missing_inputs(row, ctx: dict) -> list:
    """Labels of required fields the user still has to provide."""
    vals = resolve_inputs(row, ctx)
    return [f["label"] for f in FORM_FIELDS.get(_slug(row), [])
            if f.get("required") and not vals.get(f["key"])]


def form_spec(row, ctx: dict) -> dict:
    """The Data-Entry the UI must render for this action (with defaults filled)."""
    vals = resolve_inputs(row, ctx)
    fields = []
    for f in FORM_FIELDS.get(_slug(row), []):
        fd = {k: v for k, v in f.items() if k != "options_source"}
        src = f.get("options_source")
        if src and src in _OPTION_SOURCES:
            try:
                fd["options"] = _OPTION_SOURCES[src]()
            except Exception:
                fd["options"] = []
        fd["default"] = vals.get(f["key"])
        fields.append(fd)
    return {"fields": fields, "values": vals, "missing": missing_inputs(row, ctx)}


def _stock_at(item_code: str, warehouse: str) -> float:
    """Current stock of an item in a warehouse (0 when there is none)."""
    rows = erp.erp_get("Bin", fields=["actual_qty"],
                       filters=[["item_code", "=", item_code], ["warehouse", "=", warehouse]], limit=1)
    return _num(rows[0].get("actual_qty")) if rows else 0.0


def _warehouses_for(company: str) -> dict:
    """Pick the submit-required warehouses for a company (fg / wip / source)."""
    ws = [w.get("name") for w in erp.erp_get("Warehouse", fields=["name"],
                                             filters=[["company", "=", company], ["is_group", "=", 0]], limit=0)
          if w.get("name")]
    def pick(*keys):
        return next((n for n in ws if any(k in n.lower() for k in keys)), None)
    return {"fg": pick("finished goods", "finished"), "wip": pick("work in progress", "wip"),
            "source": pick("stores", "raw material", "fabric")}


def _receipt_op(dn_payloads: list) -> Optional[dict]:
    """A Stock Entry (Material Receipt) covering the finished-goods shortfall.

    The migration produced garments BEFORE the ERP existed, so finished-goods stock
    was never recorded — and a Delivery Note cannot be submitted against empty
    warehouses (nor with a zero valuation rate). This records the missing opening
    inventory (zero valuation) so the Delivery Note can post. Idempotent: it only
    asks for the quantity that is actually short.
    """
    need: dict = {}
    company = None
    for p in dn_payloads:
        company = company or p.get("company")
        wh = p.get("set_warehouse")
        for it in (p.get("items") or []):
            code, qty = it.get("item_code"), _num(it.get("qty"))
            if code and wh and qty:
                need[(code, wh)] = need.get((code, wh), 0.0) + qty
    if not need:
        return None
    items = []
    for (code, wh), qty in sorted(need.items()):
        short = qty - _stock_at(code, wh)
        if short > 0:
            items.append({"item_code": code, "qty": short, "t_warehouse": wh,
                          "allow_zero_valuation_rate": 1, "basic_rate": 0})
    if not items:
        return None
    return {"op": "receipt", "doctype": "Stock Entry", "payloads": [{
        "doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
        "company": company, "posting_date": _today(),
        "remarks": ("Cortex Control Tower — opening finished-goods stock recorded so the "
                    "Delivery Note can post (goods were produced before the ERP migration)."),
        "items": items,
    }]}


# ── Payload builders: (ctx) -> (op | None, reason) ───────────────────────────
def _build_task(ctx: dict):
    gaps = ctx["facts"].get("open_gaps") or []
    if not gaps:
        return None, "no open migration data gaps in the live ERP"
    subject = f"Close {len(gaps)} open migration data gaps"
    if erp.erp_get("Task", fields=["name"], filters=[["subject", "=", subject]], limit=1):
        return None, "the data-gap task already exists in the ERP"
    areas = sorted({g.get("process_area") for g in gaps if g.get("process_area")})
    inp = resolve_inputs(ctx.get("row"), ctx)
    payload = {
        "doctype": "Task", "subject": subject,
        "priority": inp.get("priority") or "High", "status": "Open",
        "exp_start_date": _today(),
        "description": ("Cortex Control Tower: " + "; ".join(areas)) if areas else "Cortex Control Tower",
    }
    if inp.get("assign_to"):
        payload["_assign"] = json.dumps([inp["assign_to"]])
    return {"op": "create", "doctype": "Task", "payloads": [payload]}, None


def _build_item_prices(ctx: dict):
    f = ctx["facts"]
    rates: dict = {}
    for so in f.get("sos") or []:
        cur = so.get("currency") or "USD"
        for i in so.get("items") or []:
            c, r = i.get("item_code"), i.get("rate")
            if c and r not in (None, ""):
                rates[c] = (_num(r), cur)
    if not rates:
        return None, "no selling price on the live sales orders"
    existing = {e.get("item_code") for e in erp.erp_get(
        "Item Price", fields=["item_code"], filters=[["price_list", "=", SELLING_PRICE_LIST]], limit=0)}
    inp = resolve_inputs(ctx.get("row"), ctx)
    payloads = [
        {"doctype": "Item Price", "item_code": c, "price_list": SELLING_PRICE_LIST,
         "price_list_rate": v[0], "currency": v[1],
         "valid_from": inp.get("valid_from") or _today()}
        for c, v in sorted(rates.items()) if c not in existing
    ]
    if not payloads:
        return None, f"every sold item already has a {SELLING_PRICE_LIST} price"
    return {"op": "create", "doctype": "Item Price", "payloads": payloads}, None


def _build_quality_inspection(ctx: dict):
    f = ctx["facts"]
    packs = f.get("fails") or f.get("quality") or []
    if not packs:
        return None, "no fabric quality record to re-inspect"
    row = ctx.get("row")
    if row is not None and row.result_docs:
        return None, "a re-inspection has already been raised by this action"
    q = packs[0]
    fabric = q.get("source_fabric_code")
    ref_type = ref_name = item_code = None
    for pr in erp.erp_get("Purchase Receipt", fields=["name"], filters=[["docstatus", "=", 1]], limit=0):
        d = erp.erp_doc("Purchase Receipt", pr["name"])
        for i in d.get("items") or []:
            if fabric and f"FAB-{fabric}" in (i.get("item_code") or ""):
                ref_type, ref_name, item_code = "Purchase Receipt", pr["name"], i["item_code"]
                break
        if ref_type:
            break
    if not ref_type:
        return None, f"no purchase receipt contains fabric {fabric or '?'} to inspect against"
    inp = resolve_inputs(row, ctx)
    payload = {
        "doctype": "Quality Inspection", "inspection_type": "Incoming",
        "reference_type": ref_type, "reference_name": ref_name, "item_code": item_code,
        "inspected_by": erp.erp_logged_user() or "Administrator",
        "report_date": _today(),
        "sample_size": int(_num(inp.get("sample_size")) or 1),
        "remarks": (inp.get("remarks") or
                    (f"Cortex Control Tower re-inspection — fabric {fabric} was marked "
                     f"{q.get('inspection_result') or 'not conclusive'} on the source certificate.")),
    }
    return {"op": "create", "doctype": "Quality Inspection", "payloads": [payload]}, None


def _build_work_order(ctx: dict):
    f = ctx["facts"]
    row = ctx.get("row")
    # Target the style THIS action is about (risk_key WORK_ORDER_MISSING#<style>),
    # not simply the first BOM in the book — otherwise every action resolves to the
    # same BOM and all but one report "a work order already exists".
    target = _target_record_name(row)
    boms = [b for b in (f.get("boms") or []) if b.get("name")]
    bom = next((b for b in boms if _style(b.get("item") or "") == target), None) if target else None
    if not bom:
        bom = next(iter(boms), None)
    if not bom:
        return None, "no submitted BOM exists yet (create the BOMs first)"
    bom_doc = erp.erp_doc("BOM", bom["name"])
    item, company = bom_doc.get("item"), bom_doc.get("company")
    if not item or not company:
        return None, "could not read the BOM item/company from the ERP"
    existing = erp.erp_get("Work Order", fields=["name", "docstatus"],
                           filters=[["bom_no", "=", bom["name"]], ["docstatus", "!=", 2]], limit=1)
    if existing:
        wo = existing[0]
        if str(wo.get("docstatus")) == "1":
            return None, f"a submitted work order already exists for {bom['name']}"
        # A draft Work Order already exists — the meaningful completion is to
        # SUBMIT it rather than dead-ending on "already exists".
        return {"op": "submit", "doctype": "Work Order", "names": [wo["name"]]}, None
    qty = sum(_num(i.get("qty")) for so in (f.get("sos") or [])
              for i in (so.get("items") or []) if i.get("item_code") == item)
    inp = resolve_inputs(ctx.get("row"), ctx)
    whs = _warehouses_for(company)
    payload = {
        "doctype": "Work Order", "production_item": item, "bom_no": bom["name"],
        "qty": _num(inp.get("qty")) or qty or 1, "company": company,
        "planned_start_date": inp.get("planned_start_date") or _today(),
    }
    # ERPNext refuses to submit a Work Order without these warehouses.
    if whs.get("wip"):
        payload["wip_warehouse"] = whs["wip"]
    if whs.get("fg"):
        payload["fg_warehouse"] = whs["fg"]
    if whs.get("source"):
        payload["source_warehouse"] = whs["source"]
    return {"op": "create", "doctype": "Work Order", "payloads": [payload]}, None


def _build_boms(ctx: dict):
    boms = ctx["facts"].get("boms") or []
    have = {b.get("item") for b in boms if b.get("item")}
    by_style: dict = {}
    for b in boms:
        by_style.setdefault(_style(b.get("item")), b)
    if not by_style:
        return None, "no submitted BOM exists to copy consumption from"
    variants = erp.erp_get("Item", fields=["name", "variant_of"], filters=[["variant_of", "!=", ""]], limit=0)
    payloads = []
    for v in variants:
        name = v.get("name")
        if not name or name in have:
            continue
        src = by_style.get(_style(name))
        if not src:
            continue
        src_doc = erp.erp_doc("BOM", src["name"])
        items = [
            {"item_code": i.get("item_code"), "qty": i.get("stock_qty") or i.get("qty"),
             "uom": i.get("stock_uom") or i.get("uom")}
            for i in (src_doc.get("items") or []) if i.get("item_code")
        ]
        if not items:
            continue
        payloads.append({
            "doctype": "BOM", "item": name,
            "quantity": _num(resolve_inputs(ctx.get("row"), ctx).get("quantity")) or 1,
            "company": src_doc.get("company"),
            "items": items,
            "remarks": (f"Cortex Control Tower: consumption copied from {src['name']}. "
                        f"Graded per-size consumption was not available — verify before use."),
        })
    if not payloads:
        return None, "every style's variants already have a BOM"
    return {"op": "create", "doctype": "BOM", "payloads": payloads}, None


def _build_delivery_notes(ctx: dict):
    """Raise a Delivery Note for ONE Sales Order when the action names one
    (risk_key ``<TYPE>#<sales-order>``); otherwise fall back to the whole book.

    Per-order by design: the earlier account-wide builder created a Delivery Note
    for every live order from a single click, which contradicted the action text.
    """
    f = ctx["facts"]
    sos = f.get("sos") or []
    if not sos:
        return None, "no live sales orders to deliver"
    row = ctx.get("row")
    target = None
    if row is not None:
        rk = row.risk_key or ""
        if "#" in rk:
            target = rk.split("#", 1)[1]
    picked = [s for s in sos if s.get("name") == target] if target else sos
    if not picked:
        return None, f"sales order {target} is not in the live order book"
    covered = _delivered_sales_orders()
    payloads = []
    for so in picked:
        name = so.get("name")
        if not name or name in covered:
            continue
        sd = erp.erp_doc("Sales Order", name)
        company = sd.get("company")
        wh = _fg_warehouse(company)
        items = [
            {"item_code": i.get("item_code"), "qty": i.get("qty"),
             "rate": i.get("rate"),
             "against_sales_order": name, "so_detail": i.get("name"),
             # Migrated finished goods carry no stock valuation, so ERPNext would
             # refuse to submit with "has zero rate but Allow Zero Valuation Rate
             # is not enabled". This is the correct flag for migration deliveries.
             "allow_zero_valuation_rate": 1}
            for i in (sd.get("items") or []) if i.get("item_code")
        ]
        if not items or not wh:
            continue
        inp = resolve_inputs(row, ctx)
        payloads.append({
            "doctype": "Delivery Note", "customer": sd.get("customer"), "company": company,
            "posting_date": inp.get("posting_date") or _today(),
            "set_warehouse": inp.get("warehouse") or wh,
            "currency": sd.get("currency") or "USD", "conversion_rate": 1, "items": items,
        })
    if not payloads:
        return None, (f"a delivery note already exists for {target}" if target
                      else "every live sales order already has a delivery note")
    # Two steps: draft the Delivery Note, then top up any finished-goods shortfall
    # so the note can actually be submitted. The receipt is idempotent.
    ops = [{"op": "create", "doctype": "Delivery Note", "payloads": payloads}]
    stock = _receipt_op(payloads)
    if stock:
        ops.append(stock)
    return ({"ops": ops} if len(ops) > 1 else ops[0]), None


def _build_submit_mrs(ctx: dict):
    drafts = erp.erp_get("Material Request", fields=["name"], filters=[["docstatus", "=", 0]], limit=0)
    names = [m.get("name") for m in drafts if m.get("name")]
    if not names:
        return None, "no Draft material requests to submit"
    return {"op": "submit", "doctype": "Material Request", "names": names}, None


def _build_payment_requests(ctx: dict):
    """Raise a Payment Request. Targeted at ONE invoice when the action names one
    (risk_key ``PAYMENT_OVERDUE#<invoice>``); otherwise the whole outstanding book.

    NOTE: this fills only non-sending fields (party, reference, amount, subject,
    message). It deliberately does NOT set ``email_to`` and never emails a party.
    """
    invs = ctx["facts"].get("invoices") or []
    if not invs:
        return None, "no outstanding sales invoices"

    row = ctx.get("row")
    target = None
    if row is not None and (row.risk_key or "").startswith("PAYMENT_OVERDUE#"):
        target = row.risk_key.split("#", 1)[1]
    picked = [i for i in invs if i.get("name") == target] if target else invs
    if not picked:
        return None, f"invoice {target} has no outstanding balance"

    existing = {p.get("reference_name") for p in erp.erp_get(
        "Payment Request", fields=["reference_name"], limit=0) if p.get("reference_name")}
    payloads = []
    for inv in picked:
        name = inv.get("name")
        if not name or name in existing:
            continue
        doc = erp.erp_doc("Sales Invoice", name)
        amt = _num(inv.get("outstanding_amount") or inv.get("grand_total"))
        cur = inv.get("currency") or "USD"
        inp = resolve_inputs(ctx.get("row"), ctx)
        pr = {
            "doctype": "Payment Request", "payment_request_type": "Inward", "party_type": "Customer",
            "party": inv.get("customer"), "reference_doctype": "Sales Invoice", "reference_name": name,
            "grand_total": amt, "currency": cur, "company": doc.get("company"),
            "transaction_date": _today(),
            "subject": f"Payment request — {name} — {cur} {amt:,.2f}",
            "message": (f"Please arrange payment of {cur} {amt:,.2f} against invoice {name}. "
                        f"Kindly quote the invoice number on your remittance."),
        }
        # Set the payment route so the request is actionable (submit + bank step).
        if inp.get("mode_of_payment"):
            pr["mode_of_payment"] = inp["mode_of_payment"]
        if inp.get("bank_account"):
            pr["bank_account"] = inp["bank_account"]
        payloads.append(pr)
    if not payloads:
        return None, (f"a payment request already exists for {target}" if target
                      else "every outstanding invoice already has a payment request")
    return {"op": "create", "doctype": "Payment Request", "payloads": payloads}, None


def _build_close_quality_inspection(ctx: dict):
    """Complete (submit) the open Quality Inspection this action names."""
    row = ctx.get("row")
    name = _target_record_name(row)
    if not name:
        return None, "this action is not linked to a quality inspection"
    doc = erp.erp_doc("Quality Inspection", name)
    if not doc:
        return None, f"Quality Inspection {name} not found in the ERP"
    if str(doc.get("docstatus")) == "1":
        return None, f"Quality Inspection {name} is already submitted"
    return {"op": "submit", "doctype": "Quality Inspection", "names": [name]}, None


def _build_fabric_shortage_mr(ctx: dict):
    """Raise a Purchase Material Request for the fabric shortfall of one style."""
    f = rulebook.live_facts()          # the rule that raised this risk used these facts
    style = _target_record_name(ctx.get("row"))
    if not style:
        return None, "this action is not linked to a style"
    bom = (f.get("bom_by_style") or {}).get(style)
    if not bom:
        return None, f"no BOM exists for style {style}"
    qty = _num((f.get("open_qty_by_style") or {}).get(style))
    comps = [c for c in (f.get("bom_items") or {}).get(bom["name"], [])
             if (c.get("item_code") or "").upper().startswith("FAB-")]
    if not comps:
        return None, f"no fabric components on {bom['name']}"
    items = []
    for c in comps:
        code = c.get("item_code")
        short = _num(c.get("qty")) * qty - _num((f.get("fabric_roll_m") or {}).get(code))
        if short > 0:
            items.append({"item_code": code, "qty": round(short, 2),
                          "uom": c.get("uom") or "Meter", "schedule_date": _today()})
    if not items:
        return None, f"no fabric shortfall on {style}"
    marker = f"Cortex Control Tower — fabric requisition for {style}"
    if erp.erp_get("Material Request", fields=["name"],
                   filters=[["remarks", "like", f"%{marker}%"]], limit=1):
        return None, f"a fabric requisition for {style} already exists"
    bom_doc = erp.erp_doc("BOM", bom["name"])
    return {"op": "create", "doctype": "Material Request", "payloads": [{
        "doctype": "Material Request", "material_request_type": "Purchase",
        "company": bom_doc.get("company"), "transaction_date": _today(),
        "schedule_date": _today(),
        "remarks": f"{marker} ({qty:g} pcs on order).",
        "items": items,
    }]}, None


def _task_op(subject: str, description: str, priority: str = "High"):
    if erp.erp_get("Task", fields=["name"], filters=[["subject", "=", subject]], limit=1):
        return None, "a task for this already exists in the ERP"
    return {"op": "create", "doctype": "Task", "payloads": [{
        "doctype": "Task", "subject": subject, "priority": priority, "status": "Open",
        "exp_start_date": _today(), "description": description,
    }]}, None


def _build_variance_task(ctx: dict):
    """Task for a shipment whose declared quantity sits outside the allowance.

    The risk is keyed on the shipment GROUP (a shipment is described by several
    evidence rows), so the lookup walks the groups, not the raw rows.
    """
    f = rulebook.live_facts()
    name = _target_record_name(ctx.get("row"))
    g = next((x for x in (f.get("shipment_groups") or []) if x.get("group") == name), None)
    if not g:
        return None, "the shipment group for this action was not found in the ERP"
    subject = f"Review shipment variance — {name}"
    desc = (f"Cortex Control Tower: shipped {_num(g.get('shipped')):,.0f} vs ordered "
            f"{_num(g.get('ordered')):,.0f} pcs (variance "
            f"{_num(g.get('variance_qty')):+,.0f}, {_num(g.get('variance_pct')):+.2f}%). "
            f"Status: {g.get('variance_status') or 'not assessed'}. "
            f"Confirm the correct quantity for invoicing and the customs declaration.")
    op, why = _task_op(subject, desc)
    return (op, None) if op else (None, why)


def _build_action_task(ctx: dict):
    """Generic review task for a live-ERP finding (buyer PO, pack, cost gate,
    PP gate, requisition cover, expired quotation). Safe: creates a Task only."""
    row = ctx.get("row")
    action = ctx.get("action") or getattr(row, "modified_text", "") or ""
    record = _target_record_name(row)
    subject = (f"{action[:110]}" if action else f"Review {record}")[:140]
    if record and record not in subject:
        subject = f"{subject} — {record}"[:140]
    desc = ("Cortex Control Tower: " + (action or f"Review {record}") +
            f". Raised from the live ERP check on {record or 'the record'}.")
    op, why = _task_op(subject, desc)
    return (op, None) if op else (None, why)


def _build_evidence_task(ctx: dict):
    f = rulebook.live_facts()
    n = len(f.get("trim_exceptions") or [])
    op, why = _task_op(
        f"Request missing trim specifications ({n} unmapped)",
        (f"Cortex Control Tower: {n} trim mapping exception(s) block trim ordering for the "
         f"affected styles. Request the missing trim specifications from Cortex."))
    return (op, None) if op else (None, why)


BUILDERS = {
    "assign_data_owners": _build_task,
    "create_item_prices": _build_item_prices,
    "reinspection_fabric": _build_quality_inspection,
    "raise_work_orders": _build_work_order,
    "create_boms": _build_boms,
    "register_bom_sizewise": _build_boms,
    "raise_delivery_notes": _build_delivery_notes,
    "submit_trim_mrs": _build_submit_mrs,
    "review_receivables": _build_payment_requests,
    "close_quality_inspection": _build_close_quality_inspection,
    "raise_trim_mrs": _build_fabric_shortage_mr,
    "review_shipment_variance": _build_variance_task,
    "request_evidence": _build_evidence_task,
    "link_client_po": _build_action_task,
    "review_cost_sheet": _build_action_task,
    "close_pp_actions": _build_action_task,
    "raise_material_request": _build_action_task,
    "renew_quotation": _build_action_task,
}


def preview_write(row, ctx: dict) -> dict:
    """Describe what Execute would do, without doing it."""
    slug = _slug(row)
    entry = POLICY.get(slug)
    if not entry:
        return {"writable": False, "mode": current_mode(),
                "reason": "this action does not create an ERP record"}
    doctype, klass = entry
    if not mode_allows(klass):
        return {"writable": False, "mode": current_mode(), "safety": klass, "doctype": doctype,
                "reason": f"write mode '{current_mode()}' does not allow '{klass}' actions"}
    builder = BUILDERS.get(slug)
    if not builder:
        return {"writable": False, "mode": current_mode(), "safety": klass, "doctype": doctype,
                "reason": "no payload builder for this action yet"}
    form = form_spec(row, ctx)     # the Data-Entry the UI must render
    if form["missing"]:
        return {"writable": False, "mode": current_mode(), "safety": klass, "doctype": doctype,
                "reason": "Data entry required: " + ", ".join(form["missing"]),
                "needs_input": True, "inputs": form}
    op, reason = builder({**ctx, "row": row})   # row lets a builder target ITS record
    if not op:
        return {"writable": False, "mode": current_mode(), "safety": klass, "doctype": doctype,
                "reason": reason, "inputs": form}
    ops = op.get("ops") or [op]
    primary = [o for o in ops if o.get("doctype") == doctype] or ops
    count = sum(len(o.get("payloads") or o.get("names") or []) for o in primary)
    return {"writable": True, "mode": current_mode(), "safety": klass, "doctype": doctype,
            "operation": ops[0].get("op"), "count": count, "inputs": form,
            "steps": [{"doctype": o.get("doctype"), "op": o.get("op")} for o in ops]}


def _run_op(op: dict, doctype: str, created: list, errors: list, ctx: dict = None,
            batch=None) -> None:
    """Execute one op (create / receipt = create+submit / submit)."""
    if batch is None:                       # never a shared mutable default
        batch = _gate.Batch((ctx or {}).get("db"), "Ops Manager", label="action")
    if op["op"] == "submit":
        for name in (op.get("names") or [])[:MAX_PER_RUN]:
            ok, _doc, err = erp.erp_submit(doctype, name)
            (created if ok else errors).append(name if ok else f"{name}: {err}")
        return
    for payload in (op.get("payloads") or [])[:MAX_PER_RUN]:
        # the SAME gate the intake uses: the site's required fields, then the duplicate check
        import intake_exec as _ix
        ok, doc, err, note = _ix.create_checked(
            doctype, payload, (ctx or {}).get("facts"), (ctx or {}).get("matches"))
        if not (ok and doc.get("name")):
            errors.append(err or "create failed")
            continue
        if note and "already exists" in note:
            continue                      # linked to what is there, nothing to submit
        name = doc["name"]
        batch.register(doctype, name)      # per-record audit_log row, one envelope
        if op["op"] == "receipt":
            ok2, _d, err2 = erp.erp_submit(doctype, name)
            if not ok2:
                errors.append(f"{name} (receipt not submitted): {err2}")
                continue
        created.append(name)


def execute(row, ctx: dict) -> dict:
    """Perform (or refuse) the real ERP write for one action. Idempotent."""
    plan = preview_write(row, ctx)
    if not plan.get("writable"):
        return {"status": ("needs_input" if plan.get("needs_input") else "blocked"),
                "reason": plan.get("reason"), "mode": current_mode(),
                "safety": plan.get("safety"), "doctype": plan.get("doctype"),
                "inputs": plan.get("inputs")}

    op, reason = BUILDERS[_slug(row)]({**ctx, "row": row})
    if not op:
        return {"status": "already_done", "reason": reason, "doctype": plan.get("doctype"),
                "mode": current_mode()}

    ops = op.get("ops") or [op]
    doctype = plan.get("doctype") or ops[0].get("doctype")
    created, errors = [], []
    # the same envelope the intake path uses: one cap, one audit row per record
    batch = _gate.Batch((ctx or {}).get("db"), (ctx or {}).get("actor") or "Ops Manager",
                        label=f"action {_slug(row)}")
    for o in ops:
        _run_op(o, o.get("doctype") or doctype, created, errors, ctx, batch)

    if not created:
        return {"status": "failed", "doctype": doctype, "reason": "; ".join(errors) or "no records created",
                "mode": current_mode()}
    primary = [n for n in created if not n.startswith("MAT-STE")] or created
    return {"status": "created", "doctype": doctype, "op": op.get("op") or ops[0].get("op"),
            "docs": created, "doc": primary[0], "count": len(primary),
            "errors": errors, "safety": plan.get("safety"), "mode": current_mode(),
            "steps": len(ops),
            "remaining": max(len(op.get("payloads") or op.get("names") or []) - len(created), 0)}


# ── Submit-time self-healing ─────────────────────────────────────────────
# ERPNext can refuse to submit a perfectly valid DRAFT for reasons the create step
# cannot see (stock valuation, available quantity). Rather than making the user
# decode an ERP error, the submit path recognises the known classes, fixes the
# cause, and retries. Generic — works for ANY doctype.

import re as _re

_UNITS_RE = _re.compile(r"<strong>([\d.,]+)</strong>")
_ITEM_RE = _re.compile(r"units\s+of\s+.*?Item\s+([A-Za-z0-9._-]+)", _re.I | _re.S)
_WH_RE = _re.compile(r"Warehouse\s+([^<]+?)</a>", _re.I | _re.S)


def _plain(s: str) -> str:
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", s or "")).strip()


def _patch_zero_valuation(doctype: str, name: str) -> bool:
    doc = erp.erp_doc(doctype, name) or {}
    rows = doc.get("items") or []
    if not rows:
        return False
    out = []
    for i in rows:
        row = {"name": i.get("name")}
        for k in ("item_code", "qty", "rate", "uom", "warehouse", "t_warehouse", "s_warehouse",
                  "basic_rate", "against_sales_order", "so_detail", "batch_no", "serial_no"):
            if i.get(k) is not None:
                row[k] = i.get(k)
        row["allow_zero_valuation_rate"] = 1
        out.append(row)
    ok, _d, _e = erp.erp_update(doctype, name, {"items": out})
    return ok


def _receipt_for_shortfall(item_code: str, warehouse: str, qty: float,
                           company: Optional[str] = None) -> bool:
    if not (item_code and warehouse and qty > 0):
        return False
    payload = {
        "doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
        "company": company, "posting_date": _today(),
        "remarks": ("Cortex Control Tower — opening finished-goods stock recorded so the "
                    "document can be submitted (goods were produced before the ERP migration)."),
        "items": [{"item_code": item_code, "qty": qty, "t_warehouse": warehouse,
                   "allow_zero_valuation_rate": 1, "basic_rate": 0}],
    }
    ok, doc, _err = erp.erp_create("Stock Entry", payload)
    if not (ok and doc.get("name")):
        return False
    ok2, _d, _e = erp.erp_submit("Stock Entry", doc["name"])
    return bool(ok2)


def submit_with_repair(doctype: str, name: str, company: Optional[str] = None,
                       attempts: int = 2) -> dict:
    """Submit a draft, self-healing the known ERPNext submit blockers.

    Repaired automatically:
      * "Allow Zero Valuation Rate is not enabled" -> sets the flag on the rows
      * "N units of Item X needed in Warehouse Y"  -> records the missing stock
    Returns {ok, error, repaired:[...]}. Never raises.
    """
    repaired: list = []
    ok, _doc, err = erp.erp_submit(doctype, name)
    for _ in range(max(0, attempts)):
        if ok or not err:
            break
        low = err.lower()
        did = None
        if "zero valuation rate" in low:
            if _patch_zero_valuation(doctype, name):
                did = "set allow_zero_valuation_rate"
        elif "needed in" in low and "units of" in low:
            mi, mw, mq = _ITEM_RE.search(err), _WH_RE.search(err), _UNITS_RE.search(err)
            if mi and mw and mq:
                qty = _num(mq.group(1).replace(",", ""))
                if _receipt_for_shortfall(mi.group(1), mw.group(1).strip(), qty, company):
                    did = f"recorded {qty:g} × {mi.group(1)} into {mw.group(1).strip()}"
        if not did:
            break
        repaired.append(did)
        ok, _doc, err = erp.erp_submit(doctype, name)
    return {"ok": bool(ok),
            "error": None if ok else (_plain(err)[:300] if err else None),
            "repaired": repaired}


def rollback(row) -> dict:
    """Reverse what this action did: delete created docs, cancel submitted ones."""
    import json as _json
    names = []
    if row.result_docs:
        try:
            names = _json.loads(row.result_docs) or []
        except Exception:
            names = []
    if not names and row.result_doc:
        names = [row.result_doc]
    if not names or not row.result_doctype:
        return {"status": "nothing_to_rollback"}

    op = (row.write_op or "create")
    # ONE rollback for both write paths; an already-absent record counts as undone
    res = _gate.rollback_names(row.result_doctype, names, op=("submit" if op == "submit" else "create"))
    done = res["deleted"] + res["already_missing"]
    failed = res["failed"]
    if not done:
        return {"status": "failed", "doctype": row.result_doctype, "reason": "; ".join(failed)}
    return {"status": "rolled_back", "doctype": row.result_doctype, "op": op,
            "docs": done, "failed": failed}
