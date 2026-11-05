# Copyright (c) 2026, Arinox AI and contributors
"""Slice D3: fabric issue, cut plan, lay report, bundles, re-cut, reconciliation inputs."""

import frappe
from frappe.utils import nowdate

from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.production_base import ProductionBase
from arinox_apparel.arinox_apparel.tests.test_production_card import make_floor_user
from arinox_apparel.materials.items import ensure_fabric_item
from arinox_apparel.production import cutting, ledger
from arinox_apparel.production.stock import issue_fabric_entry, moved, roll_available

_roll = {"n": 0}


class CuttingBase(ProductionBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.navy_fabric = ensure_fabric_item("_ATQ-D3", "Navy", "_ATQ-D3, 100% Cotton, CW 132CM", 145, 132)
		cls.black_fabric = ensure_fabric_item("_ATQ-D3", "Black", "_ATQ-D3, 100% Cotton, CW 132CM", 145, 132)
		# the settings point at the default company's warehouses; the test company needs its own
		abbr = frappe.db.get_value("Company", cls.company, "abbr")
		cls._saved = {}
		for field, name in (("store_warehouse_fabric", "_AT Fabric Store"), ("cutting_wip_warehouse", "_AT Cutting WIP")):
			full = f"{name} - {abbr}"
			if not frappe.db.exists("Warehouse", full):
				frappe.get_doc({"doctype": "Warehouse", "warehouse_name": name, "company": cls.company}).insert(ignore_permissions=True)
			cls._saved[field] = frappe.db.get_single_value("Apparel Settings", field)
			frappe.db.set_single_value("Apparel Settings", field, full)

	@classmethod
	def tearDownClass(cls):
		for field, val in getattr(cls, "_saved", {}).items():
			frappe.db.set_single_value("Apparel Settings", field, val)
		super().tearDownClass()

	def setUp(self):
		self.clean()
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)
		self.store = frappe.db.get_single_value("Apparel Settings", "store_warehouse_fabric")
		self.wip = frappe.db.get_single_value("Apparel Settings", "cutting_wip_warehouse")
		self.card = self.issue_card(fabrics=[{"colour": "Navy", "fabric_item": self.navy_fabric, "consumption": 1.2, "consumption_uom": "Meter", "consumption_source": "Manual"}])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)

	def make_roll(self, length, shade="A", width=132, status="Accepted", warehouse=None, item=None, dye_lot="L1"):
		_roll["n"] += 1
		item = item or self.navy_fabric
		bid = f"_AT-R{_roll['n']}-{frappe.generate_hash(length=4)}"
		b = frappe.get_doc({"doctype": "Batch", "batch_id": bid, "item": item}).insert(ignore_permissions=True)
		frappe.db.set_value("Batch", b.name, {"apparel_roll_no": str(_roll["n"]), "apparel_shade_band": shade, "apparel_width_cm": width,
											   "apparel_inspection_status": status, "apparel_dye_lot": dye_lot, "apparel_actual_length": length})
		wh = warehouse or self.wip
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt", "company": self.company,
							 "items": [{"item_code": item, "qty": length, "t_warehouse": wh, "batch_no": b.name, "use_serial_batch_fields": 1, "basic_rate": 1}]})
		se.insert(ignore_permissions=True)
		se.submit()
		return b.name

	def plan(self, plies=105, ratios=((("S", 2), ("M", 3), ("L", 2))), marker=8.4, shade="A", **kw):
		doc = frappe.get_doc({
			"doctype": "Cut Plan", "production_card": self.card.name, "colour": "Navy", "fabric_item": self.navy_fabric,
			"lays": [{"lay_no": 1, "marker_ref": "M1", "marker_length_m": marker, "planned_plies": plies, "shade_band": shade}],
			"ratios": [{"lay_no": 1, "size": s, "ratio": r} for s, r in ratios], **kw})
		doc.insert()
		return doc

	def lay(self, rolls, sizes=(("S", 2), ("M", 3), ("L", 2)), submit=False, **kw):
		data = {"doctype": "Lay Report", "production_card": self.card.name, "colour": "Navy", "fabric_item": self.navy_fabric, "lay_no": 1,
				"marker_length_m": 8.4, "lay_date": nowdate(), "gate_override": 1, "gate_override_reason": "test",
				"rolls": [{"batch": b, "plies": p} for b, p in rolls], "sizes": [{"size": s, "ratio": r} for s, r in sizes]}
		data.update(kw)
		doc = frappe.get_doc(data)
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def rolls_for(self, plies=105, per_roll=35, **kw):
		return [(self.make_roll(per_roll * 8.4 + 6, **kw), per_roll) for _ in range(plies // per_roll)]


class TestFabricIssue(CuttingBase):
	def test_issue_moves_accepted_rolls_to_cutting(self):
		b = self.make_roll(300, warehouse=self.store)
		self.assertEqual(roll_available(b, self.store, self.navy_fabric), 300)
		name = issue_fabric_entry(self.card.name, [{"batch_no": b, "qty": 300}])
		self.assertTrue(name)
		self.assertEqual(roll_available(b, self.wip, self.navy_fabric), 300)
		self.assertEqual(moved(self.card.name, "Fabric Issue", self.navy_fabric), 300)
		self.card.reload()
		self.assertEqual(self.card.fabrics[0].issued_m, 300)

	def test_rejected_and_unknown_rolls_cannot_be_issued(self):
		bad = self.make_roll(100, warehouse=self.store, status="Rejected")
		with self.assertRaises(frappe.ValidationError):
			issue_fabric_entry(self.card.name, [{"batch_no": bad, "qty": 100}])
		other = ensure_fabric_item("_ATQ-OTHER", "Navy", "other", 145, 132)
		b2 = self.make_roll(100, warehouse=self.store, item=other)
		with self.assertRaises(frappe.ValidationError):
			issue_fabric_entry(self.card.name, [{"batch_no": b2, "qty": 100}])

	def test_issuable_rolls_listing(self):
		b = self.make_roll(120, warehouse=self.store)
		rows = cutting.get_issuable_rolls(self.card.name)
		self.assertIn(b, [r["batch"] for r in rows])


class TestCutPlan(CuttingBase):
	def test_plan_matches_the_card(self):
		p = self.plan()
		self.assertEqual(p.lays[0].pieces_per_ply, 7)
		self.assertEqual(p.lays[0].planned_pieces, 735)
		self.assertAlmostEqual(p.marker_consumption, 1.2, 4)
		self.assertAlmostEqual(p.fr_consumption, 1.2, 4)
		self.assertEqual(p.variance_pct, 0)
		self.assertIn("S: plan 210, lays 210 (+0)", p.size_summary)
		self.assertEqual(p.release(), "Released")

	def test_variance_needs_manager_approval(self):
		p = self.plan(marker=9.4)  # 1.343 m per piece vs 1.2
		self.assertGreater(p.variance_pct, 5)
		self.assertEqual(p.release(), "Pending Approval")
		with self.assertRaises(frappe.ValidationError):
			p.approve()  # reason needed
		self.assertEqual(p.approve("Buyer accepted the heavier marker"), "Released")
		self.assertTrue(frappe.db.get_value("Cut Plan", p.name, "approved_by"))

	def test_size_missing_and_overshoot_are_flagged(self):
		p = self.plan(ratios=(("S", 2), ("M", 3)))  # no L
		self.assertIn("Size L is on the card but in no lay", p.red_flags)
		p = self.plan(plies=130, ratios=(("S", 2), ("M", 3), ("L", 2)))
		self.assertIn("more than planned", p.red_flags)

	def test_validation(self):
		with self.assertRaises(frappe.ValidationError):
			self.plan(ratios=(("XXL", 1),))
		doc = frappe.get_doc({"doctype": "Cut Plan", "production_card": self.card.name, "colour": "Navy", "fabric_item": self.navy_fabric,
							  "lays": [{"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}, {"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}],
							  "ratios": [{"lay_no": 1, "size": "S", "ratio": 1}]})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		doc = frappe.get_doc({"doctype": "Cut Plan", "production_card": self.card.name, "colour": "Navy", "fabric_item": self.black_fabric,
							  "lays": [{"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}], "ratios": [{"lay_no": 1, "size": "S", "ratio": 1}]})
		with self.assertRaises(frappe.ValidationError):  # not a fabric of this colour on the card
			doc.insert()

	def test_suggest_rolls_groups_by_shade_and_uses_longest_first(self):
		a1, a2 = self.make_roll(300, shade="Z1"), self.make_roll(200, shade="Z1")
		self.make_roll(500, shade="Z2")
		p = self.plan(plies=40, shade="Z1")  # 40 plies x 8.4 m = 336 m, shade Z1
		res = p.suggest_rolls()
		lay = res["lays"][0]
		self.assertEqual([r["batch"] for r in lay["rolls"]], [a1, a2])
		self.assertEqual(lay["rolls"][0]["plies"], 35)  # 294 m
		self.assertTrue(all(r["shade"] == "Z1" for r in lay["rolls"]))
		self.assertEqual(res["short"], [])

	def test_suggest_rolls_reports_a_short_lay(self):
		self.make_roll(100, shade="Z9")
		res = self.plan(plies=40, shade="Z9").suggest_rolls()
		self.assertEqual(res["short"][0]["lay_no"], 1)

	def test_cannot_reopen_a_plan_that_has_been_cut(self):
		p = self.plan()
		p.release()
		lay = self.lay(self.rolls_for(), cut_plan=p.name, submit=True)
		with self.assertRaises(frappe.ValidationError):
			p.reopen()


class TestLayReport(CuttingBase):
	def test_submit_posts_pieces_numbers_plies_and_returns_remnants(self):
		rolls = self.rolls_for()
		lay = self.lay(rolls, submit=True)
		self.assertEqual((lay.total_plies, lay.pieces_cut), (105, 735))
		self.assertAlmostEqual(lay.laid_m, 882.0, 3)
		self.assertAlmostEqual(lay.lay_consumption, 1.2, 4)
		tot = ledger.totals(self.card.name)
		self.assertEqual((tot[("Navy", "S")]["CUT"], tot[("Navy", "M")]["CUT"], tot[("Navy", "L")]["CUT"]), (210, 315, 210))
		bundles = frappe.get_all("Cut Bundle", {"lay_report": lay.name}, ["size", "body_no", "ply_from", "ply_to", "qty", "bundle_no", "is_short", "status"], order_by="bundle_no")
		self.assertEqual(len(bundles), 42)  # S 2 bodies x 6 + M 3 x 6 + L 2 x 6
		self.assertEqual(min(b.ply_from for b in bundles), 1)
		self.assertEqual(max(b.ply_to for b in bundles), 105)
		self.assertEqual(sum(b.qty for b in bundles), 735)
		self.assertTrue(all(b.status == "Cut" for b in bundles))
		last = [b for b in bundles if b.size == "S" and b.body_no == 1][-1]
		self.assertEqual((last.ply_from, last.ply_to, last.qty, last.is_short), (101, 105, 5, 1))  # the short bundle
		self.assertEqual(len({b.bundle_no for b in bundles}), 42)
		# each roll had 6 m left: returned to the store as a remnant
		self.assertTrue(lay.remnant_entry)
		self.assertAlmostEqual(moved(self.card.name, "Remnant Return", self.navy_fabric), 18.0, 3)
		self.assertEqual(frappe.db.get_value("Production Card", self.card.name, "status"), "In Cutting")

	def test_balance_below_the_remnant_minimum_becomes_end_bit(self):
		b = self.make_roll(35 * 8.4 + 3)  # 3 m left, minimum is 5
		lay = self.lay([(b, 35)], sizes=(("S", 2),))
		self.assertEqual(lay.rolls[0].balance_returned_m, 0)
		self.assertAlmostEqual(lay.rolls[0].end_bit_m, 3.0, 3)

	def test_one_shade_per_lay(self):
		a, b = self.make_roll(300, shade="A"), self.make_roll(300, shade="B")
		with self.assertRaises(frappe.ValidationError):
			self.lay([(a, 10), (b, 10)])

	def test_width_spread_and_marker_width(self):
		a, b = self.make_roll(300, width=132), self.make_roll(300, width=135)
		with self.assertRaises(frappe.ValidationError):
			self.lay([(a, 10), (b, 10)])
		with self.assertRaises(frappe.ValidationError):  # marker wider than the roll
			self.lay([(a, 10)], marker_width_cm=140)

	def test_only_accepted_rolls_are_cut(self):
		hold = self.make_roll(300, status="Hold")
		with self.assertRaises(frappe.ValidationError):
			self.lay([(hold, 10)])

	def test_roll_must_be_issued_to_cutting(self):
		in_store = self.make_roll(300, warehouse=self.store)
		with self.assertRaises(frappe.ValidationError):
			self.lay([(in_store, 10)])

	def test_a_roll_cannot_be_laid_twice_beyond_its_length(self):
		b = self.make_roll(300)
		self.lay([(b, 30)], submit=True)  # 252 m used, 48 m returned
		with self.assertRaises(frappe.ValidationError):
			self.lay([(b, 30)], lay_no=2)

	def test_wrong_fabric_roll(self):
		other = ensure_fabric_item("_ATQ-OTHER2", "Navy", "other", 145, 132)
		b = self.make_roll(300, item=other)
		with self.assertRaises(frappe.ValidationError):
			self.lay([(b, 10)])

	def test_cut_cap_blocks_an_excess_cut(self):
		rolls = self.rolls_for(plies=105)
		self.lay(rolls, submit=True)
		extra = self.make_roll(35 * 8.4 + 6)
		l2 = self.lay([(extra, 35)], lay_no=2, gate_override=0, gate_override_reason=None)
		with self.assertRaises(frappe.ValidationError):  # gate blockers or cap: either way it must not be cut
			l2.submit()

	def test_gate_blocks_without_override(self):
		rolls = self.rolls_for()
		lay = self.lay(rolls, gate_override=0, gate_override_reason=None)
		with self.assertRaises(frappe.ValidationError) as cm:
			lay.submit()
		self.assertIn("Cutting is blocked", str(cm.exception))

	def test_override_needs_manager_and_reason(self):
		rolls = self.rolls_for()
		with self.assertRaises(frappe.ValidationError):
			self.lay(rolls, gate_override_reason="")
		lay = self.lay(rolls, gate_override=0, gate_override_reason=None)
		lay.gate_override, lay.gate_override_reason = 1, "Buyer verbal approval"
		floor = make_floor_user()
		frappe.set_user(floor)
		try:
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
				lay.save()
		finally:
			frappe.set_user("Administrator")

	def test_released_plan_is_needed_for_bulk(self):
		p = self.plan()
		rolls = self.rolls_for()
		with self.assertRaises(frappe.ValidationError):
			self.lay(rolls, cut_plan=p.name)  # still Draft
		p.release()
		lay = self.lay(rolls, cut_plan=p.name)
		self.assertEqual(lay.marker_ref, "M1")

	def test_sizes_must_follow_the_plan_ratios(self):
		p = self.plan()
		p.release()
		with self.assertRaises(frappe.ValidationError):
			self.lay(self.rolls_for(), cut_plan=p.name, sizes=(("S", 3), ("M", 3), ("L", 2)))
		lay = self.lay(self.rolls_for(), cut_plan=p.name, sizes=())  # sizes come from the plan
		self.assertEqual({s.size: s.ratio for s in lay.sizes}, {"S": 2, "M": 3, "L": 2})

	def test_size_not_on_the_card(self):
		with self.assertRaises(frappe.ValidationError):
			self.lay(self.rolls_for(plies=35), sizes=(("XXL", 1),))

	def test_pilot_lay_is_tracked_apart(self):
		b = self.make_roll(35 * 8.4 + 6)
		lay = self.lay([(b, 3)], sizes=(("S", 1), ("M", 1)), purpose="Pilot", submit=True)
		tot = ledger.totals(self.card.name, purpose="Pilot")
		self.assertEqual(tot[("Navy", "S")]["CUT"], 3)
		self.assertEqual(ledger.totals(self.card.name, purpose="Bulk"), {})
		self.assertEqual(frappe.get_all("PP Meeting", {"sales_order": self.so.name}), [])
		self.assertFalse(frappe.db.exists("Production Movement", {"production_card": self.card.name, "purpose": "Bulk"}))

	def test_panel_rejects_post_cut_reject(self):
		rolls = self.rolls_for(plies=35)
		lay = self.lay(rolls, sizes=(("S", 2),), panel_rejects=[{"size": "S", "qty": 4, "defect_code": "Cutting Damage", "fault_source": "Cutting"}], submit=True)
		self.assertEqual(lay.sizes[0].panels_rejected, 4)
		self.assertEqual(ledger.stage_total(self.card.name, "CUT_REJECT", "Navy", "S"), 4)
		with self.assertRaises(frappe.ValidationError):
			self.lay(rolls, sizes=(("S", 2),), lay_no=2, panel_rejects=[{"size": "M", "qty": 1, "defect_code": "Cutting Damage"}])

	def test_cancel_voids_bundles_and_reverses_everything(self):
		rolls = self.rolls_for()
		lay = self.lay(rolls, submit=True)
		remnant = lay.remnant_entry
		lay.cancel()
		self.assertEqual(ledger.totals(self.card.name), {})
		self.assertEqual(frappe.db.count("Cut Bundle", {"lay_report": lay.name, "status": "Voided"}), 42)
		self.assertEqual(frappe.db.get_value("Stock Entry", remnant, "docstatus"), 2)

	def test_cancel_blocked_once_a_bundle_left_cutting(self):
		lay = self.lay(self.rolls_for(), submit=True)
		n = frappe.get_all("Cut Bundle", {"lay_report": lay.name}, pluck="name")[0]
		frappe.db.set_value("Cut Bundle", n, "status", "Issued")
		with self.assertRaises(frappe.ValidationError):
			lay.cancel()

	def test_ply_numbers_never_repeat_across_lays(self):
		p = self.plan(plies=70)
		first = self.lay(self.rolls_for(plies=70), sizes=(("S", 2),), submit=True)
		b2 = self.make_roll(35 * 8.4 + 6)
		second = self.lay([(b2, 35)], sizes=(("M", 3),), lay_no=2, submit=True)
		s = frappe.db.sql("select max(ply_to) from `tabCut Bundle` where lay_report = %s", first.name)[0][0]
		m = frappe.db.sql("select min(ply_from) from `tabCut Bundle` where lay_report = %s", second.name)[0][0]
		self.assertEqual((s, m), (70, 71))

	def test_lining_lay_mirrors_the_shell_ply_numbers(self):
		self.card.cancel()
		self.clean()
		self.card = self.issue_card(fabrics=[
			{"colour": "Navy", "fabric_item": self.navy_fabric, "material_role": "Shell", "consumption": 1.2, "consumption_uom": "Meter", "consumption_source": "Manual"},
			{"colour": "Navy", "fabric_item": self.black_fabric, "material_role": "Lining", "consumption": 0.5, "consumption_uom": "Meter", "consumption_source": "Manual"}])
		shell = self.lay(self.rolls_for(plies=35), sizes=(("S", 1),), submit=True)
		lining_roll = self.make_roll(35 * 3 + 6, item=self.black_fabric)
		with self.assertRaises(frappe.ValidationError):  # unpaired
			self.lay([(lining_roll, 35)], sizes=(("S", 1),), marker_length_m=3, fabric_item=self.black_fabric, component="Lining", lay_no=2)
		with self.assertRaises(frappe.ValidationError):  # plies differ
			self.lay([(lining_roll, 30)], sizes=(("S", 1),), marker_length_m=3, fabric_item=self.black_fabric, component="Lining", lay_no=2, paired_with=shell.name)
		lining = self.lay([(lining_roll, 35)], sizes=(("S", 1),), marker_length_m=3, fabric_item=self.black_fabric, component="Lining", lay_no=2, paired_with=shell.name, submit=True)
		s_b = frappe.get_all("Cut Bundle", {"lay_report": shell.name}, ["kit_key", "ply_from", "ply_to"], order_by="bundle_no")
		l_b = frappe.get_all("Cut Bundle", {"lay_report": lining.name}, ["kit_key", "ply_from", "ply_to", "component"], order_by="bundle_no")
		self.assertEqual([(b.kit_key, b.ply_from, b.ply_to) for b in s_b], [(b.kit_key, b.ply_from, b.ply_to) for b in l_b])
		self.assertTrue(all(b.component == "Lining" for b in l_b))
		self.assertEqual(ledger.stage_total(self.card.name, "CUT"), 35)  # the lining lay adds no garments
		self.assertEqual(cutting.kit_missing([frappe.get_all("Cut Bundle", {"lay_report": shell.name}, pluck="name")[0]]), [])


class TestRecut(CuttingBase):
	def reject(self, n=4):
		rolls = self.rolls_for(plies=35)
		self.lay(rolls, sizes=(("S", 2),), panel_rejects=[{"size": "S", "qty": n, "defect_code": "Cutting Damage"}], submit=True)

	def request(self, qty=3, **kw):
		d = frappe.get_doc({"doctype": "Recut Request", "production_card": self.card.name, "colour": "Navy", "size": "S", "qty": qty, "reason": "Cutting Damage", **kw})
		d.insert()
		return d

	def test_request_is_limited_by_rejects(self):
		self.reject(4)
		with self.assertRaises(frappe.ValidationError):
			self.request(5)
		self.request(3).submit()
		with self.assertRaises(frappe.ValidationError):  # only 1 left to replace
			self.request(2)

	def test_recut_lay_closes_the_loop(self):
		self.reject(4)
		req = self.request(3)
		req.submit()
		roll = self.make_roll(40)
		with self.assertRaises(frappe.ValidationError):  # wrong size cut
			self.lay([(roll, 3)], sizes=(("M", 1),), purpose="Re-cut", recut_request=req.name)
		lay = self.lay([(roll, 3)], sizes=(("S", 1),), purpose="Re-cut", recut_request=req.name, marker_length_m=1.2, submit=True)
		self.assertEqual(frappe.db.get_value("Recut Request", req.name, "status"), "Cut")
		self.assertEqual(ledger.stage_total(self.card.name, "CUT", "Navy", "S", "Re-cut"), 3)
		lay.cancel()
		self.assertEqual(frappe.db.get_value("Recut Request", req.name, "status"), "Open")

	def test_different_shade_needs_manager_approval(self):
		self.reject(4)
		orig = frappe.get_all("Lay Report", {"production_card": self.card.name}, pluck="name")[0]
		other = self.make_roll(40, shade="B")
		with self.assertRaises(frappe.ValidationError):
			self.request(2, replaces_lay=orig, source_roll=other)
		self.request(2, replaces_lay=orig, source_roll=other, different_roll_approved=1)


class TestCuttingReports(CuttingBase):
	def cut_from_store(self):
		rolls = []
		for _ in range(3):
			b = self.make_roll(35 * 8.4 + 6, warehouse=self.store)
			issue_fabric_entry(self.card.name, [{"batch_no": b, "qty": 35 * 8.4 + 6}])
			rolls.append((b, 35))
		return self.lay(rolls, marker_efficiency_pct=80, submit=True)

	def test_fabric_consumption_report(self):
		from arinox_apparel.arinox_apparel.report.fabric_consumption.fabric_consumption import execute

		lay = self.cut_from_store()
		cols, data = execute({"production_card": self.card.name})
		row = data[0]
		self.assertEqual((row["issued_m"], row["returned_m"]), (900.0, 18.0))
		self.assertAlmostEqual(row["laid_m"], 882.0, 2)
		self.assertEqual(row["good_cut"], 735)
		self.assertAlmostEqual(row["lay_consumption"], 1.2, 4)
		self.assertAlmostEqual(row["actual_consumption"], (900 - 18) / 735, 4)  # 1.2: nothing lost beyond the remnants
		self.assertAlmostEqual(row["variance_pct"], 0, 3)
		self.assertAlmostEqual(row["marker_efficiency"], 80, 3)
		self.assertAlmostEqual(row["required_m"], 735 * 1.2, 2)

	def test_daily_cutting_report(self):
		from arinox_apparel.arinox_apparel.report.daily_cutting_report.daily_cutting_report import execute

		self.cut_from_store()
		cols, data = execute({"production_card": self.card.name})
		s = next(r for r in data if r["colour"] == "Navy" and r["size"] == "S")
		self.assertEqual((s["planned"], s["cut"], s["balance"]), (210, 210, 0))
		self.assertEqual(s["d6"], 210)  # today is the last day column
		black = next(r for r in data if r["colour"] == "Black" and r["size"] == "S")
		self.assertEqual((black["cut"], black["balance"]), (0, 158))
		with self.assertRaises(frappe.ValidationError):
			execute({"production_card": self.card.name, "from_date": "2026-01-01", "to_date": "2026-06-01"})

	def test_card_status_follows_the_ledger(self):
		lay = self.cut_from_store()
		self.assertEqual(frappe.db.get_value("Production Card", self.card.name, "status"), "In Cutting")
		lay.cancel()
		self.assertEqual(frappe.db.get_value("Production Card", self.card.name, "status"), "Issued")

	def test_summary_reads_the_ledger(self):
		from arinox_apparel.production.summary import fabric_usage, good_cut, stage_qty

		self.cut_from_store()
		self.assertEqual(good_cut(self.so.name, self.style, "Navy"), 735)
		self.assertEqual(stage_qty(self.so.name, self.style, "Navy", ["CUT"], purpose="Pilot"), 0)
		cut, net, per = fabric_usage(self.so.name, self.style, "Navy", self.navy_fabric)
		self.assertEqual((cut, net), (735, 882))
		self.assertAlmostEqual(per, 1.2, 4)

	def test_print_formats_render(self):
		lay = self.cut_from_store()
		html = frappe.get_print("Lay Report", lay.name, print_format="Lay Report Form")
		self.assertIn("LAY REPORT", html)
		self.assertIn("735", html)
		bundle = frappe.get_all("Cut Bundle", {"lay_report": lay.name}, pluck="name")[0]
		self.assertIn(bundle, frappe.get_print("Cut Bundle", bundle, print_format="Bundle Ticket"))
