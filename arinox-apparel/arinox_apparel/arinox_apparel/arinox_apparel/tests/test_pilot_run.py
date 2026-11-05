# Copyright (c) 2026, Arinox AI and contributors
"""Slice D2: Pilot Run and the pilot part of the bulk gate."""

import frappe
from frappe.utils import nowdate

from arinox_apparel.arinox_apparel.tests.production_base import ProductionBase
from arinox_apparel.arinox_apparel.tests.test_production_card import make_floor_user
from arinox_apparel.production import gate, ledger


class TestPilotRun(ProductionBase):
	def setUp(self):
		self.clean()
		frappe.db.delete("Pilot Run", {"sales_order": self.so.name})
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)
		self.card = self.issue_card()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)

	def pilot_pieces(self, cut=30, sewn=30, washed=0):
		rows = [dict(stage="CUT", colour="Navy", size="S", qty=cut, purpose="Pilot"), dict(stage="SEW_IN", colour="Navy", size="S", qty=cut, purpose="Pilot"),
				dict(stage="SEW_OUT", colour="Navy", size="S", qty=sewn, purpose="Pilot")]
		ledger.post(self.card.name, rows, "Production Adjustment", "_PILOT-1", check=False)
		if washed:
			ledger.post(self.card.name, [dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=washed, purpose="Pilot", process="Wash")],
						"Production Adjustment", "_PILOT-2", check=False)

	def run_doc(self, **kw):
		data = {"doctype": "Pilot Run", "production_card": self.card.name, "run_date": nowdate(), "colours": [{"colour": "Navy", "sizes_run": "S"}],
				"checks": [{"check_item": "Construction", "result": "Yes"}, {"check_item": "Packing", "result": "Yes"}], "decision": "Approved"}
		data.update(kw)
		return frappe.get_doc(data)

	def pilot_blockers(self, colour="Navy", stage="bulk"):
		return [b for b in gate.bulk_gate_for(self.so.name, self.style, colour, stage=stage)["blockers"] if b.startswith("Pilot Run")]

	def test_pieces_come_from_the_ledger(self):
		self.pilot_pieces(cut=30, sewn=28, washed=27)
		ledger.post(self.card.name, [dict(stage="CUT_REJECT", colour="Navy", size="S", qty=2, purpose="Pilot")], "Production Adjustment", "_PILOT-3", check=False)
		d = self.run_doc()
		d.insert()
		r = d.colours[0]
		self.assertEqual((r.cut_qty, r.sewn_qty, r.washed_qty, r.rejected_qty), (28, 28, 27, 2))

	def test_needs_pp_meeting_when_required(self):
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)
		with self.assertRaises(frappe.ValidationError):
			self.run_doc().insert()
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)

	def test_colour_must_be_on_the_card(self):
		with self.assertRaises(frappe.ValidationError):
			self.run_doc(colours=[{"colour": "Pink"}]).insert()

	def test_approve_needs_sewn_pieces(self):
		d = self.run_doc()
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()

	def test_approve_needs_every_check_answered_and_actions_on_failures(self):
		self.pilot_pieces()
		d = self.run_doc(checks=[{"check_item": "Construction"}])
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		d = self.run_doc(checks=[{"check_item": "Construction", "result": "No"}])
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		d.reload()
		d.checks[0].action_taken = "Pattern corrected"
		d.save()
		d.submit()
		self.assertEqual(d.status, "Approved")

	def test_no_checks_no_approval(self):
		self.pilot_pieces()
		d = self.run_doc(checks=[])
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()

	def test_washed_style_needs_washed_pieces(self):
		frappe.db.set_value("Production Card", self.card.name, "is_washed", 1)
		self.pilot_pieces(washed=0)
		d = self.run_doc()
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		ledger.post(self.card.name, [dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=25, purpose="Pilot", process="Wash")],
					"Production Adjustment", "_PILOT-4", check=False)
		d = self.run_doc()
		d.insert()
		d.submit()
		self.assertEqual(d.status, "Approved")

	def test_out_of_tolerance_needs_a_reason(self):
		self.pilot_pieces()
		meas = [{"point_of_measure": "Chest", "size": "M", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 52}]
		d = self.run_doc(measurements=meas)
		d.insert()
		self.assertEqual(d.measurements[0].in_tolerance, 0)
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		d.reload()
		d.measurement_note = "Buyer accepted +2 on chest"
		d.save()
		d.submit()

	def test_reject_needs_notes(self):
		d = self.run_doc(decision="Rejected")
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		d.reload()
		d.result_notes = "Collar wavy"
		d.save()
		d.submit()
		self.assertEqual(d.status, "Rejected")

	def test_decision_required_and_role_checked(self):
		self.pilot_pieces()
		d = self.run_doc(decision=None)
		d.insert()
		with self.assertRaises(frappe.ValidationError):
			d.submit()
		d.reload()
		d.decision = "Approved"
		d.save()
		frappe.set_user(make_floor_user())
		try:
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
				d.submit()
		finally:
			frappe.set_user("Administrator")

	def test_gate_blocks_bulk_until_an_approved_pilot_covers_the_colour(self):
		self.assertEqual(len(self.pilot_blockers()), 1)  # none recorded
		self.pilot_pieces()
		rej = self.run_doc(decision="Rejected", result_notes="Bad")
		rej.insert()
		rej.submit()
		self.assertEqual(len(self.pilot_blockers()), 1)  # rejected does not open the gate
		ok = self.run_doc()
		ok.insert()
		ok.submit()
		self.assertEqual(self.pilot_blockers("Navy"), [])
		self.assertEqual(len(self.pilot_blockers("Black")), 1)  # Navy's approval does not cover Black
		self.assertEqual(self.pilot_blockers("Black", stage="pilot"), [])  # the pilot-stage gate never asks for a pilot

	def test_waiver_opens_the_gate(self):
		frappe.db.set_value("Production Card", self.card.name, {"pilot_waiver": 1, "pilot_waiver_reason": "Repeat style"})
		self.assertEqual(self.pilot_blockers(), [])

	def test_small_order_needs_no_pilot(self):
		frappe.db.set_value("Production Card", self.card.name, "pilot_required", 0)
		self.assertEqual(self.pilot_blockers(), [])

	def test_cancel_reopens_the_gate(self):
		self.pilot_pieces()
		d = self.run_doc()
		d.insert()
		d.submit()
		self.assertEqual(self.pilot_blockers(), [])
		d.cancel()
		self.assertEqual(len(self.pilot_blockers()), 1)
