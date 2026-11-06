import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_contract import contract


def order(item_code, **kw):
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	return frappe.get_doc({"doctype": "Sales Order", "customer": fx.customer(), "company": fx.company(), "delivery_date": add_days(nowdate(), 60),
						   "items": [{"item_code": item_code, "qty": 10, "rate": 10, "delivery_date": add_days(nowdate(), 60), "warehouse": wh}], **kw})


@test("order")
def a_hand_typed_order_gets_colour_and_size_from_the_variant():
	template, variant = fx.variant_item("Navy", "M")
	so = order(variant).insert()
	eq(so.items[0].apparel_colour, "Navy")
	eq(so.items[0].apparel_size, "M")


@test("order")
def a_contract_must_be_signed_and_belong_to_the_customer():
	sc = contract(300).insert()                       # not signed
	true(throws(lambda: order(fx.item(), apparel_sales_contract=sc.name).insert(), "not signed"))
	sc.submit()
	other = fx.customer("HT Other Buyer")
	true(throws(lambda: order(fx.item(), customer=other, apparel_sales_contract=sc.name).insert(), "is for"))


@test("order")
def the_order_fills_dates_tolerance_and_po_from_its_one_contract_line():
	sc = contract(300)
	sc.items[0].buyer_po_code = "PO-A/1"
	sc.sizes[0].buyer_po_no = "PO-A/1"
	sc.insert()
	sc.submit()
	so = order(fx.item(), apparel_sales_contract=sc.name)
	so.items[0].apparel_colour = "Navy"
	so.insert()
	eq(so.items[0].apparel_buyer_po, "PO-A/1")
	true(so.items[0].apparel_etd, "etd filled from the line")


@test("order")
def a_contract_has_one_live_order_and_submit_and_cancel_move_its_status():
	sc = contract(300).insert()
	sc.submit()
	so = order(fx.item(), apparel_sales_contract=sc.name).insert()
	so.submit()
	eq(frappe.db.get_value("Sales Contract", sc.name, "status"), "Ordered")
	eq(frappe.db.get_value("Sales Contract", sc.name, "sales_order"), so.name)
	second = order(fx.item(), apparel_sales_contract=sc.name)
	true(throws(lambda: second.insert(), "already has Sales Order"))
	so.cancel()
	eq(frappe.db.get_value("Sales Contract", sc.name, "status"), "Signed")
