"""Phase C setup: custom fields on ERPNext doctypes, seed masters, warehouses, stock setting.
Idempotent. Seeds are only inserted when missing; edits made on the site are never overwritten."""

import frappe

MATERIAL_TYPES = "\nFabric\nLining\nContrast Fabric\nTrim\nLabel\nPackaging"


def _chain(doctype, fields, anchor):
	"""Give each field insert_after = the previous one, starting at `anchor`."""
	out, prev = [], anchor
	for f in fields:
		f = dict(f)
		f["insert_after"] = prev
		prev = f["fieldname"]
		out.append(f)
	return out


def _anchor(doctype, *candidates):
	meta = frappe.get_meta(doctype)
	for c in candidates:
		if meta.has_field(c):
			return c
	return meta.fields[-1].fieldname


def get_custom_fields():
	D = dict
	req = D(fieldtype="Select", options="\nFR\nTR", label="Requisition Type", read_only=1)
	cf = {
		"Company": _chain("Company", [
			D(fieldname="apparel_fr_prefix", fieldtype="Data", label="Fabric Requisition Prefix", default="FR",
			  description="Number format: PREFIX + YY.MM.### (counter restarts each month)"),
			D(fieldname="apparel_tr_prefix", fieldtype="Data", label="Trim Requisition Prefix", default="TR"),
		], "apparel_contract_prefix"),
		"Supplier": _chain("Supplier", [
			D(fieldname="apparel_section", fieldtype="Section Break", label="Apparel", collapsible=1),
			D(fieldname="apparel_purchase_terms", fieldtype="Link", options="Material Purchase Terms", label="Purchase Terms"),
			D(fieldname="apparel_supplier_type", fieldtype="Select", label="Apparel Supplier Type",
			  options="\nMill\nConverter\nTrim Supplier\nWashing\nOther"),
		], "default_currency"),
		"Item": _chain("Item", [
			D(fieldname="apparel_item_section", fieldtype="Section Break", label="Apparel Material", collapsible=1),
			D(fieldname="apparel_material_type", fieldtype="Select", label="Material Type", options=MATERIAL_TYPES),
			D(fieldname="apparel_trim_category", fieldtype="Link", options="Trim Category", label="Trim Category"),
			D(fieldname="apparel_fabric_content", fieldtype="Data", label="Fabric Content"),
			D(fieldname="apparel_construction", fieldtype="Data", label="Construction"),
			D(fieldname="apparel_item_col", fieldtype="Column Break"),
			D(fieldname="apparel_fabric_gsm", fieldtype="Float", label="Fabric GSM"),
			D(fieldname="apparel_fabric_width_cm", fieldtype="Float", label="Cuttable Width (cm)"),
		], "brand"),
		"Material Request Item": _chain("Material Request Item", [
			D(fieldname="apparel_requisition_type", **req),
			D(fieldname="apparel_requisition", fieldtype="Data", label="Requisition", read_only=1),
			D(fieldname="apparel_requisition_item", fieldtype="Data", label="Requisition Row", read_only=1),
			D(fieldname="apparel_style_no", fieldtype="Data", label="Style No", read_only=1),
			D(fieldname="apparel_colour", fieldtype="Data", label="Colour", read_only=1),
			D(fieldname="apparel_hold_reason", fieldtype="Small Text", label="Hold Reason", read_only=1),
		], "project"),
		"Purchase Order Item": _chain("Purchase Order Item", [
			D(fieldname="apparel_requisition_type", **req),
			D(fieldname="apparel_requisition", fieldtype="Data", label="Requisition", read_only=1),
			D(fieldname="apparel_requisition_item", fieldtype="Data", label="Requisition Row", read_only=1),
			D(fieldname="apparel_style_no", fieldtype="Data", label="Style No", read_only=1),
			D(fieldname="apparel_colour", fieldtype="Data", label="Colour", read_only=1),
			D(fieldname="apparel_hold_reason", fieldtype="Small Text", label="Hold Reason", read_only=1),
		], "project"),
		"Purchase Order": _chain("Purchase Order", [
			D(fieldname="apparel_po_section", fieldtype="Section Break", label="Apparel Purchase", collapsible=1),
			D(fieldname="apparel_purchase_terms", fieldtype="Link", options="Material Purchase Terms", label="Purchase Terms"),
			D(fieldname="apparel_supplier_contract_no", fieldtype="Data", label="Supplier Contract No"),
			D(fieldname="apparel_shipment_mode", fieldtype="Select", label="Shipment Mode", options="\nSea\nAir\nRoad\nCourier"),
			D(fieldname="apparel_port_of_loading", fieldtype="Data", label="Port of Loading"),
			D(fieldname="apparel_destination", fieldtype="Data", label="Destination"),
			D(fieldname="apparel_po_col", fieldtype="Column Break"),
			D(fieldname="apparel_pi_no", fieldtype="Data", label="PI No", allow_on_submit=1),
			D(fieldname="apparel_pi_date", fieldtype="Date", label="PI Date", allow_on_submit=1),
			D(fieldname="apparel_mill_ready_date", fieldtype="Date", label="Bulk Ready at Mill", allow_on_submit=1),
			D(fieldname="apparel_etd_planned", fieldtype="Date", label="ETD (Plan)", allow_on_submit=1),
			D(fieldname="apparel_etd_revised", fieldtype="Date", label="ETD (Revised)", allow_on_submit=1),
			D(fieldname="apparel_etd_actual", fieldtype="Date", label="ETD (Actual)", allow_on_submit=1),
			D(fieldname="apparel_eta", fieldtype="Date", label="ETA", allow_on_submit=1),
			D(fieldname="apparel_bl_awb_no", fieldtype="Data", label="BL / AWB No", allow_on_submit=1),
			D(fieldname="apparel_po_override_section", fieldtype="Section Break", label="Approval Override"),
			D(fieldname="apparel_approval_override", fieldtype="Check", label="Override Approval Hold", no_copy=1,
			  description="Apparel Merchandising Manager only"),
			D(fieldname="apparel_approval_override_reason", fieldtype="Small Text", label="Override Reason", no_copy=1,
			  depends_on="apparel_approval_override"),
		], _anchor("Purchase Order", "terms", "tc_name")),
		"Purchase Receipt": _chain("Purchase Receipt", [
			D(fieldname="apparel_pr_section", fieldtype="Section Break", label="Apparel Receipt", collapsible=1),
			D(fieldname="apparel_delay_days", fieldtype="Int", label="Delay (days)", read_only=1, no_copy=1),
			D(fieldname="apparel_penalty_pct", fieldtype="Percent", label="Delay Penalty %", read_only=1, no_copy=1),
			D(fieldname="apparel_penalty_amount", fieldtype="Currency", label="Delay Penalty Amount", read_only=1, no_copy=1,
			  options="currency"),
			D(fieldname="apparel_qty_band_note", fieldtype="Small Text", label="Quantity Band Note", read_only=1, no_copy=1),
		], _anchor("Purchase Receipt", "terms", "tc_name")),
		"Batch": _chain("Batch", [
			D(fieldname="apparel_roll_section", fieldtype="Section Break", label="Fabric Roll", collapsible=1),
			D(fieldname="apparel_roll_no", fieldtype="Data", label="Roll No", search_index=1),
			D(fieldname="apparel_dye_lot", fieldtype="Data", label="Dye Lot"),
			D(fieldname="apparel_shade_band", fieldtype="Data", label="Shade Band"),
			D(fieldname="apparel_ticket_length", fieldtype="Float", label="Ticket Length"),
			D(fieldname="apparel_actual_length", fieldtype="Float", label="Actual Length"),
			D(fieldname="apparel_roll_col", fieldtype="Column Break"),
			D(fieldname="apparel_width_cm", fieldtype="Float", label="Width (cm)"),
			D(fieldname="apparel_points_per_100", fieldtype="Float", label="Points per 100", read_only=1),
			D(fieldname="apparel_inspection_status", fieldtype="Select", label="Inspection Status", read_only=1, default="Uninspected",
			  options="Uninspected\nAccepted\nAccepted by Lot\nRejected\nHold", in_standard_filter=1),
			D(fieldname="apparel_fabric_inspection", fieldtype="Link", options="Fabric Inspection", label="Fabric Inspection",
			  read_only=1),
			D(fieldname="apparel_shrinkage_warp_pct", fieldtype="Float", label="Shrinkage Warp %", read_only=1),
			D(fieldname="apparel_shrinkage_weft_pct", fieldtype="Float", label="Shrinkage Weft %", read_only=1),
		], "description"),
	}
	return cf


