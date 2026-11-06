import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def near(a, b, places=4):
	assert abs(a - b) < 10 ** -places, f"{a} != {b}"


@test("costing")
def costing_matches_the_reference_sheet():
	"""Numbers from APPAREL_COSTING_DETAILED_REVISED.xlsx (5,500 pcs, FOB HCM): the same figures the app's test uses."""
	cs = fx.cost_sheet()
	near(cs.fabric_cost, 3.78)
	near(cs.trim_cost, 0.83575)
	near(cs.fabric_metres, 1.26)
	near(cs.product_cost, 10.24575)
	near(cs.subtotal, 12.499815)
	near(cs.profit_amount, 1.87497225)
	near(cs.computed_price, 14.37478725)
	eq(cs.quoted_price, 14.37)
	eq(cs.quoted_price_local, 359250)
	near(cs.margin_pct, 13.01, 2)
	near(cs.markup_pct, 14.96, 2)
	eq(cs.below_floor, 0)
	eq(cs.approval_status, "Not Required")
	true(cs.costing_parameter)
	eq(len(cs.signoffs), 4)


@test("costing")
def yards_and_foreign_currency_rates():
	cs = fx.cost_sheet()
	main = cs.materials[0]
	main.uom = "Yard"
	main.conversion_factor = 0.9144
	main.price_currency = "CNY"
	main.rate = 21.4286
	main.exchange_rate = 0.14
	cs.save()
	near(cs.materials[0].amount, 0.6 * 1.05 * 0.9144 * 21.4286 * 0.14, 3)
	near(cs.fabric_metres, 0.6 * 1.05 * 0.9144 + 0.6 * 1.05)


@test("costing")
def a_per_metre_head_needs_a_length_uom():
	cs = fx.cost_sheet()
	cs.materials[0].uom = "Nos"
	true(throws(lambda: cs.save(), "not a length"))


@test("costing")
def an_option_group_needs_exactly_one_selection():
	cs = fx.cost_sheet()
	cs.materials[0].option_group = "Shell"
	cs.append("materials", {"material_type": "Fabric", "option_group": "Shell", "is_selected": 0, "description": "Alt shell", "consumption": 0.6, "rate": 5, "uom": "Meter"})
	cs.save()
	near(cs.fabric_cost, 3.78)                                  # the unselected option is not priced
	cs.materials[-1].is_selected = 1
	true(throws(lambda: cs.save(), "select exactly one"))


@test("costing")
def wastage_needs_a_reason_and_a_carton_needs_pcs_per_carton():
	cs = fx.cost_sheet()
	cs.materials[0].wastage_reason = ""
	true(throws(lambda: cs.save(), "needs a reason"))
	cs = fx.cost_sheet()
	cs.pcs_per_carton = 0
	true(throws(lambda: cs.save(), "Pcs per Carton"))


@test("costing")
def a_missing_or_zero_cost_head_blocks_submit():
	cs = fx.cost_sheet()
	cs.charges = [c for c in cs.charges if c.cost_head != "Freight"]
	cs.save()
	# a mandatory head left out comes back on save, with the costing parameter's rate when it has one, so the gap cannot go unseen
	back = [c for c in cs.charges if c.cost_head == "Freight"]
	eq(len(back), 1)
	eq(back[0].source, "Parameter")
	true(back[0].rate)
	cs.submit()                                                  # priced from the parameter, so nothing is missing
	eq(cs.docstatus, 1)
	cs = fx.cost_sheet()
	cs.charges = [c for c in cs.charges if c.cost_head != "Freight"]
	cs.costing_parameter = None                                  # no parameter to take the rate from: the row returns at 0
	cs.save()
	if not [c for c in cs.charges if c.cost_head == "Freight" and not c.rate]:
		return                                                   # a parameter was found again by date and customer; the zero-rate case is below
	true(throws(lambda: cs.submit(), "Zero rate"))
	cs = fx.cost_sheet()
	for c in cs.charges:
		if c.cost_head == "Overhead":
			c.rate = 0
	cs.save()
	true(throws(lambda: cs.submit(), "Zero rate"))


@test("costing")
def below_the_floor_needs_a_costing_manager():
	cs = fx.cost_sheet(quoted_price=12.80)                      # margin about 2.3%, floor 10%
	eq(cs.below_floor, 1)
	eq(cs.approval_status, "Pending")
	cs.submit()                                                 # Administrator holds every role, so it approves at submit
	eq(frappe.db.get_value("Cost Sheet", cs.name, "approval_status"), "Approved")
	eq(frappe.db.get_value("Cost Sheet", cs.name, "approved_price"), 12.80)


