# Copyright (c) 2026, Arinox AI and contributors
"""Slice D4: Operation Bulletin, Line Input, Daily Line Report, Line QC Report and the sewing reports."""

import os
import unittest

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.test_cutting import CuttingBase
from arinox_apparel.production import cutting, ledger, sewing

# set ARINOX_OB_WORKBOOK to the path of the reference "BELLADAHL OBS R&D.xlsx" to run the real-workbook test
REF_OB = os.environ.get("ARINOX_OB_WORKBOOK", "")

# four operations that add up to the C2027 sheet: 18.8 machine minutes + 5.6 manual minutes = 24.4
OPS = [{"seq": i + 1, "operation": f"Op {i + 1}", "part_group": "Body", "machine_type": "SNLS", "machine_sam": 4.7, "manual_sam": 1.4} for i in range(4)]


class SewingBase(CuttingBase):
	def setUp(self):
		super().setUp()
		self.lines = u.make_floors()
		self.line = self.lines["_AT Factory A"][0]
		self.line2 = self.lines["_AT Factory A"][1]
		frappe.db.delete("Operation Bulletin", {"style_item": self.style})
		self.cut = self.lay(self.rolls_for(), submit=True)

	def tearDown(self):
		frappe.db.delete("Operation Bulletin", {"style_item": self.style})
		super().tearDown()

	def ob(self, activate=True, **kw):
		d = frappe.get_doc({"doctype": "Operation Bulletin", "style_item": self.style, "operators": 28, "working_minutes": 480,
							"expected_efficiency_pct": 65, "operations": [dict(o) for o in OPS], **kw})
		d.insert()
		if activate:
			d.activate()
		return d

	def bundles(self, size="S", body=1, n=1):
		return frappe.get_all("Cut Bundle", {"production_card": self.card.name, "size": size, "body_no": body, "status": ["in", ["Cut", "Back"]], "component": "Shell"},
							  ["name", "qty"], order_by="bundle_no", limit=n)

	def loaded(self, size="S", body=1, n=1):
		return frappe.get_all("Cut Bundle", {"production_card": self.card.name, "size": size, "body_no": body, "status": "Issued", "component": "Shell"}, ["name", "qty"], order_by="bundle_no", limit=n)

	def load(self, bundles, line=None, date=None, submit=True, **kw):
		d = frappe.get_doc({"doctype": "Line Input", "production_card": self.card.name, "line": line or self.line, "input_date": date or nowdate(),
							"bundles": [{"bundle": b.name if hasattr(b, "name") else b} for b in bundles], **kw})
		d.insert()
		if submit:
			d.submit()
		return d

	def dlr(self, outputs, submit=True, **kw):
		data = {"doctype": "Daily Line Report", "report_date": nowdate(), "line": self.line, "operators_present": 28, "shift_minutes": 480,
				"outputs": [{"production_card": self.card.name, "colour": "Navy", **o} for o in outputs]}
		data.update(kw)
		d = frappe.get_doc(data)
		d.insert()
		if submit:
			d.submit()
		return d


