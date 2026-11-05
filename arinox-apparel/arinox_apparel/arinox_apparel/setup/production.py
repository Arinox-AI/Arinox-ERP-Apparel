"""Phase D setup: seed masters, settings child rows, production warehouses. Idempotent: seeds are only inserted when
missing, edits made on the site are never overwritten. No company, buyer or vendor is named here."""

import frappe

# name, stage, severity, fault_source. From the company's end-line audit and final inspection forms, the loss
# categories of the daily production report, and cutting practice. Severities are a starting point for QA to confirm.
DEFECTS = [
	# sewing (end-line audit form)
	("Broken or Loose Stitch", "Sewing", "Major", "Factory Sewing"),
	("Open Seam or Raw Edge", "Sewing", "Major", "Factory Sewing"),
	("Puckering", "Sewing", "Minor", "Factory Sewing"),
	("Joint Stitch Visible", "Sewing", "Minor", "Factory Sewing"),
	("Bar Tack Insecure", "Sewing", "Major", "Factory Sewing"),
	("Button or Buttonhole Missing", "Sewing", "Major", "Factory Sewing"),
	("Alignment Defect", "Sewing", "Minor", "Factory Sewing"),
	("Wrong Size Label", "Any", "Critical", "Trims"),
	("Incorrect Label Placement", "Any", "Minor", "Factory Sewing"),
	("Crossed Label", "Any", "Minor", "Factory Sewing"),
	("Poor Ironing", "Any", "Minor", "Factory Sewing"),
	("Shine or Crease Marks", "Any", "Minor", "Factory Sewing"),
	# fabric
	("Stains", "Any", "Minor", "Handling"),
	("Holes", "Any", "Major", "Fabric"),
	("Shade Variation", "Any", "Major", "Fabric"),
	("Weaving Defect", "Any", "Minor", "Fabric"),
	# final inspection form
	("Weak Seams", "Final", "Major", "Factory Sewing"),
	("Overlock Quality", "Final", "Minor", "Factory Sewing"),
	("Balancing of Garment", "Final", "Minor", "Factory Sewing"),
	("Needle Marks", "Final", "Major", "Factory Sewing"),
	("Wavy Stitching", "Final", "Minor", "Factory Sewing"),
	("Neck Shape", "Final", "Major", "Factory Sewing"),
	("Snagging", "Final", "Minor", "Handling"),
	("Uncut or Loose Threads", "Final", "Minor", "Factory Sewing"),
	("Inside Finishing", "Final", "Minor", "Factory Sewing"),
	("Elastic Quality", "Final", "Major", "Trims"),
	("Embroidery Placement", "Final", "Major", "Subcontractor"),
	("Embroidery Fraying", "Final", "Major", "Subcontractor"),
	("Snaps, Studs or Zipper", "Final", "Major", "Trims"),
	("Pilling", "Final", "Minor", "Fabric"),
	("Hand Feel", "Final", "Minor", "Fabric"),
	("Print Defect", "Final", "Major", "Subcontractor"),
	("Measurement Out of Tolerance", "Final", "Major", "Spec or Pattern"),
	# loss categories of the daily production report
	("Washing Rejection", "Washing", "Major", "Subcontractor"),
	("Stain Garment", "Any", "Minor", "Handling"),
	("Factory Rejection", "Any", "Major", "Factory Sewing"),
	("Fabric Rejection", "Any", "Major", "Fabric"),
	("Spec Issue", "Any", "Major", "Spec or Pattern"),
	("Damage", "Any", "Major", "Handling"),
	# cutting
	("Cutting Damage", "Cutting", "Major", "Cutting"),
	("Wrong Cut or Missing Notch", "Cutting", "Major", "Cutting"),
	("Fabric Hole in Panel", "Cutting", "Major", "Fabric"),
	("Shade Mismatch in Panel", "Cutting", "Major", "Fabric"),
	# finishing
	("Metal or Needle Found", "Finishing", "Critical", "Factory Sewing"),
]

# name, position, item state, billing uom, needs approved standard
PROCESSES = [
	("Wash", "After Sewing", "Garments", "Pcs", 1),
	("Embroidery", "Before Sewing", "Cut Panels", "Pcs", 1),
	("Print", "Before Sewing", "Cut Panels", "Pcs", 1),
	("Appliqué", "Before Sewing", "Cut Panels", "Pcs", 1),
	("Heat Transfer", "Before Sewing", "Cut Panels", "Pcs", 1),
	("Garment Dye", "After Sewing", "Garments", "Kg", 1),
]