def make_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	cf = get_custom_fields()
	# Batch / Purchase Receipt link to doctypes that may not exist yet in an early slice; skip them until they do.
	for dt, fields in list(cf.items()):
		fields[:] = [f for f in fields if not (f.get("fieldtype") == "Link" and not frappe.db.exists("DocType", f.get("options")))]
	create_custom_fields(cf, ignore_validate=True, update=True)


# ---- seeds ---------------------------------------------------------------------------------------------------

ALLOWANCES = [  # material_type, trim_category, pct
	("Fabric", None, 5), ("Lining", None, 5), ("Contrast Fabric", None, 5),
	("Label", None, 10), ("Trim", None, 2), ("Packaging", None, 2),
	("Trim", "Button", 10),  # the reference TR applies 10% to buttons: 1800 x (10 + 1) x 1.10 = 21,780
]

TRIM_CATEGORIES = [  # name, calc basis, needed for
	("Woven Label", "Per Garment", "Sewing"), ("Size Label", "Per Size", "Sewing"), ("Care Label", "Per Garment", "Sewing"),
	("Thread", "By Length", "Sewing"), ("Fusing / Interlining", "By Length", "Cutting"),
	("Security Tag", "Per Garment", "Finishing"), ("Hang Tag", "Per Garment", "Finishing"),
	("Button", "Per Garment", "Sewing"), ("Branding", "Per Garment", "Sewing"),
	("Zipper / Hooks / Fasteners", "Per Garment", "Sewing"), ("Elastic / Tape", "By Length", "Sewing"),
	("Packaging", "Per Carton", "Packing"), ("Others", "Per Garment", "Finishing"),
]