class TestOperationBulletin(SewingBase):
	def test_targets_match_the_company_sheet(self):
		ob = self.ob()
		self.assertEqual((ob.total_sam, ob.sewing_sam, ob.manual_sam), (24.4, 18.8, 5.6))
		self.assertAlmostEqual(ob.target_per_day, 358.03, 2)
		self.assertAlmostEqual(ob.target_per_hour, 44.75, 2)  # the sheet shows 37.69 (divides by 9.5 h)
		self.assertAlmostEqual(ob.pcs_per_machine, 12.7869, 4)
		self.assertAlmostEqual(ob.pitch_time, 6.1, 3)
		self.assertAlmostEqual(ob.operations[0].target_per_hr, 60 * 0.65 / 6.1, 2)
		self.assertAlmostEqual(ob.operations[0].operators_needed, 44.75 / (60 * 0.65 / 6.1), 2)
		self.assertEqual(ob.status, "Active")

	def test_balance_flags(self):
		ops = [dict(o) for o in OPS]
		ops[0].update(machine_sam=9.0, manual_sam=0)  # far above the pitch
		ops[1].update(machine_sam=1.0, manual_sam=0)  # far below
		ob = self.ob(operations=ops, activate=False)
		self.assertEqual((ob.operations[0].pitch_flag, ob.operations[1].pitch_flag), ("Above", "Below"))

	def test_heading_rows_have_no_time(self):
		ops = [{"operation": "COLLAR"}] + [dict(o) for o in OPS]
		ob = self.ob(operations=ops, activate=False)
		self.assertEqual(ob.operation_count, 4)
		self.assertEqual(ob.total_sam, 24.4)

	def test_activation_needs_times_and_supersedes_the_old_version(self):
		empty = self.ob(operations=[], activate=False)
		with self.assertRaises(frappe.ValidationError):
			empty.activate()
		first = self.ob()
		second = self.ob(version=2)
		self.assertEqual(frappe.db.get_value("Operation Bulletin", first.name, "status"), "Superseded")
		self.assertEqual(sewing.active_ob(self.style).name, second.name)

	def test_validation(self):
		with self.assertRaises(frappe.ValidationError):
			self.ob(operators=0)
		bad = [dict(OPS[0], machine_sam=-1)]
		with self.assertRaises(frappe.ValidationError):
			self.ob(operations=bad)

	def test_parse_the_sheet_layout(self):
		rows = [
			["CORTEX TEXTILE"], ["O P E R A T I O N   B U L L E T I N"],
			["DATE", "2026-07-20", "BUYER 客户", "BELLADAHL", "NO.OF WORKERS 车位人数", 28],
			["STYLE NAME", "C2027", "WORKING TIME / DAY 每天工作时间", 480],
			["DESCRIPTION 描述", "LS BUTTON DOWN", "COLOUR颜色", "OLIVE", "EXPECTED EFFICIENCY 预期完成量", 0.65],
			["OPRN NUM", "PARTS / DESCRIPTION", "M/C SM", "MANUAL SM", "TARGET/ HR", "LABOUR REQ/ HR", "OPR NEEDED", "NO OF HLP", "M/C TYPE"],
			[None, "COLLAR"],
			[1, "MARK COLLAR", 0.5, None, 78, 0.48, None, None, "TABLE"],
			[2, "MAKE COLLAR", 0.7, 0.2, 55, 0.67, None, None, "SNEC"],
			[None, "CUFF"],
			["MAKE CUFF", "MAKE CUFF", 0.7, None, 55, 0.67, None, None, "SNEC"],
			["TOTAL", None, 1.9, 0.2],
			[99, "AFTER TOTAL", 5, None],
		]
		p = sewing.parse_ob_rows(rows)
		self.assertEqual(p["header"]["operators"], 28)
		self.assertEqual(p["header"]["working_minutes"], 480)
		self.assertAlmostEqual(p["header"]["expected_efficiency_pct"], 65)
		self.assertEqual([o["operation"] for o in p["operations"]], ["MARK COLLAR", "MAKE COLLAR", "MAKE CUFF"])
		self.assertEqual(p["operations"][0]["part_group"], "COLLAR")
		self.assertEqual(p["operations"][2]["part_group"], "CUFF")
		self.assertEqual((p["operations"][1]["machine_sam"], p["operations"][1]["manual_sam"]), (0.7, 0.2))
		self.assertEqual(p["operations"][2]["seq"], 3)  # a non-numeric number is replaced by the running count

	@unittest.skipUnless(REF_OB and os.path.exists(REF_OB), "set ARINOX_OB_WORKBOOK to run this")
	def test_parse_the_real_workbook(self):
		import openpyxl

		wb = openpyxl.load_workbook(REF_OB, data_only=True, read_only=True)
		p = sewing.parse_ob_rows([list(r) for r in wb["C2027"].iter_rows(values_only=True)])
		self.assertEqual(p["header"]["operators"], 28)
		self.assertEqual(p["header"]["working_minutes"], 480)
		self.assertGreater(len(p["operations"]), 20)
		self.assertAlmostEqual(p["header"]["sheet_machine_total"], 18.8, 2)  # the sheet's own TOTAL row
		self.assertAlmostEqual(p["header"]["sheet_manual_total"], 5.6, 2)
		ob = self.ob(operations=p["operations"], operators=p["header"]["operators"])
		# the 38 operation rows add up to 27.0 minutes, not the sheet's 24.4: the importer warns about this
		self.assertEqual(len(p["operations"]), 38)
		self.assertAlmostEqual(ob.total_sam, 27.0, 1)


