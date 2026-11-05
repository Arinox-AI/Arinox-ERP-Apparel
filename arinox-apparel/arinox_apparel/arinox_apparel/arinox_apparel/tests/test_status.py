# Copyright (c) 2026, Arinox AI and contributors
"""Phase C: material status, running fabric stock, the material gate, PP meeting auto-fill, number cards."""

from types import SimpleNamespace as NS

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from arinox_apparel.arinox_apparel.report.material_status.material_status import execute as material_status
from arinox_apparel.arinox_apparel.report.running_fabric_stock.running_fabric_stock import execute as running_stock
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.test_inspection import InspectionBase
from arinox_apparel.materials import cards
from arinox_apparel.materials.items import ensure_trim_item
from arinox_apparel.materials.status import line_status, material_gate, trim_readiness
from arinox_apparel.overrides import work_order as gate


def L(**kw):
	base = dict(net=100, ordered=0, received=0, accepted=0, rejected=0, hold=0, etd_actual=None, eta=None)
	base.update(kw)
	return frappe._dict(base)


class TestLineStatus(IntegrationTestCase):
	def test_every_status(self):
		self.assertEqual(line_status(L()), "Requested")
		self.assertEqual(line_status(L(hold=1)), "On Hold")
		self.assertEqual(line_status(L(ordered=100, hold=1)), "Ordered")  # once ordered, the hold no longer matters
		self.assertEqual(line_status(L(ordered=100, eta="2026-12-01")), "In Transit")
		self.assertEqual(line_status(L(ordered=100, etd_actual="2026-12-01")), "In Transit")
		self.assertEqual(line_status(L(ordered=100, received=100)), "In House - QC Pending")
		self.assertEqual(line_status(L(ordered=100, received=100, accepted=100)), "Accepted")
		self.assertEqual(line_status(L(ordered=100, received=100, accepted=60, rejected=40)), "Rejected")
		self.assertEqual(line_status(L(ordered=100, received=80, accepted=80)), "Short")
		self.assertEqual(line_status(L(net=0)), "Accepted")  # fully covered by stock
		self.assertEqual(line_status(L(accepted=95), min_pct=95), "Accepted")
		self.assertEqual(line_status(L(accepted=94, received=94), min_pct=95), "Short")