FABRIC_DEFECTS = [  # code, name, always 4, category  (from the 4-point inspection format)
	("A", "Double Pick", 0, "Weaving"), ("B", "Broken Pick", 0, "Weaving"), ("C", "Colour Bar", 0, "Dyeing"),
	("D", "Dye Streak", 0, "Dyeing"), ("E", "Dye Mistake", 0, "Dyeing"), ("F", "Foreign Yarn", 0, "Weaving"),
	("G", "Dye Patch", 0, "Dyeing"), ("H", "Hole", 1, "Weaving"), ("I", "Stain Mark", 0, "Other"),
	("J", "Crack", 0, "Other"), ("K", "Knot", 0, "Weaving"), ("L", "Loose Weave", 0, "Weaving"),
	("M", "Double End", 0, "Weaving"), ("N", "Broken End", 0, "Weaving"), ("O", "Oil Mark", 0, "Other"),
	("P", "Printing Mistake", 0, "Printing"), ("Q", "Folding Mark", 0, "Finishing"), ("R", "Crease Mark", 0, "Finishing"),
	("S", "Stop Mark", 0, "Weaving"), ("T", "Tiny Dot", 0, "Printing"), ("U", "Slub", 0, "Weaving"),
	("V", "Pull Yarn", 0, "Weaving"), ("W", "Weaving Defect", 0, "Weaving"), ("X", "Shine Mark", 0, "Finishing"),
	("Y", "Press Mark", 0, "Finishing"), ("Z", "Shift Print", 0, "Printing"), ("MILL", "Mill Mark", 0, "Other"),
	("SL", "Slack / Tight End", 0, "Weaving"),
]