class TestLineInput(SewingBase):
	def test_load_posts_sew_in_and_marks_bundles(self):
		b = self.bundles("S", 1, 2)
		li = self.load(b)
		self.assertEqual(li.total_qty, sum(x.qty for x in b))
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_IN", "Navy", "S"), li.total_qty)
		self.assertEqual(frappe.db.get_value("Cut Bundle", b[0].name, "status"), "Issued")
		self.assertEqual(frappe.db.get_value("Cut Bundle", b[0].name, "line"), self.line)
		self.assertEqual(frappe.db.get_value("Production Card", self.card.name, "status"), "In Sewing")

	def test_bundle_cannot_be_loaded_twice_or_from_another_card(self):
		b = self.bundles("S", 1, 1)
		self.load(b)
		with self.assertRaises(frappe.ValidationError):
			self.load(b)
		dup = frappe.get_doc({"doctype": "Line Input", "production_card": self.card.name, "line": self.line, "bundles": [{"bundle": self.bundles("M", 1, 1)[0].name}] * 2})
		with self.assertRaises(frappe.ValidationError):
			dup.insert()

	def test_bundle_purpose_must_match(self):
		b = self.bundles("S", 1, 1)
		with self.assertRaises(frappe.ValidationError):
			self.load(b, purpose="Pilot")

	def test_before_sewing_process_blocks_until_the_bundle_is_back(self):
		frappe.get_doc({"doctype": "Production Card Process", "parent": self.card.name, "parenttype": "Production Card", "parentfield": "processes",
						"subcontract_process": "Embroidery", "position": "Before Sewing", "item_state": "Cut Panels", "idx": 1}).db_insert()
		b = self.bundles("S", 1, 1)
		with self.assertRaises(frappe.ValidationError):
			self.load(b)
		frappe.db.set_value("Cut Bundle", b[0].name, "status", "Back")
		ledger.post(self.card.name, [dict(stage="SC_OUT", colour="Navy", size="S", qty=b[0].qty, process="Embroidery"),
									 dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=b[0].qty, process="Embroidery")], "Production Adjustment", "_E1")
		self.load(b)

	def test_kit_check_for_lining(self):
		self.clean()
		self.card = self.issue_card(fabrics=[
			{"colour": "Navy", "fabric_item": self.navy_fabric, "material_role": "Shell", "consumption": 1.2, "consumption_uom": "Meter", "consumption_source": "Manual"},
			{"colour": "Navy", "fabric_item": self.black_fabric, "material_role": "Lining", "consumption": 0.5, "consumption_uom": "Meter", "consumption_source": "Manual"}])
		self.lay(self.rolls_for(plies=35), sizes=(("S", 1),), submit=True)
		b = self.bundles("S", 1, 1)
		frappe.db.set_single_value("Apparel Settings", "kit_check", "Block")
		try:
			with self.assertRaises(frappe.ValidationError):
				self.load(b)
		finally:
			frappe.db.set_single_value("Apparel Settings", "kit_check", "Warn")
		self.load(b)  # a warning only

	def test_cancel_restores_the_bundle_unless_it_was_sewn(self):
		b = self.bundles("S", 1, 1)
		li = self.load(b)
		li.cancel()
		self.assertEqual(frappe.db.get_value("Cut Bundle", b[0].name, "status"), "Cut")
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_IN"), 0)
		li = self.load(b)
		frappe.db.set_value("Cut Bundle", b[0].name, "sewn_qty", 5)
		with self.assertRaises(frappe.ValidationError):
			li.cancel()

	def test_without_bundles_when_the_setting_allows(self):
		frappe.db.set_single_value("Apparel Settings", "require_bundle_on_input", 0)
		try:
			d = frappe.get_doc({"doctype": "Line Input", "production_card": self.card.name, "line": self.line,
								"bundles": [{"colour": "Navy", "size": "S", "qty": 50}]})
			d.insert()
			d.submit()
			self.assertEqual(ledger.stage_total(self.card.name, "SEW_IN", "Navy", "S"), 50)
			frappe.db.set_single_value("Apparel Settings", "require_bundle_on_input", 1)
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": "Line Input", "production_card": self.card.name, "line": self.line, "bundles": [{"colour": "Navy", "size": "S", "qty": 5}]}).insert()
		finally:
			frappe.db.set_single_value("Apparel Settings", "require_bundle_on_input", 1)


