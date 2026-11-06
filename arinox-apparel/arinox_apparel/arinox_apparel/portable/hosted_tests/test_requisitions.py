import json

import frappe
from frappe.utils import add_days, flt, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import call, fr, supplier, tr, trim_item, warehouses, world


def revise(name, script="arinox_fabric_requisition_revise_fabric_requisition"):
	d = call(script, source_name=name)
	d.pop("name", None)
	return frappe.get_doc(d)


def mrs_of(requisition):
	return frappe.get_all("Material Request Item", filters={"apparel_requisition": requisition}, fields=["parent", "qty", "stock_qty", "sales_order", "apparel_hold_reason", "item_code"])


@test("requisitions")
def lines_come_from_the_tech_pack_and_order():
	w = world()
	rows = call("arinox_fabric_requisition_get_lines_from_sales_orders", doc=json.dumps({"customer": fx.customer(), "company": fx.company(), "items": []}),
				sales_orders=json.dumps([w["so"].name]))["arinox_doc"]["items"]
	eq({r["colour"]: r["garment_qty"] for r in rows}, {"Navy": 700, "Black": 500})
	true(all(r["consumption"] == 1.2 and r["consumption_uom"] == "Meter" for r in rows))
	true(all(r["material_role"] == "Shell" for r in rows), "the Trim row is not on the FR")
	again = call("arinox_fabric_requisition_get_lines_from_sales_orders", doc=json.dumps({"customer": fx.customer(), "company": fx.company(), "items": rows}),
				 sales_orders=json.dumps([w["so"].name]))
	eq((again["count"], len(again["arinox_doc"]["items"])), (0, 2))             # lines already there are not added again
	# two fabrics of one style and colour with no linked item (a lining and a self fabric typed "Fabric") are two lines: a form row that came from a
	# different Tech Pack material row must not hide the Tech Pack's own line
	other = [dict(r, tech_pack_material="another-material-row", fabric_description="Another fabric") if r["colour"] == "Navy" else r for r in rows]
	more = call("arinox_fabric_requisition_get_lines_from_sales_orders", doc=json.dumps({"customer": fx.customer(), "company": fx.company(), "items": other}),
				sales_orders=json.dumps([w["so"].name]))
	eq((more["count"], len(more["arinox_doc"]["items"])), (1, 3))


@test("requisitions")
def golden_number_total_is_computed_and_kg_and_yards_convert():
	w = world()
	doc = fr(w)
	doc.items[0].garment_qty = 553
	doc.items[0].consumption = 1.97
	doc.items[0].gross_qty = 1
	doc.items[0].net_qty = 1
	doc.insert()
	near = lambda a, b: abs(a - b) < 0.001
	true(near(doc.items[0].gross_qty, 1143.8805), doc.items[0].gross_qty)       # FR Format Reference.xlsx: 553 x 1.97 m x 1.05
	true(near(doc.items[0].net_qty, 1143.8805))
	doc = fr(w)
	doc.items[0].consumption_uom = "Yard"
	doc.insert()
	true(near(doc.items[0].gross_qty, 700 * 1.2 * 0.9144 * 1.05), doc.items[0].gross_qty)
	doc = fr(w)
	doc.items[0].consumption_uom = "Kg"
	doc.items[0].consumption = 0.2
	doc.insert()                                                                # 1 kg of 145 gsm x 132 cm = 5.2247 m
	true(near(doc.items[0].gross_qty, 700 * 0.2 * 5.2247 * 1.05) or abs(doc.items[0].gross_qty - 700 * 0.2 * 5.2247 * 1.05) < 0.1, doc.items[0].gross_qty)


@test("requisitions")
def a_kg_line_needs_gsm_width_and_source():
	w = world()
	doc = fr(w)
	doc.items[0].consumption_uom = "Kg"
	doc.items[0].gsm = 0
	true(throws(lambda: doc.insert(), "needs the GSM"))
	doc = fr(w)
	doc.items[0].cuttable_width_cm = 0
	true(throws(lambda: doc.insert(), "cuttable width"))
	doc = fr(w)
	doc.items[0].consumption_source = None
	true(throws(lambda: doc.insert(), "where the consumption comes from"))


