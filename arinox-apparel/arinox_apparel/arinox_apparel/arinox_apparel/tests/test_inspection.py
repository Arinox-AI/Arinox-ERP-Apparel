# Copyright (c) 2026, Arinox AI and contributors
"""Phase C: fabric and trim inspection."""

from types import SimpleNamespace as NS

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from arinox_apparel.arinox_apparel.doctype.fabric_inspection.fabric_inspection import make_inspection as make_fi
from arinox_apparel.arinox_apparel.doctype.fabric_inspection.fabric_inspection import make_purchase_return
from arinox_apparel.arinox_apparel.doctype.trim_inspection.trim_inspection import make_inspection as make_ti
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.test_materials import MaterialsBase, make_supplier
from arinox_apparel.materials import common as mc
from arinox_apparel.materials import inspection as ins
from arinox_apparel.materials.items import ensure_trim_item
from arinox_apparel.materials.rolls import import_roll_list
from arinox_apparel.overrides.purchase_order import make_purchase_orders


class TestInspectionMaths(IntegrationTestCase):
	def test_defect_points_by_length(self):
		self.assertEqual([ins.defect_points(x) for x in (0.5, 3, 3.01, 6, 6.01, 9, 9.01, 40)], [1, 1, 2, 2, 3, 3, 4, 4])
		self.assertEqual(ins.defect_points(0.5, always_four=True), 4)  # a hole

	def test_four_point_cap_per_yard(self):
		self.assertEqual(ins.roll_points([(5, 4), (5, 4), (6, 2)]), 4 + 2)  # yard 5 capped at 4
		self.assertEqual(ins.roll_points([(1, 3), (1, 1), (2, 1)]), 4 + 1)
		self.assertEqual(ins.roll_points([(None, 4), (None, 4)]), 8)  # no yard number: counted one by one

	def test_points_per_100_formulas(self):
		m = 150 * 0.9144  # 150 yd
		self.assertAlmostEqual(ins.points_per_100_linear(30, m), 20.0, places=2)
		self.assertAlmostEqual(ins.points_per_100_square(30, m, 57 * 2.54), 12.63, places=2)
		self.assertEqual(ins.points_per_100_linear(10, 0), 0)

	def test_sampling_bands(self):
		bands = [NS(from_length_m=a, to_length_m=b, inspect_pct=c) for a, b, c in [(0, 1000, 50), (1001, 2000, 30), (2001, 3000, 20), (3001, 5000, 15), (5001, 0, 10)]]
		self.assertEqual([ins.sampling_pct(bands, x) for x in (500, 1000, 1500, 2500, 4000, 9000)], [50, 50, 30, 20, 15, 10])
		self.assertEqual(1500 * ins.sampling_pct(bands, 1500) / 100, 450)

	def test_lot_decision(self):
		self.assertEqual(ins.lot_decision(10, 20, 0, 5, 10, 10), "Pass")
		self.assertEqual(ins.lot_decision(25, 20, 0, 5, 10, 10), "Re-inspect 100%")
		self.assertEqual(ins.lot_decision(25, 20, 0, 10, 10, 10), "Fail")
		self.assertEqual(ins.lot_decision(10, 20, 2, 5, 10, 10), "Re-inspect 100%")  # 40% of the sample rolls rejected
		self.assertEqual(ins.lot_decision(10, 20, 1, 10, 10, 10), "Pass")  # 10% is not above 10%
		self.assertEqual(ins.lot_decision(5, 20, 0, 10, 10, 10, on_hold=True), "Hold")

	def test_roll_disposition(self):
		self.assertEqual(ins.roll_disposition(1, "Accept", "Pass"), "Accepted")
		self.assertEqual(ins.roll_disposition(1, "Reject", "Pass"), "Rejected")
		self.assertEqual(ins.roll_disposition(0, None, "Pass"), "Accepted by Lot")
		self.assertEqual(ins.roll_disposition(0, None, "Fail"), "Hold")
		self.assertEqual(ins.roll_disposition(1, "Hold", "Pass"), "Hold")

	def test_width_impact(self):
		self.assertAlmostEqual(ins.width_impact(128, 132, 1000), 31.25, places=2)
		self.assertEqual(ins.width_impact(133, 132, 1000), 0)
		self.assertEqual(ins.width_impact(0, 132, 1000), 0)

	def test_trim_sampling_and_result(self):
		pct = NS(method="Percent", inspect_pct=10, max_defective_pct=5, rows=[], full_inspect_up_to=50)
		self.assertEqual(ins.trim_sample(pct, 500), (50, None, None))
		aql = NS(method="AQL Table", full_inspect_up_to=50, max_defective_pct=5, inspect_pct=0, rows=[
			NS(lot_from=501, lot_to=1200, sample_size=80, accept_max=5, reject_min=6), NS(lot_from=1201, lot_to=3200, sample_size=125, accept_max=7, reject_min=8)])
		self.assertEqual(ins.trim_sample(aql, 40), (40, None, None))  # small lots are checked in full
		self.assertEqual(ins.trim_sample(aql, 1100), (80, 5, 6))
		self.assertEqual(ins.trim_result(aql, 5, 80, 6, False), "Pass")
		self.assertEqual(ins.trim_result(aql, 6, 80, 6, False), "Fail")
		self.assertEqual(ins.trim_result(pct, 5, 100, None, False), "Pass")
		self.assertEqual(ins.trim_result(pct, 6, 100, None, False), "Fail")
		self.assertEqual(ins.trim_result(pct, 0, 100, None, True), "Fail")  # size mix-up always fails


