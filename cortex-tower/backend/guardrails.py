"""Guardrails: who may do what to which document, what a field may be set to, and how risky an operation is.

Data, not code, decides the matrix (``guardrails.json`` next to this file overrides the defaults below), so the
client can tighten it without a release. Everything is checked **server-side** on every function — the UI hiding
a button is a courtesy, not a control.

Never looser than the ERP: the defaults mirror the Arinox role permissions of the bundle (``03_doctypes.json``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))

ROLES = ["Merchandiser", "Costing", "Sampling", "Planner", "Purchase", "QC", "Production", "Shipping", "Accounts",
         "Management", "Admin"]

# doctype -> group
GROUP = {}
for _g, _dts in {
    "enquire": ["Opportunity", "Tech Pack", "Tech Pack Colour", "Tech Pack Material", "Tech Pack Measurement", "Price Negotiation",
                "Quotation", "Lead", "Customer"],
    "costing": ["Cost Sheet", "Costing Parameter", "Cost Head"],
    "win": ["Sales Contract", "Sales Contract Template", "Sales Order", "Item"],
    "plan": ["Factory Allocation", "Sample Approval", "PP Meeting", "Order TNA", "TNA Milestone", "TNA Template"],
    "materials": ["Fabric Requisition", "Trim Requisition", "Purchase Order", "Material Request", "Purchase Receipt",
                  "Supplier", "Supplier Quotation"],
    "inspection": ["Fabric Inspection", "Trim Inspection", "Final Inspection", "Line QC Report", "AQL Plan", "Quality Inspection"],
    "make": ["Production Card", "Cut Plan", "Lay Report", "Cut Bundle", "Daily Line Report", "Line Input", "Operation Bulletin",
             "Pilot Run", "Recut Request", "Production Adjustment", "Subcontract Challan", "Subcontract Return",
             "Subcontract Settlement", "Finishing Receipt", "Work Order", "Needle Detector Log"],
    "pack": ["Packing List"],
    "ship": ["Shipment", "Delivery Note", "Letter of Credit", "Shipment Declaration", "Shipment Filing"],
    "accounts": ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Payment Request", "Buyer Claim"],
    "settings": ["Apparel Settings", "Apparel Sample Rule", "Traffic Light Rule", "Destination Filing Rule"],
    # 2026-11-07: every Arinox doctype now has a home (14 fell through to "make" before)
    "masters": ["Product Type", "Size Chart", "Trim Category", "Carton Type", "Apparel Defect Code", "Fabric Defect Code",
                "Trim Defect Type", "TNA Milestone Type", "Subcontract Process", "Production Check Item",
                "Material Allowance Rule", "Material Purchase Terms", "Sample Requirement", "Trim Sampling Plan",
                "Arinox Number", "Production Movement", "Item Price", "UOM", "Warehouse", "Brand", "Item Group",
                "Contact", "Address"],
    "work": ["Task", "ToDo", "Project", "Comment", "Event", "Note"],
}.items():
    for _d in _dts:
        GROUP[_d] = _g

# group -> roles that may create/edit (Management and Admin may do everything, added below)
WRITE = {
    "enquire": ["Merchandiser", "Costing"],
    "costing": ["Costing", "Merchandiser"],
    "win": ["Merchandiser"],
    "plan": ["Planner", "Sampling", "Merchandiser"],
    "materials": ["Purchase", "Merchandiser", "Planner"],
    "inspection": ["QC"],
    "make": ["Production", "Planner"],
    "pack": ["Shipping", "QC"],
    "ship": ["Shipping"],
    "accounts": ["Accounts"],
    "settings": [],
    "masters": ["Merchandiser", "Costing", "Planner", "Purchase", "QC"],
    "work": ROLES[:-2],
    "other": [],
}
# group -> roles that may submit / cancel (cancel is always at least this strict)
SUBMIT = {
    "enquire": ["Merchandiser"], "costing": ["Costing"], "win": ["Merchandiser"], "plan": ["Planner", "Sampling"],
    "materials": ["Purchase"], "inspection": ["QC"], "make": ["Production"], "pack": ["Shipping", "QC"],
    "ship": ["Shipping"], "accounts": ["Accounts"], "settings": [], "masters": [], "work": ROLES[:-2], "other": [],
}
# read is open to every signed-in role EXCEPT these groups
READ_RESTRICTED = {"accounts": ["Accounts", "Management", "Admin", "Shipping", "Merchandiser", "Costing"],
                   "costing": ["Costing", "Management", "Admin", "Merchandiser", "Accounts"],
                   "settings": ["Management", "Admin"]}
ALL_POWER = ["Management", "Admin"]

# submitting or cancelling these posts ledger entries (stock / GL / production) -> approval class "risky"
LEDGER_DOCTYPES = {"Sales Invoice", "Purchase Invoice", "Delivery Note", "Stock Entry", "Purchase Receipt", "Payment Entry",
                   "Packing List", "Lay Report", "Daily Line Report", "Production Adjustment", "Subcontract Return",
                   "Subcontract Challan", "Finishing Receipt", "Line Input", "Shipment"}
RISKY_API = re.compile(r"(make_delivery_notes|invoicing_submit|commercial_close|ledger_rebuild|settlement_make_invoices|"
                       r"credit_note|short_close|api_close|scripts_switch|issue_fabric|make_purchase_orders)")
DENY_FIELDS = {"owner", "creation", "modified", "modified_by", "amended_from", "naming_series", "arinox_name", "idx",
               "parent", "parenttype", "parentfield"}
NON_NEGATIVE = re.compile(r"(^|_)(qty|quantity|rate|price|amount|pcs|pieces|consumption|wastage)(_|$)")

#: callers that must be signed in by an administrator, never delegated.
ADMIN_ONLY_FUNCTIONS = {"tsr_set_script", "tsr_kill_switch", "set_tower_user", "set_write_mode", "install_webhooks"}


def _override() -> dict:
    p = os.path.join(HERE, "guardrails.json")
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def _roles_for(table: dict, group: str, name: str) -> set:
    o = _override().get(name, {})
    return set(o.get(group, table.get(group, []))) | set(ALL_POWER)


GROUP.setdefault("BOM", "materials")


def group_of(doctype: str) -> str:
    # An unknown doctype is readable by every role and changeable only by Management/Admin. (It used
    # to fall into "make", which let a Production user edit any doctype the tower had never heard of.)
    return GROUP.get(doctype, "other")


class Denied(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def can(user_roles: list[str], doctype: str, perm: str) -> bool:
    roles = set(user_roles or [])
    if roles & {"Admin"}:
        return True
    g = group_of(doctype)
    if perm == "read":
        allowed = set(_override().get("read_restricted", READ_RESTRICTED).get(g, [])) or None
        return True if allowed is None else bool(roles & (allowed | set(ALL_POWER)))
    if perm in ("create", "write"):
        return bool(roles & _roles_for(WRITE, g, "write"))
    if perm in ("submit", "cancel"):
        return bool(roles & _roles_for(SUBMIT, g, "submit"))
    if perm == "delete":
        return bool(roles & set(ALL_POWER))      # only Management/Admin delete, always
    return False


def require(user_roles: list[str], doctype: str, perm: str, name: Optional[str] = None):
    if not can(user_roles, doctype, perm):
        raise Denied(f"Your role does not allow you to {perm} {doctype}"
                     + (f" {name}" if name else "") + ". Ask a manager if you need this.")


def classify(op: str, doctype: str = "", method: str = "") -> str:
    """safe | draft | risky — drives the mode gate and whether an approval is needed."""
    if op == "api":
        return "risky" if RISKY_API.search(method or "") else "draft"
    if op in ("cancel", "delete"):
        return "risky"
    if op == "submit":
        return "risky" if doctype in LEDGER_DOCTYPES else "draft"
    if doctype in ("Comment", "ToDo", "Task"):
        return "safe"
    return "draft"


MODE_FOR_CLASS = {"safe": "safe", "draft": "draft", "risky": "all"}


def check_fields(doctype: str, data: dict, existing: Optional[dict] = None) -> list[str]:
    """Problems with the values a caller wants to write. Empty list = fine."""
    problems = []
    for k, v in (data or {}).items():
        if k in DENY_FIELDS:
            problems.append(f"{k} cannot be set from the tower")
        if k == "docstatus" and (existing is None or v != existing.get("docstatus")):
            problems.append("docstatus changes only through Submit / Cancel")
        if NON_NEGATIVE.search(k) and isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            problems.append(f"{k} cannot be negative")
        if isinstance(v, str) and re.search(r"(^|_)(date|etd|eta|pcd)$", k) and v:
            if not re.match(r"^\d{4}-\d{2}-\d{2}", v):
                problems.append(f"{k} must be a date like 2026-12-31")
        if isinstance(v, list):
            for i, row in enumerate(v):
                if isinstance(row, dict):
                    for p in check_fields(doctype, {a: b for a, b in row.items() if a not in DENY_FIELDS}, None):
                        problems.append(f"{k} row {i + 1}: {p}")
    return problems