@test("requisitions")
def allowance_rule_reason_duplicates_and_customer_check():
	w = world()
	doc = fr(w)
	doc.items[0].allowance_pct = 8
	true(throws(lambda: doc.insert(), "differs from the rule"))
	doc = fr(w)
	doc.items[0].allowance_pct = 8
	doc.items[0].allowance_reason = "Directional print"
	doc.insert()
	true(abs(doc.items[0].gross_qty - 700 * 1.2 * 1.08) < 0.001, doc.items[0].gross_qty)
	doc = fr(w)
	doc.append("items", doc.items[0].as_dict(no_default_fields=True))
	true(throws(lambda: doc.insert(), "repeats row"))
	doc = fr(w)
	doc.customer = fx.customer("HT Buyer 2")
	true(throws(lambda: doc.insert(), "belongs to another buyer"))
	doc = fr(w)
	doc.insert()
	true(doc.name.startswith("FR") and len(doc.name.split(".")) == 3, doc.name)      # FRyy.mm.###
	eq(doc.status, "Draft")


@test("requisitions")
def a_missing_lab_dip_holds_the_line_and_a_costing_difference_is_flagged():
	w = world()
	frappe.db.delete("Sample Approval", {"sample_type": "Lab Dip", "style_item": w["template"]})
	doc = fr(w)
	doc.insert()
	true(all(r.hold for r in doc.items))
	true("lab dip" in doc.red_flags.lower(), doc.red_flags)
	doc = fr(w)
	doc.items[0].consumption = 1.5
	doc.items[0].costed_consumption = 1.2
	doc.insert()
	true("more than 5%" in doc.red_flags, doc.red_flags)


@test("requisitions")
def submit_makes_material_requests_by_supplier_and_cancel_cancels_them():
	w = world()
	doc = fr(w)
	doc.items[1].supplier = w["mill_b"]
	doc.insert()
	doc.submit()
	eq(len({m.parent for m in mrs_of(doc.name)}), 2)                             # one per supplier
	true(all(m.sales_order == w["so"].name for m in mrs_of(doc.name)))
	doc.reload()
	true(all(r.material_request for r in doc.items))
	eq((doc.status, doc.approved_by), ("Approved", "Administrator"))
	mr = doc.items[0].material_request
	doc.cancel()
	eq(frappe.db.get_value("Material Request", mr, "docstatus"), 2)
	eq(frappe.db.get_value("Fabric Requisition", doc.name, "status"), "Cancelled")


@test("requisitions")
def a_revision_requests_only_the_increase_and_flags_a_decrease():
	w = world()
	doc = fr(w)
	doc.insert()
	doc.submit()
	rev = revise(doc.name)
	true(throws(lambda: rev.insert(), "reason for this revision"))
	rev = revise(doc.name)
	rev.revision_reason = "Buyer PO revision: +100 Navy"
	rev.items[0].garment_qty = 800
	rev.items[1].garment_qty = 400                                               # decrease
	rev.insert()
	true("Reduce the order" in rev.red_flags, rev.red_flags)
	rev.submit()
	new_qty = sum(flt(i.stock_qty) for i in mrs_of(rev.name))
	true(abs(new_qty - 100 * 1.2 * 1.05) < 0.01, new_qty)                        # only the Navy increase
	doc.reload()
	eq(doc.status, "Superseded")
	rev.cancel()                                                                 # cancelling the revision brings the original back
	doc.reload()
	eq(doc.status, "Approved")


@test("requisitions")
def stock_reduces_the_net_requirement_and_cannot_be_claimed_twice():
	w = world()
	wh = w["wh"]["store_warehouse_fabric"]
	frappe.get_doc({"doctype": "Bin", "item_code": w["navy_fabric"], "warehouse": wh, "actual_qty": 100}).insert(ignore_permissions=True)
	a = fr(w)
	a.items[0].stock_warehouse = wh
	a.items[0].stock_used = 80
	a.insert()
	true(abs(a.items[0].net_qty - (700 * 1.2 * 1.05 - 80)) < 0.001)
	a.submit()
	b = fr(w)
	b.items[0].stock_warehouse = wh
	b.items[0].stock_used = 50                                                   # only 20 m is free now
	true(throws(lambda: b.insert(), "is free in"))
	b.items[0].stock_used = 20
	b.insert()


