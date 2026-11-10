"""Field ownership (TNA plan section 4.3): a field has exactly one owner, and one module is the only writer of the tower's fields.

``tna_plan.py`` is that module; it writes only through the ERP script ``arinox_tna_apply_plan`` and ``arinox_order_tna_lock_baseline``
(the pipeline's own rules and audit apply). ``check`` is the per-field allowlist; a test fails if any other module writes a TNA doctype.
"""

from __future__ import annotations

#: field -> who owns it. "tower" fields are written by tna_plan.py; "erp" fields by the ERP's own hooks / the factory's documents;
#: "person" fields by a human through the tower UI (still through tna_plan.py); "shared" fields are set at creation and then adopted.
OWNER = {
    "Order TNA": {
        "sales_order": "erp", "style_item": "erp", "colour": "erp", "order_qty": "erp", "customer": "erp", "company": "erp", "style_no": "erp",
        "template": "shared", "order_received_date": "shared", "pcd": "shared", "ex_factory_date": "shared", "factory": "shared",
        "plan_feasible": "tower", "feasibility_note": "tower", "critical_delay_days": "tower",
        "baseline_locked": "person", "status": "tower",
    },
    "TNA Milestone": {
        "order_tna": "erp", "milestone_type": "tower", "sequence": "tower", "label": "tower", "department": "tower", "is_critical": "tower", "not_applicable": "tower",
        "planned_start": "tower", "planned_date": "tower",                        # tower, until baseline_locked; never afterwards
        "revised_date": "tower", "revision_reason": "tower",
        "actual_date": "erp", "partial": "erp",                                   # ERP evidence, or a person through the manual path
        "status": "tower", "delay_days": "tower", "progress": "tower", "color": "tower",
        "delay_reason_category": "person", "owner_user": "person",
    },
}
#: the fields the tower's single writer may send (the apply script's own parameters)
TOWER_WRITES = {"TNA Milestone": {"milestone_type", "sequence", "is_critical", "planned_start", "planned_date", "revised_date", "revision_reason"},
                "Order TNA": {"plan_feasible", "feasibility_note", "critical_delay_days", "baseline_locked"}}


def check(doctype: str, fields, locked: bool = False) -> None:
    """Raise ``PermissionError`` for a field the tower may not write (not in the allowlist, or a planned date after the lock)."""
    allowed = TOWER_WRITES.get(doctype, set())
    for f in fields:
        if f not in allowed:
            raise PermissionError(f"{doctype}.{f} is not a field the T&A writer may send")
        if locked and doctype == "TNA Milestone" and f in ("planned_start", "planned_date"):
            raise PermissionError("The baseline is locked: use the revised date with a reason")
