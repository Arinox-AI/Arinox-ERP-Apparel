"""One vocabulary for the ERP and the tower (TNA plan section 5.3 and Appendix C). Pure data plus lookups.

Rule: where the ERP already has the concept, the ERP code wins; every other checkpoint of the tower's 61-milestone template is seeded
into ``TNA Milestone Type`` under its own tower code, so no two milestones of one plan share a type (the ERP stamps by
``order_tna`` + ``milestone_type``). Appendix C lists several tower codes against one ERP code (for example SEW_START, SEW_END and
FINISH_END all against BULK_FINISH). One type can carry only one of them, so the *finishing* checkpoint takes the ERP code and the
others keep their own code. Appendix C lists 22 new types; two tower codes (BULK_TRIM_RELEASE, PP_SAMPLE_SUB) have no entry in it
and are seeded too, and the checkpoints that share an ERP code in the Appendix are seeded as well.
"""

from __future__ import annotations

#: tower code -> ERP ``TNA Milestone Type`` code (the representative of each concept)
TOWER_TO_ERP = {
    "ORD_CONF": "ORDER_RECEIVED", "TECH_PACK": "TECH_PACK_RECEIVED", "BOM_APPROVAL": "BOM_RECEIVED", "WASH_STD_APPROVAL": "BULK_STANDARD_RECEIVED",
    "MARKER_APP": "MINI_MARKER", "FABRIC_BOOK": "FR_RAISED", "TRIMS_BOOK": "TR_RAISED", "FABRIC_PO": "FABRIC_BOOKED",
    "TRIM_CARD_APPROVAL": "TRIMS_APPROVED", "FIT_APPROVE": "FIT", "LABDIP_APP": "LAB_DIP", "BULK_FABRIC_RELEASE": "BULK_FABRIC_READY_MILL",
    "FABRIC_INHOUSE": "FABRIC_IN_HOUSE", "FABRIC_INSPECT": "FABRIC_QC_PASSED", "TRIMS_INHOUSE": "TRIMS_IN_HOUSE", "TRIMS_INSPECT": "TRIMS_QC_PASSED",
    "PP_SAMPLE_APP": "PP_GPT", "PP_MEETING": "PP_MEETING", "PILOT_RUN": "PILOT_RUN", "SIZE_SET": "TOP", "SEW_END": "BULK_FINISH",
    "WASH_RECV": "WASH_FINISHED", "PACK_END": "PACK_FINISHED", "FINAL_INSP": "FINAL_INSPECTION", "FORWARDER": "FREIGHT_BOOKING",
    "SHIP": "EX_FACTORY", "BL_AWB": "ON_BOARD", "DELIVERY": "IN_WAREHOUSE",
}
#: ERP types that are not tasks of the 61-milestone template but that the evidence table (section 8.1) and the ERP's own scripts use.
#: They join the plan as extra tasks so no evidence rule is dropped (D6).
ERP_ONLY_TASKS = {
    "FABRIC_ETD": {"name": "Bulk fabric ETD (supplier ship date)", "category": "Material", "owner_role": "Fabric Sourcing", "after": ["BULK_FABRIC_RELEASE"],
                   "before": ["FABRIC_INHOUSE"], "duration": 1, "calendar": "CN_FACTORY", "is_critical": True},
    "PCD": {"name": "PCD (production commencement, pinned)", "category": "Pre-production", "owner_role": "Merchandising Manager", "after": ["LINE_PLAN"],
            "before": ["CUT_START"], "duration": 0, "calendar": "VN_FACTORY", "is_critical": True, "pinned_anchor": True},
}
#: old tower code -> code to use now, so overlay rows and old URLs keep working (section 5.3 ``VOCAB_ALIASES``)
VOCAB_ALIASES = dict(TOWER_TO_ERP)
#: the Appendix C pairs that the "one type per milestone" rule split: they keep their tower code and are seeded as types
APPENDIX_C_SHARED = {"SEW_START": "BULK_FINISH", "FINISH_END": "BULK_FINISH", "WASH_SEND": "WASH_FINISHED", "WASH_TRIAL_APPROVAL": "WASH_FINISHED",
                     "PACK_START": "PACK_FINISHED", "QC_ENDLINE": "FINAL_INSPECTION", "SHIP_READY": "EX_FACTORY", "CARGO_HANDOVER": "ON_BOARD",
                     "LABDIP_SUB": "LAB_DIP"}
#: tower category -> ERP department (``TNA Milestone Type.department``)
DEPARTMENT = {"Order": "Merchandising", "Development": "Sampling", "Material": "Purchasing", "Pre-production": "Production", "Production": "Production",
              "Quality": "Quality", "Packing": "Production", "Logistics": "Shipping"}


def erp_code(tower_code: str) -> str:
    """The ``TNA Milestone Type`` code of a tower milestone (its own code when the ERP has no equivalent)."""
    return TOWER_TO_ERP.get(tower_code, tower_code)


def tower_code(code: str) -> str:
    """Back again: the tower code of an ERP code (identity for codes with no alias)."""
    back = {v: k for k, v in TOWER_TO_ERP.items()}
    return back.get(code, code)


def seed_types(template_rows: list[dict], erp_types: set[str]) -> list[dict]:
    """The ``TNA Milestone Type`` records to add: every task whose (mapped) code the ERP does not have yet, plus the ERP-only tasks' codes
    are already ERP types. Each record: code, label, department, is_critical, phase, source."""
    out = []
    for r in template_rows:
        code = erp_code(r["code"])
        if code in erp_types:
            continue
        out.append({"code": code, "label": r["name"], "department": DEPARTMENT.get(r.get("category"), "Merchandising"), "is_critical": 1 if r.get("is_critical") else 0,
                    "phase": r.get("category"), "auto_source": "Manual", "applies_when": "Always", "tower_code": r["code"]})
    return out