@test("requisitions")
def create_fabric_items_makes_a_template_with_a_colour_variant_and_yard_kg_uoms():
	code = "_ATQ-NEW"
	res = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [
		{"idx": 1, "fabric_description": code + ", 100% Cotton, CW 132CM", "colour": "Navy", "gsm": 145, "cuttable_width_cm": 132}]}))
	item = res["made"][0]
	tpl = frappe.get_doc("Item", code)
	eq((tpl.stock_uom, tpl.has_variants, tpl.has_batch_no), ("Meter", 1, 1))
	true(set(["Yard", "Kg"]) <= {u.uom for u in tpl.uoms}, [u.uom for u in tpl.uoms])
	eq(frappe.db.get_value("Item", item, "variant_of"), code)
	again = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [
		{"idx": 1, "fabric_description": code + ", 100% Cotton, CW 132CM", "colour": "Navy", "gsm": 145, "cuttable_width_cm": 132}]}))
	eq(again["made"][0], item)                                                   # safe to call again
	# the colour as the Tech Pack spells it ("NAVY", "A New Colour") is matched to the attribute's own spelling, or added: it used to fail with
	# "BLACK is not a valid Value for Attribute Colour" when the attribute said "Black"
	upper = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [
		{"idx": 1, "fabric_description": code + ", 100% Cotton, CW 132CM", "colour": "NAVY", "gsm": 145, "cuttable_width_cm": 132}]}))
	eq(upper["made"][0], item)                                                   # the same Navy variant, not a failure and not a second one
	fresh = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [
		{"idx": 1, "fabric_description": code + ", 100% Cotton, CW 132CM", "colour": "HT Sunset Orange", "gsm": 145, "cuttable_width_cm": 132}]}))["made"][0]
	eq(frappe.db.get_value("Item", fresh, "variant_of"), code)
	true(throws(lambda: call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [{"idx": 1, "fabric_description": "", "colour": "Navy"}]})), "quality code"))


@test("requisitions")
def the_save_button_and_the_agent_context():
	w = world()
	d = fr(w).as_dict()
	for k in ("name", "creation", "modified", "owner", "modified_by", "docstatus", "idx"):
		d.pop(k, None)
	for r in d["items"]:
		for k in ("name", "creation", "modified", "owner", "modified_by", "parent", "parentfield", "parenttype", "docstatus", "allowance_pct", "hold", "gross_qty", "net_qty", "order_qty"):
			r.pop(k, None)
	name = call("arinox_fabric_requisition_save_fabric_requisition", data=json.dumps(d, default=str))
	eq(frappe.db.get_value("Fabric Requisition", name, "docstatus"), 0)
	ctx = call("arinox_fabric_requisition_get_requisition_context", sales_order=w["so"].name)
	eq((ctx["customer"], len(ctx["styles"]), sorted(c["colour"] for c in ctx["styles"][0]["colours"])), (fx.customer(), 1, ["Black", "Navy"]))
	true(ctx["styles"][0]["tech_pack"], "tech pack named")
	frappe.get_doc("Fabric Requisition", name).submit()
	true(throws(lambda: call("arinox_fabric_requisition_save_fabric_requisition", data=json.dumps({"name": name})), "Only a draft"))


# ---------------------------------------------------------------- trims

def label_row(w, label, **kw):
	return dict({"trim_category": "Woven Label", "trim_item": label, "garment_qty": 1800, "qty_per_garment": 1}, **kw)


@test("requisitions")
def trim_lines_come_from_the_tech_pack_and_the_category_is_guessed():
	w = world()
	rows = call("arinox_trim_requisition_get_lines_from_sales_orders", doc=json.dumps({"customer": fx.customer(), "company": fx.company(), "items": []}),
				sales_orders=json.dumps([w["so"].name]))["arinox_doc"]["items"]
	eq(len(rows), 1)                                                             # the Neck label; the Jersey fabric belongs on the FR
	eq((rows[0]["trim_category"], rows[0]["garment_qty"], rows[0]["calc_basis"]), ("Woven Label", 1200, "Per Garment"))


