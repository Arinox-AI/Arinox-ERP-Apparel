"""Cortex Control Tower — grounded, ERP-aware copilot (Ask KOGO).

This is the retrieval layer behind ``ask_kogo``. It answers a free-text question
with the LLM's reasoning **over live ERP data**, using three steps:

1. **Retrieve** — ``build_evidence(question)`` reads the live ERP (through
   ``rulebook.live_facts()`` + ``forecast.build()``) and selects the datasets the
   question needs (orders, receivables, BOM/material, purchasing, quality,
   logistics, production, migration gaps) plus an always-on core snapshot.
   A keyword router picks the sections; when nothing matches, every section is
   included so the copilot can still answer. This is what makes arbitrary
   questions answerable — it is not a fixed digest.
2. **Reason** — the model is told to answer using ONLY that evidence pack, and
   may rank/filter/compare/compute from the rows it was given.
3. **Validate** — every meaningful number in the answer is checked against the
   evidence pack. Anything unsourced is returned in ``unsourced`` and clears the
   ``grounded`` flag. The reasoning channel (``<think>…</think>``) is stripped by
   ``ai_nextsteps._llm`` before it ever reaches here.

Nothing in this module writes to the ERP.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import erp
import rulebook
import forecast as _forecast
import ai_nextsteps as _ai


# ── small helpers ───────────────────────────────────────────────────────────
def _n(v, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _d(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _iso(v) -> str:
    return str(v) if v not in (None, "") else ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── section builders (each reads ONLY the live facts dict) ──────────────────
def _orders(facts, today) -> list:
    rows = []
    for s in facts.get("sos", []):
        items = s.get("items") or []
        qty = sum(_n(i.get("qty")) for i in items)
        ed = s.get("earliest_delivery")
        rows.append({
            "order": s.get("name"),
            "customer": s.get("customer_name") or s.get("customer"),
            "customer_po": s.get("po_no"),
            "status": s.get("status"),
            "currency": s.get("currency"),
            "value": round(_n(s.get("grand_total")), 2),
            "qty_pcs": round(qty, 1),
            "delivery_date": _iso(s.get("delivery_date")),
            "earliest_item_delivery": _iso(ed),
            "days_to_earliest_delivery": ((ed - today).days if ed else None),
            "delivered_pct": s.get("per_delivered"),
            "billed_pct": s.get("per_billed"),
            "item_codes": sorted({i.get("item_code") for i in items if i.get("item_code")}),
        })
    return rows


def _order_book(facts, orders) -> dict:
    open_rows = facts.get("open_sos", [])
    return {
        "count": len(orders),
        "open": len(open_rows),
        "total_value": round(sum(o["value"] for o in orders), 2),
        "total_qty_pcs": round(sum(o["qty_pcs"] for o in orders), 1),
        "styles_in_demand": len(facts.get("so_styles", {})),
        "currencies": sorted({o["currency"] for o in orders if o.get("currency")}),
    }


def _styles(facts) -> list:
    return [{"style": k, "qty_pcs": round(_n(v.get("qty")), 1), "orders": v.get("orders")}
            for k, v in (facts.get("so_styles") or {}).items()]


def _risks(facts) -> list:
    risks = rulebook.build_risks()
    return [{"key": r.get("key"), "severity": r.get("severity"), "title": r.get("title")}
            for r in risks[:60]]


def _forecast_section() -> dict:
    try:
        fc = _forecast.build()
    except Exception:
        return {}
    return {"cash": fc.get("cash"), "margin": fc.get("margin")[:10],
            "supplier": fc.get("supplier")[:10], "delivery": fc.get("delivery")[:10],
            "stockout": fc.get("stockout")[:10]}


def _finance(facts, today) -> dict:
    rows, overdue, out_by_cur = [], [], {}
    for i in facts.get("invoices", []):
        cur = i.get("currency") or ""
        out = _n(i.get("outstanding_amount"))
        if out > 0:
            out_by_cur[cur] = round(out_by_cur.get(cur, 0.0) + out, 2)
        due = _d(i.get("due_date"))
        days = (due - today).days if due else None
        row = {"invoice": i.get("name"), "customer": i.get("customer"),
               "grand_total": round(_n(i.get("grand_total")), 2), "outstanding": round(out, 2),
               "currency": cur, "due_date": _iso(i.get("due_date")),
               "days_overdue": (-days if (days is not None and days < 0) else 0),
               "status": i.get("status")}
        rows.append(row)
        if out > 0 and days is not None and days < 0:
            overdue.append(row)
    pes = facts.get("payment_entries", [])
    return {
        "receivables_outstanding_by_currency": out_by_cur,
        "overdue_invoices": sorted(overdue, key=lambda r: -r["outstanding"]),
        "all_invoices": sorted(rows, key=lambda r: -r["outstanding"]),
        "payment_entry_count": len(pes),
        "payment_entries": [{"payment": p.get("name"), "party": p.get("party"),
                             "paid_amount": round(_n(p.get("paid_amount")), 2),
                             "docstatus": p.get("docstatus")} for p in pes[:30]],
    }


def _materials(facts, today) -> dict:
    boms = facts.get("boms", [])
    bom_styles = set(facts.get("bom_styles", set()))
    all_styles = list((facts.get("so_styles") or {}).keys())
    rolls = facts.get("fabric_roll_m", {})
    mrs = facts.get("material_requests", [])
    # Material Requests WITH their line items — this is where the non-fabric
    # raw materials (Labels, Buttons, Thread, Fusing, Elastic, Packaging) live.
    mr_rows = []
    mr_groups: dict = {}
    for m in mrs:
        try:
            doc = erp.erp_doc("Material Request", m.get("name")) or {}
        except Exception:
            doc = {}
        items = _line_items(doc)
        for it in items:
            g = it.get("item_group") or "Unspecified"
            mr_groups[g] = mr_groups.get(g, 0) + 1
        mr_rows.append({"mr": m.get("name"), "status": m.get("status"),
                        "type": m.get("material_request_type"), "docstatus": m.get("docstatus"),
                        "date": _iso(m.get("transaction_date")),
                        "item_groups": sorted({i["item_group"] for i in items if i.get("item_group")}),
                        "items": items})
    return {
        "bom_count": len(boms),
        "styles_with_bom": sorted(bom_styles),
        "styles_missing_bom": sorted([s for s in all_styles if s not in bom_styles]),
        "boms": [{"bom": b.get("name"), "item": b.get("item"), "item_name": b.get("item_name"),
                  "total_cost": round(_n(b.get("total_cost")), 2)} for b in boms],
        "material_request_lines_by_item_group": mr_groups,
        "material_requests": mr_rows[:40],
        "draft_material_requests": len([m for m in mrs if (m.get("status") or "").lower() == "draft"]),
        "cancelled_material_requests": len([m for m in mrs if (m.get("status") or "").lower() == "cancelled"]),
        "trim_exceptions": len(facts.get("trim_exceptions", [])),
        "fabric_roll_metres_by_item": sorted(
            ({"item": k, "metres": round(v, 2)} for k, v in rolls.items()),
            key=lambda r: -r["metres"])[:40],
    }


def _line_items(doc: dict) -> list:
    """Flatten a purchase document's child items — this is where the item
    category actually lives (item_group 'Fabric' / 'Trims' / 'Washing Services' /...).
    Header-only summaries could not answer 'who supplies fabric?'; the lines can."""
    return [{"item_code": it.get("item_code"), "item_name": it.get("item_name"),
             "item_group": it.get("item_group"), "qty": _n(it.get("qty")), "uom": it.get("uom"),
             "rate": _n(it.get("rate")), "amount": _n(it.get("amount"))}
            for it in (doc.get("items") or []) if it.get("item_code") or it.get("item_name")]


def _procurement(facts, today) -> dict:
    """Purchase orders / receipts / invoices WITH their line items, plus the
    supplier master — so the copilot can tell *what* each supplier actually supplied."""
    def _docs(doctype, records, key_name, date_key):
        out = []
        for r in records:
            try:
                doc = erp.erp_doc(doctype, r.get("name")) or {}
            except Exception:
                doc = {}
            items = _line_items(doc)
            out.append({
                "name": r.get("name"), "supplier": r.get("supplier"),
                "date": _iso(r.get(date_key)), "status": r.get("status"),
                "currency": r.get("currency"),
                "grand_total": round(_n(r.get("grand_total")), 2),
                "outstanding": round(_n(r.get("outstanding_amount")), 2),
                "per_received": r.get("per_received"),
                "item_groups": sorted({i["item_group"] for i in items if i.get("item_group")}),
                "items": items,
            })
        return out

    pos = _docs("Purchase Order", facts.get("purchase_orders", []), "po", "transaction_date")
    prs = _docs("Purchase Receipt", facts.get("purchase_receipts", []), "receipt", "posting_date")
    pis = _docs("Purchase Invoice", facts.get("purchase_invoices", []), "invoice", "due_date")

    # suppliers who actually supplied fabric (any line in item_group 'Fabric')
    fabric_suppliers = sorted({
        d["supplier"] for d in (pos + pis) if any(i.get("item_group") == "Fabric" for i in d["items"])
    })
    # suppliers with only service/other lines (e.g. washing) — not fabric
    non_fabric = sorted({
        d["supplier"] for d in (pos + pis)
        if d["items"] and not any(i.get("item_group") == "Fabric" for i in d["items"])
    } - set(fabric_suppliers))

    try:
        suppliers = erp.erp_get("Supplier", ["name", "supplier_name", "supplier_group", "country"]) or []
    except Exception:
        suppliers = []

    return {
        "purchase_orders": pos,
        "purchase_receipts": prs,
        "purchase_invoices": pis,
        "fabric_suppliers": fabric_suppliers,
        "non_fabric_suppliers": non_fabric,
        "supplier_master": [{"supplier": s.get("name"), "group": s.get("supplier_group"),
                             "country": s.get("country")} for s in suppliers],
    }


def _quality(facts, today) -> dict:
    return {
        "fabric_quality_evidence": [{"record": q.get("name"), "fabric": q.get("source_fabric_code"),
                                     "result": q.get("inspection_result"),
                                     "source_document": q.get("source_document")}
                                    for q in facts.get("quality_evidence", [])],
        "quality_inspections": [{"inspection": q.get("name"), "status": q.get("status"),
                                 "docstatus": q.get("docstatus"), "item": q.get("item_code"),
                                 "reference": q.get("reference_name"), "type": q.get("inspection_type")}
                                for q in facts.get("quality_inspections", [])],
    }


def _logistics(facts, today) -> dict:
    return {
        "shipments": [{"shipment": s.get("name"), "order": s.get("sales_order"), "item": s.get("item"),
                       "shipped_qty": _n(s.get("shipped_qty")), "order_qty": _n(s.get("sales_order_qty")),
                       "variance_qty": _n(s.get("shipment_variance_qty")),
                       "customer_po": s.get("customer_po_no"), "invoice": s.get("source_invoice_no")}
                      for s in facts.get("shipments", [])],
        "shipment_documents": [{"group": s.get("shipment_group"), "order": s.get("sales_order"),
                                "customer_po": s.get("customer_po_no"), "document_types": s.get("files")}
                               for s in facts.get("shipment_docs", [])],
        "orders_with_delivery_note": sorted(facts.get("delivered_by_so", set())),
    }


def _production(facts, today) -> dict:
    pde = facts.get("production_daily", [])
    return {
        "work_orders": [{"wo": w.get("name"), "item": w.get("production_item"), "qty": _n(w.get("qty")),
                         "produced_qty": _n(w.get("produced_qty")), "docstatus": w.get("docstatus"),
                         "status": w.get("status"), "planned_start": _iso(w.get("planned_start_date"))}
                        for w in facts.get("work_orders", [])],
        "production_daily_evidence_count": len(pde),
        "production_daily_evidence": [{"record": p.get("name"), "style": p.get("style_no"),
                                       "order": p.get("sales_order"), "order_qty": _n(p.get("source_order_qty_pcs")),
                                       "packed": _n(p.get("source_total_packed")),
                                       "cutting": _n(p.get("source_total_cutting")),
                                       "sewing": _n(p.get("source_total_sewing")),
                                       "delivery_date": _iso(p.get("delivery_date"))}
                                      for p in pde[:30]],
    }


def _gaps(facts, today) -> dict:
    return {"migration_data_gaps": [
        {"name": g.get("name"), "gap_key": g.get("gap_key"), "process_area": g.get("process_area"),
         "status": g.get("status")} for g in facts.get("mdg", [])]}


_BUILDERS = {
    "finance": _finance,
    "materials": _materials,
    "procurement": _procurement,
    "quality": _quality,
    "logistics": _logistics,
    "production": _production,
    "gaps": _gaps,
}

_ROUTES = {
    "finance": ("finance", "financial", "payment", "payments", "unpaid", "receivable", "receivables",
                "outstanding", "overdue", "invoice", "invoices", "cash", "money", "profit", "margin",
                "cost", "costing", "price", "pricing", "payable", "payables", "revenue", "owed"),
    "materials": ("bom", "boms", "material", "materials", "fabric", "fabrics", "trim", "trims",
                  "sourcing", "component", "components", "requirement", "requirements", "requisition",
                  "stock", "inventory", "roll", "rolls", "yield", "shortage"),
    "procurement": ("supplier", "suppliers", "vendor", "vendors", "purchase", "procurement",
                    "po ", "purchase order", "receipt", "receipts", "source", "sourcing", "sourced",
                    "supply", "supplied", "supplies", "buy", "bought", "where do i get",
                    "come from", "comes from", "raw material", "raw materials"),
    "quality": ("quality", "inspection", "inspections", "defect", "defects", "fail", "failed",
                "fails", "reject", "rejected"),
    "logistics": ("ship", "shipment", "shipments", "shipping", "dispatch", "dispatched", "delivery",
                  "deliveries", "logistics", "delivered", "delivery note"),
    "production": ("production", "produce", "producing", "manufacture", "manufacturing", "work order",
                   "work orders", "sewing", "sew", "washing", "wash", "cutting", "cut ", "packed",
                   "packing", "capacity", "planned", "job card", "style"),
    "gaps": ("gap", "gaps", "migration", "data gap", "missing data", "evidence"),
}


# Section dependencies: asking about materials/product inevitably needs the
# purchases & suppliers too ("where do I get X from?"), so pull them together.
_DEPS = {"materials": {"procurement"}}


def _route_sections(q: str) -> list:
    q = (q or "").lower()
    hit = {name for name, kws in _ROUTES.items() if any(k in q for k in kws)}
    for name in list(hit):
        hit |= _DEPS.get(name, set())
    # Nothing specific asked (e.g. "summarise", "what should I do") -> include everything
    # so the copilot can still answer a broad question.
    return sorted(hit) if hit else list(_BUILDERS.keys())


# ── public API ──────────────────────────────────────────────────────────────
def build_evidence(question: str) -> dict:
    """Assemble the live evidence pack relevant to ``question``."""
    facts = rulebook.live_facts()
    today = facts.get("today") or date.today()

    orders = _orders(facts, today)
    ev = {
        "today": str(today),
        "order_book": _order_book(facts, orders),
        "orders": orders,
        "styles_in_demand": _styles(facts),
        "risk_summary": rulebook.summarize(rulebook.build_risks()),
        "risks": _risks(facts),
        "forecast": _forecast_section(),
    }
    for name in _route_sections(question):
        try:
            ev[name] = _BUILDERS[name](facts, today)
        except Exception:
            ev[name] = {"error": "section unavailable"}
    ev["evidence_sections"] = sorted(ev.keys())
    return ev


_INSTR = (
    "Answer the user's question using ONLY the FACTS below (a live snapshot of the KOGO ERP). "
    "The FACTS contain real records — orders, invoices/receivables, BOM/material, purchasing, quality, "
    "logistics, production and migration gaps (only the sections relevant to the question are present). "
    "Purchase documents AND material requests carry their line `items` with `item_group` and `item_name` "
    "(e.g. group 'Fabric', 'Labels', 'Buttons', 'Washing Services'), so you CAN tell what each supplier "
    "supplied, and what is only *requested* (draft Material Requests — see `material_request_lines_by_item_group`). "
    "Who supplies fabric is whoever has lines in item_group 'Fabric' (see `fabric_suppliers`). "
    "You MAY rank, filter, compare, group and compute from the rows provided (e.g. biggest/smallest, "
    "most urgent/overdue, by customer or style, totals within a currency). Always cite the exact numbers "
    "you used. Never invent numbers, names or records, and never mix currencies. If the FACTS genuinely "
    "lack what is needed, say exactly what is missing. "
    "FORMAT FOR READABILITY: one short summary line, then up to 6 short bullet lines each starting with "
    "'• ' holding the key figures — do not merge everything into one long paragraph. "
    "Output ONLY the final answer. Do NOT show any reasoning, planning, analysis or chain-of-thought, do "
    "NOT start with a heading such as 'KOGO analysis', do not restate the question, and do not repeat "
    "these instructions."
)


def answer(db, question: str = "") -> dict | None:
    """Grounded answer over live ERP data, or ``None`` if the model is unavailable
    (so the caller can fall back to the deterministic answerer)."""
    status = erp.erp_status()
    if not status.get("connected"):
        return {
            "answer": ("I can't reach KOGO ERP right now, so I have no live data to analyse. "
                       "Check the ERP connection and ask again — the answer always mirrors the live "
                       "ERP figures."),
            "related": [], "grounded": True, "unsourced": [], "live": False,
            "source": "KOGO ERP", "generated_at": _now_iso(), "connection": status,
            "evidence_sections": [],
        }

    ev = build_evidence(question)
    prompt = ("You are the Cortex Control Tower copilot for an apparel manufacturer. "
              + _INSTR + "\n\nFACTS:\n" + json.dumps(ev, ensure_ascii=False, default=str)
              + "\n\nQUESTION: " + (question or "Summarise the most important things to act on now."))

    reply = _ai._llm(db, prompt)
    if not reply:
        return None

    reply = reply.replace(_INSTR, "").strip()          # drop any echoed instruction
    evidence = _ai._evidence_text(ev)
    unsourced = [t for t in _ai._num_tokens(reply) if t and t not in evidence]
    risks = rulebook.build_risks()
    return {
        "answer": reply,
        "related": [r.get("title") for r in risks if r.get("severity") == "critical"][:5],
        "grounded": len(unsourced) == 0,
        "unsourced": unsourced,
        "evidence_sections": [s for s in ev.get("evidence_sections", []) if s not in ("today",)],
        "live": True, "source": "KOGO ERP", "generated_at": _now_iso(),
        "connection": status,
    }
