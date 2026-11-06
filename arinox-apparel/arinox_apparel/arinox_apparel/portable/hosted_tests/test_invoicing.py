import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_contract import contract


def shipped_note(with_contract=None):
	card, pl, dn = fx.delivery_chain()
	if with_contract:
		frappe.db.set_value("Sales Order", card.sales_order, "apparel_sales_contract", with_contract)
		dn.save()
	dn.submit()
	return card, pl, dn


def prepare(sh):
	return fx.engine_call("arinox_invoicing_prepare_invoices", shipment=sh.name)["arinox_result"]


@test("invoicing")
def the_direct_route_drafts_one_invoice_numbered_from_the_contract_or_order():
	card, pl, dn = shipped_note()
	sh = fx.shipment([dn])
	made = prepare(sh)
	eq(len(made), 1)
	si = frappe.get_doc("Sales Invoice", made[0])
	eq((si.docstatus, si.apparel_route_leg, si.apparel_shipment), (0, 1, sh.name))
	true("-INV-" in si.apparel_commercial_invoice_no, si.apparel_commercial_invoice_no)
	eq(si.total_qty, 100)
	eq(si.apparel_all_contracts, card.sales_order)                              # no contract: the order stands in


@test("invoicing")
def running_it_again_replaces_the_draft_and_keeps_the_number():
	card, pl, dn = shipped_note()
	sh = fx.shipment([dn])
	first = frappe.get_doc("Sales Invoice", prepare(sh)[0]).apparel_commercial_invoice_no
	again = prepare(sh)
	eq(len(again), 1)
	eq(frappe.get_doc("Sales Invoice", again[0]).apparel_commercial_invoice_no, first)
	eq(frappe.db.count("Sales Invoice", {"apparel_shipment": sh.name, "docstatus": ["<", 2]}), 1)


@test("invoicing")
def submit_invoices_submits_and_a_later_prepare_leaves_them_alone():
	card, pl, dn = shipped_note()
	sh = fx.shipment([dn])
	prepare(sh)
	done = fx.engine_call("arinox_invoicing_submit_invoices", shipment=sh.name)["arinox_result"]
	eq(len(done), 1)
	eq(frappe.db.get_value("Sales Invoice", done[0], "docstatus"), 1)
	true(frappe.db.get_value("Sales Invoice", done[0], "apparel_expected_due_date"))
	eq(prepare(sh), [])                                                         # submitted invoices are left as they are
	true(throws(lambda: fx.engine_call("arinox_invoicing_submit_invoices", shipment=sh.name), "no draft invoices"))


@test("invoicing")
def a_delivery_note_must_be_submitted_before_it_is_invoiced():
	card, pl, dn = fx.delivery_chain()
	sh = fx.shipment([dn])
	true(throws(lambda: prepare(sh), "must be submitted"))


@test("invoicing")
def the_group_route_makes_two_invoices_with_one_number_and_a_transfer_price():
	trader = fx.trading_company()
	buyer = frappe.get_doc("Customer", fx.customer())
	buyer.apparel_invoice_via_company = trader
	buyer.apparel_transfer_basis = "Percent of Customer Price"
	buyer.apparel_transfer_pct = 40
	buyer.save()
	card, pl, dn = shipped_note()
	sh = fx.shipment([dn])
	made = prepare(sh)
	eq(len(made), 2)
	one, two = [frappe.get_doc("Sales Invoice", n) for n in made]
	eq((one.apparel_route_leg, one.company, one.customer), (1, fx.company(), trader))
	eq((two.apparel_route_leg, two.company, two.customer), (2, trader, fx.customer()))
	eq(one.apparel_commercial_invoice_no, two.apparel_commercial_invoice_no)
	eq(one.items[0].rate, 4.0)                                                  # 40% of the order price of 10
	eq(two.items[0].rate, 10.0)


@test("invoicing")
def the_contract_decides_the_expected_due_date_from_the_delivery():
	sc = contract(300).insert()
	sc.submit()                                                                 # payment: 15 days after receipt of goods
	card, pl, dn = shipped_note(with_contract=sc.name)
	sh = fx.shipment([dn], apparel_delivery_date=add_days(nowdate(), -20))
	made = prepare(sh)
	si = frappe.get_doc("Sales Invoice", made[0])
	eq(si.apparel_sales_contract, sc.name)
	eq(str(si.apparel_expected_due_date), add_days(nowdate(), -5))             # delivery + 15 days
	eq(si.apparel_basis_source, "Delivery")
	sh.reload()
	sh.apparel_delivery_date = add_days(nowdate(), -10)                        # a later delivery date moves the due date
	sh.save()
	eq(str(frappe.db.get_value("Sales Invoice", made[0], "apparel_expected_due_date")), add_days(nowdate(), 5))


@test("invoicing")
def follow_up_status_reminders_and_promises():
	sc = contract(300).insert()
	sc.submit()
	card, pl, dn = shipped_note(with_contract=sc.name)
	sh = fx.shipment([dn], apparel_delivery_date=add_days(nowdate(), -40))     # due 25 days ago
	fx.engine_call("arinox_invoicing_prepare_invoices", shipment=sh.name)
	done = fx.engine_call("arinox_invoicing_submit_invoices", shipment=sh.name)["arinox_result"]
	fx.run_scheduled("arinox_followup_daily")
	row = frappe.db.get_value("Sales Invoice", done[0], ["apparel_followup_status", "apparel_days_overdue"], as_dict=True)
	eq((row.apparel_followup_status, row.apparel_days_overdue), ("Overdue", 25))
	true(frappe.db.exists("ToDo", {"reference_type": "Sales Invoice", "reference_name": done[0], "description": ["like", "%overdue-15%"]}))
	fx.run_scheduled("arinox_followup_daily")                                     # a second run does not raise the same reminder again
	eq(frappe.db.count("ToDo", {"reference_type": "Sales Invoice", "reference_name": done[0], "description": ["like", "%overdue-15%"]}), 1)
	true(throws(lambda: fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="x", promise_date=add_days(nowdate(), -2), promise_amount=100), "in the past"))
	true(throws(lambda: fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="x", promise_date=add_days(nowdate(), 3), promise_amount=0), "amount the buyer promised"))
	true(throws(lambda: fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="x", promise_date=add_days(nowdate(), 3), promise_amount=99999999), "still owed"))
	status = fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="Buyer promised to pay", promise_date=add_days(nowdate(), 3), promise_amount=500)["arinox_result"]
	eq(status, "Promised")
	status = fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="Wrong sizes", dispute_reason="Sizes wrong")["arinox_result"]
	eq(status, "Disputed")
	true(throws(lambda: fx.engine_call("arinox_followup_log_follow_up", invoice=done[0], note="  "), "Write what was said"))