@test("requisitions")
def trim_golden_numbers_and_bases():
	w = world()
	label = trim_item("HT-LBL-1", "Main label", "Woven Label")
	button = trim_item("HT-BTN-1", "18L shell button", "Button")
	thread = trim_item("HT-THR-1", "Thread", "Thread", "Meter")
	carton = trim_item("HT-CTN-1", "Carton", "Packaging")
	d = tr(w, [label_row(w, label)])
	d.insert()
	eq(d.items[0].order_qty, 1980)                                               # 1800 labels + 10%
	d = tr(w, [{"trim_category": "Button", "trim_item": button, "garment_qty": 1800, "qty_per_garment": 10, "spare_per_garment": 1}])
	d.insert()
	eq(d.items[0].order_qty, 21780)                                              # 1800 x (10 + 1) x 1.10
	true(d.name.startswith("TR") and len(d.name.split(".")) == 3, d.name)
	true(throws(lambda: tr(w, [label_row(w, label, calc_basis="Per Size")]).insert(), "needs the size"))
	d = tr(w, [label_row(w, label, calc_basis="Per Size", size="S", garment_qty=350)])
	d.insert()
	eq(d.items[0].order_qty, 385)
	d = tr(w, [label_row(w, label, colour="Navy", trim_colour="DTM", garment_qty=700)])
	d.insert()
	eq(d.items[0].trim_colour, "Navy")                                           # DTM resolves to the garment colour
	d = tr(w, [{"trim_category": "Packaging", "trim_item": carton, "calc_basis": "Per Carton", "garment_qty": 1200, "qty_per_garment": 1, "pcs_per_carton": 40}])
	d.insert()
	eq(d.items[0].order_qty, 31)                                                 # 30 cartons + 2% = 30.6 -> 31
	true(throws(lambda: tr(w, [{"trim_category": "Packaging", "trim_item": carton, "calc_basis": "Per Carton", "garment_qty": 1200, "qty_per_garment": 1}]).insert(), "pieces per carton"))
	d = tr(w, [{"trim_category": "Thread", "trim_item": thread, "calc_basis": "By Length", "garment_qty": 1800, "consumption": 150, "consumption_uom": "Meter", "pack_size": 5000}])
	d.insert()
	true(abs(d.items[0].gross_qty - 1800 * 150 * 1.02) < 0.01, d.items[0].gross_qty)
	eq(d.items[0].order_qty, 280000)
	true(throws(lambda: tr(w, [label_row(w, label, allowance_pct=15)]).insert(), "differs from the rule"))


@test("requisitions")
def trim_hold_supplier_rule_buyer_supplied_and_revision():
	w = world()
	label = trim_item("HT-LBL-2", "Main label", "Woven Label")
	tag = trim_item("HT-TAG-1", "Buyer hang tag", "Hang Tag", provided=1)
	frappe.db.delete("Sample Approval", {"sample_type": "Bulk Trim", "style_item": w["template"]})
	d = tr(w, [label_row(w, label)])
	d.insert()
	eq(d.items[0].hold, 1)
	true("trim approval" in d.red_flags.lower(), d.red_flags)
	nosup = tr(w, [label_row(w, label, supplier=None)])
	nosup.insert()
	true(throws(lambda: nosup.submit(), "choose a supplier"))
	d = tr(w, [label_row(w, label), {"trim_category": "Hang Tag", "trim_item": tag, "garment_qty": 1200, "qty_per_garment": 1, "customer_provided": 1, "supplier": None}])
	d.insert()
	d.submit()
	types = sorted({frappe.db.get_value("Material Request", m.parent, "material_request_type") for m in mrs_of(d.name)})
	eq(types, ["Customer Provided", "Purchase"])
	true(frappe.db.get_value("Material Request Item", {"apparel_requisition": d.name, "item_code": label}, "apparel_hold_reason"), "no bulk trim approval on this order")
	rev = revise(d.name, "arinox_trim_requisition_revise_trim_requisition")
	rev.revision_reason = "PO +200"
	rev.items[0].garment_qty = 2000
	rev.insert()
	rev.submit()
	eq(sum(flt(i.stock_qty) for i in mrs_of(rev.name) if i.item_code == label), 220)       # 200 more garments x 1.10
	d.reload()
	eq(d.status, "Superseded")
