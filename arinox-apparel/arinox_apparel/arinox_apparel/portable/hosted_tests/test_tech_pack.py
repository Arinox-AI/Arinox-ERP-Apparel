import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def tech_pack(style_no="HT-TP-1", colours=("Navy", "Black"), sizes=("S", "M", "L"), submit=False, **kw):
	"""Mirrors the app's utils.make_tech_pack."""
	d = {"doctype": "Tech Pack", "naming_series": "TP-.YYYY.-", "customer": fx.customer(), "style_no": style_no, "style_name": "Test Tee", "product_type": fx.PRODUCT_TYPE,
		 "sizes": [{"size": s, "ratio": 1, "is_base_size": 1 if s == "M" else 0} for s in sizes],
		 "colours": [{"colour": c} for c in colours],
		 "measurements": [dict({"pom_code": "A", "point_of_measure": "Chest", "tolerance": 1}, **{s.lower(): 50 + i * 2 for i, s in enumerate(sizes)})],
		 "materials": [{"material_type": "Fabric", "description": "Jersey 180gsm", "consumption": 1.2, "uom": "Meter"},
					   {"material_type": "Trim", "description": "Neck label", "consumption": 1, "uom": "Nos"}]}
	d.update(kw)
	tp = frappe.get_doc(d).insert()
	if submit:
		tp.submit()
	return tp


@test("tech_pack")
def same_pom_code_may_describe_two_measures():
	"""T210 is both 'shoulder seam forward at neck' and 'at armhole' on a real tech pack."""
	tp = tech_pack("HT-TP-POM")
	for name in ("SHOULDER SEAM FORWARD AT NECK", "SHOULDER SEAM FORWARD AT ARMHOLE"):
		tp.append("measurements", {"pom_code": "T210", "point_of_measure": name, "m": 1, "tolerance": 0.125})
	tp.save()
	eq(tp.measurements[-1].tolerance, 0.125)     # one +/- figure per point
	tp.append("measurements", {"pom_code": "T210", "point_of_measure": "SHOULDER SEAM FORWARD AT NECK", "m": 2})
	true(throws(lambda: tp.save(), "entered twice"))


@test("tech_pack")
def latest_fit_round_sets_the_header_result():
	tp = tech_pack("HT-TP-FIT")
	tp.append("fit_rounds", {"fit_round": "1st Fit", "round_date": "2026-03-04", "round_status": "AWC"})
	tp.append("fit_rounds", {"fit_round": "2nd Fit", "round_date": "2026-04-13", "round_status": "Approved"})
	tp.save()
	eq(tp.fit_status, "Approved")
	# rows are ordered by date, not by position: an earlier-dated row added last does not win
	tp.append("fit_rounds", {"fit_round": "Proto", "round_date": "2026-01-01", "round_status": "Rejected"})
	tp.save()
	eq(tp.fit_status, "Approved")


@test("tech_pack")
def buyer_bom_row_keeps_the_buyer_codes():
	tp = tech_pack("HT-TP-BOM")
	tp.append("materials", {"material_type": "Fusing", "description": "9930 LIGHT FUSING", "consumption": 0.2, "uom": "Yard", "buyer_item_code": "FUS001",
							"job_code": "(SO)", "size_applicability": "*"})
	tp.save()
	eq(tp.materials[-1].buyer_item_code, "FUS001")


@test("tech_pack")
def sizes_are_unique_with_one_base_size():
	tp = tech_pack("HT-TP-SIZE")
	eq(tp.base_size, "M")
	tp.append("sizes", {"size": " s ", "ratio": 1})
	true(throws(lambda: tp.save(), "listed twice"))
	tp = frappe.get_doc("Tech Pack", tp.name)
	tp.sizes[0].is_base_size = 1                         # S and M both base
	true(throws(lambda: tp.save(), "Only one base size"))
	tp = frappe.get_doc("Tech Pack", tp.name)
	tp.sizes[1].is_base_size = 0
	tp.sizes[2].is_base_size = 1                         # L becomes the base
	tp.save()
	eq(tp.base_size, "L")


