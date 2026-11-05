# Copyright (c) 2026, Arinox AI and contributors
"""Phase C: fabric requisition, trim requisition, purchasing extensions."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from arinox_apparel.arinox_apparel.doctype.fabric_requisition.fabric_requisition import (
	lines_for_sales_order,
	revise_fabric_requisition,
	row_key,
)
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.materials import common as mc
from arinox_apparel.materials.items import ensure_fabric_item


def make_supplier(name):
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert()
	return name


class MaterialsBase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = u.setup_masters()
		cls.so, cls.style, cls.sc = u.make_order("_AT-C1")
		cls.mill_a, cls.mill_b = make_supplier("_AT Mill A"), make_supplier("_AT Mill B")
		cls.navy_fabric = ensure_fabric_item("_ATQ-1", "Navy", "_ATQ-1, 100% Cotton, CW 132CM", 145, 132)
		cls.black_fabric = ensure_fabric_item("_ATQ-1", "Black", "_ATQ-1, 100% Cotton, CW 132CM", 145, 132)
		# Lab dip is a required gate in the default rules; approve it so nothing is on hold unless a test wants it
		cls.fr_seq = 0

	def tearDown(self):
		frappe.set_user("Administrator")

	def approve_lab_dips(self):
		for colour in ("Navy", "Black"):
			if not frappe.db.exists("Sample Approval", {"sample_type": "Lab Dip", "style_item": self.style, "colour": colour, "sales_order": self.so.name}):
				frappe.get_doc({
					"doctype": "Sample Approval", "sample_type": "Lab Dip", "style_item": self.style, "sales_order": self.so.name, "colour": colour,
					"material_description": "Jersey", "rounds": [{"sent_on": add_days(nowdate(), -3), "decision": "Approved", "decision_on": nowdate()}],
				}).insert()

	def fr(self, **kw):
		"""A draft FR with a fully-filled line per colour."""
		rows = lines_for_sales_order(self.so.name, u.CUSTOMER, self.company)
		for r in rows:
			r.update(cuttable_width_cm=132, gsm=145, consumption_source="Cost Sheet",
				fabric_item=self.navy_fabric if r["colour"] == "Navy" else self.black_fabric,
				fabric_description="_ATQ-1, 100% Cotton, CW 132CM", supplier=self.mill_a)
		rows.sort(key=lambda r: r["colour"], reverse=True)  # Navy first, then Black
		doc = frappe.get_doc({"doctype": "Fabric Requisition", "company": self.company, "customer": u.CUSTOMER, "items": rows, **kw})
		return doc

	def clean(self):
		for dt in ("Fabric Requisition", "Material Request"):
			for n in frappe.get_all(dt, pluck="name"):
				d = frappe.get_doc(dt, n)
				if d.docstatus == 1:
					d.flags.ignore_permissions = True
					d.cancel()
		frappe.db.delete("Fabric Requisition Item")
		frappe.db.delete("Fabric Requisition")


class TestFabricRequisition(MaterialsBase):
	def setUp(self):
		self.approve_lab_dips()

	def test_lines_come_from_the_tech_pack_and_order(self):
		rows = lines_for_sales_order(self.so.name, u.CUSTOMER, self.company)
		self.assertEqual({r["colour"]: r["garment_qty"] for r in rows}, {"Navy": 700, "Black": 500})
		self.assertTrue(all(r["consumption"] == 1.2 and r["consumption_uom"] == "Meter" for r in rows))
		self.assertTrue(all(r["material_role"] == "Shell" for r in rows))  # the Trim row is not on the FR

	def test_reference_golden_number(self):
		# FR Format Reference.xlsx row 1: 553 garments x 1.97 m x (1 + 5%) = 1143.8805 m
		doc = self.fr()
		doc.items[0].update(dict(garment_qty=553, consumption=1.97))
		doc.insert()
		self.assertAlmostEqual(doc.items[0].gross_qty, 1143.8805, places=3)
		self.assertAlmostEqual(doc.items[0].net_qty, 1143.8805, places=3)

	def test_total_is_computed_not_typed(self):
		doc = self.fr()
		doc.items[0].gross_qty = 1
		doc.items[0].net_qty = 1
		doc.insert()
		self.assertAlmostEqual(doc.items[0].net_qty, 700 * 1.2 * 1.05, places=3)

	def test_yards_and_kg(self):
		self.assertAlmostEqual(mc.to_metres(100, "Yard"), 91.44, places=4)
		self.assertAlmostEqual(mc.from_metres(91.44, "Yard"), 100, places=4)
		# 1 kg of 145 gsm fabric 132 cm wide = 1000 / (145 x 1.32) = 5.2247 m
		self.assertAlmostEqual(mc.to_metres(1, "Kg", 145, 132), 5.2247, places=3)
		self.assertRaises(frappe.ValidationError, mc.to_metres, 1, "Kg")
		self.assertEqual(mc.parse_width_cm('57"'), 144.8)
		self.assertEqual(mc.parse_width_cm("CW 132CM"), 132)

	def test_kg_line_needs_gsm_and_width_needs_a_value(self):
		doc = self.fr()
		doc.items[0].update(dict(consumption_uom="Kg", gsm=0))
		self.assertRaises(frappe.ValidationError, doc.insert)
		doc = self.fr()
		doc.items[0].cuttable_width_cm = 0
		self.assertRaises(frappe.ValidationError, doc.insert)
		doc = self.fr()
		doc.items[0].consumption_source = None
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_allowance_rule_and_reason(self):
		doc = self.fr()
		doc.items[0].allowance_pct = 8
		self.assertRaises(frappe.ValidationError, doc.insert)  # differs from the 5% rule, no reason
		doc = self.fr()
		doc.items[0].update(dict(allowance_pct=8, allowance_reason="Directional print"))
		doc.insert()
		self.assertAlmostEqual(doc.items[0].gross_qty, 700 * 1.2 * 1.08, places=3)

	def test_duplicate_line_rejected(self):
		doc = self.fr()
		doc.append("items", doc.items[0].as_dict(no_default_fields=True))
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_pack_size_rounding(self):
		self.assertEqual(mc.round_up_to_pack(1143.88, 50), 1150)
		self.assertEqual(mc.round_up_to_pack(1150, 50), 1150)
		self.assertEqual(mc.round_up_to_pack(10, 0), 10)

	def test_approval_hold_flag(self):
		frappe.db.delete("Sample Approval", {"sample_type": "Lab Dip", "style_item": self.style})
		doc = self.fr()
		doc.insert()
		self.assertTrue(all(r.hold for r in doc.items))
		self.assertIn("lab dip", doc.red_flags.lower())

	def test_costing_difference_flag(self):
		doc = self.fr()
		doc.items[0].update(dict(consumption=1.5, costed_consumption=1.2))
		doc.insert()
		self.assertIn("more than 5%", doc.red_flags)

	def test_submit_creates_material_requests_grouped_by_supplier(self):
		doc = self.fr()
		doc.items[1].supplier = self.mill_b
		doc.insert()
		doc.submit()
		mrs = {m.parent for m in frappe.get_all("Material Request Item", {"apparel_requisition": doc.name}, ["parent"])}
		self.assertEqual(len(mrs), 2)  # one per supplier
		item = frappe.get_all("Material Request Item", {"apparel_requisition": doc.name}, ["sales_order", "apparel_requisition_item", "qty", "apparel_style_no"])[0]
		self.assertEqual(item.sales_order, self.so.name)
		doc.reload()
		self.assertTrue(all(r.material_request for r in doc.items))
		self.assertEqual(doc.status, "Approved")

	def test_cancel_cancels_unordered_material_requests(self):
		doc = self.fr()
		doc.insert()
		doc.submit()
		mr = doc.items[0].material_request
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Material Request", mr, "docstatus"), 2)

	def test_revision_requests_only_the_increase_and_flags_a_decrease(self):
		doc = self.fr()
		doc.insert()
		doc.submit()
		first_total = sum(flt(r.net_qty) for r in doc.items)
		rev = revise_fabric_requisition(doc.name)
		rev.revision_reason = "Buyer PO revision: +100 Navy"
		rev.items[0].garment_qty = 800
		rev.items[1].garment_qty = 400  # decrease
		rev.insert()
		self.assertIn("Reduce the order", rev.red_flags)
		rev.submit()
		new_qty = sum(flt(i.stock_qty) for i in frappe.get_all("Material Request Item", {"apparel_requisition": rev.name}, ["stock_qty"]))
		self.assertAlmostEqual(new_qty, 100 * 1.2 * 1.05, places=2)  # only the Navy increase
		doc.reload()
		self.assertEqual(doc.status, "Superseded")
		# cancelling the revision brings the original back
		rev.cancel()
		doc.reload()
		self.assertEqual(doc.status, "Approved")

	def test_revision_needs_a_reason(self):
		doc = self.fr()
		doc.insert()
		doc.submit()
		rev = revise_fabric_requisition(doc.name)
		self.assertRaises(frappe.ValidationError, rev.insert)

	def test_stock_claim_cannot_be_used_twice(self):
		wh = mc.company_warehouse("store_warehouse_fabric", self.company)
		frappe.get_doc({"doctype": "Bin", "item_code": self.navy_fabric, "warehouse": wh, "actual_qty": 100}).insert(ignore_permissions=True)
		try:
			a = self.fr()
			a.items[0].update(dict(stock_warehouse=wh, stock_used=80))
			a.insert()
			a.submit()
			b = self.fr()
			b.items[0].update(dict(stock_warehouse=wh, stock_used=50))  # only 20 m is free now
			self.assertRaises(frappe.ValidationError, b.insert)
			b.items[0].stock_used = 20
			b.insert()
		finally:
			frappe.db.delete("Bin", {"item_code": self.navy_fabric, "warehouse": wh})

	def test_stock_reduces_the_net_requirement(self):
		wh = mc.company_warehouse("store_warehouse_fabric", self.company)
		frappe.get_doc({"doctype": "Bin", "item_code": self.black_fabric, "warehouse": wh, "actual_qty": 100}).insert(ignore_permissions=True)
		try:
			doc = self.fr()
			doc.items[1].update(dict(stock_warehouse=wh, stock_used=100))
			doc.insert()
			self.assertAlmostEqual(doc.items[1].net_qty, 500 * 1.2 * 1.05 - 100, places=3)
		finally:
			frappe.db.delete("Bin", {"item_code": self.black_fabric, "warehouse": wh})

	def test_wrong_customer_order_rejected(self):
		doc = self.fr()
		doc.customer = u.OTHER_CUSTOMER
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_number_format_restarts_monthly(self):
		doc = self.fr()
		doc.insert()
		self.assertRegex(doc.name, r"^FR\d{2}\.\d{2}\.\d{3}$")


from arinox_apparel.arinox_apparel.doctype.trim_requisition.trim_requisition import (  # noqa: E402
	guess_category,
	revise_trim_requisition,
)
from arinox_apparel.arinox_apparel.doctype.trim_requisition.trim_requisition import (  # noqa: E402
	lines_for_sales_order as trim_lines,
)
from arinox_apparel.materials.items import ensure_trim_item  # noqa: E402


class TestTrimRequisition(MaterialsBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label = ensure_trim_item("_AT-LBL-1", "Main label", "Woven Label")
		cls.button = ensure_trim_item("_AT-BTN-1", "18L shell button", "Button")
		cls.thread = ensure_trim_item("_AT-THR-1", "Thread", "Thread", "Meter")
		cls.carton = ensure_trim_item("_AT-CTN-1", "Carton", "Packaging")
		cls.buyer_tag = ensure_trim_item("_AT-TAG-1", "Buyer hang tag", "Hang Tag", customer=u.CUSTOMER, customer_provided=1)

	def tr(self, rows, **kw):
		base = {"sales_order": self.so.name, "style_item": self.style, "calc_basis": "Per Garment", "supplier": self.mill_a}
		return frappe.get_doc({"doctype": "Trim Requisition", "company": self.company, "customer": u.CUSTOMER,
			"items": [{**base, **r} for r in rows], **kw})

	def label_row(self, **kw):
		return {"trim_category": "Woven Label", "trim_item": self.label, "garment_qty": 1800, "qty_per_garment": 1, **kw}

	def test_lines_come_from_the_tech_pack(self):
		rows = trim_lines(self.so.name, u.CUSTOMER, self.company)
		self.assertEqual(len(rows), 1)  # the Neck label; the Jersey fabric belongs on the FR
		self.assertEqual((rows[0]["trim_category"], rows[0]["garment_qty"], rows[0]["calc_basis"]), ("Woven Label", 1200, "Per Garment"))

	def test_category_guess(self):
		self.assertEqual(guess_category("Trim", "18L 2 hole shell button"), "Button")
		self.assertEqual(guess_category("Label", "Size label ST022"), "Size Label")
		self.assertEqual(guess_category("Trim", "Thread DTM"), "Thread")
		self.assertEqual(guess_category("Packaging", "Master carton"), "Packaging")
		self.assertEqual(guess_category("Trim", "Whatever"), "Others")

	def test_reference_label_golden_number(self):
		# TRIM REQUEST 02.05.26: 1800 labels + 10% = 1980
		doc = self.tr([self.label_row()])
		doc.insert()
		self.assertEqual(doc.items[0].order_qty, 1980)

	def test_reference_button_golden_number(self):
		# 1800 garments x (10 buttons + 1 spare) x 1.10 = 21,780
		doc = self.tr([{"trim_category": "Button", "trim_item": self.button, "garment_qty": 1800, "qty_per_garment": 10, "spare_per_garment": 1}])
		doc.insert()
		self.assertEqual(doc.items[0].order_qty, 21780)

	def test_per_size_needs_a_size(self):
		doc = self.tr([self.label_row(calc_basis="Per Size")])
		self.assertRaises(frappe.ValidationError, doc.insert)
		doc = self.tr([self.label_row(calc_basis="Per Size", size="S", garment_qty=350)])
		doc.insert()
		self.assertEqual(doc.items[0].order_qty, 385)

	def test_dtm_becomes_the_garment_colour(self):
		doc = self.tr([self.label_row(colour="Navy", trim_colour="DTM", garment_qty=700)])
		doc.insert()
		self.assertEqual(doc.items[0].trim_colour, "Navy")

	def test_carton_rounds_up(self):
		doc = self.tr([{"trim_category": "Packaging", "trim_item": self.carton, "calc_basis": "Per Carton", "garment_qty": 1200,
			"qty_per_garment": 1, "pcs_per_carton": 40}])
		doc.insert()
		self.assertEqual(doc.items[0].order_qty, 31)  # 30 cartons + 2% = 30.6 -> 31
		doc = self.tr([{"trim_category": "Packaging", "trim_item": self.carton, "calc_basis": "Per Carton", "garment_qty": 1200, "qty_per_garment": 1}])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_thread_by_length_rounds_to_pack(self):
		doc = self.tr([{"trim_category": "Thread", "trim_item": self.thread, "calc_basis": "By Length", "garment_qty": 1800, "consumption": 150,
			"consumption_uom": "Meter", "pack_size": 5000}])
		doc.insert()
		self.assertAlmostEqual(doc.items[0].gross_qty, 1800 * 150 * 1.02, places=2)
		self.assertEqual(doc.items[0].order_qty, 280000)

	def test_allowance_override_needs_a_reason(self):
		doc = self.tr([self.label_row(allowance_pct=15)])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_hold_when_trim_approval_missing(self):
		frappe.db.delete("Sample Approval", {"sample_type": "Bulk Trim", "style_item": self.style})
		doc = self.tr([self.label_row()])
		doc.insert()
		self.assertEqual(doc.items[0].hold, 1)
		self.assertIn("trim approval", doc.red_flags.lower())

	def test_submit_needs_supplier_unless_buyer_supplied(self):
		doc = self.tr([self.label_row(supplier=None)])
		doc.insert()
		self.assertRaises(frappe.ValidationError, doc.submit)

	def test_submit_makes_mr_and_buyer_supplied_makes_customer_provided_mr(self):
		doc = self.tr([self.label_row(), {"trim_category": "Hang Tag", "trim_item": self.buyer_tag, "garment_qty": 1200, "qty_per_garment": 1,
			"customer_provided": 1, "supplier": None}])
		doc.insert()
		doc.submit()
		types = sorted(frappe.db.get_value("Material Request", m, "material_request_type") for m in {r.material_request for r in doc.items if r.material_request} | {
			frappe.db.get_value("Material Request Item", {"apparel_requisition": doc.name, "item_code": self.buyer_tag}, "parent")})
		self.assertIn("Customer Provided", types)
		self.assertIn("Purchase", types)
		hold = frappe.db.get_value("Material Request Item", {"apparel_requisition": doc.name, "item_code": self.label}, "apparel_hold_reason")
		self.assertTrue(hold)  # no bulk trim approval on this order

	def test_revision_requests_only_the_increase(self):
		doc = self.tr([self.label_row()])
		doc.insert()
		doc.submit()
		rev = revise_trim_requisition(doc.name)
		rev.revision_reason = "PO +200"
		rev.items[0].garment_qty = 2000
		rev.insert()
		rev.submit()
		qty = sum(flt(i.stock_qty) for i in frappe.get_all("Material Request Item", {"apparel_requisition": rev.name}, ["stock_qty"]))
		self.assertEqual(qty, 220)  # 200 more garments x 1.10
		doc.reload()
		self.assertEqual(doc.status, "Superseded")

	def test_number_format(self):
		doc = self.tr([self.label_row()])
		doc.insert()
		self.assertRegex(doc.name, r"^TR\d{2}\.\d{2}\.\d{3}$")


from arinox_apparel.overrides.purchase_order import make_purchase_orders  # noqa: E402
from arinox_apparel.materials import purchasing  # noqa: E402


class TestPurchasing(MaterialsBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label = ensure_trim_item("_AT-LBL-2", "Main label", "Woven Label")

	def setUp(self):
		self.approve_lab_dips()
		frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Warn")

	def terms(self):
		return frappe.get_doc("Material Purchase Terms", "Standard Fabric Terms")

	def test_quantity_bands_at_the_edges(self):
		t = self.terms()
		self.assertEqual([purchasing.qty_tolerance(t, q) for q in (500, 1000, 1001, 3000, 3001, 10000, 10001)], [7, 7, 5, 5, 3, 3, 0])

	def test_delay_penalty_at_the_band_edges(self):
		t = self.terms()
		got = {d: purchasing.delay_penalty(t, d) for d in (-1, 0, 1, 3, 4, 11, 12, 21, 22, 40)}
		self.assertEqual([got[d][0] for d in (-1, 0, 1, 3, 4, 11, 12, 21, 22, 40)], [0, 0, 0, 0, 10, 10, 25, 25, 50, 50])
		self.assertEqual(got[22][1], "Cancel or Discount")

	def make_tr_po(self, late_days=10, supplier=None):
		tr = frappe.get_doc({"doctype": "Trim Requisition", "company": self.company, "customer": u.CUSTOMER, "items": [{
			"sales_order": self.so.name, "style_item": self.style, "trim_category": "Woven Label", "trim_item": self.label, "calc_basis": "Per Garment",
			"garment_qty": 1000, "qty_per_garment": 1, "supplier": supplier or self.mill_a}]})
		tr.insert()
		tr.submit()
		po_name = make_purchase_orders("TR", tr.name)[0]
		po = frappe.get_doc("Purchase Order", po_name)
		po.transaction_date = add_days(nowdate(), -20)
		po.schedule_date = add_days(nowdate(), -late_days)
		for i in po.items:
			i.rate, i.schedule_date = 1, add_days(nowdate(), -late_days)
		po.apparel_purchase_terms = "Standard Fabric Terms"
		return tr, po

	def test_purchase_order_from_requisition_keeps_the_links(self):
		tr, po = self.make_tr_po()
		po.save()
		it = po.items[0]
		self.assertEqual((it.apparel_requisition_type, it.apparel_requisition), ("TR", tr.name))
		self.assertEqual(it.material_request_item, frappe.db.get_value("Trim Requisition Item", {"parent": tr.name}, "material_request_item"))
		self.assertEqual(po.supplier, self.mill_a)
		self.assertEqual(make_purchase_orders("TR", tr.name), [])  # nothing left to order

	def test_hold_blocks_submit_only_in_block_mode_and_override_needs_manager(self):
		frappe.db.delete("Sample Approval", {"sample_type": "Bulk Trim", "style_item": self.style})
		tr, po = self.make_tr_po()
		po.save()
		po.submit()  # Warn mode: submits
		po.cancel()
		frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Block")
		_tr, po2 = self.make_tr_po(supplier=self.mill_b)
		po2.save()
		self.assertRaises(frappe.ValidationError, po2.submit)
		po2.reload()
		po2.apparel_approval_override = 1
		po2.apparel_approval_override_reason = "Buyer verbally approved"
		frappe.set_user("Administrator")
		po2.save()
		po2.submit()

	def test_etd_rules(self):
		tr, po = self.make_tr_po()
		po.apparel_etd_planned, po.apparel_eta = add_days(nowdate(), 10), add_days(nowdate(), 5)
		self.assertRaises(frappe.ValidationError, po.save)
		po.apparel_eta = add_days(nowdate(), 20)
		po.apparel_etd_actual = add_days(nowdate(), 3)
		self.assertRaises(frappe.ValidationError, po.save)

	def receive(self, po, qty=None):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		pr = make_purchase_receipt(po.name)
		if qty is not None:
			pr.items[0].qty = qty
		pr.insert()
		return pr

	def test_receipt_rolls_up_and_applies_delay_penalty(self):
		tr, po = self.make_tr_po(late_days=10)
		po.save()
		po.submit()
		tr.reload()
		self.assertEqual(tr.items[0].ordered_qty, 1000 * 1.1)
		self.assertEqual(tr.status, "Ordered")
		pr = self.receive(po)
		pr.submit()
		pr.reload()
		self.assertEqual(pr.apparel_delay_days, 10)  # received today, due 10 days ago
		self.assertEqual(pr.apparel_penalty_pct, 10)  # the 4-11 day band
		self.assertAlmostEqual(pr.apparel_penalty_amount, flt(pr.items[0].net_amount) * 0.10, places=2)
		tr.reload()
		self.assertEqual(tr.items[0].received_qty, 1100)
		self.assertEqual(tr.status, "Received")
		pr.cancel()
		tr.reload()
		self.assertEqual(tr.items[0].received_qty, 0)
		self.assertEqual(tr.status, "Ordered")

	def test_on_time_receipt_has_no_penalty(self):
		tr, po = self.make_tr_po(late_days=0)
		po.save()
		po.submit()
		pr = self.receive(po)
		pr.submit()
		pr.reload()
		self.assertEqual((pr.apparel_delay_days, pr.apparel_penalty_pct), (0, 0))

	def test_over_delivery_beyond_the_band(self):
		tr, po = self.make_tr_po()
		po.save()
		po.submit()  # ordered 1100, band 1001-3000 -> +/-5%, upper 1155
		pr = self.receive(po, qty=1200)
		self.assertRegex(pr.apparel_qty_band_note, r"over the \+5(\.0)?% band")
		self.assertIn("must not be invoiced", pr.apparel_qty_band_note)
		pr2 = self.receive(po, qty=1100)
		self.assertFalse(pr2.apparel_qty_band_note)
		frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "extra_qty_policy", "Reject")
		frappe.clear_cache()
		try:
			po_doc = frappe.get_doc("Purchase Order", po.name)
			from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

			pr3 = make_purchase_receipt(po_doc.name)
			pr3.items[0].qty = 1200
			self.assertRaises(frappe.ValidationError, pr3.insert)
		finally:
			frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "extra_qty_policy", "Accept Unpaid")
			frappe.clear_cache()

	def test_cancel_blocked_once_ordered(self):
		tr, po = self.make_tr_po()
		po.save()
		self.assertRaises(frappe.ValidationError, tr.cancel)


from arinox_apparel.materials.rolls import import_roll_list, parse_roll_text  # noqa: E402


class TestReceivingRolls(MaterialsBase):
	def setUp(self):
		self.approve_lab_dips()

	def fabric_po_and_pr(self, navy_only=True):
		doc = self.fr()
		doc.items = [r for r in doc.items if r.colour == "Navy"]  # 882 m
		doc.insert()
		doc.submit()
		po = frappe.get_doc("Purchase Order", make_purchase_orders("FR", doc.name)[0])
		po.transaction_date = add_days(nowdate(), -20)
		po.schedule_date = add_days(nowdate(), -2)
		for i in po.items:
			i.rate, i.schedule_date = 3, add_days(nowdate(), -2)
		po.save()
		po.submit()
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		pr = make_purchase_receipt(po.name)
		pr.insert()
		return doc, po, pr

	def rolls(self, n=10, each=88.2, prefix="R"):
		return [{"roll_no": f"{prefix}{i + 1:02d}", "dye_lot": "LOT-A" if i < 6 else "LOT-B", "length": each} for i in range(n)]

	def test_parse_pasted_list(self):
		text = "Roll\tLot\tLength\nR1\tL1\t100.5\nR2, L1, 99\n\nbad line\nR3;L2;50;132"
		got = parse_roll_text(text)
		self.assertEqual([(r["roll_no"], r["length"]) for r in got], [("R1", 100.5), ("R2", 99.0), ("R3", 50.0)])
		self.assertEqual(got[2]["width_cm"], 132)

	def test_import_creates_a_batch_per_roll_and_the_receipt_submits(self):
		fr, po, pr = self.fabric_po_and_pr()
		out = import_roll_list(pr.name, pr.items[0].name, self.rolls())
		self.assertEqual((out["rolls"], out["total"]), (10, 882.0))
		batches = frappe.get_all("Batch", {"reference_name": pr.name}, ["name", "apparel_roll_no", "apparel_dye_lot", "apparel_ticket_length", "apparel_inspection_status"])
		self.assertEqual(len(batches), 10)
		self.assertTrue(all(b.apparel_inspection_status == "Uninspected" and abs(b.apparel_ticket_length - 88.2) < 0.01 for b in batches))
		pr.reload()
		pr.submit()
		self.assertEqual(frappe.db.get_value("Serial and Batch Bundle", pr.items[0].serial_and_batch_bundle, "total_qty"), 882)
		fr.reload()
		self.assertEqual(fr.items[0].received_qty, 882)
		self.assertEqual(fr.status, "Received")

	def test_submit_without_rolls_is_blocked(self):
		fr, po, pr = self.fabric_po_and_pr()
		self.assertRaises(frappe.ValidationError, pr.submit)

	def test_duplicate_roll_numbers_blocked(self):
		fr, po, pr = self.fabric_po_and_pr()
		rolls = self.rolls()
		rolls[3]["roll_no"] = rolls[2]["roll_no"]
		self.assertRaises(frappe.ValidationError, import_roll_list, pr.name, pr.items[0].name, rolls)

	def test_total_must_match_the_row_unless_asked(self):
		fr, po, pr = self.fabric_po_and_pr()
		self.assertRaises(frappe.ValidationError, import_roll_list, pr.name, pr.items[0].name, self.rolls(each=80))
		out = import_roll_list(pr.name, pr.items[0].name, self.rolls(each=80), update_row_qty=1)
		self.assertEqual(out["total"], 800)
		pr.reload()
		self.assertEqual(pr.items[0].qty, 800)

	def test_yards_are_converted(self):
		fr, po, pr = self.fabric_po_and_pr()
		each_yd = 88.2 / 0.9144
		out = import_roll_list(pr.name, pr.items[0].name, self.rolls(each=each_yd), length_uom="Yard")
		self.assertAlmostEqual(out["total"], 882.0, places=1)

	def test_reimport_replaces_the_previous_rolls(self):
		fr, po, pr = self.fabric_po_and_pr()
		import_roll_list(pr.name, pr.items[0].name, self.rolls())
		pr.reload()
		import_roll_list(pr.name, pr.items[0].name, self.rolls(prefix="X"))
		names = {b.apparel_roll_no for b in frappe.get_all("Batch", {"reference_name": pr.name}, ["apparel_roll_no"])}
		self.assertEqual(len(names), 10)
		self.assertTrue(all(n.startswith("X") for n in names))

	def test_bad_rolls_rejected(self):
		fr, po, pr = self.fabric_po_and_pr()
		self.assertRaises(frappe.ValidationError, import_roll_list, pr.name, pr.items[0].name, [])
		self.assertRaises(frappe.ValidationError, import_roll_list, pr.name, pr.items[0].name, [{"roll_no": "", "length": 5}])
		self.assertRaises(frappe.ValidationError, import_roll_list, pr.name, pr.items[0].name, [{"roll_no": "A", "length": 0}])
