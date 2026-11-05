# Copyright (c) 2026, Arinox AI and contributors
"""Phase D foundations: the pure production maths (golden numbers from the company's own sheets), the movement
ledger, the flow rules and Production Adjustment."""

import datetime as dt

import frappe
from frappe.tests import IntegrationTestCase

from arinox_apparel.arinox_apparel.tests.production_base import ProductionBase
from arinox_apparel.production import ledger, maths
from arinox_apparel.production.flow import Flow


class TestMaths(IntegrationTestCase):
	def test_planned_cut_rounds_up_per_size(self):
		sizes = [156, 433, 313, 458, 171, 221, 52]
		cut = [maths.planned_cut(s, 5) for s in sizes]
		self.assertEqual(cut, [164, 455, 329, 481, 180, 233, 55])
		self.assertEqual(sum(cut), 1897)  # not the sheet's fractional 1,894.2
		self.assertAlmostEqual(maths.required_fabric(sum(cut), 1.72), 3262.84, 2)
		self.assertEqual(maths.planned_cut(0, 5), 0)
		self.assertEqual(maths.planned_cut(100, 0), 100)

	def test_ship_tolerance_floor(self):
		self.assertEqual(maths.max_ship_qty(1462, 7.5), 1571)

	def test_ob_targets(self):
		self.assertAlmostEqual(maths.day_target(28, 480, 65, 24.4), 358.03, 2)
		self.assertAlmostEqual(maths.hour_target(28, 480, 65, 24.4), 44.75, 2)  # the sheet's 37.69 divides by 9.5 h
		self.assertAlmostEqual(maths.pcs_per_machine_per_day(480, 65, 24.4), 12.7869, 4)
		self.assertAlmostEqual(maths.operation_target_per_hour(0.5, 65), 78.0)
		self.assertEqual(maths.day_target(10, 480, 65, 0), 0)

	def test_learning_curve_and_traffic_light(self):
		curve = [(1, 50), (2, 75), (3, 90), (4, 100)]
		self.assertEqual(maths.learning_factor(1, curve), 0.5)
		self.assertEqual(maths.learning_factor(3, curve), 0.9)
		self.assertEqual(maths.learning_factor(9, curve), 1.0)
		self.assertEqual(maths.learning_factor(2, []), 1.0)
		rules = [("Yellow", 1), ("Red", 2)]
		self.assertEqual(maths.traffic_colour(0, rules), "Green")
		self.assertEqual(maths.traffic_colour(1, rules), "Yellow")
		self.assertEqual(maths.traffic_colour(3, rules), "Red")
		self.assertEqual(maths.traffic_colour(1, [("Red", 1)]), "Red")  # the stricter variant

	def test_quality_rates(self):
		self.assertAlmostEqual(maths.dhu(7, 140), 5.0)
		self.assertIsNone(maths.dhu(3, 0))
		self.assertAlmostEqual(maths.rft(130, 140), 92.857, 3)

	def test_reconciliation_identities_of_the_daily_report(self):
		# row 3: cut 1362 = packed 1322 + B 2 + rejects (11 + 20 + 5 + 2); packed = shipped 1291 + A stock 31
		self.assertEqual(1322 + 2 + (11 + 20 + 5 + 2), 1362)
		self.assertEqual(1291 + 31, 1322)
		self.assertAlmostEqual(maths.ratio(38, 1362), 0.0279, 4)
		self.assertAlmostEqual(maths.ratio(1291, 1362), 0.9479, 4)
		self.assertAlmostEqual(maths.ratio(1291, 1350), 0.9563, 4)
		# row 1: 1568 = 1544 + 4 + 20
		self.assertEqual(1544 + 4 + 20, 1568)
		self.assertAlmostEqual(maths.ratio(20, 1568), 0.012755, 6)
		self.assertAlmostEqual(maths.ratio(1525, 1568), 0.97258, 5)
		self.assertAlmostEqual(maths.ratio(1525, 1500), 1.01667, 5)

	def test_penalty_scopes(self):
		self.assertEqual(maths.penalty(2000, 30, 1, 1.0, "All Damaged"), (1.5, 30, 30.0))
		self.assertEqual(maths.penalty(2000, 30, 1, 1.0, "Excess Only"), (1.5, 10, 10.0))
		self.assertEqual(maths.penalty(2000, 20, 1, 5.0)[1:], (0, 0.0))  # exactly at the threshold: no penalty
		self.assertEqual(maths.penalty(0, 0, 1, 5.0), (None, 0, 0.0))

	def test_working_days_skip_sunday_and_holiday(self):
		fri = dt.date(2026, 11, 6)
		self.assertEqual(maths.add_working_days(fri, 3, [dt.date(2026, 11, 9)]), dt.date(2026, 11, 11))
		self.assertEqual(maths.add_working_days(fri, 1), dt.date(2026, 11, 7))  # a Saturday counts
		self.assertEqual(maths.add_working_days(fri, 2), dt.date(2026, 11, 9))  # Sunday skipped

	def test_packing_maths(self):
		self.assertAlmostEqual(maths.carton_cbm(54, 33, 14), 0.024948, 6)
		self.assertEqual(maths.cartons_needed(1520, 24), 64)
		self.assertEqual(maths.full_packs({"XS": 276, "S": 456, "M": 438, "L": 231}, {"XS": 1, "S": 2, "M": 2, "L": 1}), 219)
		self.assertEqual(maths.inspect_cartons(64), 8)
		self.assertEqual(maths.inspect_cartons(65), 9)
		self.assertEqual(maths.inspect_cartons(0), 0)
		self.assertAlmostEqual(maths.over_short_pct(1520, 1462), 3.967, 3)

	def test_gs1_check_digits(self):
		self.assertEqual(maths.gs1_check_digit("03600029145"), 2)  # the standard UPC-A worked example
		self.assertTrue(maths.valid_gs1("036000291452"))
		self.assertFalse(maths.valid_gs1("036000291453"))
		self.assertEqual(maths.gs1_check_digit("400638133393"), 1)  # EAN-13 4006381333931
		self.assertFalse(maths.valid_gs1("12ab"))

	def test_weighted_marker_efficiency(self):
		self.assertAlmostEqual(maths.weighted_marker_efficiency([(80, 10), (70, 30)]), 72.5)
		self.assertIsNone(maths.weighted_marker_efficiency([]))