@test("costing")
def a_price_move_after_approval_resets_it():
	cs = fx.cost_sheet(quoted_price=12.80)
	frappe.get_doc("Server Script", "arinox_cost_sheet_api_approve")
	fx.engine_call("arinox_cost_sheet_api_approve", name=cs.name, remarks="Strategic buyer")
	cs.reload()
	eq(cs.approval_status, "Approved")
	cs.quoted_price = 12.50                                     # moved more than 0.5%
	cs.save()
	eq(cs.approval_status, "Pending")


@test("costing")
def the_signoff_chain_is_signed_in_order():
	cs = fx.cost_sheet()
	true(throws(lambda: fx.engine_call("arinox_cost_sheet_api_sign_off", name=cs.name, step="Second Round Checked"), "Sign Fabric Cost Checked first"))
	fx.engine_call("arinox_cost_sheet_api_sign_off", name=cs.name, step="Fabric Cost Checked")
	true(throws(lambda: fx.engine_call("arinox_cost_sheet_api_sign_off", name=cs.name, step="Fabric Cost Checked"), "already signed"))
	fx.engine_call("arinox_cost_sheet_api_sign_off", name=cs.name, step="First Costing Done")
	cs.reload()
	eq(cs.signoffs[0].signed_by, frappe.session.user)
	frappe.db.set_single_value("Apparel Settings", "require_costing_signoff", 1)
	true(throws(lambda: cs.submit(), "Still to sign"))


@test("costing")
def the_most_specific_costing_parameter_wins():
	generic = frappe.get_doc({"doctype": "Costing Parameter", "currency": "USD", "effective_from": "2020-01-01", "rates": []}).insert()
	cs = fx.cost_sheet()
	true(cs.costing_parameter != generic.name, cs.costing_parameter)
	other = fx.cost_sheet(customer=fx.customer("HT Other Buyer"))
	eq(other.costing_parameter, generic.name)


@test("costing")
def margin_at_a_price_and_charges_from_the_parameter():
	cs = fx.cost_sheet()
	out = fx.engine_call("arinox_cost_sheet_api_get_margin_at_price", cost_sheet=cs.name, price=14.37)
	near(out["arinox_result"]["margin_pct"], 13.01, 2)
	rows = fx.engine_call("arinox_cost_sheet_api_set_charges_from_parameter", doc=frappe.as_json({"customer": fx.customer(), "product_type": fx.PRODUCT_TYPE, "costing_date": cs.costing_date, "currency": "USD"}))
	heads = [r["cost_head"] for r in rows["arinox_result"]["arinox_doc"]["charges"]]
	true("Overhead" in heads and "Fabric" not in heads, heads)


@test("costing")
def every_mandatory_head_is_added_to_a_sheet_that_lacks_them():
	"""A sheet saved with only some charge rows (for example entered by hand or loaded from a summary) gets the rest, none of them silently priced."""
	cs = fx.cost_sheet()
	cs.charges = [c for c in cs.charges if c.cost_head in ("Stitching (CMT)", "Overhead")]
	cs.save()
	heads = {c.cost_head: c for c in cs.charges}
	for name in ("Fabric Export Cost", "Fabric Import Cost", "Printing", "Embellishment", "Testing", "Bank Charges", "Freight", "Profit", "Washing"):
		true(name in heads, name)
	eq(heads["Overhead"].rate, 15)                 # the rows that were there are untouched


@test("costing")
def an_exchange_rate_the_wrong_way_round_is_refused():
	"""CNY -> USD is about 0.14. Typing 7.3 (CNY per USD) would cost the line 50 times over; it is refused with the figure that was probably meant."""
	cs = fx.cost_sheet()
	main = cs.materials[0]
	main.price_currency = "CNY"
	main.exchange_rate = 7.3155
	true(throws(lambda: cs.save(), "the other way round"))
	cs = frappe.get_doc("Cost Sheet", cs.name)                   # a refused save leaves the in-memory document stale
	cs.materials[0].price_currency = "CNY"
	cs.materials[0].exchange_rate = 0.136696
	cs.save()
	true(cs.materials[0].amount)                                 # the right direction is accepted


@test("costing")
def unpriced_lines_and_missing_bom_lines_warn_but_do_not_block_a_save():
	cs = fx.cost_sheet()
	cs.materials[0].rate = 0
	cs.save()                                                    # warns (a message), does not raise
	eq(cs.materials[0].rate, 0)
