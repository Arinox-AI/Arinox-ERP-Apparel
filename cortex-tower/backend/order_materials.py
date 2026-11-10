"""Order page step 5, Materials (ORDER_TO_SHIP_PLAN section 4): requisition -> purchase order -> (receipt in the ERP) -> inspection, and the material status table.

Same rules as ``order_samples``: reads run the vendored scripts in record mode; every write goes through ``deals._ex`` (pipeline, preview first). Making
purchase orders is a risky class (``guardrails.RISKY_API``) and comes back as ``needs_approval`` until a manager approves it. The Purchase Receipt itself
is made in the ERP (it posts stock); the tower reads it and inspects it.

``order_materials_get`` runs the ERP's own **Material Status** script report (``lib_material_status.line_status``): the status of each requisition line is
never recomputed here. Only the comparison with the PCD (ETA vs PCD) is the tower's, and it is arithmetic on two dates.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Callable

import cortex_api
import deal_api
import deals
import guardrails
import order_flow
import pipeline
from order_samples import _ex, _ok, clean, groups, need, read_script
from tsr import reports as tsr_reports

guarded = deal_api.guarded

KINDS = {
    "fabric": {"dt": "Fabric Requisition", "type": "FR", "lines": "arinox_fabric_requisition_get_lines_from_sales_orders", "save": "arinox_fabric_requisition_save_fabric_requisition",
               "revise": "arinox_fabric_requisition_revise_fabric_requisition", "items": "arinox_fabric_requisition_create_fabric_items", "insp": "Fabric Inspection",
               "make_insp": "arinox_fabric_inspection_make_inspection", "item_field": "fabric_item", "label": "Fabric"},
    "trim": {"dt": "Trim Requisition", "type": "TR", "lines": "arinox_trim_requisition_get_lines_from_sales_orders", "save": "arinox_trim_requisition_save_trim_requisition",
             "revise": "arinox_trim_requisition_revise_trim_requisition", "items": "arinox_trim_requisition_create_trim_items", "insp": "Trim Inspection",
             "make_insp": "arinox_trim_inspection_make_inspection", "item_field": "trim_item", "label": "Trim"},
}
#: the quantity field that must be above zero for a requisition row to be sent (a zero-quantity row is never sent)
QTY_FIELD = {"fabric": "garment_qty", "trim": "garment_qty"}


def _kind(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError("kind is fabric or trim")
    return KINDS[kind]


def _day(v):
    try:
        return _dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _pcds(be, chain: list) -> dict:
    """PCD per (style, colour) from the saved allocation (its lines carry the PCD); `""` key = the earliest PCD of the order."""
    out: dict = {}
    fa = be.get_list("Factory Allocation", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["name"], limit=1)
    if not fa:
        return out
    for ln in be.get_list("Factory Allocation Line", [["parent", "=", fa[0]["name"]]], ["style_item", "style_no", "colour", "pcd"], limit=500, parent="Factory Allocation"):
        d = _day(ln.get("pcd"))
        if not d:
            continue
        for sty in {ln.get("style_item"), ln.get("style_no")} - {None, ""}:
            k = (sty, (ln.get("colour") or "").strip().upper())
            out[k] = min(out.get(k, d), d)
        out[""] = min(out.get("", d), d)
    return out


def material_table(rows: list[dict], pcds: dict, today: _dt.date) -> list[dict]:
    """One row per requisition line: required / ordered / received / passed / short, and ETA against the PCD in a sentence."""
    out = []
    for r in rows:
        net, acc = float(r.get("net") or 0), float(r.get("accepted") or 0)
        key = ((r.get("style_no") or ""), (r.get("colour") or "").strip().upper())
        pcd = pcds.get(key) or pcds.get("")
        eta = _day(r.get("eta")) or _day(r.get("etd_revised")) or _day(r.get("etd_planned"))
        passed = r.get("status") == "Accepted"
        note, late = "", False
        if pcd and not passed:
            if eta and eta > pcd:
                late, note = True, f"ETA {eta.isoformat()} is {(eta - pcd).days} day(s) after the PCD {pcd.isoformat()}."
            elif eta:
                note = f"ETA {eta.isoformat()} is {(pcd - eta).days} day(s) before the PCD {pcd.isoformat()}."
            elif pcd < today:
                late, note = True, f"The PCD {pcd.isoformat()} has passed and the material is not accepted."
            else:
                note = f"No ETA yet; the PCD is {pcd.isoformat()}."
        out.append({"type": r.get("type"), "requisition": r.get("requisition"), "style_no": r.get("style_no"), "colour": r.get("colour"), "item": r.get("item"),
                    "supplier": r.get("supplier"), "required": net, "ordered": float(r.get("ordered") or 0), "received": float(r.get("received") or 0), "passed": acc,
                    "in_qc": float(r.get("in_inspection") or 0), "rejected": float(r.get("rejected") or 0), "short": max(net - acc, 0.0), "status": r.get("status"),
                    "po": r.get("po"), "eta": str(eta or ""), "required_by": str(r.get("required_by") or ""), "pcd": str(pcd or ""), "late": late, "note": note, "in_house": float(r.get("received") or 0) > 0,
                    "passed_all": passed})
    return out


def _requisitions(be, chain: list) -> list[dict]:
    out = []
    for kind, k in KINDS.items():
        names: list = []
        for c in be.get_list(k["dt"] + " Item", [["sales_order", "in", chain]], ["parent"], limit=2000, parent=k["dt"]):
            if c.get("parent") and c["parent"] not in names:
                names.append(c["parent"])
        if names:
            for r in be.get_list(k["dt"], [["name", "in", names], ["docstatus", "!=", 2]], ["name", "status", "docstatus", "revision_no"], limit=200):
                out.append({"kind": kind, "name": r["name"], "status": r.get("status"), "docstatus": int(r.get("docstatus") or 0), "revision_no": r.get("revision_no") or 0,
                            "can_order": int(r.get("docstatus") or 0) == 1 and r.get("status") in ("Approved", "Partly Ordered")})
    return sorted(out, key=lambda r: (r["kind"], r["name"]))


def _receipts(be, chain: list, kinds: dict) -> list[dict]:
    """The Purchase Receipt rows of the order with their inspection: what can be done next to each (import rolls, make the inspection, submit it)."""
    rows = be.get_list("Purchase Receipt Item", [["sales_order", "in", chain]], ["name", "parent", "item_code", "qty"], limit=1000, parent="Purchase Receipt")
    if not rows:
        return []
    prs = {r["name"]: r for r in be.get_list("Purchase Receipt", [["name", "in", sorted({r["parent"] for r in rows})]], ["name", "docstatus", "supplier"], limit=500)}
    insp: dict = {}
    for dt in ("Fabric Inspection", "Trim Inspection"):
        for i in be.get_list(dt, [["purchase_receipt", "in", sorted(prs)], ["docstatus", "!=", 2]], ["name", "purchase_receipt", "purchase_receipt_item", "docstatus", "lot_result" if dt == "Fabric Inspection" else "result"], limit=500):
            insp[(i["purchase_receipt"], i.get("purchase_receipt_item"))] = {"name": i["name"], "docstatus": int(i.get("docstatus") or 0), "result": i.get("lot_result") or i.get("result") or "",
                                                                                "kind": "fabric" if dt == "Fabric Inspection" else "trim"}
    out = []
    for r in rows:
        pr = prs.get(r["parent"]) or {}
        kind = kinds.get(r.get("item_code")) or "fabric"
        i = insp.get((r["parent"], r["name"]))
        out.append({"purchase_receipt": r["parent"], "row_name": r["name"], "item": r.get("item_code"), "qty": float(r.get("qty") or 0), "docstatus": int(pr.get("docstatus") or 0),
                    "supplier": pr.get("supplier"), "kind": (i or {}).get("kind") or kind, "inspection": i,
                    "can_import_rolls": int(pr.get("docstatus") or 0) == 0 and kind == "fabric", "can_inspect": int(pr.get("docstatus") or 0) == 1 and not i})
    return sorted(out, key=lambda r: (r["purchase_receipt"], r["row_name"]))


@guarded
def order_materials_get(db, me, sales_order: str = "", **_):
    """The material status table of one order, from the ERP's **Material Status** report (so its status words are the ERP's): per requisition line what is
    required, ordered, received, passed (accepted by inspection) and short, with the ETA set against the PCD, and a summary (all passed, any late). Also
    which styles have no requisition yet, the requisitions with what can be done next, and the receipt rows with their inspection. Read only. Params: `sales_order`. Returns `{ok, head, rows, summary, no_requisition, requisitions, receipts}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Fabric Requisition", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    rows: list[dict] = []
    for so in chain:
        res = tsr_reports.run(cortex_api._reg(), pipeline.engine(), be, "Material Status", {"sales_order": so}, user=me["email"])
        rows += res.get("rows") or []
    today = _dt.date.today()
    table = material_table(rows, _pcds(be, chain), today)
    have = {(r["style_no"] or "").strip() for r in table}
    sod = be.get_doc("Sales Order", head)
    no_req = sorted({g["style_item"] for g in groups(be, sod)} - have) if table else sorted({g["style_item"] for g in groups(be, sod)})
    can = bool(set(me["roles"]) & (set(guardrails.WRITE["materials"]) | set(guardrails.ALL_POWER)))
    kinds = {r["item"]: ("fabric" if r["type"] == "FR" else "trim") for r in table if r.get("item")}
    return {"ok": True, "head": head, "rows": table, "no_requisition": no_req, "can_write": can, "requisitions": _requisitions(be, chain), "receipts": _receipts(be, chain, kinds),
            "summary": {"lines": len(table), "passed": sum(1 for r in table if r["passed_all"]), "late": sum(1 for r in table if r["late"]),
                        "short": round(sum(r["short"] for r in table), 2), "all_passed": bool(table) and all(r["passed_all"] for r in table),
                        "all_in_house_before_pcd": bool(table) and all(r["passed_all"] and not r["late"] for r in table)}}


@guarded
def order_req_lines(db, me, sales_order: str = "", kind: str = "fabric", **_):
    """The requisition lines the ERP proposes for the order (one per style x colour x material of the Tech Pack, quantities from the Sales Order), through
    `arinox_fabric_requisition_get_lines_from_sales_orders` or the trim equivalent. Read only: nothing is saved until `order_req_save`. Params:
    `sales_order`, `kind` (fabric or trim). Returns `{ok, kind, customer, company, items}`."""
    k = _kind(kind)
    need(me, "materials", "raise a requisition")
    be = deals._be()
    _chain, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    out = read_script(me, k["lines"], {"doc": json.dumps({"customer": so.get("customer"), "company": so.get("company"), "items": []}), "sales_orders": json.dumps([head])}) or {}
    return {"ok": True, "kind": kind, "head": head, "customer": so.get("customer"), "company": so.get("company"), "items": (out.get("arinox_doc") or {}).get("items") or [],
            "count": out.get("count", 0)}


@guarded
def order_items_create(db, me, kind: str = "fabric", items: list | None = None, preview: bool = False, **_):
    """Make the ERP items (the style of fabric or trim and its colour variant) for the rows that have none, through
    `arinox_fabric_requisition_create_fabric_items` / `arinox_trim_requisition_create_trim_items`. Returns the rows with their item codes. Params: `kind`, `items`, `preview`."""
    k = _kind(kind)
    need(me, "materials", "make material items")
    rows = clean(items or [])
    if not rows:
        return {"ok": False, "error": "There are no rows."}
    res = _ex(db, me, {"op": "api", "method": k["items"], "doctype": k["dt"], "params": {"doc": json.dumps({"items": rows}, default=str)}}, preview, "the items")
    if not res.get("ok"):
        return res
    r = res.get("result") if isinstance(res.get("result"), dict) else {}
    return {"ok": True, "items": (r.get("arinox_doc") or {}).get("items") or [], "made": r.get("made") or [], "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_req_save(db, me, sales_order: str = "", kind: str = "fabric", items: list | None = None, name: str = "", preview: bool = False, **_):
    """Save a DRAFT requisition through the ERP's script (`arinox_fabric_requisition_save_fabric_requisition` / trim): its validation runs (width, GSM, the
    source of the consumption, the supplier, the allowance). Rows with no garment quantity are never sent. Never submits (see `order_req_approve`).
    Params: `sales_order`, `kind`, `items`, `name` (to update a draft), `preview`. Returns `{ok, name}`."""
    k = _kind(kind)
    need(me, "materials", "raise a requisition")
    be = deals._be()
    _c, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    rows = []
    for it in items or []:
        try:
            q = float(it.get(QTY_FIELD[kind]) or 0)
        except (TypeError, ValueError):
            q = 0
        if q > 0:
            rows.append(clean(it))
    if not rows:
        return {"ok": False, "error": "There is nothing to save: every row has no quantity."}
    data = {"company": so.get("company"), "customer": so.get("customer"), "items": rows}
    if name:
        data["name"] = name
    res = _ex(db, me, {"op": "api", "method": k["save"], "doctype": k["dt"], "params": {"data": json.dumps(data, default=str)}}, preview, "the requisition")
    if not res.get("ok"):
        return res
    nm = res.get("result")
    return {"ok": True, "name": nm if isinstance(nm, str) else name, "rows": len(rows), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_req_approve(db, me, kind: str = "fabric", name: str = "", preview: bool = False, **_):
    """Approve (submit) a requisition. The ERP then makes the Material Requests that the purchase orders are made from. Purchase role or a manager.
    Params: `kind`, `name`, `preview`. Returns `{ok, name}`."""
    k = _kind(kind)
    need(me, "materials", "approve a requisition")
    if not name:
        return {"ok": False, "error": "Say which requisition."}
    return _ok(_ex(db, me, {"op": "submit", "doctype": k["dt"], "name": name}, preview, "the approval"), name, preview)


@guarded
def order_req_revise(db, me, kind: str = "fabric", name: str = "", reason: str = "", preview: bool = False, **_):
    """Revise an approved requisition: the ERP makes a new draft revision (quantities refreshed from the order; only the increase is requested again when it
    is submitted). A reason is required. Params: `kind`, `name`, `reason`, `preview`. Returns `{ok, name}`."""
    k = _kind(kind)
    need(me, "materials", "revise a requisition")
    if not (reason or "").strip():
        return {"ok": False, "error": "Say why the requisition is revised."}
    doc = read_script(me, k["revise"], {"source_name": name}) or {}
    data = clean(doc)
    data["revision_reason"] = reason.strip()
    res = _ex(db, me, {"op": "insert", "doctype": k["dt"], "data": data}, preview, "the revision")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": (res.get("doc") or {}).get("name") or "", "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_po_make(db, me, kind: str = "fabric", name: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Make draft Purchase Orders from an approved requisition, one per supplier, for the lines not yet ordered (`arinox_purchase_order_make_purchase_orders`).
    This is a risky class: the answer is `needs_approval` with an `approval_id` until a manager approves it; run it again with that `approval_id`. Params:
    `kind`, `name`, `preview`, `approval_id`. Returns `{ok, made:[PO names]}` or `{ok: false, needs_approval: true, approval_id}`."""
    k = _kind(kind)
    need(me, "materials", "order material")
    if not name:
        return {"ok": False, "error": "Say which requisition."}
    res = deals._ex(db, me, {"op": "api", "method": "arinox_purchase_order_make_purchase_orders", "doctype": "Purchase Order", "preview": bool(preview),
                             "approval_id": approval_id or None, "params": {"requisition_type": k["type"], "name": name}})
    if res.get("needs_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": res.get("approval_id"), "error": res.get("error"), "preview": res.get("preview")}
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the purchase orders.")), "preview": res.get("preview")}
    made = res.get("result")
    return {"ok": True, "made": made if isinstance(made, list) else [], "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_rolls_import(db, me, purchase_receipt: str = "", row_name: str = "", rolls: list | str | None = None, length_uom: str = "Meter", update_row_qty: bool = False,
                       preview: bool = False, **_):
    """Import a roll list into one row of a DRAFT Purchase Receipt (`arinox_rolls_import_roll_list`): one batch per roll and the bundle. `rolls` is a list of
    `{roll_no, dye_lot, length, width_cm}` or pasted text (`roll no, dye lot, length` per line). The roll total must equal the row quantity unless
    `update_row_qty`. Params: `purchase_receipt`, `row_name`, `rolls`, `length_uom`, `update_row_qty`, `preview`. Returns `{ok, rolls, total}`."""
    need(me, "materials", "import rolls")
    if not purchase_receipt or not row_name or not rolls:
        return {"ok": False, "error": "Say which receipt, which row and give the roll list."}
    res = _ex(db, me, {"op": "api", "method": "arinox_rolls_import_roll_list", "doctype": "Purchase Receipt",
                       "params": {"pr_name": purchase_receipt, "row_name": row_name, "rolls": rolls if isinstance(rolls, str) else json.dumps(rolls), "length_uom": length_uom,
                                  "update_row_qty": 1 if update_row_qty else 0}}, preview, "the roll list")
    if not res.get("ok"):
        return res
    r = res.get("result") if isinstance(res.get("result"), dict) else {}
    return {"ok": True, "rolls": r.get("rolls"), "total": r.get("total"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_inspection_make(db, me, kind: str = "fabric", purchase_receipt: str = "", purchase_receipt_item: str = "", preview: bool = False, **_):
    """Make the inspection of one received Purchase Receipt row: the ERP's script builds it (a fabric one comes with a line per roll), then it is saved as a
    draft through the pipeline. The Purchase Receipt must be submitted. Params: `kind`, `purchase_receipt`, `purchase_receipt_item`, `preview`. Returns `{ok, name}`."""
    k = _kind(kind)
    need(me, "inspection", "make an inspection")
    if not purchase_receipt or not purchase_receipt_item:
        return {"ok": False, "error": "Say which receipt and which row."}
    try:
        doc = read_script(me, k["make_insp"], {"purchase_receipt": purchase_receipt, "purchase_receipt_item": purchase_receipt_item}) or {}
    except Exception as e:                                  # noqa: BLE001 - the script's own sentence ("... is not submitted")
        return {"ok": False, "error": deals._strip_html(str(getattr(e, "message", None) or e))[:300]}
    res = _ex(db, me, {"op": "insert", "doctype": k["insp"], "data": clean(doc)}, preview, "the inspection")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": (res.get("doc") or {}).get("name") or "", "rolls": len((res.get("doc") or {}).get("rolls") or []), "preview": res.get("preview") if preview else None,
            "saved": not preview}


@guarded
def order_inspection_submit(db, me, kind: str = "fabric", name: str = "", preview: bool = False, **_):
    """Submit a drafted inspection: the ERP works out the lot result and moves the accepted quantity to store (and the rejected to the rejected warehouse).
    After a real submit the requisition's passed quantity is recomputed (`arinox_fabric_requisition_refresh_quantities`), because the
    ERP's after-submit rule computes it on a read made before the submit; `warnings` carries anything the ERP said that needs setup. Role: QC or a manager.
    Params: `kind`, `name`, `preview`. Returns `{ok, name, refreshed, warnings}`."""
    k = _kind(kind)
    if not set(me["roles"]) & (set(guardrails.SUBMIT["inspection"]) | set(guardrails.ALL_POWER)):
        raise guardrails.Denied("Your role cannot submit an inspection. Ask QC or a manager.")
    if not name:
        return {"ok": False, "error": "Say which inspection."}
    res = _ex(db, me, {"op": "submit", "doctype": k["insp"], "name": name}, preview, "the inspection")
    if not res.get("ok") or preview:
        return _ok(res, name, preview)
    out = {"ok": True, "name": name, "saved": True, "preview": None, "warnings": [m.get("message") for m in res.get("messages") or [] if m.get("indicator") == "orange"]}
    # the ERP's after-submit rule computes the requisition's passed quantity on a read made before this submit; recompute it now that the inspection is saved
    try:
        d = deals._be().get_doc(k["insp"], name)
        req = d.get("fabric_requisition") or d.get("trim_requisition")
        if req:
            r2 = deals._ex(db, me, {"op": "api", "method": "arinox_fabric_requisition_refresh_quantities", "doctype": k["insp"], "params": {"requisition_type": k["type"], "name": req}})
            out["refreshed"] = bool(r2.get("ok"))
            if not r2.get("ok"):
                out["warnings"].append("The requisition quantities could not be refreshed: " + deals._strip_html(str(r2.get("error") or ""))[:200])
    except Exception as e:                                  # noqa: BLE001 - the inspection itself is saved; say what did not follow
        out["warnings"].append(f"The requisition quantities could not be refreshed: {str(e)[:160]}")
    return out


FUNCTIONS: dict[str, Callable] = {"order_materials_get": order_materials_get, "order_req_lines": order_req_lines, "order_items_create": order_items_create,
                                  "order_req_save": order_req_save, "order_req_approve": order_req_approve, "order_req_revise": order_req_revise, "order_po_make": order_po_make,
                                  "order_rolls_import": order_rolls_import, "order_inspection_make": order_inspection_make, "order_inspection_submit": order_inspection_submit}