class TestLedger(ProductionBase):
	def setUp(self):
		self.clean()
		self.card = self.issue_card()

	def post(self, stage, colour="Navy", size="S", qty=10, **kw):
		ledger.post(self.card.name, [dict(stage=stage, colour=colour, size=size, qty=qty, **kw)], "Production Adjustment", "_T-1")

	def test_post_unpost_totals(self):
		self.post("CUT", qty=50)
		self.post("CUT", size="M", qty=30)
		tot = ledger.totals(self.card.name)
		self.assertEqual(tot[("Navy", "S")]["CUT"], 50)
		self.assertEqual(ledger.stage_total(self.card.name, "CUT", colour="Navy"), 80)
		ledger.unpost("Production Adjustment", "_T-1")
		self.assertEqual(ledger.totals(self.card.name), {})

	def test_unknown_stage_and_unlisted_cell_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.post("NOPE")
		with self.assertRaises(frappe.ValidationError):
			self.post("CUT", colour="Green")  # not on the card

	def test_cut_cap(self):
		# Navy S: order 200, 5% extra -> 210 planned, +3 spare pieces -> 213
		self.post("CUT", qty=213)
		with self.assertRaises(frappe.ValidationError):
			self.post("CUT", qty=1)

	def test_cut_cap_warn_and_off(self):
		frappe.db.set_single_value("Apparel Settings", "cut_cap_mode", "Warn")
		try:
			self.post("CUT", qty=300)  # warns, does not raise
			frappe.db.set_single_value("Apparel Settings", "cut_cap_mode", "Off")
			self.post("CUT", qty=100)
		finally:
			frappe.db.set_single_value("Apparel Settings", "cut_cap_mode", "Block")

	def test_chain_cut_to_sew_to_finish_to_pack_to_ship(self):
		self.post("CUT", qty=100)
		self.post("CUT_REJECT", qty=4)
		with self.assertRaises(frappe.ValidationError):  # only 96 good panels
			self.post("SEW_IN", qty=97)
		self.post("SEW_IN", qty=96)
		with self.assertRaises(frappe.ValidationError):
			self.post("SEW_OUT", qty=97)
		self.post("SEW_OUT", qty=90)
		self.post("SEW_REJECT", qty=6)
		with self.assertRaises(frappe.ValidationError):  # nothing left in the line
			self.post("SEW_OUT", qty=1)
		with self.assertRaises(frappe.ValidationError):  # no wash route: finishing takes sewn output only
			self.post("FIN_IN", qty=91)
		self.post("FIN_IN", qty=90)
		self.post("FIN_A", qty=85)
		self.post("FIN_B", qty=3)
		self.post("FIN_REJECT", qty=2)
		with self.assertRaises(frappe.ValidationError):
			self.post("FIN_A", qty=1)
		self.post("SAMPLE_OUT", qty=2)
		with self.assertRaises(frappe.ValidationError):  # 85 A-grade less 2 samples
			self.post("PACKED", qty=84)
		self.post("PACKED", qty=83)
		with self.assertRaises(frappe.ValidationError):
			self.post("SHIPPED", qty=84)
		self.post("SHIPPED", qty=80)

	def test_rows_of_one_document_accumulate(self):
		rows = [dict(stage="CUT", colour="Navy", size="S", qty=100), dict(stage="SEW_IN", colour="Navy", size="S", qty=60),
				dict(stage="SEW_IN", colour="Navy", size="S", qty=41)]
		with self.assertRaises(frappe.ValidationError):
			ledger.post(self.card.name, rows, "Production Adjustment", "_T-2")
		self.assertEqual(ledger.totals(self.card.name), {})  # nothing half-written

	def test_override_skips_the_rules(self):
		ledger.post(self.card.name, [dict(stage="SEW_IN", colour="Navy", size="S", qty=5)], "Production Adjustment", "_T-3", override=True)
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_IN"), 5)

	def test_recut_is_limited_by_rejects(self):
		self.post("CUT", qty=100)
		self.post("CUT_REJECT", qty=5)
		self.post("CUT", qty=5, purpose="Re-cut")
		with self.assertRaises(frappe.ValidationError):
			self.post("CUT", qty=1, purpose="Re-cut")

	def test_subcontract_route_rules(self):
		# a wash after sewing and an embroidery before sewing
		self.card.cancel()
		self.clean()
		card = self.card_doc(processes=[
			{"subcontract_process": "Embroidery", "position": "Before Sewing", "sequence": 10, "item_state": "Cut Panels"},
			{"subcontract_process": "Wash", "position": "After Sewing", "sequence": 10, "item_state": "Garments"}])
		card.insert()
		card.submit()
		self.card = card
		self.post("CUT", qty=100)
		with self.assertRaises(frappe.ValidationError):  # embroidery not back yet
			self.post("SEW_IN", qty=10)
		self.post("SC_OUT", qty=100, process="Embroidery")
		with self.assertRaises(frappe.ValidationError):
			self.post("SC_OUT", qty=101, process="Embroidery")
		self.post("SC_BACK_GOOD", qty=60, process="Embroidery")
		self.post("SEW_IN", qty=60)
		with self.assertRaises(frappe.ValidationError):
			self.post("SEW_IN", qty=1)
		self.post("SEW_OUT", qty=60)
		with self.assertRaises(frappe.ValidationError):  # must go through the wash first
			self.post("FIN_IN", qty=1)
		with self.assertRaises(frappe.ValidationError):
			self.post("SC_OUT", qty=1, process="Print")  # not on the route
		self.post("SC_OUT", qty=60, process="Wash")
		self.post("SC_BACK_GOOD", qty=55, process="Wash")
		self.post("SC_BACK_REJECT_VENDOR", qty=5, process="Wash")
		self.post("FIN_IN", qty=55)
		with self.assertRaises(frappe.ValidationError):
			self.post("FIN_IN", qty=1)

	def test_rebuild_matches_incremental(self):
		adj = frappe.get_doc({"doctype": "Production Adjustment", "production_card": self.card.name, "stage": "CUT", "colour": "Navy",
							  "size": "S", "qty": 40, "reason": "Opening count", "posting_date": frappe.utils.nowdate()})
		adj.insert()
		adj.submit()
		before = ledger.totals(self.card.name)
		self.assertEqual(before[("Navy", "S")]["CUT"], 40)
		written = ledger.rebuild_movements(self.card.name)
		self.assertEqual(written, 1)
		self.assertEqual(ledger.totals(self.card.name), before)