class TestDailyLineReport(SewingBase):
	def setUp(self):
		super().setUp()
		self.ob()
		self.input = self.load(self.bundles("S", 1, 6) + self.bundles("M", 1, 6), date=add_days(nowdate(), -3))  # day 4 of the style on the line

	def test_efficiency_and_target_follow_the_bulletin(self):
		d = self.dlr([{"size": "S", "qty": 100}, {"size": "M", "qty": 100}])
		self.assertEqual(d.total_output, 200)
		self.assertAlmostEqual(d.produced_minutes, 200 * 24.4, 1)
		self.assertAlmostEqual(d.available_minutes, 28 * 480, 1)
		self.assertAlmostEqual(d.efficiency_pct, 200 * 24.4 / (28 * 480) * 100, 1)
		self.assertEqual(d.learning_day, 4)
		self.assertAlmostEqual(d.learning_factor_pct, 92.31, 2)  # day 4: 60 % planned efficiency against 65 %
		self.assertAlmostEqual(d.target_qty, 358.03 * 0.9231, 0)
		self.assertAlmostEqual(d.variance_to_target, 200 - d.target_qty, 1)
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_OUT"), 200)

	def test_learning_curve_scales_the_first_day(self):
		self.input.cancel()
		self.input = self.load(self.bundles("S", 1, 6), date=nowdate())
		d = self.dlr([{"size": "S", "qty": 60}], submit=False)
		self.assertEqual(d.learning_day, 1)
		self.assertAlmostEqual(d.target_qty, 358.03 * 0.5385, 0)

	def test_overtime_and_downtime_change_the_available_minutes(self):
		d = self.dlr([{"size": "S", "qty": 100}], overtime_minutes=60, downtime_minutes=30, downtime_reason="Power")
		self.assertEqual(d.available_minutes, 28 * (480 + 60 - 30))
		h = self.dlr([{"size": "S", "qty": 1}], operators_present=21, helpers_present=7, submit=False)  # the sheet's 21 operators + 7 helpers
		self.assertEqual(h.available_minutes, 28 * 480)
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "S", "qty": 10}], downtime_minutes=15, downtime_reason="")

	def test_output_cannot_exceed_what_was_loaded(self):
		total_s = ledger.stage_total(self.card.name, "SEW_IN", "Navy", "S")
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "S", "qty": total_s + 1}])

	def test_bundle_completion(self):
		b = self.loaded("S", 1, 1)[0]
		d = self.dlr([{"size": "S", "qty": b.qty - 5, "bundle": b.name}])
		self.assertEqual(frappe.db.get_value("Cut Bundle", b.name, "status"), "Issued")
		d2 = self.dlr([{"size": "S", "qty": 5, "bundle": b.name}])
		self.assertEqual(frappe.db.get_value("Cut Bundle", b.name, "status"), "Complete")
		with self.assertRaises(frappe.ValidationError):  # nothing left on the bundle
			self.dlr([{"size": "S", "qty": 1, "bundle": b.name}])
		d2.cancel()
		self.assertEqual(frappe.db.get_value("Cut Bundle", b.name, "status"), "Issued")
		self.assertEqual(frappe.db.get_value("Cut Bundle", b.name, "sewn_qty"), b.qty - 5)

	def test_bundle_must_match_row_and_line(self):
		b = self.loaded("S", 1, 1)[0]
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "M", "qty": 5, "bundle": b.name}])
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "S", "qty": 5, "bundle": b.name}], line=self.line2)

	def test_needs_an_active_bulletin_for_efficiency(self):
		frappe.db.delete("Operation Bulletin", {"style_item": self.style})
		d = self.dlr([{"size": "S", "qty": 10}])
		self.assertEqual((d.produced_minutes, d.target_qty), (0, 0))

	def test_validation(self):
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "S", "qty": 10}], operators_present=0)
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "S", "qty": 0}])
		with self.assertRaises(frappe.ValidationError):
			self.dlr([{"size": "XXL", "qty": 5}])
		with self.assertRaises(frappe.ValidationError):
			self.dlr([])

	def test_reports(self):
		from arinox_apparel.arinox_apparel.report.daily_production_report.daily_production_report import execute as daily
		from arinox_apparel.arinox_apparel.report.line_efficiency_and_dhu.line_efficiency_and_dhu import execute as eff
		from arinox_apparel.arinox_apparel.report.line_loading.line_loading import execute as loading
		from arinox_apparel.arinox_apparel.report.sewing_wip.sewing_wip import execute as wip

		self.dlr([{"size": "S", "qty": 100}])
		loaded = ledger.stage_total(self.card.name, "SEW_IN")
		_c, rows = loading({"production_card": self.card.name})
		self.assertEqual((rows[0]["loaded"], rows[0]["cumulative"]), (loaded, loaded))  # loaded three days ago: inside the 7-day window
		_c, rows = wip({"production_card": self.card.name})
		self.assertEqual(rows[0]["wip"], loaded - 100)
		_c, rows = eff({"line": self.line})
		self.assertEqual(rows[0]["output"], 100)
		_c, rows = daily({"production_card": self.card.name})
		navy = next(r for r in rows if r["colour"] == "Navy")
		self.assertEqual((navy["sew_total"], navy["sew_today"]), (100, 100))
		self.assertEqual(navy["cut_total"], 735)


