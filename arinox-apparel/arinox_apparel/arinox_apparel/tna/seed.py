"""T&A milestone types and the default template. The day offsets come from the company's own T&A sheet (the `T & A` sheet
inside the trim requisition workbooks); rows marked 'assumed' were not on that sheet. Seeds are inserted only when missing."""

import frappe

# code, label, department, stamped by, critical, applies when, sample type
TYPES = [
	("ORDER_RECEIVED", "Order Received", "Merchandising", "Sales Order", 0, "Always", None),
	("TECH_PACK_RECEIVED", "Tech Pack Received", "Merchandising", "Tech Pack", 0, "Always", None),
	("BOM_RECEIVED", "BOM Received", "Merchandising", "Tech Pack", 0, "Always", None),
	("BULK_STANDARD_RECEIVED", "Bulk Standard Received", "Sampling", "Manual", 0, "Always", None),
	("MINI_MARKER", "Mini Marker", "Merchandising", "Fabric Requisition", 0, "Always", None),
	("FR_RAISED", "FR Raised", "Merchandising", "Fabric Requisition", 1, "Always", None),
	("TR_RAISED", "TR Raised", "Merchandising", "Trim Requisition", 1, "Always", None),
	("FABRIC_BOOKED", "Fabric Booked (PO)", "Purchasing", "Purchase Order", 1, "Always", None),
	("TRIM_PI", "Trim PI Received", "Purchasing", "Purchase Order", 0, "Always", None),
	("FIT", "Fit Approved", "Sampling", "Sample Approval", 1, "Sample Type Required", "Fit"),
	("LAB_DIP", "Lab Dip Approved", "Sampling", "Sample Approval", 1, "Sample Type Required", "Lab Dip"),
	("TRIMS_APPROVED", "Trims Approved", "Sampling", "Sample Approval", 0, "Sample Type Required", "Bulk Trim"),
	("BULK_FABRIC_READY_MILL", "Bulk Fabric Ready at Mill", "Purchasing", "Purchase Order", 1, "Always", None),
	("FABRIC_ETD", "Fabric ETD", "Purchasing", "Purchase Order", 1, "Always", None),
	("FABRIC_IN_HOUSE", "Fabric In-house", "Purchasing", "Purchase Receipt", 1, "Always", None),
	("FABRIC_QC_PASSED", "Fabric QC Passed", "Quality", "Fabric Inspection", 1, "Always", None),
	("FPT_PASSED", "FPT (Fabric Test) Passed", "Quality", "Sample Approval", 0, "Sample Type Required", "Fabric Test (FPT)"),
	("TRIMS_IN_HOUSE", "Trims In-house", "Purchasing", "Purchase Receipt", 0, "Always", None),
	("TRIMS_QC_PASSED", "Trims QC Passed", "Quality", "Trim Inspection", 0, "Always", None),
	("BULK_FABRIC_APPROVED", "Bulk Fabric Approved by Buyer", "Sampling", "Sample Approval", 1, "Sample Type Required", "Bulk Fabric"),
	("PP_GPT", "PP Sample + GPT Approved", "Sampling", "Sample Approval", 1, "Sample Type Required", "PP"),
	("PP_MEETING", "PP Meeting", "Production", "PP Meeting", 1, "Always", None),
	("PCD", "PCD (Planned Cut Date)", "Production", "Work Order", 1, "Always", None),
	("PILOT_RUN", "Pilot Run", "Production", "PP Meeting", 0, "Always", None),
	("TOP", "TOP / Size Set", "Sampling", "Sample Approval", 0, "Sample Type Required", "TOP"),
	("BULK_FINISH", "Bulk Finish (Sewing)", "Production", "Manual", 1, "Always", None),
	("WASH_FINISHED", "Washing Finished", "Washing", "Manual", 0, "Washed Only", None),
	("PACK_FINISHED", "Packing Finished", "Production", "Manual", 1, "Always", None),
	("FINAL_INSPECTION", "Final Inspection", "Quality", "Manual", 1, "Always", None),
	("FREIGHT_BOOKING", "Freight Booking", "Shipping", "Manual", 0, "Always", None),
	("EX_FACTORY", "Ex-Factory", "Shipping", "Manual", 1, "Always", None),
	("ON_BOARD", "On Board", "Shipping", "Shipment", 0, "Always", None),
	("IN_WAREHOUSE", "In Buyer's Warehouse", "Shipping", "Shipment", 0, "Always", None),
]

