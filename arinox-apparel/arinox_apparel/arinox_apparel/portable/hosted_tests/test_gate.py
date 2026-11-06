import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_allocation import order
from arinox_apparel.portable.hosted_tests.test_pp_meeting import call, meeting
from arinox_apparel.portable.hosted_tests.test_samples import sample
from arinox_apparel.portable.hosted_tests.test_tech_pack import tech_pack


def gate_order(rows=None, days=60):
	"""A style template with Navy and Black variants, a Tech Pack for it, and a submitted order on the variants (Navy 700, Black 500 unless `rows` says otherwise)."""
	frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 1)
	frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)
	template, navy = fx.variant_item("Navy", "M", code="HT-GATE-STYLE")
	black = fx.variant_item("Black", "M", code="HT-GATE-STYLE")[1]
	if not frappe.db.exists("Tech Pack", {"style_item": template}):
		tech_pack("HT-GATE-STYLE", style_item=template)
	so = order(rows or [("Navy", "M", 700, None), ("Black", "M", 500, None)], item_code={"Navy": navy, "Black": black}, days=days)
	return so, template, navy, black


def blockers(navy, so):
	return fx.engine_call("arinox_work_order_get_bulk_gate", production_item=navy, sales_order=so.name)["arinox_result"]["blockers"]


def approve_everything(so, template, colour="Navy"):
	for stype in ("Fit", "Bulk Trim"):
		sample(so, stype, style_item=template).insert()
	for stype in ("Lab Dip", "Bulk Fabric"):
		sample(so, stype, colour=colour, style_item=template).insert()
	pp = sample(so, "PP", in_bulk_fabric=1, style_item=template).insert()
	return pp, meeting(so, pp, style_item=template)


def bom_of(item):
	bom = frappe.get_doc({"doctype": "BOM", "item": item, "quantity": 1, "company": fx.company(), "rm_cost_as_per": "Valuation Rate",
						  "items": [{"item_code": fx.item(), "qty": 1, "uom": "Nos"}]}).insert()
	bom.submit()
	return bom.name


def work_order(so, item, qty=10, bom=None):
	"""A real ERPNext Work Order on the variant item (needs a BOM)."""
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	bom = type("B", (), {"name": bom or bom_of(item)})
	return frappe.get_doc({"doctype": "Work Order", "production_item": item, "bom_no": bom.name, "qty": qty, "company": fx.company(), "sales_order": so.name,
						   "wip_warehouse": wh, "fg_warehouse": wh, "source_warehouse": wh, "planned_start_date": nowdate()})


@test("gate")
def the_gate_lists_every_blocker_and_blocks_the_work_order():
	so, template, navy, black = gate_order()
	res = fx.engine_call("arinox_work_order_get_bulk_gate", production_item=navy, sales_order=so.name)["arinox_result"]
	eq((res["applies"], res["colour"], res["style"]), (True, "Navy", template))
	text = " | ".join(res["blockers"])
	for part in ("Fit", "Lab Dip (Navy)", "Bulk Fabric (Navy)", "Bulk Trim", "PP:", "PP Meeting"):
		true(part in text, "blocker mentioning %s in: %s" % (part, text))
	wo = work_order(so, navy).insert()
	true(throws(lambda: wo.submit(), "Bulk production is blocked"))


@test("gate")
def the_gate_opens_when_approvals_and_meeting_are_in():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template)
	true([b for b in blockers(navy, so) if "PP Meeting" in b], "the meeting is still missing")
	m.insert().submit()
	eq(blockers(navy, so), [])
	wo = work_order(so, navy).insert()
	wo.submit()
	eq(frappe.db.get_value("Work Order", wo.name, "docstatus"), 1)


@test("gate")
def the_gate_is_per_colour_for_lab_dip_and_bulk_fabric():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template, colour="Navy")
	m.insert().submit()
	text = " | ".join(blockers(black, so))
	true("Lab Dip (Black)" in text and "Bulk Fabric (Black)" in text, text)
	true("Fit" not in text, text)


@test("gate")
def a_rejected_sample_blocks_even_when_others_are_approved():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template)
	m.insert().submit()
	sample(so, "Strike Off", colour="Navy", decision="Rejected", style_item=template, comments=[{"round_no": 1, "comment": "Print off-register"}]).insert()
	true([b for b in blockers(navy, so) if "Strike Off" in b])


@test("gate")
def an_open_cutting_action_blocks_bulk_until_it_is_closed():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template)
	sample(so, "Size Set", decision="Approved with Comments", style_item=template, comments=[{"round_no": 1, "comment": "Armhole 0.5cm lower", "relevant_to_cutting": 1}]).insert()
	m.insert()
	m.set("actions", call("arinox_pp_meeting_get_buyer_comments", m)["arinox_doc"]["actions"])
	for a in m.actions:
		a.action_taken = "Pattern corrected"
		a.action_owner = "Administrator"
		a.target_date = add_days(nowdate(), 5)
	m.save()
	m.submit()
	true([b for b in blockers(navy, so) if "cutting comment still open" in b])
	m.actions[0].status = "Closed"
	m.save()
	eq(blockers(navy, so), [])