class TestLineQC(SewingBase):
	def qc(self, submit=False, **kw):
		data = {"doctype": "Line QC Report", "audit_type": "End-line", "report_date": nowdate(), "line": self.line, "production_card": self.card.name,
				"hours": [{"hour_slot": "7.30-8.30", "checked": 70, "passed": 66}, {"hour_slot": "8.30-9.30", "checked": 70, "passed": 64}],
				"defects": [{"hour_slot": "7.30-8.30", "defect_code": "Puckering", "qty": 4}, {"hour_slot": "8.30-9.30", "defect_code": "Open Seam or Raw Edge", "qty": 3}]}
		data.update(kw)
		d = frappe.get_doc(data)
		d.insert()
		if submit:
			d.submit()
		return d

	def setUp(self):
		super().setUp()
		self.load(self.bundles("S", 1, 6))

	def test_dhu_rft_and_defect_rate(self):
		d = self.qc()
		self.assertEqual((d.total_checked, d.total_passed, d.total_defects), (140, 130, 7))
		self.assertAlmostEqual(d.dhu, 5.0)
		self.assertAlmostEqual(d.defect_pct, 7.14, 2)
		self.assertAlmostEqual(d.rft_pct, 92.86, 2)

	def test_hour_rules(self):
		with self.assertRaises(frappe.ValidationError):
			self.qc(hours=[{"hour_slot": "7.30-8.30", "checked": 10, "passed": 11}])

	def test_reject_posts_sew_reject_and_raises_a_recut(self):
		d = self.qc(dispositions=[{"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 3, "defect_code": "Holes", "replace": 1},
								  {"colour": "Navy", "size": "S", "disposition": "Rework", "qty": 5, "defect_code": "Puckering"}], submit=True)
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_REJECT", "Navy", "S"), 3)
		req = frappe.get_all("Recut Request", {"production_card": self.card.name, "remarks": ["like", f"%{d.name}%"]}, ["qty", "reason", "docstatus", "size"])
		self.assertEqual([(r.qty, r.reason, r.docstatus, r.size) for r in req], [(3, "Holes", 0, "S")])  # a draft the cutting supervisor reviews
		d.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "SEW_REJECT"), 0)

	def test_disposition_rules(self):
		with self.assertRaises(frappe.ValidationError):  # B-grade is decided at finishing
			self.qc(dispositions=[{"colour": "Navy", "size": "S", "disposition": "B-Grade", "qty": 1}])
		with self.assertRaises(frappe.ValidationError):  # only a reject needs a re-cut
			self.qc(dispositions=[{"colour": "Navy", "size": "S", "disposition": "Rework", "qty": 1, "defect_code": "Holes", "replace": 1}])
		with self.assertRaises(frappe.ValidationError):  # a re-cut needs the defect
			self.qc(dispositions=[{"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 1, "replace": 1}])
		with self.assertRaises(frappe.ValidationError):
			self.qc(dispositions=[{"colour": "Pink", "size": "S", "disposition": "Reject", "qty": 1}])

	def test_traffic_light_rounds(self):
		d = self.qc(audit_type="Inline (Traffic Light)", traffic=[
			{"operator": "A", "round_no": 1, "pieces_checked": 5, "defects": 0}, {"operator": "B", "round_no": 1, "pieces_checked": 5, "defects": 1},
			{"operator": "C", "round_no": 1, "pieces_checked": 5, "defects": 3}])
		self.assertEqual([t.light for t in d.traffic], ["Green", "Yellow", "Red"])

	def test_finishing_posts_a_grade_b_grade_and_rejects(self):
		self.dlr_input = None
		ob = self.ob()
		sewn = self.dlr([{"size": "S", "qty": 100}])
		ledger.post(self.card.name, [dict(stage="FIN_IN", colour="Navy", size="S", qty=100)], "Production Adjustment", "_F1")
		d = self.qc(audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 100, "passed": 94}],
					passes=[{"colour": "Navy", "size": "S", "qty": 94}], defects=[],
					dispositions=[{"colour": "Navy", "size": "S", "disposition": "B-Grade", "qty": 4, "defect_code": "Stains"},
								  {"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 2, "defect_code": "Holes"}], submit=True)
		self.assertEqual(ledger.stage_total(self.card.name, "FIN_A", "Navy", "S"), 94)
		self.assertEqual(ledger.stage_total(self.card.name, "FIN_B", "Navy", "S"), 4)
		self.assertEqual(ledger.stage_total(self.card.name, "FIN_REJECT", "Navy", "S"), 2)

	def test_finishing_passes_must_add_up(self):
		with self.assertRaises(frappe.ValidationError):
			self.qc(audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 100, "passed": 94}], passes=[{"colour": "Navy", "size": "S", "qty": 90}], defects=[])

	def test_finishing_cannot_classify_more_than_received(self):
		with self.assertRaises(frappe.ValidationError):
			self.qc(audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 10, "passed": 10}], passes=[{"colour": "Navy", "size": "S", "qty": 10}], defects=[], submit=True)