@test("tech_pack")
def a_measurement_must_use_a_listed_size():
	tp = tech_pack("HT-TP-MSIZE")
	tp.append("measurements", {"pom_code": "B", "point_of_measure": "Length", "xxl": 70})
	true(throws(lambda: tp.save(), "not in the size list"))


@test("tech_pack")
def submit_accepts_and_cancel_cancels():
	tp = tech_pack("HT-TP-SUB")
	eq(tp.status, "Draft")
	tp.submit()
	eq(frappe.db.get_value("Tech Pack", tp.name, "status"), "Accepted")
	tp = frappe.get_doc("Tech Pack", tp.name)
	tp.cancel()
	eq(frappe.db.get_value("Tech Pack", tp.name, "status"), "Cancelled")


@test("tech_pack")
def make_tech_pack_from_an_opportunity():
	cust = fx.customer()
	opp = frappe.get_doc({"doctype": "Opportunity", "opportunity_from": "Customer", "party_name": cust, "company": fx.company(), "apparel_product_type": fx.PRODUCT_TYPE,
						  "apparel_season": "SS27"}).insert()
	res = fx.engine_call("arinox_tech_pack_make_tech_pack", source_name=opp.name)["arinox_result"]
	eq((res["doctype"], res["customer"], res["opportunity"], res["product_type"], res["season"]), ("Tech Pack", cust, opp.name, fx.PRODUCT_TYPE, "SS27"))
	true(not res.get("name") or str(res.get("name")).startswith("new"), "unsaved")
	# a Lead must be converted first
	lead = frappe.get_doc({"doctype": "Lead", "first_name": "HT Lead"}).insert()
	opp2 = frappe.get_doc({"doctype": "Opportunity", "opportunity_from": "Lead", "party_name": lead.name, "company": fx.company()}).insert()
	true(throws(lambda: fx.engine_call("arinox_tech_pack_make_tech_pack", source_name=opp2.name), "Convert the Lead"))


@test("tech_pack")
def make_cost_sheet_copies_the_bom_and_charges():
	fx.costing_parameter()
	tp = tech_pack("HT-TP-CS")
	cs = fx.engine_call("arinox_tech_pack_make_cost_sheet", source_name=tp.name)["arinox_result"]
	eq((cs["doctype"], cs["tech_pack"], cs["style_no"], cs["product_type"], cs["customer"]), ("Cost Sheet", tp.name, "HT-TP-CS", fx.PRODUCT_TYPE, tp.customer))
	eq(cs["currency"], "USD")
	eq(cs["costing_parameter"], fx.costing_parameter())
	eq([(m["material_type"], m["consumption"], m["is_selected"]) for m in cs["materials"]], [("Fabric", 1.2, 1), ("Trim", 1, 1)])
	true(len(cs["charges"]) > 5, "charge rows from the parameter")
	true(any(c["cost_head"] == "Profit" and c["rate"] == 15 for c in cs["charges"]), "Profit rate 15 from the parameter")
	# the unsaved sheet is a valid Cost Sheet once it is saved
	doc = frappe.get_doc(dict(cs, naming_series="CS-.YYYY.-", quoted_price=None)).insert()
	eq(doc.tech_pack, tp.name)


@test("tech_pack")
def make_cost_sheet_needs_a_product_type_and_a_live_pack():
	tp = tech_pack("HT-TP-CS2", product_type=None)
	true(throws(lambda: fx.engine_call("arinox_tech_pack_make_cost_sheet", source_name=tp.name), "Product Type"))
	tp2 = tech_pack("HT-TP-CS3", submit=True)
	tp2.cancel()
	true(throws(lambda: fx.engine_call("arinox_tech_pack_make_cost_sheet", source_name=tp2.name), "cancelled"))


