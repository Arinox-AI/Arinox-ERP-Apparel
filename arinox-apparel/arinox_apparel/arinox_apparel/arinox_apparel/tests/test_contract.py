# Copyright (c) 2026, Arinox AI and contributors

import re

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet import make_price_negotiation
from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import (
	get_default_company,
	make_quotation,
)
from arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract import make_sales_contract, make_sales_order
from arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack import create_style_item

CONTRACT_NO = re.compile(r"^[A-Z]+\d{2}\.\d{2}\.\d{3}$")


class TestSalesContract(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		u.setup_masters()
		frappe.db.set_value("Company", get_default_company(), "apparel_contract_prefix", None)
		frappe.db.set_single_value("Apparel Settings", "contract_prefix", "SC")

	def quoted_contract(self, style_no):
		tp = u.make_tech_pack(style_no=style_no)
		create_style_item(tp.name)
		tp.reload()
		cs = u.make_cost_sheet(tech_pack=tp, submit=True)
		pn = frappe.get_doc("Price Negotiation", make_price_negotiation(cs.name))
		pn.append("rounds", {"cost_sheet": cs.name, "direction": "Buyer Counter", "price": 13.90})
		pn.append("rounds", {"cost_sheet": cs.name, "direction": "Agreed", "price": u.AGREED_PRICE, "qty": 1200})
		pn.save()
		self.assertEqual(pn.status, "Agreed")
		self.assertEqual(pn.styles[0].agreed_price, u.AGREED_PRICE)
		q = make_quotation(pn.name)
		q.insert()
		q.submit()
		pn.reload()
		self.assertEqual(pn.rounds[-1].quotation, q.name)  # submit logged a round
		sc = make_sales_contract(q.name)
		return sc, q

	def fill(self, sc, navy=700, black=500):
		ex = add_days(nowdate(), 60)
		for it in sc.items:
			it.qty = navy if it.colour == "Navy" else black
			it.ex_factory_date = ex
		per = {"Navy": [200, 300, 200], "Black": [150, 200, 150]}
		for colour, qtys in per.items():
			for s, q in zip([s for s in sc.sizes if s.colour == colour], qtys):
				s.qty = q
		sc.buyer_po_no = "PO-AT-1"
		return sc

	def test_full_flow_to_sales_order(self):
		sc, q = self.quoted_contract("_AT-FLOW")
		self.assertEqual(len(sc.items), 2)  # one line per tech-pack colour
		self.assertEqual(len(sc.sizes), 6)
		self.assertEqual(sc.payment_basis, "Days after Receipt of Goods (ROG)")  # from the template
		self.fill(sc).insert()
		line = sc.items[0]
		self.assertEqual(str(line.etd), add_days(line.ex_factory_date, 7))
		self.assertEqual(str(line.in_warehouse_date), add_days(line.etd, 30))
		self.assertEqual(next(i for i in sc.items if i.colour == "Navy").tolerance_pct, 10)  # 501-800 pcs
		self.assertEqual(next(i for i in sc.items if i.colour == "Black").tolerance_pct, 15)  # up to 500 pcs
		self.assertEqual(sc.total_qty, 1200)
		sc.submit()
		self.assertEqual(sc.status, "Signed")
		self.assertRegex(sc.name, CONTRACT_NO)
		self.assertTrue(sc.name.startswith("SC"))

		so = make_sales_order(sc.name)
		self.assertEqual(len(so.items), 6)
		self.assertTrue(all(frappe.db.get_value("Item", i.item_code, "variant_of") for i in so.items))
		so.insert()
		so.submit()
		sc.reload()
		self.assertEqual(sc.sales_order, so.name)
		self.assertEqual(sc.status, "Ordered")
		self.assertRaises(frappe.ValidationError, make_sales_order, sc.name)
		self.assertRaises(frappe.ValidationError, sc.cancel)

	def test_contract_number_uses_the_issuing_company_prefix_and_restarts_monthly(self):
		company = get_default_company()
		self.addCleanup(frappe.db.set_value, "Company", company, "apparel_contract_prefix", None)
		frappe.db.set_value("Company", company, "apparel_contract_prefix", "TESTCO")
		sc1, _q = self.quoted_contract("_AT-NUM1")
		sc2, _q = self.quoted_contract("_AT-NUM2")
		for sc in (sc1, sc2):
			self.fill(sc).insert()
		self.assertRegex(sc1.name, CONTRACT_NO)
		self.assertTrue(sc1.name.startswith("TESTCO"))
		self.assertEqual(int(sc2.name[-3:]), int(sc1.name[-3:]) + 1)
		yy_mm = sc1.name[len("TESTCO"):len("TESTCO") + 5]
		self.assertEqual(yy_mm, frappe.utils.getdate(sc1.contract_date).strftime("%y.%m"))
		# an October contract starts again at 001
		frappe.db.set_value("Company", company, "apparel_contract_prefix", "TESTCO2")
		sc3, _q = self.quoted_contract("_AT-NUM3")
		self.fill(sc3)
		sc3.contract_date = "2027-10-15"
		sc3.insert()
		self.assertEqual(sc3.name, "TESTCO227.10.001")

	def test_amendment_counts_the_revision(self):
		sc, q = self.quoted_contract("_AT-REV")
		self.fill(sc).insert()
		self.assertEqual(sc.revision_no, 0)
		sc.submit()
		sc.cancel()
		amended = frappe.copy_doc(sc)
		amended.docstatus = 0
		amended.amended_from = sc.name
		amended.revised_for = "Quantity change"
		amended.insert()
		self.assertEqual(amended.revision_no, 1)
		self.assertEqual(amended.name, sc.name + "-1")

	def test_bank_account_comes_from_the_company(self):
		sc, q = self.quoted_contract("_AT-BANK")
		self.fill(sc)
		company = sc.company
		account = frappe.db.get_value("Bank Account", {"is_company_account": 1, "company": company}, "name")
		if not account:
			self.skipTest("no company bank account on the dev site")
		frappe.db.set_value("Company", company, "default_bank_account", account)
		sc.insert()
		self.assertEqual(sc.bank_account, account)

	def test_price_lock(self):
		sc, q = self.quoted_contract("_AT-LOCK")
		self.fill(sc)
		sc.items[0].rate = u.AGREED_PRICE + 0.30
		self.assertRaises(frappe.ValidationError, sc.insert)

	def test_size_breakdown_must_match(self):
		sc, q = self.quoted_contract("_AT-SIZE")
		self.fill(sc).insert()
		sc.sizes[0].qty += 1
		sc.save()
		self.assertRaises(frappe.ValidationError, sc.submit)

	def test_one_po_can_ship_to_several_destinations(self):
		sc, q = self.quoted_contract("_AT-SHIP")
		self.fill(sc)
		first = sc.sizes[0]  # Navy S: 200 pcs
		first.qty, first.ship_to = 150, "NADC-TM"
		sc.append("sizes", {"style_item": first.style_item, "colour": first.colour, "size": first.size, "qty": 50,
							"ship_to": "MARKETING"})
		sc.insert()
		sc.submit()
		so = make_sales_order(sc.name)
		self.assertEqual(len(so.items), 7)
		self.assertEqual({i.apparel_ship_to for i in so.items if i.apparel_ship_to}, {"NADC-TM", "MARKETING"})
		# the same size to the same destination twice is an entry error
		sc2, q2 = self.quoted_contract("_AT-SHIP2")
		self.fill(sc2)
		dup = sc2.sizes[0]
		sc2.append("sizes", {"style_item": dup.style_item, "colour": dup.colour, "size": dup.size, "qty": 5})
		self.assertRaises(frappe.ValidationError, sc2.insert)

	def test_payment_terms_are_required_to_sign(self):
		sc, q = self.quoted_contract("_AT-PAY")
		self.fill(sc)
		sc.payment_basis, sc.payment_days, sc.payment_terms_template = None, 0, None
		sc.insert()
		self.assertRaises(frappe.ValidationError, sc.submit)

	def test_placeholder_blocks_signing(self):
		sc, q = self.quoted_contract("_AT-TBA")
		self.fill(sc)
		sc.port_of_discharge = "TBA"
		sc.insert()
		self.assertRaises(frappe.ValidationError, sc.submit)

	def test_max_skus(self):
		sc, q = self.quoted_contract("_AT-SKU")
		self.fill(sc)
		for i in range(7):
			sc.append("items", {"style_item": sc.items[0].style_item, "colour": f"Extra {i}", "qty": 10, "rate": u.AGREED_PRICE})
		self.assertRaises(frappe.ValidationError, sc.insert)

	def test_quotation_below_floor_blocked(self):
		cs = u.make_cost_sheet(tech_pack=u.make_tech_pack(style_no="_AT-FLOOR"), submit=True)
		from arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet import make_quotation as cs_quote

		q = cs_quote(cs.name)
		q.items[0].rate = u.BELOW_FLOOR_PRICE
		self.assertRaises(frappe.ValidationError, q.insert)
