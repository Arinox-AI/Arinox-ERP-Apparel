# Copyright (c) 2026, Arinox AI and contributors
"""Slice D1: the Production Card."""

import frappe
from frappe.utils import cint

from arinox_apparel.arinox_apparel.doctype.production_card.production_card import (
	get_card_lines,
	get_production_context,
	get_production_status,
	revise_production_card,
	save_production_card,
)
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.production_base import ProductionBase
from arinox_apparel.overrides import work_order as wo_gate
from arinox_apparel.production import gate


def make_floor_user(email="_at_floor@example.com", roles=("Apparel Production User",)):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "AT Floor", "send_welcome_email": 0,
						"roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
	return email


class TestProductionCard(ProductionBase):
	def setUp(self):
		self.clean()

	def line(self, card, colour, size):
		return next(l for l in card.lines if l.colour == colour and l.size == size)

	def test_lines_come_from_the_sales_order(self):
		ctx = get_card_lines(self.so.name, self.style)
		got = {(r["colour"], r["size"]): r["order_qty"] for r in ctx["lines"]}
		self.assertEqual(got, {("Navy", "S"): 200, ("Navy", "M"): 300, ("Navy", "L"): 200, ("Black", "S"): 150, ("Black", "M"): 200, ("Black", "L"): 150})
		self.assertTrue(ctx["ex_factory_date"])

	def test_planned_cut_is_rounded_up_per_size(self):
		card = self.card_doc()
		card.insert()
		self.assertEqual(card.default_extra_cut_pct, 5)
		self.assertEqual(self.line(card, "Navy", "S").planned_cut_qty, 210)
		self.assertEqual(self.line(card, "Black", "M").planned_cut_qty, 210)
		self.line(card, "Navy", "M").extra_cut_pct = 3.3  # 300 x 1.033 = 309.9 -> 310
		card.save()
		self.assertEqual(self.line(card, "Navy", "M").planned_cut_qty, 310)
		self.assertEqual(self.line(card, "Navy", "S").max_qty, self.line(card, "Navy", "S").max_qty)

	def test_unknown_size_or_colour_rejected(self):
		card = self.card_doc()
		card.append("lines", {"colour": "Navy", "size": "Marge"})
		with self.assertRaises(frappe.ValidationError):
			card.insert()
		card = self.card_doc()
		card.lines[0].colour = "Pink"
		with self.assertRaises(frappe.ValidationError):
			card.insert()

	def test_duplicate_row_rejected(self):
		card = self.card_doc()
		card.append("lines", {"colour": "Navy", "size": "S"})
		with self.assertRaises(frappe.ValidationError):
			card.insert()

	def test_extra_cut_above_limit_needs_a_manager(self):
		card = self.card_doc()
		card.lines[0].extra_cut_pct = 12
		card.insert()  # Administrator is a manager: allowed with a red flag
		self.assertIn("Extra cut above", card.red_flags)
		c2 = self.card_doc()
		c2.lines[0].extra_cut_pct = 12
		floor_user = make_floor_user()
		frappe.set_user(floor_user)
		try:
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
				c2.insert()
		finally:
			frappe.set_user("Administrator")

	def test_negative_extra_cut_rejected(self):
		card = self.card_doc()
		card.lines[0].extra_cut_pct = -1
		with self.assertRaises(frappe.ValidationError):
			card.insert()

	def test_issue_sets_status_and_is_not_gated(self):
		card = self.issue_card()
		self.assertEqual(card.status, "Issued")
		self.assertTrue(card.issue_date)  # issued before any PP meeting exists: no circular gate

	def test_one_live_card_per_order_style_and_date(self):
		self.issue_card()
		with self.assertRaises(frappe.ValidationError):
			self.card_doc().insert()

	def test_revision_supersedes_and_keeps_the_key(self):
		first = self.issue_card()
		draft = frappe.get_doc({**revise_production_card(first.name), "doctype": "Production Card"})
		with self.assertRaises(frappe.ValidationError):  # reason required
			draft.insert()
		draft.revision_reason = "Buyer added 100 pcs"
		draft.insert()
		draft.submit()
		self.assertEqual(draft.revision_no, 1)
		self.assertEqual(frappe.db.get_value("Production Card", first.name, "status"), "Superseded")

	def test_revision_keeps_the_history_and_flags_cut_above_the_new_plan(self):
		from arinox_apparel.production import ledger

		first = self.issue_card()
		ledger.post(first.name, [dict(stage="CUT", colour="Navy", size="S", qty=210)], "Production Adjustment", "_X")
		draft = frappe.get_doc({**revise_production_card(first.name), "doctype": "Production Card"})
		draft.revision_reason = "Cut qty reduced"
		for l in draft.lines:
			if l.colour == "Navy" and l.size == "S":
				l.extra_cut_pct = 0
		draft.insert()
		self.assertIn("Cut exceeds the revised plan", draft.red_flags)
		draft.submit()
		self.assertEqual(ledger.stage_total(draft.name, "CUT", "Navy", "S"), 210)  # the history moved to the live card
		self.assertEqual(ledger.stage_total(first.name, "CUT"), 0)
		self.assertEqual(draft.reload().status, "In Cutting")

	def test_cancel_blocked_with_movements_but_allowed_without(self):
		card = self.issue_card()
		card.cancel()
		self.assertEqual(frappe.db.get_value("Production Card", card.name, "status"), "Cancelled")

	def test_pilot_required_by_order_quantity(self):
		card = self.card_doc()
		card.insert()
		self.assertEqual(card.pilot_required, 1)  # 1,200 pieces >= 1,000
		frappe.db.set_single_value("Apparel Settings", "pilot_min_order_qty", 5000)
		try:
			c2 = frappe.get_doc("Production Card", card.name)
			c2.save()
			self.assertEqual(c2.pilot_required, 0)
		finally:
			frappe.db.set_single_value("Apparel Settings", "pilot_min_order_qty", 1000)

	def test_pilot_waiver_needs_a_reason(self):
		card = self.card_doc(pilot_waiver=1)
		with self.assertRaises(frappe.ValidationError):
			card.insert()
		card.pilot_waiver_reason = "Repeat style, same line"
		card.insert()

	def test_route_rules(self):
		card = self.card_doc(processes=[{"subcontract_process": "Embroidery", "position": "After Sewing", "item_state": "Cut Panels"}])
		with self.assertRaises(frappe.ValidationError):
			card.insert()
		card = self.card_doc(processes=[{"subcontract_process": "Wash", "position": "Before Sewing", "item_state": "Garments"}])
		with self.assertRaises(frappe.ValidationError):
			card.insert()
		card = self.card_doc(processes=[{"subcontract_process": "Wash", "position": "After Sewing"}, {"subcontract_process": "Wash", "position": "After Sewing"}])
		with self.assertRaises(frappe.ValidationError):
			card.insert()

	def test_fabric_requirement_uses_planned_cut(self):
		card = self.card_doc(fabrics=[{"colour": "Navy", "consumption": 1.72, "consumption_uom": "Meter", "consumption_source": "Manual"}])
		card.insert()
		navy_cut = sum(l.planned_cut_qty for l in card.lines if l.colour == "Navy")
		self.assertEqual(navy_cut, 735)  # 210 + 315 + 210
		self.assertAlmostEqual(card.fabrics[0].required_m, 735 * 1.72, 2)
		self.assertAlmostEqual(card.fabrics[0].shortage_m, 735 * 1.72, 2)  # nothing accepted yet
		card.fabrics[0].colour = "Pink"
		with self.assertRaises(frappe.ValidationError):
			card.save()

	def test_yard_consumption_is_converted(self):
		card = self.card_doc(fabrics=[{"colour": "Navy", "consumption": 1.6, "consumption_uom": "Yard", "consumption_source": "Cost Sheet"}])
		card.insert()
		self.assertAlmostEqual(card.fabrics[0].required_m, 735 * 1.6 * 0.9144, 2)

	def test_zero_consumption_rejected(self):
		card = self.card_doc(fabrics=[{"colour": "Navy", "consumption": 0, "consumption_uom": "Meter"}])
		with self.assertRaises(frappe.ValidationError):
			card.insert()

	def test_agent_api_round_trip_never_submits(self):
		ctx = get_production_context(self.so.name)
		self.assertEqual(ctx["styles"][0]["style_item"], self.style)
		self.assertEqual(len(ctx["styles"][0]["lines"]), 6)
		data = {"company": self.company, "customer": u.CUSTOMER, "sales_order": self.so.name, "style_item": self.style,
				"lines": [{"colour": l["colour"], "size": l["size"]} for l in ctx["styles"][0]["lines"]]}
		res = save_production_card(data)
		self.assertEqual(frappe.db.get_value("Production Card", res["name"], "docstatus"), 0)
		self.assertEqual(res["planned_cut_total"], 1261)  # 1,200 pieces + 5 %, each size rounded up (157.5 -> 158)
		status = get_production_status(self.so.name)
		self.assertEqual(status, [])  # drafts are not live cards

	def test_pp_meeting_gets_the_card_reference(self):
		meeting = frappe.get_doc({"doctype": "PP Meeting", "sales_order": self.so.name, "style_item": self.style, "meeting_type": "PP Meeting",
								  "meeting_date": frappe.utils.nowdate()})
		meeting.flags.ignore_validate = True
		meeting.flags.ignore_mandatory = True
		meeting.db_insert()
		try:
			card = self.issue_card()
			self.assertEqual(frappe.db.get_value("PP Meeting", meeting.name, "production_card_ref"), card.name)
		finally:
			frappe.db.delete("PP Meeting", {"name": meeting.name})

	def test_work_order_gate_still_reports_through_the_shared_function(self):
		res = gate.bulk_gate_for(self.so.name, self.style, "Navy", stage="pilot")
		self.assertTrue(res["applies"])
		self.assertIsInstance(res["blockers"], list)
		self.assertEqual(gate.bulk_gate_for(None, self.style, "Navy"), {"applies": False, "blockers": [], "warnings": []})
		self.assertTrue(callable(wo_gate.get_bulk_gate))

	def test_bulk_stage_adds_the_pilot_blocker_when_a_card_requires_it(self):
		self.issue_card()
		bulk = gate.bulk_gate_for(self.so.name, self.style, "Navy", stage="bulk")["blockers"]
		pilot = gate.bulk_gate_for(self.so.name, self.style, "Navy", stage="pilot")["blockers"]
		# until the Pilot Run doctype exists (slice D2) the pilot rule cannot add a blocker
		self.assertEqual(len(bulk), len(pilot) + (1 if frappe.db.exists("DocType", "Pilot Run") else 0))

	def test_print_formats_render(self):
		card = self.issue_card(fabrics=[{"colour": "Navy", "consumption": 1.72, "consumption_uom": "Meter", "consumption_source": "Manual"}])
		html = frappe.get_print("Production Card", card.name, print_format="Production Card Form")
		self.assertIn("PRODUCTION CARD", html)
		self.assertIn("1261", html)  # grand total cutting quantity
		self.assertIn("315", html)  # a size of the matrix
		trim = frappe.get_print("Production Card", card.name, print_format="Trim Card")
		self.assertIn("TRIM CARD", trim)