class InspectionBase(MaterialsBase):
	def setUp(self):
		self.approve_lab_dips()
		frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Warn")

	def received_fabric(self, rolls=10, each=88.2):
		"""FR (Navy, 882 m) -> PO -> receipt with a roll list, submitted."""
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		fr = self.fr()
		fr.items = [r for r in fr.items if r.colour == "Navy"]
		fr.insert()
		fr.submit()
		po = frappe.get_doc("Purchase Order", make_purchase_orders("FR", fr.name)[0])
		po.transaction_date = add_days(nowdate(), -20)
		po.schedule_date = add_days(nowdate(), -1)
		for i in po.items:
			i.rate, i.schedule_date = 3, add_days(nowdate(), -1)
		po.save()
		po.submit()
		pr = make_purchase_receipt(po.name)
		pr.insert()
		import_roll_list(pr.name, pr.items[0].name, [{"roll_no": f"R{i + 1:02d}", "dye_lot": "L1", "length": each} for i in range(rolls)])
		pr.reload()
		pr.submit()
		return fr, po, pr

	def inspection(self, pr, inspect=10, widths=None, shade=None):
		fi = make_fi(pr.name, pr.items[0].name)
		for i, r in enumerate(fi.rolls):
			r.inspected = 1 if i < inspect else 0
			if widths:
				r.width_start_cm = r.width_middle_cm = r.width_end_cm = widths
			if shade:
				r.shade_band = shade[i % len(shade)]
		return fi

	def defects(self, fi, roll_no, n, code="C", length=10):
		"""n defects of 4 points in different yards of one roll."""
		for y in range(1, n + 1):
			fi.append("defects", {"roll_no": roll_no, "yard_position": y * 5, "defect_code": code, "defect_length_in": length})

	def tearDown(self):
		frappe.set_user("Administrator")

	def bin_qty(self, item, wh):
		return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))


