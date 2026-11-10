"""The read side of the generic record workspace: meta, lists, one document, link search, global search.

All reads are role-filtered (``guardrails.can(..., "read")``) and field-filtered (``permlevel`` > 0 only for
managers). The frontend never sees an ERP URL — it asks the tower, the tower asks the ERP.
"""

from __future__ import annotations

import re
from typing import Optional

import guardrails
from tsr.errors import TSRNotFound

LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold"}
SEARCH_DOCTYPES = ["Sales Order", "Sales Contract", "Opportunity", "Tech Pack", "Cost Sheet", "Production Card", "Shipment",
                   "Customer", "Item", "Purchase Order", "Packing List", "Sales Invoice",
                   # 2026-11-07: the rest of the order flow (search used to stop at 12 doctypes)
                   "Order TNA", "Quotation", "Price Negotiation", "Factory Allocation", "Sample Approval", "PP Meeting",
                   "Fabric Requisition", "Trim Requisition", "Fabric Inspection", "Trim Inspection", "Final Inspection",
                   "Cut Plan", "Lay Report", "Daily Line Report", "Subcontract Challan", "Finishing Receipt",
                   "Delivery Note", "Letter of Credit", "Buyer Claim", "Supplier", "Purchase Receipt"]
STATUS_FIELDS = ("status", "workflow_state")
POWER = set(guardrails.ALL_POWER)


def _visible(f: dict, roles: list[str]) -> bool:
    if f.get("hidden"):
        return False
    return (f.get("permlevel") or 0) == 0 or bool(set(roles) & POWER)


def ui_meta(backend, doctype: str, roles: list[str]) -> dict:
    m = backend.meta(doctype)
    fields = []
    for f in m["fields"]:
        if f["fieldtype"] in LAYOUT or not _visible(f, roles):
            continue
        item = {k: f.get(k) for k in ("fieldname", "label", "fieldtype", "options", "reqd", "read_only", "in_list_view",
                                       "depends_on", "allow_on_submit", "default")}
        if f["fieldtype"] in ("Table", "Table MultiSelect") and f.get("options"):
            try:
                cm = backend.meta(f["options"])
                item["columns"] = [{k: c.get(k) for k in ("fieldname", "label", "fieldtype", "options", "reqd", "read_only", "in_list_view")}
                                   for c in cm["fields"] if c["fieldtype"] not in LAYOUT and _visible(c, roles) and not c.get("hidden")]
            except Exception:
                item["columns"] = []
        fields.append(item)
    return {"doctype": doctype, "is_submittable": m["is_submittable"], "issingle": m["issingle"],
            "numbered": bool(m.get("autoname") and "arinox_name" in str(m.get("autoname"))), "fields": fields}


def list_docs(backend, doctype: str, roles: list[str], search: str = "", filters: Optional[list] = None, page: int = 1,
              page_size: int = 25, order_by: str = "modified desc", status: str = "") -> dict:
    guardrails.require(roles, doctype, "read")
    m = backend.meta(doctype)
    cols = [f["fieldname"] for f in m["fields"] if f.get("in_list_view") and f["fieldtype"] not in LAYOUT
            and _visible(f, roles) and f["fieldtype"] not in ("Table", "Text Editor", "Long Text")][:7]
    want = ["name", "modified", "docstatus"] + [c for c in cols if c not in ("name", "modified", "docstatus")]
    if "status" in {f["fieldname"] for f in m["fields"]} and "status" not in want:
        want.append("status")
    flt: list = list(filters or [])
    if status and "status" in want:
        flt.append(["status", "=", status])
    if not re.match(r"^[a-z_ ]+( (asc|desc))?$", order_by or ""):
        order_by = "modified desc"
    page = max(1, int(page))
    size = max(1, min(100, int(page_size)))
    if search:
        s = f"%{search}%"
        title = m.get("title_field") if isinstance(m.get("title_field"), str) else None
        rows_by_name = backend.get_list(doctype, flt + [["name", "like", s]], want, order_by=order_by, limit=size * page)
        rows = rows_by_name
        if title and title in want and len(rows) < size * page:
            more = backend.get_list(doctype, flt + [[title, "like", s]], want, order_by=order_by, limit=size * page)
            seen = {r["name"] for r in rows}
            rows += [r for r in more if r["name"] not in seen]
        total = len(rows)
        rows = rows[(page - 1) * size: page * size]
    else:
        total = backend.count(doctype, flt or None)
        rows = backend.get_list(doctype, flt or None, want, order_by=order_by, limit=size + (page - 1) * size)[(page - 1) * size:]
    labels = {f["fieldname"]: f.get("label") for f in m["fields"]}
    return {"doctype": doctype, "columns": [{"fieldname": c, "label": labels.get(c) or c} for c in want if c not in ("modified",)],
            "rows": rows, "total": total, "page": page, "page_size": size}


def get_doc(backend, registry, doctype: str, name: str, roles: list[str]) -> dict:
    guardrails.require(roles, doctype, "read", name)
    d = backend.get_doc(doctype, name)
    m = backend.meta(doctype)
    hidden = {f["fieldname"] for f in m["fields"] if not _visible(f, roles)}
    d = {k: v for k, v in d.items() if k not in hidden}
    slug = "arinox_" + doctype.lower().replace(" ", "_") + "_"
    actions = sorted({r["api_method"] for r in registry.by_name.values()
                      if r["script_type"] == "API" and (r.get("api_method") or "").startswith(slug)})
    return {"doc": d, "actions": actions, "can_write": guardrails.can(roles, doctype, "write"),
            "can_submit": guardrails.can(roles, doctype, "submit"), "can_cancel": guardrails.can(roles, doctype, "cancel")}


def link_search(backend, doctype: str, txt: str, roles: list[str], limit: int = 15) -> list[dict]:
    guardrails.require(roles, doctype, "read")
    s = f"%{txt}%"
    rows = backend.get_list(doctype, [["name", "like", s]], ["name"], limit=limit)
    m = backend.meta(doctype)
    tf = m.get("title_field") if isinstance(m.get("title_field"), str) else None
    if tf and len(rows) < limit:
        more = backend.get_list(doctype, [[tf, "like", s]], ["name", tf], limit=limit)
        seen = {r["name"] for r in rows}
        rows += [r for r in more if r["name"] not in seen]
    return [{"value": r["name"], "description": r.get(tf) if tf else ""} for r in rows[:limit]]


def global_search(backend, txt: str, roles: list[str], per: int = 4) -> list[dict]:
    """Name search across the order flow. The doctypes are asked in parallel (one slow or missing
    doctype never holds up the rest); results keep the SEARCH_DOCTYPES order."""
    from concurrent.futures import ThreadPoolExecutor
    wanted = [dt for dt in SEARCH_DOCTYPES if guardrails.can(roles, dt, "read")]

    def one(dt):
        try:
            return [{"doctype": dt, "name": r["name"]}
                    for r in backend.get_list(dt, [["name", "like", f"%{txt}%"]], ["name"], limit=per)]
        except TSRNotFound:
            return []
        except Exception:
            return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        found = list(ex.map(one, wanted))
    return [r for rows in found for r in rows]


def nav_counts(backend, items: list[dict], roles: list[str]) -> dict:
    """Open (draft) counts per doctype for the sidebar badges. Cheap COUNT calls, skipped on error."""
    out = {}
    for it in items:
        dt = it.get("doctype")
        if it.get("kind") != "doc" or not dt or not guardrails.can(roles, dt, "read"):
            continue
        try:
            out[it["key"]] = backend.count(dt, [["docstatus", "=", 0]])
        except Exception:
            continue
    return out