class TestMaterialFlow(InspectionBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label = ensure_trim_item("_AT-LBL-4", "Main label", "Woven Label")
		cls.carton = ensure_trim_item("_AT-CTN-4", "Carton", "Packaging")

	def setUp(self):
		# a fresh order per test: requisitions, receipts and inspections of one test must not show up in the next
		self.so, self.style, self.sc = u.make_order("_AT-S" + frappe.generate_hash(length=6))
		self.navy_variant = next(i.item_code for i in self.so.items if i.apparel_colour == "Navy")
		super().setUp()

	def rows(self, **f):
		_cols, data = material_status(dict(sales_order=self.so.name, **f))
		return data

	def navy_fabric_row(self):
		return next(r for r in self.rows(material_type="Fabric") if r["colour"] == "Navy")

	def test_status_follows_the_goods(self):
		frappe.db.delete("Sample Approval", {"sample_type": "Lab Dip", "style_item": self.style})
		fr = self.fr()
		fr.items = [r for r in fr.items if r.colour == "Navy"]
		fr.insert()
		fr.submit()
		self.assertEqual(self.navy_fabric_row()["status"], "On Hold")  # lab dip not approved
		self.approve_lab_dips()
		from arinox_apparel.overrides.purchase_order import make_purchase_orders

		po = frappe.get_doc("Purchase Order", make_purchase_orders("FR", fr.name)[0])
		po.transaction_date, po.schedule_date = add_days(nowdate(), -20), add_days(nowdate(), -3)
		for i in po.items:
			i.rate, i.schedule_date = 3, add_days(nowdate(), -3)
		po.save()
		po.submit()
		row = self.navy_fabric_row()
		self.assertEqual((row["status"], row["po"], row["ordered"]), ("Ordered", po.name, 882))
		self.assertGreaterEqual(row["days_late"], 0)
		po.db_set("apparel_eta", add_days(nowdate(), 5))
		self.assertEqual(self.navy_fabric_row()["status"], "In Transit")

	def test_receipt_inspection_and_the_gate(self):
		fr, po, pr = self.received_fabric()
		row = self.navy_fabric_row()
		self.assertEqual((row["status"], row["received"], row["in_inspection"]), ("In House - QC Pending", 882, 882))
		blockers, warnings = material_gate(self.so.name, self.style, "Navy")
		self.assertTrue(any("Fabric" in b and "0.0 m of 882.0" in b for b in blockers), blockers)
		self.assertIn("Fabric", " | ".join(gate.get_bulk_gate(self.navy_variant, self.so.name)["blockers"]))
		fi = self.inspection(pr, inspect=10)
		fi.insert()
		fi.submit()
		self.assertEqual(self.navy_fabric_row()["status"], "Accepted")
		blockers, _w = material_gate(self.so.name, self.style, "Navy")
		self.assertEqual(blockers, [])
		self.assertEqual(material_gate(self.so.name, self.style, "Black")[0], [])  # no FR for Black: nothing to hold

	def test_gate_modes(self):
		fr, po, pr = self.received_fabric()
		try:
			frappe.db.set_single_value("Apparel Settings", "material_gate_fabric", "Warn")
			blockers, warnings = material_gate(self.so.name, self.style, "Navy")
			self.assertEqual((blockers, len(warnings)), ([], 1))
			frappe.db.set_single_value("Apparel Settings", "material_gate_fabric", "Off")
			self.assertEqual(material_gate(self.so.name, self.style, "Navy"), ([], []))
		finally:
			frappe.db.set_single_value("Apparel Settings", "material_gate_fabric", "Block")

	def test_trims_warn_and_packaging_never_blocks(self):
		tr = frappe.get_doc({"doctype": "Trim Requisition", "company": self.company, "customer": u.CUSTOMER, "items": [
			{"sales_order": self.so.name, "style_item": self.style, "trim_category": "Woven Label", "trim_item": self.label, "calc_basis": "Per Garment",
			 "garment_qty": 1000, "qty_per_garment": 1, "supplier": self.mill_a},
			{"sales_order": self.so.name, "style_item": self.style, "trim_category": "Packaging", "trim_item": self.carton, "calc_basis": "Per Carton",
			 "garment_qty": 1000, "qty_per_garment": 1, "pcs_per_carton": 40, "supplier": self.mill_a}]})
		tr.insert()
		tr.submit()
		blockers, warnings = material_gate(self.so.name, self.style, "Navy")
		self.assertTrue(any("Trim" in w and self.label in w for w in warnings), warnings)
		self.assertFalse(any(self.carton in w for w in warnings + blockers))  # packaging does not hold cutting
		self.assertFalse(any(self.label in b for b in blockers))  # trims are warn-only by default
		self.assertEqual(trim_readiness(self.so.name, self.style, "Sewing"), "Not Available")
		self.assertEqual(trim_readiness(self.so.name, self.style, "Packing"), "Not Available")
		self.assertIsNone(trim_readiness(self.so.name, self.style, "Finishing"))

	def test_running_fabric_stock_row(self):
		fr, po, pr = self.received_fabric()
		_c, data = running_stock({"sales_order": self.so.name})
		row = next(r for r in data if r["po"] == po.name)
		self.assertEqual((row["ordered"], row["received"], row["balance"], row["issued"], row["colour"]), (882, 882, 882, 0, "Navy"))
		self.assertEqual(row["over_short"], 0)
		self.assertEqual(row["delay_days"], 1)  # due yesterday, received today
		self.assertAlmostEqual(row["stock_value"], 882 * 3)
		self.assertIsNone(row["cut_qty"])  # filled by the cutting phase

	def test_pp_meeting_loads_fabric_and_trims(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10, shade=["A", "B"])
		fi.insert()
		fi.submit()
		pp = frappe.new_doc("PP Meeting")
		pp.sales_order, pp.style_item = self.so.name, self.style
		self.assertEqual(pp.load_from_requisitions(), 1)
		navy = next(c for c in pp.colours if c.colour == "Navy")
		self.assertEqual((navy.fabric_required_m, navy.fabric_received_m, navy.no_of_shades), (882, 882, 2))

	def test_number_cards(self):
		fr, po, pr = self.received_fabric()
		for fn in (cards.fabric_overdue, cards.rolls_awaiting_inspection, cards.rejected_lots, cards.trim_lines_on_hold):
			out = fn()
			self.assertEqual(out["fieldtype"], "Int")
			self.assertGreaterEqual(out["value"], 0)
		self.assertGreaterEqual(cards.rolls_awaiting_inspection()["value"], 10)