@test("tech_pack")
def create_style_item_makes_a_template_with_colour_and_size():
	frappe.db.set_single_value("Apparel Settings", "style_item_group", frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
	tp = tech_pack("HT-TP-ITEM", colours=("Navy", "Zebra Stripe"), sizes=("S", "M", "ZZL"))
	name = fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp.name)["arinox_result"]
	eq(name, "HT-TP-ITEM")
	item = frappe.get_doc("Item", name)
	eq((item.has_variants, item.variant_based_on, sorted(a.attribute for a in item.attributes)), (1, "Item Attribute", ["Colour", "Size"]))
	colours = [v.attribute_value for v in frappe.get_doc("Item Attribute", "Colour").item_attribute_values]
	sizes = [v.attribute_value for v in frappe.get_doc("Item Attribute", "Size").item_attribute_values]
	true("Zebra Stripe" in colours and "ZZL" in sizes, "new values added to the attribute lists")
	eq(frappe.db.get_value("Tech Pack", tp.name, "style_item"), name)
	# a second call answers the same item; an item that already exists under that code is refused
	eq(fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp.name)["arinox_result"], name)
	tp2 = tech_pack("HT-TP-ITEM-2")
	frappe.get_doc({"doctype": "Item", "item_code": "HT-TP-ITEM-2", "item_name": "x", "item_group": item.item_group, "stock_uom": "Nos"}).insert()
	true(throws(lambda: fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp2.name), "already exists"))


@test("tech_pack")
def old_layout_measurement_rows_are_merged_by_the_api():
	"""Rows saved when the measurement doctype had one row per size (size/value) show every point once per size at 0 and trip 'entered twice'.
	The API script folds them into one row per point, any Tech Pack, and is safe to run twice."""
	if "size" not in frappe.db.sql("select column_name from information_schema.columns where table_schema = database() and table_name = 'tabTech Pack Measurement'", pluck=True):
		return          # a site that never had the old layout has nothing to convert
	tp = tech_pack("HT-TP-OLD")
	tp.append("measurements", {"pom_code": "T100", "point_of_measure": "Shoulder Width", "tolerance": 0.25, "s": 15.75, "m": 16.25, "l": 16.75})
	tp.save()
	# rewrite both points the old way: one row per size, value in `value`, tolerance in tolerance_plus / tolerance_minus
	old = []
	for row in tp.measurements:
		for size in ("s", "m", "l"):
			old.append((row.pom_code, row.point_of_measure, size.upper(), row.get(size), row.tolerance))
	frappe.db.sql("delete from `tabTech Pack Measurement` where parent = %s", tp.name)
	for i, (pom, point, size, value, tol) in enumerate(old, 1):
		frappe.get_doc({"doctype": "Tech Pack Measurement", "parent": tp.name, "parenttype": "Tech Pack", "parentfield": "measurements", "idx": i,
						"pom_code": pom, "point_of_measure": point}).db_insert()
		frappe.db.sql("update `tabTech Pack Measurement` set size = %s, value = %s, tolerance_plus = %s, tolerance_minus = %s "
					  "where parent = %s and idx = %s", (size, value, tol, tol, tp.name, i))
	broken = frappe.get_doc("Tech Pack", tp.name)
	eq(len(broken.measurements), 6)
	true(throws(lambda: broken.save(), "entered twice"))

	res = fx.engine_call("arinox_tech_pack_merge_measurements", tech_pack=tp.name)["arinox_result"]
	eq(res["converted_points"], 2)
	eq(res["removed_rows"], 4)
	fixed = frappe.get_doc("Tech Pack", tp.name)
	eq(len(fixed.measurements), 2)
	eq([r.idx for r in fixed.measurements], [1, 2])
	chest = fixed.measurements[0]
	eq([chest.s, chest.m, chest.l, chest.tolerance], [50, 52, 54, 1])
	shoulder = fixed.measurements[1]
	eq([shoulder.s, shoulder.m, shoulder.l, shoulder.tolerance], [15.75, 16.25, 16.75, 0.25])
	fixed.save()                                                         # the rule no longer fires
	again = fx.engine_call("arinox_tech_pack_merge_measurements", tech_pack=tp.name)["arinox_result"]
	eq([again["converted_points"], again["removed_rows"]], [0, 0])