TRIM_DEFECTS = [
	("Letter Missing", "Major"), ("Print Missing", "Major"), ("Shape Out", "Major"), ("Stains", "Major"),
	("Fusing Problem", "Major"), ("Scratch", "Minor"), ("Needle Hole Missing", "Major"), ("Damaged Button / Label", "Major"),
	("Colour Variation", "Major"), ("Size Variation", "Major"), ("Size Mix-up", "Major"), ("Unmatching Thread", "Minor"),
]

# From the fabric purchase contract
FABRIC_TERMS = dict(
	terms_name="Standard Fabric Terms", material_kind="Fabric", claim_window_days=45, points_threshold=20,
	extra_qty_policy="Accept Unpaid",
	qty_bands=[(0, 1000, 7), (1001, 3000, 5), (3001, 10000, 3)],
	delay_bands=[(1, 3, 0, "Discount"), (4, 11, 10, "Discount"), (12, 21, 25, "Discount"), (22, 0, 50, "Cancel or Discount")],
	terms_text=(
		"<ol><li>Delivery: delay of 1-3 days 0%, 4-11 days 10%, 12-21 days 25%, over 21 days order cancellation or 50% "
		"discount.</li><li>Quantity allowance: up to 1000 m +/-7%, 1001-3000 m +/-5%, 3001-10000 m +/-3%. Extra fabric will "
		"not be taken or paid.</li><li>Inspection standard: 20 points per 100 linear yards.</li><li>Bulk testing is borne by "
		"the buyer; the cost of re-testing after a failure is borne by the supplier.</li><li>Quality or quantity issues "
		"found after receipt will be raised with the supplier within 45 days.</li><li>Shipping marks: colour, qty, roll no, "
		"lot no and consignee.</li></ol>"),
)
TRIM_TERMS = dict(
	terms_name="Standard Trim Terms", material_kind="Trim", claim_window_days=30, extra_qty_policy="Accept Unpaid",
	qty_bands=[(0, 0, 5)], delay_bands=[], terms_text="<p>Quantity allowance +/-5%. Quality as per the approved trim card.</p>",
)

FABRIC_SAMPLING = [(0, 1000, 50), (1001, 2000, 30), (2001, 3000, 20), (3001, 5000, 15), (5001, 0, 10)]
# The last row is not on the paper form; confirm with the user.

# General inspection level II, AQL 2.5. NOT confirmed against ISO 2859-1; QA must check before relying on it.
TRIM_AQL = [(51, 90, 13, 1, 2), (91, 150, 20, 1, 2), (151, 280, 32, 2, 3), (281, 500, 50, 3, 4), (501, 1200, 80, 5, 6),
	(1201, 3200, 125, 7, 8), (3201, 10000, 200, 10, 11), (10001, 35000, 315, 14, 15), (35001, 150000, 500, 21, 22)]