# code, basis, after, offset, duration rule, daily output
TEMPLATE_ROWS = [
	("ORDER_RECEIVED", "Order Received", None, 0, "Fixed", 0),
	("TECH_PACK_RECEIVED", "Order Received", None, 0, "Fixed", 0),
	("BOM_RECEIVED", "Order Received", None, 0, "Fixed", 0),
	("MINI_MARKER", "Order Received", None, 3, "Fixed", 0),
	("FR_RAISED", "Order Received", None, 6, "Fixed", 0),
	("TR_RAISED", "Order Received", None, 9, "Fixed", 0),
	("FABRIC_BOOKED", "After Milestone", "FR_RAISED", 2, "Fixed", 0),  # assumed
	("TRIM_PI", "After Milestone", "TR_RAISED", 3, "Fixed", 0),  # assumed
	("FIT", "Order Received", None, 12, "Fixed", 0),
	("LAB_DIP", "Order Received", None, 13, "Fixed", 0),
	("TRIMS_APPROVED", "Order Received", None, 19, "Fixed", 0),
	("BULK_FABRIC_READY_MILL", "Order Received", None, 28, "Fixed", 0),
	("FABRIC_ETD", "After Milestone", "BULK_FABRIC_READY_MILL", 2, "Fixed", 0),  # assumed
	("FPT_PASSED", "Order Received", None, 29, "Fixed", 0),
	("TRIMS_IN_HOUSE", "Order Received", None, 29, "Fixed", 0),
	("TRIMS_QC_PASSED", "After Milestone", "TRIMS_IN_HOUSE", 2, "Fixed", 0),  # assumed
	("FABRIC_IN_HOUSE", "After Milestone", "FABRIC_ETD", 7, "Fixed", 0),  # assumed transit time; set it per route
	("FABRIC_QC_PASSED", "After Milestone", "FABRIC_IN_HOUSE", 3, "Fixed", 0),  # assumed
	("BULK_FABRIC_APPROVED", "Order Received", None, 31, "Fixed", 0),
	("PP_GPT", "Order Received", None, 36, "Fixed", 0),
	("PP_MEETING", "Order Received", None, 39, "Fixed", 0),
	("PCD", "Order Received", None, 41, "Fixed", 0),
	("PILOT_RUN", "After Milestone", "PCD", 3, "Fixed", 0),
	("TOP", "After Milestone", "PCD", 4, "Fixed", 0),
	("BULK_FINISH", "After Milestone", "TOP", 0, "Qty / Daily Output", 300),
	("WASH_FINISHED", "After Milestone", "BULK_FINISH", 3, "Fixed", 0),
	("PACK_FINISHED", "After Milestone", "WASH_FINISHED", 3, "Fixed", 0),
	("FINAL_INSPECTION", "After Milestone", "PACK_FINISHED", 2, "Fixed", 0),
	("FREIGHT_BOOKING", "After Milestone", "FINAL_INSPECTION", 3, "Fixed", 0),
	("EX_FACTORY", "Ex-Factory", None, 0, "Fixed", 0),
]
# The tower's other checkpoints (2026-11-09, TNA_PRODUCTION_GRADE_PLAN section 5.3 / Appendix C): one `TNA Milestone Type` per milestone
# of the tower's 61-milestone template that the ERP's 33 types do not already carry, under the tower's own code. They are types only (a
# vocabulary): the default template above is unchanged, and the tower's scheduler decides which of them an order uses.
TOWER_TYPES = [
	("SALES_CONTRACT", "Sales contract signed", "Merchandising", "Manual", 0, "Always", None),
	("COST_APPROVAL", "Costing / price approved", "Merchandising", "Manual", 0, "Always", None),
	("CAPACITY_BOOK", "Capacity booked / line plan set", "Merchandising", "Manual", 0, "Always", None),
	("PATTERN", "Pattern & size grading complete", "Sampling", "Manual", 0, "Always", None),
	("PROTO_SAMPLE", "Proto sample submitted", "Sampling", "Manual", 0, "Always", None),
	("PROTO_APPROVE", "Proto sample approved", "Sampling", "Manual", 0, "Always", None),
	("LABDIP_SUB", "Lab dip submitted", "Purchasing", "Manual", 0, "Always", None),
	("BULK_TRIM_RELEASE", "Bulk trim production released", "Purchasing", "Manual", 0, "Always", None),
	("SHADE_BAND", "Shade band / shade grouping approved", "Purchasing", "Manual", 1, "Always", None),
	("MAT_RELEASE", "Material released to production", "Production", "Manual", 1, "Always", None),
	("PP_SAMPLE_SUB", "PP sample submitted", "Production", "Manual", 0, "Always", None),
	("OPS_BULLETIN", "Operation bulletin & quality plan finalised", "Production", "Manual", 0, "Always", None),
	("LINE_PLAN", "Line plan / loading confirmed", "Production", "Manual", 0, "Always", None),
	("CUT_START", "Bulk cutting start", "Production", "Manual", 1, "Always", None),
	("CUT_END", "Bulk cutting complete", "Production", "Manual", 1, "Always", None),
	("CUT_PANEL_QC", "Cut panel & bundle inspection", "Quality", "Manual", 0, "Always", None),
	("SEW_START", "Sewing line loaded / start", "Production", "Manual", 1, "Always", None),
	("QC_INLINE", "Inline quality inspection", "Quality", "Manual", 0, "Always", None),
	("QC_ENDLINE", "End-line quality inspection", "Quality", "Manual", 1, "Always", None),
	("WASH_SEND", "Sent to wash", "Production", "Manual", 1, "Always", None),
	("WASH_TRIAL_APPROVAL", "Trial wash approved", "Quality", "Manual", 0, "Always", None),
	("POST_WASH_MEAS", "Post-wash measurement audit", "Quality", "Manual", 0, "Always", None),
	("FINISH_END", "Finishing complete", "Production", "Manual", 1, "Always", None),
	("PACK_START", "Packing start", "Production", "Manual", 1, "Always", None),
	("CARTON_AUDIT", "Carton audit & packing reconciliation", "Production", "Manual", 0, "Always", None),
	("PACKLIST", "Packing list prepared", "Shipping", "Manual", 0, "Always", None),
	("SHIP_READY", "Shipment readiness confirmed", "Shipping", "Manual", 0, "Always", None),
	("COMM_INVOICE", "Commercial invoice prepared", "Shipping", "Manual", 0, "Always", None),
	("COO_DOCS", "COO / export customs documents", "Shipping", "Manual", 0, "Always", None),
	("CARGO_HANDOVER", "Container loading / cargo handover", "Shipping", "Manual", 1, "Always", None),
	("SHIPPING_ADVICE", "Shipping advice / ASN sent to buyer", "Shipping", "Manual", 0, "Always", None),
	("DOC_DISPATCH", "Documents dispatched to buyer", "Shipping", "Manual", 0, "Always", None),
	("ORDER_CLOSURE", "Order closure & final settlement", "Shipping", "Manual", 0, "Always", None),
]
TYPES = TYPES + TOWER_TYPES
TEMPLATE_NAME = "Standard 60-Day (forward)"