class TestFabricInspection(InspectionBase):
	def test_minimum_sample_is_enforced(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=2)
		fi.insert()
		self.assertEqual((fi.total_rolls, flt(fi.total_received_m), fi.sampling_pct, fi.required_inspect_m), (10, 882.0, 50, 441.0))
		self.assertRaises(frappe.ValidationError, fi.submit)  # 176 m of 441 m

	def test_passing_lot_releases_everything_to_the_store(self):
		before = self.bin_qty(self.navy_fabric, mc.company_warehouse("store_warehouse_fabric", self.company))
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=5)
		self.defects(fi, "R01", 1, length=2)  # one 1-point defect
		fi.insert()
		self.assertEqual(fi.lot_result, "Pass")
		fi.submit()
		fi.reload()
		statuses = {b.apparel_roll_no: b.apparel_inspection_status for b in frappe.get_all("Batch", {"reference_name": pr.name}, ["apparel_roll_no", "apparel_inspection_status"])}
		self.assertEqual(statuses["R01"], "Accepted")
		self.assertEqual(statuses["R10"], "Accepted by Lot")  # not inspected, lot passed
		self.assertEqual(frappe.db.get_value("Quality Inspection", fi.quality_inspection, "status"), "Accepted")
		self.assertEqual(frappe.db.get_value("Stock Entry", fi.stock_entry, "docstatus"), 1)
		store = mc.company_warehouse("store_warehouse_fabric", self.company)
		self.assertAlmostEqual(self.bin_qty(self.navy_fabric, store) - before, 882, places=1)
		fr.reload()
		self.assertAlmostEqual(fr.items[0].accepted_qty, 882, places=1)
		self.assertEqual(frappe.db.get_value("Fabric Inspection", fi.name, "claim_deadline"), frappe.utils.getdate(add_days(pr.posting_date, 45)))

	def test_one_bad_roll_is_rejected_but_the_lot_passes(self):
		before = self.bin_qty(self.navy_fabric, mc.company_warehouse("rejected_warehouse", self.company))
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10)  # every roll
		self.defects(fi, "R01", 6)  # 24 points over ~96 yd = 24.9 per 100 > 20
		fi.insert()
		by = {r.roll_no: r.roll_result for r in fi.rolls}
		self.assertEqual(by["R01"], "Reject")
		self.assertEqual(by["R02"], "Accept")
		self.assertEqual((fi.rejected_rolls, fi.lot_result), (1, "Pass"))  # 10% of rolls is not above the 10% limit
		fi.submit()
		fi.reload()
		reject = mc.company_warehouse("rejected_warehouse", self.company)
		self.assertAlmostEqual(self.bin_qty(self.navy_fabric, reject) - before, 88.2, places=1)
		fr.reload()
		self.assertAlmostEqual(fr.items[0].accepted_qty, 793.8, places=1)
		self.assertAlmostEqual(fr.items[0].rejected_qty, 88.2, places=1)

	def test_failed_sample_needs_every_roll(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=5)
		self.defects(fi, "R01", 6)
		self.defects(fi, "R02", 6)
		fi.insert()
		self.assertEqual(fi.lot_result, "Re-inspect 100%")
		self.assertRaises(frappe.ValidationError, fi.submit)
		fi.reload()  # a refused submit leaves the in-memory copy stale
		for r in fi.rolls:
			r.inspected = 1
		fi.save()
		self.assertEqual(fi.lot_result, "Pass" if fi.rejected_rolls == 1 else "Fail")  # 2 of 10 rejected = 20%
		self.assertEqual(fi.lot_result, "Fail")
		fi.submit()
		self.assertEqual(frappe.db.get_value("Quality Inspection", fi.quality_inspection, "status"), "Rejected")

	def test_width_and_shade_flags_reach_the_requisition(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10, widths=128, shade=["A", "B"])
		fi.insert()
		self.assertEqual(fi.avg_actual_width_cm, 128)
		fi.submit()
		fi.reload()
		self.assertAlmostEqual(fi.width_shortfall_m, 882 * (132 / 128 - 1), places=1)
		flags = frappe.db.get_value("Fabric Requisition", fr.name, "red_flags")
		self.assertIn("narrower", flags)
		self.assertIn("Cut by shade band", flags)

	def test_cancel_puts_everything_back(self):
		store = mc.company_warehouse("store_warehouse_fabric", self.company)
		before = self.bin_qty(self.navy_fabric, store)
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10)
		fi.insert()
		fi.submit()
		fi.cancel()
		self.assertEqual(self.bin_qty(self.navy_fabric, store), before)
		self.assertTrue(all(b.apparel_inspection_status == "Uninspected" for b in frappe.get_all("Batch", {"reference_name": pr.name}, ["apparel_inspection_status"])))
		fr.reload()
		self.assertEqual(fr.items[0].accepted_qty, 0)

	def test_purchase_return_of_rejected_rolls(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10)
		self.defects(fi, "R01", 6)
		fi.insert()
		fi.submit()
		ret = make_purchase_return(fi.name)
		self.assertEqual(len(ret.items), 1)
		self.assertAlmostEqual(ret.items[0].qty, -88.2, places=2)
		self.assertEqual(ret.items[0].warehouse, mc.company_warehouse("rejected_warehouse", self.company))
		self.assertTrue(ret.is_return)

	def test_unknown_roll_and_bad_defects_rejected(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr)
		fi.append("defects", {"roll_no": "NOPE", "yard_position": 1, "defect_code": "C", "defect_length_in": 2})
		self.assertRaises(frappe.ValidationError, fi.insert)
		fi = self.inspection(pr)
		fi.append("defects", {"roll_no": "R01", "yard_position": 1, "defect_code": "C", "defect_length_in": 0})
		self.assertRaises(frappe.ValidationError, fi.insert)

	def test_a_hole_needs_no_length(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr)
		fi.append("defects", {"roll_no": "R01", "yard_position": 1, "defect_code": "H", "defect_length_in": 0})
		fi.insert()
		self.assertEqual(fi.defects[0].points, 4)

	def test_override_is_manager_only(self):
		fr, po, pr = self.received_fabric()
		fi = self.inspection(pr, inspect=10)
		fi.insert()
		fi.result_override, fi.override_reason = 1, "Buyer accepted"
		email = "_at_merch_c5@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "mc5", "send_welcome_email": 0, "roles": [{"role": "Apparel Merchandiser"}]}).insert(ignore_permissions=True)
		frappe.set_user(email)
		self.assertRaises(frappe.ValidationError, fi.check_override)
		frappe.set_user("Administrator")
		fi.check_override()

	def test_supplier_terms_set_the_threshold(self):
		fr, po, pr = self.received_fabric()
		frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "points_threshold", 12)
		frappe.clear_cache()
		try:
			fi = self.inspection(pr)
			fi.insert()
			self.assertEqual(fi.points_threshold, 12)
		finally:
			frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "points_threshold", 20)
			frappe.clear_cache()


