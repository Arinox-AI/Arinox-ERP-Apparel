# Copyright (c) 2026, Arinox AI and contributors

import frappe
from frappe.tests import IntegrationTestCase

from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet import (
	approve,
	find_costing_parameter,
	get_costing_context,
	make_price_negotiation,
	make_quotation,
	sign_off,
)


class TestCostSheet(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		u.setup_masters()

	def test_costing_matches_the_reference_sheet(self):
		"""Numbers from APPAREL_COSTING_DETAILED_REVISED.xlsx (5,500 pcs, FOB HCM)."""
		cs = u.make_cost_sheet()
		self.assertAlmostEqual(cs.fabric_cost, 3.78, places=4)  # 2 x 0.6 m x 1.05 x 3
		self.assertAlmostEqual(cs.trim_cost, 0.83575, places=4)  # includes carton = 1/40 x 0.15
		self.assertAlmostEqual(cs.fabric_metres, 1.26, places=4)
		# export + import 2 x 1.26 x 0.25 = 0.63; CMT 5  ->  product cost 10.24575
		self.assertAlmostEqual(cs.product_cost, 10.24575, places=4)
		# 22% of product cost (3+1+1+2+15) = 2.254065  ->  cost before profit 12.499815
		self.assertAlmostEqual(cs.subtotal, u.COST_BEFORE_PROFIT, places=4)
		self.assertAlmostEqual(cs.profit_amount, 1.87497225, places=4)  # 15% markup on cost
		self.assertAlmostEqual(cs.computed_price, u.FOB_UNROUNDED, places=4)
		self.assertEqual(cs.quoted_price, 14.37)
		self.assertEqual(cs.quoted_price_local, 359250)  # 14.37 x 25,000 VND
		# margin is on the price, markup on the cost
		self.assertAlmostEqual(cs.margin_pct, 13.01, places=2)
		self.assertAlmostEqual(cs.markup_pct, 14.96, places=2)
		self.assertEqual(cs.below_floor, 0)
		self.assertEqual(cs.approval_status, "Not Required")
		self.assertTrue(cs.costing_parameter)
		self.assertEqual(len(cs.signoffs), 4)

	def test_yards_and_foreign_currency_rates(self):
		cs = u.make_cost_sheet()
		main = cs.materials[0]
		main.uom, main.conversion_factor = "Yard", 0.9144  # consumption in yards, rate per metre
		main.price_currency, main.rate, main.exchange_rate = "CNY", 21.4286, 0.14  # RMB per metre -> USD
		cs.save()
		self.assertAlmostEqual(main.amount, 0.6 * 1.05 * 0.9144 * 21.4286 * 0.14, places=3)
		self.assertAlmostEqual(cs.fabric_metres, 0.6 * 1.05 * 0.9144 + 0.6 * 1.05, places=4)

	def test_per_metre_head_needs_a_length_uom(self):
		cs = u.make_cost_sheet()
		cs.materials[0].uom = "Nos"
		self.assertRaises(frappe.ValidationError, cs.save)

	def test_option_group_needs_exactly_one_selection(self):
		cs = u.make_cost_sheet()
		cs.materials[0].option_group = "Shell"
		cs.append("materials", {"material_type": "Fabric", "option_group": "Shell", "is_selected": 0,
								"description": "Alt shell", "consumption": 0.6, "rate": 5, "uom": "Meter"})
		cs.save()  # one selected: fine
		self.assertAlmostEqual(cs.fabric_cost, 3.78, places=4)  # the unselected option is not priced
		cs.materials[-1].is_selected = 1
		self.assertRaises(frappe.ValidationError, cs.save)

	def test_wastage_needs_reason(self):
		cs = u.make_cost_sheet()
		cs.materials[0].wastage_reason = ""
		self.assertRaises(frappe.ValidationError, cs.save)

	def test_carton_needs_pcs_per_carton(self):
		cs = u.make_cost_sheet()
		cs.pcs_per_carton = 0
		self.assertRaises(frappe.ValidationError, cs.save)

	def test_missing_cost_head_blocks_submit(self):
		cs = u.make_cost_sheet()
		cs.charges = [c for c in cs.charges if c.cost_head != "Freight"]
		cs.save()
		self.assertRaises(frappe.ValidationError, cs.submit)

	def test_zero_rate_without_na_blocks_submit(self):
		cs = u.make_cost_sheet()
		for c in cs.charges:
			if c.cost_head == "Overhead":
				c.rate = 0
		cs.save()
		self.assertRaises(frappe.ValidationError, cs.submit)

	def test_below_floor_needs_manager_approval(self):
		cs = u.make_cost_sheet(quoted_price=u.BELOW_FLOOR_PRICE)  # margin ~2.3%, floor 10%
		self.assertEqual(cs.below_floor, 1)
		self.assertEqual(cs.approval_status, "Pending")
		user = make_user("_at_merch@example.com", ["Apparel Merchandiser"])
		with self.set_user(user):
			doc = frappe.get_doc("Cost Sheet", cs.name)
			self.assertRaises(frappe.ValidationError, doc.submit)
			self.assertRaises(frappe.PermissionError, approve, cs.name)
		approve(cs.name, "Strategic buyer")  # Administrator holds every role
		cs.reload()
		self.assertEqual(cs.approval_status, "Approved")
		self.assertEqual(cs.approved_price, u.BELOW_FLOOR_PRICE)
		cs.quoted_price = 12.50  # moved more than 0.5% after approval
		cs.save()
		self.assertEqual(cs.approval_status, "Pending")

	def test_signoff_chain(self):
		cs = u.make_cost_sheet()
		self.assertRaises(frappe.ValidationError, sign_off, cs.name, "Second Round Checked")  # out of order
		sign_off(cs.name, "Fabric Cost Checked")
		self.assertRaises(frappe.ValidationError, sign_off, cs.name, "Fabric Cost Checked")  # already signed
		sign_off(cs.name, "First Costing Done")
		cs.reload()
		self.assertEqual(cs.signoffs[0].signed_by, frappe.session.user)

		frappe.db.set_single_value("Apparel Settings", "require_costing_signoff", 1)
		try:
			self.assertRaises(frappe.ValidationError, cs.submit)  # two steps still open
			sign_off(cs.name, "Second Round Checked")
			sign_off(cs.name, "Final Checked & Approved")
			cs.reload()
			cs.submit()
			self.assertEqual(cs.docstatus, 1)
		finally:
			frappe.db.set_single_value("Apparel Settings", "require_costing_signoff", 0)

	def test_parameter_specificity(self):
		generic = frappe.get_doc({"doctype": "Costing Parameter", "currency": u.CURRENCY,
								  "effective_from": "2020-01-01", "rates": []}).insert()
		self.assertNotEqual(find_costing_parameter(u.CUSTOMER, u.PRODUCT_TYPE, None, u.CURRENCY), generic.name)
		self.assertEqual(find_costing_parameter(u.OTHER_CUSTOMER, u.PRODUCT_TYPE, None, u.CURRENCY), generic.name)
		generic.enabled = 0
		generic.save()

	def test_profit_must_be_a_percentage(self):
		head = frappe.get_doc("Cost Head", "Profit")
		head.calc_type = "Per Piece"
		self.assertRaises(frappe.ValidationError, head.save)

	def test_revision_number_follows_amendment(self):
		cs = u.make_cost_sheet(submit=True)
		cs.cancel()
		amended = frappe.copy_doc(cs)
		amended.docstatus = 0  # what the desk's Amend does
		amended.amended_from = cs.name
		amended.insert()
		self.assertEqual(amended.revision_no, 2)

	def test_negotiation_and_quotation_from_cost_sheet(self):
		cs = u.make_cost_sheet(submit=True)
		pn = frappe.get_doc("Price Negotiation", make_price_negotiation(cs.name))
		self.assertEqual(len(pn.styles), 1)
		self.assertEqual(pn.rounds[0].direction, "Our Offer")
		q = make_quotation(cs.name)
		self.assertEqual(q.items[0].apparel_cost_sheet, cs.name)
		self.assertEqual(q.items[0].rate, cs.quoted_price)

	def test_costing_context_for_ai_agent(self):
		u.make_cost_sheet(submit=True)
		ctx = get_costing_context(u.CUSTOMER, u.PRODUCT_TYPE, style_no="_AT-STY-1", currency=u.CURRENCY)
		self.assertTrue(ctx["costing_parameter"])
		self.assertTrue(ctx["previous_costings"])
		self.assertTrue(ctx["previous_costings"][0]["same_style"])


class TestTechPack(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		u.setup_masters()

	def test_same_pom_code_may_describe_two_measures(self):
		"""T210 is both 'shoulder seam forward at neck' and 'at armhole' on a real tech pack."""
		tp = u.make_tech_pack(style_no="_AT-POM", submit=False)
		for name in ("SHOULDER SEAM FORWARD AT NECK", "SHOULDER SEAM FORWARD AT ARMHOLE"):
			tp.append("measurements", {"pom_code": "T210", "point_of_measure": name, "size": "M", "value": 1,
									   "tolerance_plus": 0.125})
		tp.save()
		self.assertEqual(tp.measurements[-1].tolerance_minus, 0.125)  # one +/- figure fills both
		tp.append("measurements", {"pom_code": "T210", "point_of_measure": "SHOULDER SEAM FORWARD AT NECK",
								   "size": "M", "value": 2})
		self.assertRaises(frappe.ValidationError, tp.save)

	def test_latest_fit_round_sets_the_header_result(self):
		tp = u.make_tech_pack(style_no="_AT-FIT", submit=False)
		tp.append("fit_rounds", {"fit_round": "1st Fit", "round_date": "2026-03-04", "round_status": "AWC"})
		tp.append("fit_rounds", {"fit_round": "2nd Fit", "round_date": "2026-04-13", "round_status": "Approved"})
		tp.save()
		self.assertEqual(tp.fit_status, "Approved")

	def test_buyer_bom_row_keeps_the_buyer_codes(self):
		tp = u.make_tech_pack(style_no="_AT-BOM", submit=False)
		tp.append("materials", {"material_type": "Fusing", "description": "9930 LIGHT FUSING", "consumption": 0.2,
								"uom": "Yard", "buyer_item_code": "FUS001", "job_code": "(SO)", "size_applicability": "*"})
		tp.save()
		self.assertEqual(tp.materials[-1].buyer_item_code, "FUS001")


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "AT", "send_welcome_email": 0}).insert()
	else:
		user = frappe.get_doc("User", email)
	user.add_roles(*roles)
	return email