def seed():
	for i, (code, label, dept, src, crit, applies, stype) in enumerate(TYPES):
		if not frappe.db.exists("TNA Milestone Type", code):
			frappe.get_doc({"doctype": "TNA Milestone Type", "code": code, "label": label, "department": dept, "auto_source": src,
				"is_critical": crit, "applies_when": applies, "sample_type": stype, "sequence": (i + 1) * 10}).insert(ignore_permissions=True)
	if not frappe.db.exists("TNA Template", TEMPLATE_NAME):
		frappe.get_doc({"doctype": "TNA Template", "template_name": TEMPLATE_NAME, "is_default": 1,
			"remarks": "Offsets from the company T&A sheet. FABRIC_BOOKED, TRIM_PI, FABRIC_ETD, TRIMS_QC_PASSED, FABRIC_IN_HOUSE and FABRIC_QC_PASSED "
				"are assumed offsets (not on the sheet): check them against your suppliers.",
			"milestones": [{"milestone_type": c, "basis": b, "after_milestone": a, "offset_days": o, "duration_rule": d, "daily_output": q}
				for c, b, a, o, d, q in TEMPLATE_ROWS]}).insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Apparel Settings", "default_tna_template") and frappe.db.exists("TNA Template", TEMPLATE_NAME):
		frappe.db.set_single_value("Apparel Settings", "default_tna_template", TEMPLATE_NAME)
	remove_shipping_rows()


def remove_shipping_rows():
	"""ON_BOARD and IN_WAREHOUSE exist as milestone types, but are not in the default template: with assumed offsets they pushed a
	fresh order past the buyer's in-warehouse date. Add them to your own template with your own offsets. An earlier run of this
	seed added them to the default template; take them out again."""
	if not frappe.db.exists("TNA Template", TEMPLATE_NAME):
		return
	tpl = frappe.get_doc("TNA Template", TEMPLATE_NAME)
	keep = [m for m in tpl.milestones if m.milestone_type not in ("ON_BOARD", "IN_WAREHOUSE")]
	if len(keep) != len(tpl.milestones):
		tpl.set("milestones", keep)
		tpl.flags.ignore_permissions = True
		tpl.save()