class TestTrimInspection(InspectionBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.label = ensure_trim_item("_AT-LBL-3", "Main label", "Woven Label")

	def received_trim(self, qty=1000):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		tr = frappe.get_doc({"doctype": "Trim Requisition", "company": self.company, "customer": u.CUSTOMER, "items": [{
			"sales_order": self.so.name, "style_item": self.style, "trim_category": "Woven Label", "trim_item": self.label, "calc_basis": "Per Garment",
			"garment_qty": qty, "qty_per_garment": 1, "supplier": self.mill_a}]})
		tr.insert()
		tr.submit()
		po = frappe.get_doc("Purchase Order", make_purchase_orders("TR", tr.name)[0])
		po.transaction_date = add_days(nowdate(), -20)
		for i in po.items:
			i.rate = 1
		po.schedule_date = add_days(nowdate(), 0)
		for i in po.items:
			i.schedule_date = add_days(nowdate(), 0)
		po.save()
		po.submit()
		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()
		return tr, pr

	def ti(self, pr, defects=None, **kw):
		doc = make_ti(pr.name, pr.items[0].name)
		doc.inspected_qty = kw.pop("inspected", doc.received_qty)
		doc.update(kw)
		for name, count in (defects or {}).items():
			doc.append("defects", {"defect_type": name, "count": count})
		return doc

	def test_passing_lot_splits_accepted_and_rejected(self):
		store, rej = mc.company_warehouse("store_warehouse_trim", self.company), mc.company_warehouse("rejected_warehouse", self.company)
		b_store, b_rej = self.bin_qty(self.label, store), self.bin_qty(self.label, rej)
		tr, pr = self.received_trim()  # 1000 + 10% = 1100 received
		ti = self.ti(pr, {"Stains": 3}, inspected=110)
		ti.insert()
		self.assertEqual((ti.sample_size, ti.result, ti.accepted_qty, ti.rejected_qty), (110, "Pass", 1097, 3))
		ti.submit()
		ti.reload()
		self.assertEqual(frappe.db.get_value("Quality Inspection", ti.quality_inspection, "status"), "Accepted")
		self.assertEqual(self.bin_qty(self.label, store) - b_store, 1097)
		self.assertEqual(self.bin_qty(self.label, rej) - b_rej, 3)
		tr.reload()
		self.assertEqual((tr.items[0].accepted_qty, tr.items[0].rejected_qty), (1097, 3))

	def test_size_mixup_always_fails_the_lot(self):
		rej = mc.company_warehouse("rejected_warehouse", self.company)
		before = self.bin_qty(self.label, rej)
		tr, pr = self.received_trim()
		ti = self.ti(pr, {"Size Mix-up": 1}, inspected=110)
		ti.insert()
		self.assertEqual((ti.result, ti.accepted_qty, ti.rejected_qty), ("Fail", 0, 1100))
		ti.submit()
		self.assertEqual(self.bin_qty(self.label, rej) - before, 1100)

	def test_percent_limit(self):
		tr, pr = self.received_trim()
		ti = self.ti(pr, {"Stains": 6}, inspected=110)  # 5.45% > 5%
		ti.insert()
		self.assertEqual(ti.result, "Fail")

	def test_aql_plan_accept_and_reject_numbers(self):
		tr, pr = self.received_trim()
		ti = self.ti(pr, {"Stains": 5}, inspected=80, sampling_plan="AQL 2.5 General II (unconfirmed)")
		ti.insert()
		self.assertEqual((ti.sample_size, ti.result), (80, "Pass"))
		ti = self.ti(pr, {"Stains": 6}, inspected=80, sampling_plan="AQL 2.5 General II (unconfirmed)")
		ti.insert()
		self.assertEqual(ti.result, "Fail")

	def test_must_inspect_the_sample(self):
		tr, pr = self.received_trim()
		ti = self.ti(pr, inspected=50)
		ti.insert()
		self.assertRaises(frappe.ValidationError, ti.submit)

	def test_more_defects_than_pieces_rejected(self):
		tr, pr = self.received_trim()
		ti = self.ti(pr, {"Stains": 200}, inspected=110)
		self.assertRaises(frappe.ValidationError, ti.insert)

	def test_cancel_returns_the_stock(self):
		store = mc.company_warehouse("store_warehouse_trim", self.company)
		before = self.bin_qty(self.label, store)
		tr, pr = self.received_trim()
		ti = self.ti(pr, {"Stains": 3}, inspected=110)
		ti.insert()
		ti.submit()
		ti.cancel()
		self.assertEqual(self.bin_qty(self.label, store), before)
		tr.reload()
		self.assertEqual(tr.items[0].accepted_qty, 0)

	def test_fabric_row_cannot_use_the_trim_inspection(self):
		fr, po, pr = TestFabricInspection.received_fabric(self)
		self.assertRaises(frappe.ValidationError, make_ti, pr.name, pr.items[0].name)