# From the company's pilot-run form and finishing practice.
CHECKS = [
	("Fit and measurements after wash", "Pilot Run"), ("Construction", "Pilot Run"), ("Wash result vs approved standard", "Pilot Run"),
	("Trims and labels", "Pilot Run"), ("Needle and thread", "Pilot Run"), ("Shade", "Pilot Run"), ("Packing", "Pilot Run"),
	("Line setting", "Line Setting"), ("Machines and attachments ready", "Line Setting"), ("Operators trained on critical operations", "Line Setting"),
	("Hang tag and sticker positions", "Pre-Pack"), ("Polybag warning and size", "Pre-Pack"), ("Barcode matches size and colour", "Pre-Pack"),
]

# From the packing list in the reference documents: one carton size, height varies with contents.
CARTONS = [("54 x 33 x 20 cm", 54, 33, 20)]

# From the company's operation bulletin sheets ("PLANNED DAY TARGET EFF%"): planned efficiency of 35, 45, 55, 60 then 65 %
# on days 1 to 5, against a final planned efficiency of 65 %. Stored as a percent of the final target (35 / 65 = 53.85 ...).
LEARNING_CURVE = [(1, 53.85), (2, 69.23), (3, 84.62), (4, 92.31), (5, 100)]
TRAFFIC_RULES = [("Yellow", 1), ("Red", 2)]

WAREHOUSES = [
	("cutting_wip_warehouse", "Cutting WIP"), ("line_wip_warehouse", "Line WIP"), ("fg_warehouse", "Finished Goods"),
	("seconds_warehouse", "Seconds (B-Grade)"), ("scrap_warehouse", "Scrap"),
]


def run():
	seed_defects()
	seed_processes()
	seed_checks()
	seed_cartons()
	seed_settings_rows()
	make_warehouses()


def seed_defects():
	for name, stage, severity, fault in DEFECTS:
		if not frappe.db.exists("Apparel Defect Code", name):
			frappe.get_doc({"doctype": "Apparel Defect Code", "defect_name": name, "stage": stage, "severity": severity,
							"fault_source": fault, "enabled": 1}).insert(ignore_permissions=True)


def seed_processes():
	for name, pos, state, uom, std in PROCESSES:
		if not frappe.db.exists("Subcontract Process", name):
			frappe.get_doc({"doctype": "Subcontract Process", "process_name": name, "default_position": pos, "item_state": state,
							"billing_uom": uom, "requires_approved_standard": std, "enabled": 1}).insert(ignore_permissions=True)


def seed_checks():
	for i, (name, applies) in enumerate(CHECKS, 1):
		if not frappe.db.exists("Production Check Item", name):
			frappe.get_doc({"doctype": "Production Check Item", "check_name": name, "applies_to": applies, "sequence": i * 10}).insert(ignore_permissions=True)


def seed_cartons():
	for name, length, width, height in CARTONS:
		if not frappe.db.exists("Shipment Parcel Template", name):
			frappe.get_doc({"doctype": "Shipment Parcel Template", "parcel_template_name": name, "length": length, "width": width, "height": height, "weight": 0}).insert(ignore_permissions=True)


def seed_settings_rows():
	"""Insert the default rows of the two settings tables once, while a table is still empty."""
	for field, child, rows, keys in (
		("learning_curve", "Learning Curve Day", LEARNING_CURVE, ("day_no", "pct_of_target")),
		("traffic_light_rules", "Traffic Light Rule", TRAFFIC_RULES, ("colour", "defects_from")),
	):
		if frappe.db.count(child, {"parent": "Apparel Settings", "parentfield": field}):
			continue
		for idx, vals in enumerate(rows, 1):
			d = {"doctype": child, "parenttype": "Apparel Settings", "parent": "Apparel Settings", "parentfield": field, "idx": idx}
			d.update(dict(zip(keys, vals)))
			frappe.get_doc(d).db_insert()


def make_warehouses():
	"""Create the production warehouses under the default company when missing, and point settings at them."""
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		return
	abbr = frappe.db.get_value("Company", company, "abbr")
	for field, wname in WAREHOUSES:
		if frappe.db.get_single_value("Apparel Settings", field):
			continue
		full = f"{wname} - {abbr}"
		if not frappe.db.exists("Warehouse", full):
			frappe.get_doc({"doctype": "Warehouse", "warehouse_name": wname, "company": company}).insert(ignore_permissions=True)
		frappe.db.set_single_value("Apparel Settings", field, full)