@test("gate")
def a_manager_may_override_with_a_reason():
	so, template, navy, black = gate_order()
	merch = fx.user("ht_merch@example.com", ["Apparel Merchandiser"])
	manager = fx.user("ht_manager@example.com", ["Apparel Merchandiser", "Apparel Merchandising Manager"])
	bom = bom_of(navy)
	try:
		frappe.set_user(merch)
		wo = work_order(so, navy, bom=bom)
		wo.apparel_gate_override = 1
		wo.apparel_gate_override_reason = "Buyer verbal OK"
		wo.flags.ignore_permissions = True
		true(throws(lambda: wo.insert(), "Only an Apparel Merchandising Manager"))
		frappe.set_user(manager)
		wo = work_order(so, navy, bom=bom)
		wo.apparel_gate_override = 1
		wo.flags.ignore_permissions = True
		true(throws(lambda: wo.insert(), "Enter the reason"))
		wo = work_order(so, navy, bom=bom)
		wo.apparel_gate_override = 1
		wo.apparel_gate_override_reason = "Buyer verbal OK"
		wo.flags.ignore_permissions = True
		wo.insert()
		wo.submit()                                                         # blockers exist, the override lets it through
		eq(frappe.db.get_value("Work Order", wo.name, "docstatus"), 1)
	finally:
		frappe.set_user("Administrator")


@test("gate")
def the_gate_can_be_switched_off_and_ignores_other_items():
	so, template, navy, black = gate_order()
	frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 0)
	wo = work_order(so, navy).insert()
	wo.submit()                                                             # not enforced
	eq(frappe.db.get_value("Work Order", wo.name, "docstatus"), 1)
	res = fx.engine_call("arinox_work_order_get_bulk_gate", production_item=fx.item(), sales_order=so.name)["arinox_result"]
	eq(res["applies"], False)                                               # a plain item is not an apparel style variant


@test("gate")
def a_pilot_run_is_required_for_bulk_when_the_production_card_says_so():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template)
	m.insert().submit()
	frappe.db.set_single_value("Apparel Settings", "pilot_min_order_qty", 100)       # the card asks for a pilot from 100 pieces (default 1000)
	card = frappe.get_doc({"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": so.name, "style_item": template,
						   "pilot_required": 1, "lines": [{"colour": "Navy", "size": "M"}]}).insert()
	card.submit()
	eq(frappe.db.get_value("Production Card", card.name, "pilot_required"), 1)
	true([b for b in blockers(navy, so) if "Pilot Run: no pilot run recorded" in b], str(blockers(navy, so)))
	pilot = fx.engine_call("arinox_engine", action="bulk_gate", sales_order=so.name, style=template, colour="Navy", stage="pilot")["arinox_result"]
	eq(pilot["blockers"], [])                                               # the pilot stage does not need a pilot run
	frappe.db.set_value("Production Card", card.name, "pilot_waiver", 1)
	eq(blockers(navy, so), [])


@test("gate")
def a_customer_waiver_and_a_split_po_exemption_open_the_gate():
	so, template, navy, black = gate_order()
	frappe.get_doc({"doctype": "Sample Requirement", "sample_type": "PP", "customer": fx.customer(), "gate": "No"}).insert()
	true("PP:" not in " | ".join(blockers(navy, so)), "PP waived by this buyer")
	frappe.get_doc({"doctype": "Sample Requirement", "sample_type": "Bulk Trim", "customer": fx.customer(), "split_po_exempt": 1}).insert()
	true("Bulk Trim" in " | ".join(blockers(navy, so)), "single destination: still required")
	split = gate_order([("Navy", "M", 400, "DC1"), ("Navy", "S", 300, "DC2"), ("Black", "M", 500, None)])[0]
	true("Bulk Trim" not in " | ".join(blockers(navy, split)), "ships to two destinations: exempt")


@test("gate")
def materials_block_bulk_until_the_accepted_quantity_is_in():
	so, template, navy, black = gate_order()
	pp, m = approve_everything(so, template)
	m.insert().submit()
	eq(blockers(navy, so), [])
	# a submitted fabric requisition line with nothing accepted yet (the requisition's own rules are not ported yet, so it is made directly)
	fr = frappe.get_doc({"doctype": "Fabric Requisition", "company": fx.company(), "customer": fx.customer(), "items": [
		{"sales_order": so.name, "style_item": template, "style_no": template, "colour": "Navy", "fabric_item": fx.item(), "net_qty": 100, "accepted_qty": 0}]})
	fr.flags.ignore_mandatory = True
	fr.flags.ignore_validate = True
	fr.insert()
	frappe.db.set_value("Fabric Requisition", fr.name, {"docstatus": 1, "status": "Approved"})
	text = " | ".join(blockers(navy, so))
	true("Fabric %s: 0.0 m of 100.0 m accepted" % fx.item() in text, text)
	true("Fabric %s:" % fx.item() not in " | ".join(blockers(black, so)), "Black has no fabric line")
	frappe.db.set_value("Fabric Requisition Item", {"parent": fr.name}, "accepted_qty", 100)
	eq(blockers(navy, so), [])
	frappe.db.set_single_value("Apparel Settings", "material_gate_fabric", "Warn")
	frappe.db.set_value("Fabric Requisition Item", {"parent": fr.name}, "accepted_qty", 40)
	eq(blockers(navy, so), [])                                                                      # Warn: listed as a warning, not a blocker
	res = fx.engine_call("arinox_engine", action="bulk_gate", sales_order=so.name, style=template, colour="Navy", stage="bulk")["arinox_result"]
	true("40.0 m of 100.0 m accepted" in " | ".join(res["warnings"]), str(res["warnings"]))


@test("gate")
def an_order_with_no_fabric_requisition_gets_a_warning_not_a_silent_pass():
	so, template, navy, black = gate_order()
	res = fx.engine_call("arinox_work_order_get_bulk_gate", production_item=navy, sales_order=so.name)["arinox_result"]
	true([w for w in res["warnings"] if "no approved Fabric Requisition" in w], res["warnings"])       # it used to say nothing at all
	true(not [b for b in res["blockers"] if "Fabric:" in b], res["blockers"])                          # free-issue fabric is allowed: a warning, not a block