class TestAdjustment(ProductionBase):
	def setUp(self):
		self.clean()
		self.card = self.issue_card()

	def adjust(self, qty, stage="CUT", **kw):
		d = frappe.get_doc({"doctype": "Production Adjustment", "production_card": self.card.name, "stage": stage, "colour": "Navy",
							"size": "M", "qty": qty, "reason": "Recount", "posting_date": frappe.utils.nowdate(), **kw})
		d.insert()
		return d

	def test_positive_then_negative(self):
		a = self.adjust(100)
		a.submit()
		b = self.adjust(-30)
		b.submit()
		self.assertEqual(ledger.stage_total(self.card.name, "CUT", "Navy", "M"), 70)
		with self.assertRaises(frappe.ValidationError):  # cannot take off more than recorded
			self.adjust(-71).submit()

	def test_needs_reason_quantity_and_listed_cell(self):
		with self.assertRaises(frappe.ValidationError):
			self.adjust(0)
		with self.assertRaises(frappe.ValidationError):
			self.adjust(5, reason="  ")
		with self.assertRaises(frappe.ValidationError):
			self.adjust(5, colour="Pink")
		with self.assertRaises(frappe.ValidationError):  # a process stage needs a process
			self.adjust(5, stage="SC_OUT")

	def test_cancel_removes_rows(self):
		a = self.adjust(10)
		a.submit()
		a.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "CUT"), 0)

	def test_card_with_movements_cannot_be_cancelled(self):
		self.adjust(10).submit()
		with self.assertRaises(frappe.ValidationError):
			self.card.cancel()
