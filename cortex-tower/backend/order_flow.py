"""Order flow: one read model per Sales Order, from the Sales Order to commercial close (ORDER_TO_SHIP_PLAN section 3 rule 1).

``status(be, so)`` reads every follow-on document of the Sales Order in a few batched ``get_list`` calls (a link filter, a
child-table filter, or an ``in`` filter over names found a moment before, chunked by 100) and returns::

    {sales_order, chain, head, history, header, steps:[{key, label, state, counts, docs, blockers, next}], by_step, focus, kpis}

Nothing here writes. Reads only; one failing document type is reported in ``errors`` and never stops the rest. State of a
step is ``todo | doing | done | blocked | na``; steps run in parallel in reality, so each has its own state.

Where the tower has to guess (a quantity tolerance, what "in house" means) the constant is named at the top of the file and
the status log lists it under open questions.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import erp as _erp

#: ± share of the ordered quantity that still counts as "all of it" (allocated, sewn). Conservative: zero. The ERP's own
#: Sales Contract tolerance bands are the right source; reading them is an open question in ORDER_TO_SHIP_STATUS.md.
QTY_TOLERANCE_PCT = 0.0
CHUNK = 100

STEPS = [
    ("confirm", "Confirm"), ("allocate", "Plan and allocate"), ("tna", "T&A plan"), ("samples", "Samples and PP"),
    ("materials", "Materials"), ("cutsew", "Cut and sew"), ("subcontract", "Subcontract and finish"),
    ("pack", "Pack and inspect"), ("ship", "Ship"), ("invoice", "Invoice, collect, close"),
]
STEP_KEYS = [k for k, _ in STEPS]

# A source says how to find one document type's rows for the order.
#   {"dt", "by": "so"|"contract"|"child_so"|"via", "field", "child", "via_dt", "fields", "step", "style"}
# "so": parent has a link to the Sales Order; "contract": parent links the Sales Contract; "child_so": a child table row
# links the Sales Order (the parent is returned); "via": parent links a document found earlier (``via_dt`` -> ``field``).
_BASE = ["name", "docstatus", "modified", "owner"]
SOURCES: list[dict] = [
    {"step": "confirm", "dt": "Sales Contract", "by": "so", "field": "sales_order", "fields": ["status"]},
    {"step": "allocate", "dt": "Factory Allocation", "by": "so", "field": "sales_order", "fields": ["status", "order_qty"]},
    {"step": "tna", "dt": "Order TNA", "by": "so", "field": "sales_order",
     "fields": ["status", "style_no", "colour", "pcd", "ex_factory_date", "plan_feasible", "baseline_locked", "critical_delay_days"]},
    {"step": "tna", "dt": "TNA Milestone", "by": "so", "field": "sales_order",
     "fields": ["status", "style_no", "colour", "milestone_type", "planned_date", "actual_date", "is_critical", "department"]},
    {"step": "samples", "dt": "Sample Approval", "by": "so", "field": "sales_order", "fields": ["status", "style_no", "colour", "sample_type"]},
    {"step": "samples", "dt": "PP Meeting", "by": "so", "field": "sales_order", "fields": ["status", "style_no"]},
    {"step": "samples", "dt": "Work Order", "by": "so", "field": "sales_order", "fields": ["status", "qty"]},
    {"step": "materials", "dt": "Fabric Requisition", "by": "child_so", "child": "Fabric Requisition Item", "field": "sales_order", "fields": ["status"]},
    {"step": "materials", "dt": "Trim Requisition", "by": "child_so", "child": "Trim Requisition Item", "field": "sales_order", "fields": ["status"]},
    {"step": "materials", "dt": "Purchase Order", "by": "child_so", "child": "Purchase Order Item", "field": "sales_order", "fields": ["status"]},
    {"step": "materials", "dt": "Purchase Receipt", "by": "child_so", "child": "Purchase Receipt Item", "field": "sales_order", "fields": ["status"]},
    {"step": "materials", "dt": "Fabric Inspection", "by": "via", "via_dt": "Fabric Requisition", "field": "fabric_requisition", "fields": ["colour", "lot_result"]},
    {"step": "materials", "dt": "Trim Inspection", "by": "via", "via_dt": "Trim Requisition", "field": "trim_requisition", "fields": ["colour", "result"]},
    {"step": "cutsew", "dt": "Production Card", "by": "so", "field": "sales_order", "fields": ["status", "style_no", "factory", "line", "pcd", "ex_factory_date"]},
    {"step": "cutsew", "dt": "Pilot Run", "by": "so", "field": "sales_order", "fields": ["status", "style_no", "line"]},
    {"step": "cutsew", "dt": "Cut Plan", "by": "so", "field": "sales_order", "fields": ["status", "style_no", "colour"]},
    {"step": "cutsew", "dt": "Lay Report", "by": "via", "via_dt": "Production Card", "field": "production_card", "fields": ["colour", "line"]},
    {"step": "cutsew", "dt": "Line Input", "by": "via", "via_dt": "Production Card", "field": "production_card", "fields": ["line"]},
    {"step": "cutsew", "dt": "Line QC Report", "by": "via", "via_dt": "Production Card", "field": "production_card", "fields": ["line"]},
    {"step": "cutsew", "dt": "Daily Line Report", "by": "child_via", "child": "Daily Line Report Output", "via_dt": "Production Card",
     "field": "production_card", "fields": ["line"]},
    {"step": "subcontract", "dt": "Subcontract Challan", "by": "so", "field": "sales_order", "fields": ["status"]},
    {"step": "subcontract", "dt": "Subcontract Return", "by": "contract", "field": "sales_contract", "fields": []},
    {"step": "subcontract", "dt": "Subcontract Settlement", "by": "contract", "field": "sales_contract", "fields": []},
    {"step": "subcontract", "dt": "Finishing Receipt", "by": "so", "field": "sales_order", "fields": ["line"]},
    {"step": "pack", "dt": "Packing List", "by": "so", "field": "sales_order", "fields": ["status", "style_item", "total_pieces", "total_cartons", "shipment"]},
    {"step": "pack", "dt": "Final Inspection", "by": "so", "field": "sales_order", "fields": ["result", "style_item", "inspection_type"]},
    {"step": "ship", "dt": "Delivery Note", "by": "child_so", "child": "Delivery Note Item", "field": "against_sales_order", "fields": ["status", "posting_date"]},
    {"step": "ship", "dt": "Letter of Credit", "by": "contract", "field": "sales_contract", "fields": ["status"]},
    {"step": "invoice", "dt": "Sales Invoice", "by": "child_so", "child": "Sales Invoice Item", "field": "sales_order",
     "fields": ["status", "posting_date", "due_date", "grand_total", "outstanding_amount"]},
    {"step": "invoice", "dt": "Buyer Claim", "by": "contract", "field": "sales_contract", "fields": ["status"]},
]
#: Shipment and Payment Entry are found from what was already read (Packing List.shipment; Payment Entry Reference).
EXTRA_SHIPMENT_FIELDS = ["status", "apparel_ship_status", "apparel_on_board_date"]


def _chunks(seq: list, n: int = CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def erp_profile(be) -> str:
    """``arinox`` when the Arinox layer (Production Card, Order TNA, Factory Allocation) is on the ERP, else ``cortex_evidence``.

    The old Cortex evidence readers (wip_plan, wip_actions) stay in the code behind the second value; on the live site the
    first is what comes back, so the new screens are used.
    """
    try:
        rows = be.get_list("DocType", [["name", "in", ["Production Card", "Order TNA", "Factory Allocation"]]], ["name"], limit=10)
        return "arinox" if len(rows) >= 3 else "cortex_evidence"
    except Exception:
        return "cortex_evidence"


def _sales_order_chain(be, so: str) -> tuple[list[str], str]:
    """Every name of this order across amendments (-1, -2 ...), oldest first, and the head (the live one)."""
    chain = [so]
    cur = so
    for _ in range(10):                                   # ancestors
        rows = be.get_list("Sales Order", [["name", "=", cur]], ["name", "amended_from"], limit=1)
        prev = rows[0].get("amended_from") if rows else None
        if not prev or prev in chain:
            break
        chain.insert(0, prev)
        cur = prev
    cur = so
    for _ in range(10):                                   # descendants
        rows = be.get_list("Sales Order", [["amended_from", "=", cur]], ["name"], limit=1)
        if not rows or rows[0]["name"] in chain:
            break
        chain.append(rows[0]["name"])
        cur = rows[0]["name"]
    return chain, chain[-1]


def _fetch(be, src: dict, ctx: dict, errors: dict) -> list[dict]:
    dt, fields = src["dt"], _BASE + list(src.get("fields") or [])
    by, field = src["by"], src.get("field")
    if by == "so" and field == "sales_order" and "sales_order" not in fields:
        fields.append("sales_order")                       # lets a document of an earlier amendment be shown as history
    try:
        if by == "so":
            return be.get_list(dt, [[field, "in", ctx["chain"]]], fields, limit=500)
        if by == "contract":
            if not ctx["contracts"]:
                return []
            return be.get_list(dt, [[field, "in", ctx["contracts"]]], fields, limit=500)
        if by == "child_so":
            parents = []
            for c in be.get_list(src["child"], [[field, "in", ctx["chain"]]], ["parent"], limit=2000, parent=dt):
                if c.get("parent") and c["parent"] not in parents:
                    parents.append(c["parent"])
        elif by == "via":
            names = [r["name"] for r in ctx["docs"].get(src["via_dt"], [])]
            parents = []
            for part in _chunks(names):
                parents += [r["name"] for r in be.get_list(dt, [[field, "in", part]], ["name"], limit=2000)]
        elif by == "child_via":
            names = [r["name"] for r in ctx["docs"].get(src["via_dt"], [])]
            parents = []
            for part in _chunks(names):
                for c in be.get_list(src["child"], [[field, "in", part]], ["parent"], limit=2000, parent=dt):
                    if c.get("parent") and c["parent"] not in parents:
                        parents.append(c["parent"])
        else:
            return []
        out: list[dict] = []
        for part in _chunks(parents):
            out += be.get_list(dt, [["name", "in", part]], fields, limit=500)
        return out
    except Exception as e:                                 # noqa: BLE001 - one document type failing must not stop the page
        errors[dt] = str(e)[:160]
        return []


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if int(r.get("docstatus") or 0) != 2 and not r.get("history")]


def _counts(rows: list[dict]) -> dict:
    return {"total": len(_live(rows)), "draft": sum(1 for r in _live(rows) if int(r.get("docstatus") or 0) == 0),
            "submitted": sum(1 for r in _live(rows) if int(r.get("docstatus") or 0) == 1),
            "cancelled": sum(1 for r in rows if int(r.get("docstatus") or 0) == 2)}


def _within(have: float, want: float) -> bool:
    return want > 0 and abs(have - want) <= want * QTY_TOLERANCE_PCT / 100.0 + 1e-9


def status(be, so: str, today: Optional[date] = None) -> dict:
    """The whole read model of one Sales Order. ``today`` is injectable for tests."""
    today = today or date.today()
    errors: dict = {}
    chain, head = _sales_order_chain(be, so)
    try:
        order = be.get_doc("Sales Order", head)
    except Exception as e:                                 # noqa: BLE001
        return {"ok": False, "error": f"Sales Order {head} could not be read: {str(e)[:160]}", "sales_order": so}
    items = order.get("items") or []
    total_qty = sum(_num(i.get("qty")) for i in items)

    ctx: dict = {"chain": chain, "contracts": [], "docs": {}}
    docs: dict[str, list[dict]] = ctx["docs"]
    # pass 1 (direct), pass 2 (needs names from pass 1): the order of SOURCES already puts parents first except Sales Contract
    for src in SOURCES:
        rows = _fetch(be, src, ctx, errors)
        docs[src["dt"]] = rows
        if src["dt"] == "Sales Contract":
            ctx["contracts"] = [r["name"] for r in rows if int(r.get("docstatus") or 0) != 2]
    # Shipments come from the Packing Lists, Payment Entries from the invoices: the two lookups nothing else can make.
    ships = sorted({r.get("shipment") for r in docs.get("Packing List", []) if r.get("shipment")})
    docs["Shipment"] = []
    try:
        for part in _chunks(ships):
            docs["Shipment"] += be.get_list("Shipment", [["name", "in", part]], _BASE + EXTRA_SHIPMENT_FIELDS, limit=500)
    except Exception as e:                                 # noqa: BLE001
        errors["Shipment"] = str(e)[:160]
    docs["Payment Entry"] = []
    try:
        inv = [r["name"] for r in docs.get("Sales Invoice", [])]
        pes: list[str] = []
        for part in _chunks(inv):
            for c in be.get_list("Payment Entry Reference", [["reference_name", "in", part]], ["parent"], limit=2000, parent="Payment Entry"):
                if c.get("parent") and c["parent"] not in pes:
                    pes.append(c["parent"])
        for part in _chunks(pes):
            docs["Payment Entry"] += be.get_list("Payment Entry", [["name", "in", part]], _BASE + ["status", "posting_date"], limit=500)
    except Exception as e:                                 # noqa: BLE001
        errors["Payment Entry"] = str(e)[:160]
    # Factory Allocation lines (qty per style x colour), and the sewn quantity from the production ledger
    lines: list[dict] = []
    try:
        fa = [r["name"] for r in docs.get("Factory Allocation", [])]
        for part in _chunks(fa):
            lines += be.get_list("Factory Allocation Line", [["parent", "in", part]],
                                 ["parent", "style_item", "style_no", "colour", "qty", "order_qty", "factory", "line", "pcd", "sewing_start", "sewing_end", "ex_factory_date"],
                                 limit=2000, parent="Factory Allocation")
    except Exception as e:                                 # noqa: BLE001
        errors["Factory Allocation Line"] = str(e)[:160]
    ledger: dict[str, float] = {}
    try:
        for r in be.get_list("Production Movement", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["stage", "qty"], limit=20000):
            ledger[r.get("stage") or ""] = ledger.get(r.get("stage") or "", 0.0) + _num(r.get("qty"))
    except Exception as e:                                 # noqa: BLE001
        errors["Production Movement"] = str(e)[:160]

    # history: a document that belongs to an earlier amendment of the order is shown, never counted
    for dt, rows in docs.items():
        for r in rows:
            if r.get("sales_order") and r["sales_order"] != head:
                r["history"] = True

    ctxr = {"head": head, "order": order, "total_qty": total_qty, "docs": docs, "lines": lines, "ledger": ledger, "today": today}
    steps = []
    for key, label in STEPS:
        st = _STEP_FN[key](ctxr)
        rows = [r for s in SOURCES if s["step"] == key for r in docs.get(s["dt"], [])]
        if key == "ship":
            rows += docs["Shipment"]
        if key == "invoice":
            rows += docs["Payment Entry"]
        dts = [s["dt"] for s in SOURCES if s["step"] == key] + (["Shipment"] if key == "ship" else []) + (["Payment Entry"] if key == "invoice" else [])
        st["docs"] = [_doc_row(dt, r) for dt in dts for r in docs.get(dt, [])]
        st["counts"] = _counts(rows)
        st["by_type"] = {dt: _counts(docs.get(dt, []))["total"] for dt in dts}
        st["key"], st["label"] = key, label
        steps.append(st)
    # pages: each step's own ERP page (a record, else the list of its main document type)
    by_step = {}
    for st in steps:
        first = next((d for d in st["docs"] if d.get("url") and d["status"] != "Cancelled"), None)
        main_dt = {"confirm": "Sales Order", "allocate": "Factory Allocation", "tna": "Order TNA", "samples": "Sample Approval",
                   "materials": "Fabric Requisition", "cutsew": "Production Card", "subcontract": "Subcontract Challan",
                   "pack": "Packing List", "ship": "Shipment", "invoice": "Sales Invoice"}[st["key"]]
        if st["key"] == "confirm":
            by_step["confirm"] = {"step": "confirm", "doctype": "Sales Order", "name": head, "url": _erp.url_for("Sales Order", head),
                                  "label": f"Open Sales Order {head}"}
        elif first:
            by_step[st["key"]] = {"step": st["key"], "doctype": first["doctype"], "name": first["name"], "url": first["url"],
                                  "label": f"Open {first['doctype']} {first['name']}"}
        else:
            by_step[st["key"]] = {"step": st["key"], "doctype": main_dt, "name": "", "url": _erp.url_for(main_dt),
                                  "label": f"Open the {main_dt} list"}
    focus_step = _focus(steps)
    header = _header(ctxr, steps)
    out = {"ok": True, "sales_order": so, "head": head, "chain": chain, "history": len(chain) > 1 and so != head,
           "superseded_by": head if so != head else "", "header": header, "steps": steps, "by_step": by_step,
           "focus": by_step.get(focus_step["key"], {}) if focus_step else {}, "next": _next(steps),
           "kpis": {"order_qty": total_qty, "sewn": ledger.get("SEW_OUT", 0.0), "packed": ledger.get("PACKED", 0.0),
                    "shipped": ledger.get("SHIPPED", 0.0), "documents": sum(len(s["docs"]) for s in steps)},
           "errors": errors, "erp_profile": erp_profile(be)}
    return out


def _doc_row(dt: str, r: dict) -> dict:
    ds = int(r.get("docstatus") or 0)
    status = r.get("result") if dt in ("Final Inspection", "Trim Inspection") and r.get("result") else r.get("status")
    shown = "Cancelled" if ds == 2 else (status or {0: "Draft", 1: "Submitted"}.get(ds, ""))
    return {"doctype": dt, "name": r.get("name"), "status": shown, "docstatus": ds, "style": r.get("style_no") or r.get("style_item") or "",
            "colour": r.get("colour") or "", "owner": r.get("owner") or "",
            "date": str(r.get("posting_date") or r.get("planned_date") or r.get("modified") or "")[:10],
            "url": _erp.url_for(dt, r.get("name") or ""), "history": bool(r.get("history"))}


def _style_of(i: dict) -> str:
    """The style of an order line from its item code: a colour/size variant is `<style>-<colour>-<size>` (the size is the line's `apparel_size`)."""
    code = (i.get("item_code") or "").strip()
    size = (i.get("apparel_size") or "").strip()
    if size and code.upper().endswith("-" + size.upper()):
        code = code[:-len(size) - 1]
        if "-" in code:
            code = code.rsplit("-", 1)[0]
    return code


def _header(c: dict, steps: list[dict]) -> dict:
    o = c["order"]
    ex = _to_date(o.get("delivery_date")) or None
    pcds = [_to_date(r.get("ex_factory_date")) for r in c["docs"].get("Order TNA", []) if r.get("ex_factory_date")]
    if pcds and all(pcds):
        ex = min(pcds)
    rag = "grey"
    if any(s["state"] == "blocked" for s in steps):
        rag = "red"
    elif any(s["blockers"] for s in steps):
        rag = "amber"
    elif steps and all(s["state"] in ("done", "na") for s in steps):
        rag = "green"
    elif any(s["state"] in ("doing", "done") for s in steps):
        rag = "green"
    return {"customer": o.get("customer_name") or o.get("customer") or "", "currency": o.get("currency") or "",
            "contract": (c["docs"].get("Sales Contract") or [{}])[0].get("name", "") if c["docs"].get("Sales Contract") else "",
            "styles": len({_style_of(i) for i in o.get("items") or []}),
            "qty": c["total_qty"], "value": _num(o.get("grand_total")), "ex_factory": str(ex or ""),
            "days_to_ex_factory": (ex - c["today"]).days if ex else None, "docstatus": int(o.get("docstatus") or 0),
            "status": o.get("status") or "", "rag": rag, "transaction_date": str(o.get("transaction_date") or "")}


def _focus(steps: list[dict]) -> Optional[dict]:
    for s in steps:
        if s["state"] == "blocked":
            return s
    for s in steps:
        if s["state"] in ("doing", "todo") and s.get("next"):
            return s
    return None


def _next(steps: list[dict]) -> dict:
    f = _focus(steps)
    if not f:
        return {"step": "done", "text": "Everything planned so far is done."}
    return {"step": f["key"], **(f.get("next") or {"text": f["label"]})}


# ───────────────────────── one function per step ─────────────────────────

def _r(state: str, blockers: Optional[list] = None, text: str = "", action: str = "") -> dict:
    return {"state": state, "blockers": blockers or [], "next": {"text": text, "action": action} if text else {}}


def _s_confirm(c: dict) -> dict:
    ds = int(c["order"].get("docstatus") or 0)
    if ds == 1:
        return _r("done")
    if ds == 2:
        return _r("blocked", ["The Sales Order is cancelled."], "The Sales Order was cancelled. Amend it in the ERP.", "open_erp")
    return _r("doing", [], "Submit the Sales Order in the ERP.", "open_erp")


def _alloc_lines(c: dict) -> list[dict]:
    live = {r["name"] for r in _live(c["docs"].get("Factory Allocation", []))}
    return [ln for ln in c["lines"] if ln.get("parent") in live]


def _s_allocate(c: dict) -> dict:
    if int(c["order"].get("docstatus") or 0) != 1:
        return _r("todo", ["The Sales Order is not submitted."], "Submit the Sales Order first.")
    fa = _live(c["docs"].get("Factory Allocation", []))
    lines = _alloc_lines(c)
    if not fa or not lines:
        return _r("todo", [], "Decide where to produce: open the allocation board.", "allocate")
    got = sum(_num(ln.get("qty")) for ln in lines)
    blockers = []
    if not _within(got, c["total_qty"]):
        blockers.append(f"Allocated {got:g} of {c['total_qty']:g} pieces.")
    nopcd = [ln for ln in lines if not ln.get("pcd")]
    if nopcd:
        blockers.append(f"{len(nopcd)} allocation line(s) have no PCD.")
    if blockers:
        return _r("doing", blockers, "Finish the allocation: " + blockers[0], "allocate")
    return _r("done")


def _s_tna(c: dict) -> dict:
    tnas = _live(c["docs"].get("Order TNA", []))
    if not tnas:
        return _r("todo", [], "Make the T&A plan for this order.", "tna")
    blockers = []
    infeasible = [t for t in tnas if t.get("plan_feasible") in (0, "0", False) and t.get("plan_feasible") is not None]
    if infeasible:
        blockers.append(f"{len(infeasible)} style/colour plan(s) do not fit the dates.")
    late = [t for t in tnas if t.get("status") == "Late"]
    if late:
        blockers.append(f"{len(late)} style/colour plan(s) are late.")
    want = len({(ln.get("style_item"), ln.get("colour")) for ln in _alloc_lines(c)})
    if want and len(tnas) < want:
        blockers.append(f"{len(tnas)} of {want} style/colour plans exist.")
    unlocked = [t for t in tnas if not int(t.get("baseline_locked") or 0)]
    if unlocked and not blockers:
        return _r("doing", [], "Lock the baseline of the T&A plan.", "tna")
    if blockers:
        return _r("blocked" if infeasible else "doing", blockers, blockers[0], "tna")
    return _r("done")


def _s_samples(c: dict) -> dict:
    sa = _live(c["docs"].get("Sample Approval", []))
    pp = _live(c["docs"].get("PP Meeting", []))
    if not sa and not pp:
        return _r("todo", [], "Create the sample approvals this order needs.", "samples")
    ok = ("Approved", "Approved with Comments", "Not Required")
    bad = [s for s in sa if s.get("status") == "Rejected"]
    pending = [s for s in sa if s.get("status") not in ok]
    blockers = []
    if bad:
        blockers.append(f"{len(bad)} sample approval(s) rejected.")
    if pending:
        blockers.append(f"{len(pending)} of {len(sa)} sample approvals still open.")
    if not pp:
        blockers.append("No PP meeting yet.")
    elif not any(int(p.get("docstatus") or 0) == 1 for p in pp):
        blockers.append("The PP meeting is not submitted.")
    if blockers:
        return _r("blocked" if bad else "doing", blockers, blockers[0], "samples")
    return _r("done")


def _s_materials(c: dict) -> dict:
    d = c["docs"]
    reqs = _live(d.get("Fabric Requisition", [])) + _live(d.get("Trim Requisition", []))
    pos = _live(d.get("Purchase Order", []))
    prs = [r for r in _live(d.get("Purchase Receipt", [])) if int(r.get("docstatus") or 0) == 1]
    insp = _live(d.get("Fabric Inspection", [])) + _live(d.get("Trim Inspection", []))
    if not reqs and not pos:
        return _r("todo", [], "Raise the fabric and trim requisitions.", "materials")
    blockers = []
    failed = [i for i in insp if (i.get("result") or i.get("lot_result")) in ("Fail", "Rejected")]
    held = [i for i in insp if (i.get("result") or i.get("lot_result")) in ("Hold", "Re-inspect 100%") and i not in failed]
    if failed:
        blockers.append(f"{len(failed)} material inspection(s) failed.")
    if held:
        blockers.append(f"{len(held)} material inspection(s) on hold or to be re-inspected.")
    if not any(int(r.get("docstatus") or 0) == 1 for r in reqs) and reqs:
        blockers.append("No requisition is approved yet.")
    if reqs and not pos:
        blockers.append("Requisitions exist but nothing is ordered.")
    if pos and len(prs) < len(pos):
        blockers.append(f"{len(pos) - len(prs)} of {len(pos)} purchase orders have no receipt yet.")
    if pos and prs and not insp:
        blockers.append("Received material has no inspection.")
    if blockers:
        return _r("blocked" if failed else "doing", blockers, blockers[0], "materials")
    return _r("done")


def _s_cutsew(c: dict) -> dict:
    cards = _live(c["docs"].get("Production Card", []))
    if not cards:
        return _r("todo", [], "Make the production card.", "cutsew")
    sewn = c["ledger"].get("SEW_OUT", 0.0)
    if _within(sewn, c["total_qty"]) or sewn >= c["total_qty"] > 0:
        return _r("done")
    cut = c["ledger"].get("CUT", 0.0)
    if not cut:
        return _r("doing", ["Nothing is cut yet: plan the cut, issue fabric and report the lays."], "Plan the cut and issue the fabric.", "cutsew")
    return _r("doing", [f"Sewn {sewn:g} of {c['total_qty']:g} pieces (cut {cut:g})."], f"Sewn {sewn:g} of {c['total_qty']:g}. Keep the line reports coming.", "cutsew")


def _s_subcontract(c: dict) -> dict:
    d = c["docs"]
    ch = _live(d.get("Subcontract Challan", []))
    fr = _live(d.get("Finishing Receipt", []))
    out_now = [x for x in ch if x.get("status") in ("Open", "Partly Returned")]
    if not ch and not fr:
        return _r("todo", [], "")
    blockers = []
    L = c.get("ledger") or {}
    pcs = L.get("SC_OUT", 0.0) - L.get("SC_BACK_GOOD", 0.0) - L.get("SC_BACK_REJECT_VENDOR", 0.0) - L.get("SC_BACK_REJECT_FACTORY", 0.0)
    if out_now:
        blockers.append(f"{len(out_now)} challan(s) still out at a subcontractor" + (f" ({pcs:g} pieces not back)." if pcs > 0 else "."))
    if not fr:
        blockers.append("No finishing receipt yet.")
    if blockers:
        return _r("doing", blockers, blockers[0], "subcontract")
    return _r("done")


def _s_pack(c: dict) -> dict:
    d = c["docs"]
    pl = _live(d.get("Packing List", []))
    fi = _live(d.get("Final Inspection", []))
    if not pl:
        return _r("todo", [], "")
    blockers = []
    if not any(int(p.get("docstatus") or 0) == 1 for p in pl):
        blockers.append("The packing list is not submitted.")
    rej = [f for f in fi if f.get("result") == "Rejected"]
    if rej:
        blockers.append("The final inspection was rejected.")
    elif not any(f.get("result") in ("Accepted", "Accepted with Concession") for f in fi):
        blockers.append("No accepted final inspection yet.")
    if blockers:
        return _r("blocked" if rej else "doing", blockers, blockers[0], "pack")
    return _r("done")


def _on_board(sh: dict) -> bool:
    return bool(sh.get("apparel_on_board_date")) or sh.get("apparel_ship_status") in ("On Board", "Arrived", "Delivered", "Closed")


def _s_ship(c: dict) -> dict:
    """Done = a delivery note submitted and a shipment on board (ORDER_TO_SHIP_PLAN section 8, S9 gate); the shipment itself is submitted by the wizard."""
    d = c["docs"]
    sh = _live(d.get("Shipment", []))
    dn = [x for x in _live(d.get("Delivery Note", [])) if int(x.get("docstatus") or 0) == 1]
    if not sh and not dn:
        return _r("todo", [], "")
    blockers = []
    if not sh:
        blockers.append("No shipment yet.")
    if not dn:
        blockers.append("No delivery note submitted yet.")
    if sh and not any(int(s.get("docstatus") or 0) == 1 for s in sh):
        blockers.append("The shipment is not submitted yet.")
    if sh and dn and not any(_on_board(s) for s in sh):
        blockers.append("Not on board yet: record the on-board date.")
    if not blockers:
        return _r("done")
    return _r("doing", blockers, blockers[0], "ship")


def _s_invoice(c: dict) -> dict:
    inv = [x for x in _live(c["docs"].get("Sales Invoice", [])) if int(x.get("docstatus") or 0) == 1]
    if not inv:
        return _r("todo", [], "")
    blockers = []
    due = [x for x in inv if _num(x.get("outstanding_amount")) > 0]
    overdue = [x for x in due if (_to_date(x.get("due_date")) or c["today"]) < c["today"]]
    if overdue:
        blockers.append(f"{len(overdue)} invoice(s) overdue.")
    if str(c["order"].get("status") or "") == "Closed" and not due:
        return _r("done")
    if due and not overdue:
        blockers.append(f"{len(due)} invoice(s) still unpaid.")
    return _r("doing", blockers, blockers[0] if blockers else "Close the order when the checklist is green.", "invoice")


_STEP_FN = {"confirm": _s_confirm, "allocate": _s_allocate, "tna": _s_tna, "samples": _s_samples, "materials": _s_materials,
            "cutsew": _s_cutsew, "subcontract": _s_subcontract, "pack": _s_pack, "ship": _s_ship, "invoice": _s_invoice}


# ───────────────────────── the order book ─────────────────────────

def order_book(be, limit: int = 60, q: str = "", only_open: bool = True) -> list[dict]:
    """Sales Orders with a chip per step. One batched read of the follow-on counts, not ``status`` per order."""
    filters: list = [["docstatus", "=", 1]]
    if only_open:
        filters.append(["status", "not in", ["Closed", "Cancelled", "Completed"]])
    rows = be.get_list("Sales Order", filters, ["name", "customer", "customer_name", "transaction_date", "delivery_date", "grand_total", "currency", "status", "per_delivered", "per_billed"],
                       order_by="transaction_date desc", limit=int(limit or 60))
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (str(r.get("name")) + " " + str(r.get("customer_name") or r.get("customer") or "")).lower()]
    names = [r["name"] for r in rows]
    have: dict[str, dict[str, int]] = {n: {} for n in names}
    probes = (("allocate", "Factory Allocation"), ("tna", "Order TNA"), ("samples", "Sample Approval"), ("cutsew", "Production Card"),
              ("pack", "Packing List"))
    errors: dict = {}
    for key, dt in probes:
        try:
            for part in _chunks(names):
                for r in be.get_list(dt, [["sales_order", "in", part], ["docstatus", "!=", 2]], ["sales_order"], limit=5000):
                    h = have.setdefault(r["sales_order"], {})
                    h[key] = h.get(key, 0) + 1
        except Exception as e:                             # noqa: BLE001
            errors[dt] = str(e)[:120]
    out = []
    for r in rows:
        h = have.get(r["name"], {})
        chips = {k: ("doing" if h.get(k) else "todo") for k, _ in probes}
        chips["confirm"] = "done"
        chips["ship"] = "done" if float(r.get("per_delivered") or 0) >= 100 else ("doing" if float(r.get("per_delivered") or 0) > 0 else "todo")
        chips["invoice"] = "done" if float(r.get("per_billed") or 0) >= 100 else ("doing" if float(r.get("per_billed") or 0) > 0 else "todo")
        out.append({**{k: r.get(k) for k in ("name", "customer", "customer_name", "transaction_date", "delivery_date", "grand_total", "currency", "status")},
                    "url": _erp.url_for("Sales Order", r["name"]), "chips": [{"key": k, "label": lbl, "state": chips.get(k, "todo")} for k, lbl in STEPS
                                                                           if k in chips]})
    return out