def seed_masters():
	for i, (name, basis, need) in enumerate(TRIM_CATEGORIES):
		if not frappe.db.exists("Trim Category", name):
			frappe.get_doc({"doctype": "Trim Category", "category_name": name, "calc_basis": basis, "needed_for": need,
				"sequence": (i + 1) * 10}).insert(ignore_permissions=True)
	for mt, cat, pct in ALLOWANCES:
		exists = [r for r in frappe.get_all("Material Allowance Rule", {"material_type": mt}, ["trim_category", "customer"])
			if (r.trim_category or None) == cat and not r.customer]
		if not exists and (not cat or frappe.db.exists("Trim Category", cat)):
			frappe.get_doc({"doctype": "Material Allowance Rule", "material_type": mt, "trim_category": cat, "allowance_pct": pct,
				"enabled": 1}).insert(ignore_permissions=True)
	for code, name, four, cat in FABRIC_DEFECTS:
		if not frappe.db.exists("Fabric Defect Code", code):
			frappe.get_doc({"doctype": "Fabric Defect Code", "code": code, "defect_name": name, "always_four_points": four,
				"category": cat}).insert(ignore_permissions=True)
	for name, sev in TRIM_DEFECTS:
		if not frappe.db.exists("Trim Defect Type", name):
			frappe.get_doc({"doctype": "Trim Defect Type", "defect_name": name, "severity": sev}).insert(ignore_permissions=True)
	for t in (FABRIC_TERMS, TRIM_TERMS):
		if not frappe.db.exists("Material Purchase Terms", t["terms_name"]):
			doc = {k: v for k, v in t.items() if k not in ("qty_bands", "delay_bands")}
			doc["doctype"] = "Material Purchase Terms"
			doc["qty_bands"] = [{"from_qty": a, "to_qty": b, "tolerance_pct": c} for a, b, c in t["qty_bands"]]
			doc["delay_bands"] = [{"from_days": a, "to_days": b, "penalty_pct": c, "action": d} for a, b, c, d in t["delay_bands"]]
			frappe.get_doc(doc).insert(ignore_permissions=True)
	if not frappe.db.exists("Trim Sampling Plan", "Trims 10 Percent"):
		frappe.get_doc({"doctype": "Trim Sampling Plan", "plan_name": "Trims 10 Percent", "method": "Percent", "inspect_pct": 10}).insert(ignore_permissions=True)
	if not frappe.db.exists("Trim Sampling Plan", "AQL 2.5 General II (unconfirmed)"):
		frappe.get_doc({"doctype": "Trim Sampling Plan", "plan_name": "AQL 2.5 General II (unconfirmed)", "method": "AQL Table",
			"full_inspect_up_to": 50, "note": "Values not yet confirmed against ISO 2859-1. QA must check before use.",
			"rows": [{"lot_from": a, "lot_to": b, "sample_size": c, "accept_max": d, "reject_min": e} for a, b, c, d, e in TRIM_AQL]}).insert(ignore_permissions=True)
	from arinox_apparel.materials.inspection import ensure_qi_parameters

	ensure_qi_parameters()
	_seed_settings()


def _seed_settings():
	s = frappe.get_single("Apparel Settings")
	changed = False
	if not s.get("fabric_sampling_bands"):
		for a, b, c in FABRIC_SAMPLING:
			s.append("fabric_sampling_bands", {"from_length_m": a, "to_length_m": b, "inspect_pct": c})
		changed = True
	if not s.get("default_purchase_terms") and frappe.db.exists("Material Purchase Terms", FABRIC_TERMS["terms_name"]):
		s.default_purchase_terms = FABRIC_TERMS["terms_name"]; changed = True
	if not s.get("default_trim_sampling_plan") and frappe.db.exists("Trim Sampling Plan", "Trims 10 Percent"):
		s.default_trim_sampling_plan = "Trims 10 Percent"; changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.save()


WAREHOUSES = [  # settings field, warehouse name
	("inspection_warehouse_fabric", "Fabric Inspection"), ("store_warehouse_fabric", "Fabric Store"),
	("inspection_warehouse_trim", "Trim Inspection"), ("store_warehouse_trim", "Trim Store"),
	("rejected_warehouse", "Rejected Material"),
]


def make_warehouses():
	"""Create the five material warehouses under the default company when missing, and point settings at them."""
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		return
	for field, wname in WAREHOUSES:
		if frappe.db.get_single_value("Apparel Settings", field):
			continue
		abbr = frappe.db.get_value("Company", company, "abbr")
		full = f"{wname} - {abbr}"
		if not frappe.db.exists("Warehouse", full):
			frappe.get_doc({"doctype": "Warehouse", "warehouse_name": wname, "company": company}).insert(ignore_permissions=True)
		frappe.db.set_single_value("Apparel Settings", field, full)


def set_stock_settings():
	"""A Quality Inspection is made after the Purchase Receipt (goods wait in a quarantine warehouse), so ERPNext
	must allow that."""
	if frappe.db.get_single_value("Stock Settings", "allow_to_make_quality_inspection_after_purchase_or_delivery") != 1:
		frappe.db.set_single_value("Stock Settings", "allow_to_make_quality_inspection_after_purchase_or_delivery", 1)


def run():
	make_custom_fields()
	seed_masters()
	make_warehouses()
	set_stock_settings()
