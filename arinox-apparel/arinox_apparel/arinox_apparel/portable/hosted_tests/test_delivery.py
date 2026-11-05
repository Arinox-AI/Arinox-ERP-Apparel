import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def shipped(card):
	return frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card = %s and stage = 'SHIPPED'", card)[0][0]


@test("delivery")
def validate_copies_the_card_down_from_the_packing_list():
	card, pl, dn = fx.delivery_chain()
	eq(dn.items[0].apparel_production_card, card.name)


@test("delivery")
def an_accepted_lot_ships_and_posts_to_the_ledger():
	card, pl, dn = fx.delivery_chain()
	dn.submit()
	eq(shipped(card.name), 100)
	eq(frappe.db.get_value("Packing List", pl.name, "status"), "Shipped")
	eq(frappe.db.get_value("Production Card", card.name, "status"), "Shipped")


@test("delivery")
def no_final_inspection_blocks_shipping():
	card, pl, dn = fx.delivery_chain(inspection=None)
	true(throws(lambda: dn.submit(), "no final inspection"))


@test("delivery")
def a_rejected_inspection_blocks_shipping():
	card, pl, dn = fx.delivery_chain(inspection="Rejected")
	true(throws(lambda: dn.submit(), "Rejected"))


@test("delivery")
def a_manager_can_override_the_gate_with_a_reason():
	card, pl, dn = fx.delivery_chain(inspection=None)
	dn.apparel_gate_override = 1
	dn.save()
	true(throws(lambda: dn.submit(), "reason"))
	dn = frappe.get_doc("Delivery Note", dn.name)
	dn.apparel_gate_override_reason = "Buyer waived"
	dn.save()
	dn.submit()
	eq(shipped(card.name), 100)


@test("delivery")
def shipping_above_the_contract_allowance_is_refused():
	card, pl, dn = fx.delivery_chain(pcs=100, tolerance=5)
	dn.items[0].qty = 106                          # allowed up to 105
	dn.save()
	true(throws(lambda: dn.submit(), "allowed up to 105"))
	dn = frappe.get_doc("Delivery Note", dn.name)
	dn.items[0].qty = 105
	dn.save()
	frappe.db.sql("update `tabProduction Movement` set qty = 105 where production_card = %s and stage in ('CUT','SEW_IN','SEW_OUT','FIN_IN','FIN_A','PACKED')", card.name)
	dn.submit()
	eq(shipped(card.name), 105)


@test("delivery")
def cancel_takes_the_shipped_quantity_back_and_reopens_the_list():
	card, pl, dn = fx.delivery_chain()
	dn.submit()
	dn.cancel()
	eq(shipped(card.name), 0)
	eq(frappe.db.get_value("Packing List", pl.name, "status"), "Open")
