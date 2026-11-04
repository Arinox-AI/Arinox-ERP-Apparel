# Copyright (c) 2026, Arinox AI and contributors
"""Phase B: factory allocation, sample approvals, PP meeting and the bulk gate (G3)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import (
	get_planning_context,
	save_allocation,
)
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import get_sampling_milestones
from arinox_apparel.overrides import work_order as gate

MERCH_USER = "_at_merch@example.com"
MANAGER_USER = "_at_merch_manager@example.com"


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}).insert(ignore_permissions=True)


class TestPlanApprove(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		u.setup_masters()
		cls.floors = u.make_floors()
		cls.fa, cls.fb = list(cls.floors)
		cls.so, cls.style, cls.sc = u.make_order("_AT-B1")
		make_user(MERCH_USER, ["Apparel Merchandiser"])
		make_user(MANAGER_USER, ["Apparel Merchandiser", "Apparel Merchandising Manager"])
		frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 1)
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)
		cls.navy_item = next(i.item_code for i in cls.so.items if i.apparel_colour == "Navy")
		cls.so2, cls.style2, _sc = u.make_order("_AT-B2", ship_split=True)  # Navy ships to two destinations
		cls.navy_item2 = next(i.item_code for i in cls.so2.items if i.apparel_colour == "Navy")

	def setUp(self):
		for dt in ("Sample Approval", "PP Meeting", "Factory Allocation", "Factory Allocation Line", "PP Meeting Action",
				   "Sample Approval Comment", "Sample Requirement"):
			frappe.db.delete(dt)  # raw delete: children are removed explicitly
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---- helpers
	def requirement(self, stype, **kw):
		return frappe.get_doc({"doctype": "Sample Requirement", "sample_type": stype, "customer": u.CUSTOMER, **kw}).insert()

	def blockers(self, item=None, so=None):
		return " | ".join(gate.get_bulk_gate(item or self.navy_item, so or self.so.name)["blockers"])

	def sample(self, stype, colour=None, decision="Approved", **kw):
		doc = {"doctype": "Sample Approval", "sample_type": stype, "style_item": self.style, "sales_order": self.so.name,
			   "colour": colour, "material_description": "Jersey 180gsm" if stype.startswith("Bulk") else None}
		rounds = []
		if decision:
			rounds.append({"sent_on": add_days(nowdate(), -3), "decision": decision,
						   "decision_on": nowdate() if decision != "Pending" else None})
		doc.update(rounds=rounds)
		doc.update(kw)
		return frappe.get_doc(doc)

	def lines(self, navy=700, black=500, **extra):
		pcd = add_days(nowdate(), 40)
		return [
			{"style_item": self.style, "colour": "Navy", "qty": navy, "factory": self.fa, "line": self.floors[self.fa][0],
			 "pcd": pcd, **extra},
			{"style_item": self.style, "colour": "Black", "qty": black, "factory": self.fb, "line": self.floors[self.fb][0], "pcd": pcd},
		]

	def approve_everything(self, colour="Navy"):
		"""All required approvals and a closed PP meeting for the Navy variant."""
		for stype in ("Fit", "Bulk Trim"):
			self.sample(stype).insert()
		for stype in ("Lab Dip", "Bulk Fabric"):
			self.sample(stype, colour=colour).insert()
		pp = self.sample("PP", in_bulk_fabric=1).insert()
		return pp, self.meeting(pp)

	def meeting(self, pp, **kw):
		doc = {
			"doctype": "PP Meeting", "sales_order": self.so.name, "style_item": self.style, "meeting_date": nowdate(),
			"production_card_issued_on": add_days(nowdate(), -2), "pp_sample": pp.name if pp else None,
			"participants": [{"department": d, "participant_name": d, "attended": 1} for d in
							 ("Planning", "Purchasing", "Cutting", "Sewing", "QC")],
		}
		doc.update(kw)
		return frappe.get_doc(doc)

	# ---- factory allocation
	def test_allocation_round_trip_and_status(self):
		name = save_allocation(self.so.name, self.lines(), agent_notes="Navy to A, Black to B")
		fa = frappe.get_doc("Factory Allocation", name)
		self.assertEqual(name, f"FA-{self.so.name}")
		self.assertEqual(fa.status, "Planned")
		self.assertEqual((fa.order_qty, fa.allocated_qty), (1200, 1200))
		self.assertEqual(fa.planned_by, "AI Agent")
		self.assertTrue(all(r.ex_factory_date for r in fa.lines))
		# replacing with a partial plan flips the status, same record
		self.assertEqual(save_allocation(self.so.name, self.lines(navy=300, black=100)), name)
		self.assertEqual(frappe.get_doc("Factory Allocation", name).status, "Partly Planned")

	def test_allocation_over_order_plus_tolerance_is_rejected(self):
		# Navy 700 pcs has a 10% band: 770 is the cap
		save_allocation(self.so.name, self.lines(navy=770))
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so.name, self.lines(navy=771))

	def test_line_must_belong_to_the_factory(self):
		bad = self.lines()
		bad[0]["line"] = self.floors[self.fb][0]
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so.name, bad)

	def test_allocation_dates_must_be_in_order(self):
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so.name, self.lines(sewing_start=add_days(nowdate(), 30)))  # before the PCD
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so.name, self.lines(sewing_start=add_days(nowdate(), 60), sewing_end=add_days(nowdate(), 50)))

	def test_allocation_needs_a_submitted_order_and_a_known_style(self):
		bad = self.lines()
		bad[0]["colour"] = "Purple"
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so.name, bad)

	def test_planning_context_has_what_the_agent_needs(self):
		save_allocation(self.so.name, self.lines())
		ctx = get_planning_context(self.so.name)
		self.assertEqual({o["colour"] for o in ctx["order_lines"]}, {"Navy", "Black"})
		self.assertIn(self.fa, [f["name"] for f in ctx["factories"]])
		self.assertTrue(ctx["current_allocation"])
		self.assertTrue(next(f for f in ctx["factories"] if f["name"] == self.fa)["lines"])

	# ---- sample approval
	def test_status_follows_the_last_round(self):
		s = self.sample("Fit", decision=None).insert()
		self.assertEqual(s.status, "Open")
		s.append("rounds", {"sent_on": add_days(nowdate(), -5), "decision": "Pending"})
		s.save()
		self.assertEqual(s.status, "Submitted")
		s.rounds[0].decision, s.rounds[0].decision_on = "Rejected", nowdate()
		s.append("comments", {"round_no": 1, "category": "Fit", "comment": "Chest too tight"})
		s.save()
		self.assertEqual(s.status, "Rejected")
		s.append("rounds", {"sent_on": nowdate(), "decision": "Approved", "decision_on": nowdate()})
		s.save()
		self.assertEqual((s.status, str(s.approved_on), [r.round_no for r in s.rounds]), ("Approved", nowdate(), [1, 2]))

	def test_decision_with_comments_needs_a_comment(self):
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", decision="Approved with Comments").insert()
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", decision="Rejected").insert()
		s = self.sample("Fit", decision="Approved with Comments", comments=[{"round_no": 1, "comment": "Shorten sleeve 1cm"}]).insert()
		self.assertEqual(s.status, "Approved with Comments")

	def test_decision_needs_a_date_that_is_not_in_the_future(self):
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", rounds=[{"sent_on": nowdate(), "decision": "Approved"}]).insert()
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", rounds=[{"decision": "Approved", "decision_on": add_days(nowdate(), 3)}]).insert()

	def test_washed_bulk_approval_follows_the_process(self):
		s = self.sample("Bulk Fabric", colour="Navy", is_washed=1)
		with self.assertRaises(frappe.ValidationError):
			s.insert()  # approved on an unwashed submission
		s = self.sample("Bulk Fabric", colour="Navy", is_washed=1,
						rounds=[{"sent_on": add_days(nowdate(), -2), "decision": "Approved", "decision_on": nowdate(), "tested_after_wash": 1}])
		s.insert()
		self.assertEqual(s.status, "Approved")

	def test_pp_must_be_in_bulk_fabric(self):
		with self.assertRaises(frappe.ValidationError):
			self.sample("PP").insert()
		self.assertEqual(self.sample("PP", in_bulk_fabric=1).insert().status, "Approved")

	def test_gpt_cannot_pass_with_a_failed_test(self):
		s = self.sample("Garment Test (GPT)", tests=[{"test_property": "Seam Strength", "result": "Pass"},
													  {"test_property": "Dimensional stability", "result": "Fail"}])
		with self.assertRaises(frappe.ValidationError):
			s.insert()
		s = self.sample("Garment Test (GPT)", tests=[{"test_property": "Seam Strength", "result": "Pass"}]).insert()
		self.assertEqual(s.status, "Approved")
		s.load_standard_tests()
		self.assertGreater(len(s.tests), 10)

	def test_per_colour_types_need_a_colour(self):
		with self.assertRaises(frappe.ValidationError):
			self.sample("Lab Dip", colour=None).insert()

	def test_waiver_needs_the_manager_role_and_a_reason(self):
		frappe.set_user(MERCH_USER)
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", decision=None, waived=1, waiver_reason="Carry over style").insert()
		frappe.set_user(MANAGER_USER)
		with self.assertRaises(frappe.ValidationError):
			self.sample("Fit", decision=None, waived=1).insert()  # no reason
		s = self.sample("Fit", decision=None, waived=1, waiver_reason="Carry over style").insert()
		self.assertEqual((s.status, s.waived_by), ("Not Required", MANAGER_USER))

	def test_due_date_comes_from_the_pcd_and_the_rule(self):
		save_allocation(self.so.name, self.lines())
		pcd = frappe.utils.getdate(add_days(nowdate(), 40))
		s = self.sample("PP", in_bulk_fabric=1).insert()
		self.assertEqual(s.due_date, add_days(pcd, -14))
		top = self.sample("TOP", colour="Navy", decision=None).insert()  # TOP is due before ex-factory
		self.assertEqual(top.due_date, add_days(frappe.utils.getdate(add_days(nowdate(), 90)), -10))

	def test_measurements_are_checked_against_tolerance(self):
		s = self.sample("Fit", decision=None, measurements=[
			{"point_of_measure": "Chest", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 50.5},
			{"point_of_measure": "Length", "spec": 70, "tol_plus": 1, "tol_minus": 1, "actual": 72},
		]).insert()
		self.assertEqual([m.in_tolerance for m in s.measurements], [1, 0])
		self.assertEqual(s.measurements[1].deviation, 2)

	# ---- PP meeting
	def test_pp_meeting_needs_an_approved_pp_sample(self):
		pp = self.sample("PP", in_bulk_fabric=1, decision="Rejected", comments=[{"round_no": 1, "comment": "Hem uneven"}]).insert()
		with self.assertRaises(frappe.ValidationError):
			self.meeting(pp).insert().submit()

	def test_pp_meeting_reviews_every_buyer_comment(self):
		pp = self.sample("PP", in_bulk_fabric=1).insert()
		self.sample("Fit", decision="Approved with Comments", comments=[
			{"round_no": 1, "category": "Fit", "comment": "Lengthen body 1cm", "relevant_to_cutting": 1}]).insert()
		m = self.meeting(pp).insert()
		with self.assertRaises(frappe.ValidationError):
			m.submit()  # the Fit comment is not in the action list
		m.reload()
		self.assertEqual(m.get_buyer_comments(), 1)
		with self.assertRaises(frappe.ValidationError):
			m.save()
			m.submit()  # no action taken, no owner, no date
		m.reload()
		a = m.actions[0]
		a.action_taken, a.action_owner, a.target_date = "Pattern corrected", MERCH_USER, add_days(nowdate(), 5)
		m.save()
		m.submit()
		self.assertEqual(m.status, "Open Actions")

	def test_pp_meeting_needs_the_departments(self):
		pp = self.sample("PP", in_bulk_fabric=1).insert()
		m = self.meeting(pp, participants=[{"department": "Planning", "attended": 1}]).insert()
		with self.assertRaises(frappe.ValidationError):
			m.submit()
		pp2 = self.meeting(pp, is_washed=1).insert()  # washing must attend too
		pp2.set("participants", [{"department": d, "attended": 1} for d in ("Planning", "Purchasing", "Cutting", "Sewing", "QC")])
		with self.assertRaises(frappe.ValidationError):
			pp2.submit()

	def test_production_card_must_be_issued_before_the_meeting(self):
		pp = self.sample("PP", in_bulk_fabric=1).insert()
		with self.assertRaises(frappe.ValidationError):
			self.meeting(pp, production_card_issued_on=None).insert().submit()
		with self.assertRaises(frappe.ValidationError):
			self.meeting(pp, production_card_issued_on=add_days(nowdate(), 2)).insert().submit()

	def test_closing_an_action_closes_the_buyer_comment(self):
		pp = self.sample("PP", in_bulk_fabric=1).insert()
		fit = self.sample("Fit", decision="Approved with Comments", comments=[
			{"round_no": 1, "comment": "Lengthen body 1cm", "relevant_to_cutting": 1}]).insert()
		m = self.meeting(pp).insert()
		m.get_buyer_comments()
		a = m.actions[0]
		a.action_taken, a.action_owner, a.target_date = "Pattern corrected", MERCH_USER, add_days(nowdate(), 5)
		m.save()
		m.submit()
		fit.reload()
		self.assertEqual(fit.comments[0].status, "Open")
		m.actions[0].status = "Closed"
		m.save()
		fit.reload()
		self.assertEqual((fit.comments[0].status, fit.comments[0].closed_in), ("Closed", m.name))
		self.assertEqual((m.status, str(m.actions[0].closed_on)), ("Closed", nowdate()))

	# ---- bulk gate
	def test_gate_lists_every_blocker(self):
		res = gate.get_bulk_gate(self.navy_item, self.so.name)
		self.assertTrue(res["applies"])
		self.assertEqual(res["colour"], "Navy")
		text = " | ".join(res["blockers"])
		for stype in ("Fit", "Lab Dip (Navy)", "Bulk Fabric (Navy)", "Bulk Trim", "PP:", "PP Meeting"):
			self.assertIn(stype, text)
		doc = frappe._dict(production_item=self.navy_item, sales_order=self.so.name, apparel_gate_override=0)
		with self.assertRaises(frappe.ValidationError):
			gate.before_submit(doc)

	def test_gate_opens_when_approvals_and_meeting_are_in(self):
		pp, m = self.approve_everything()
		self.assertTrue(any("PP Meeting" in b for b in gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"]))
		m.insert().submit()
		self.assertEqual(gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"], [])
		gate.before_submit(frappe._dict(production_item=self.navy_item, sales_order=self.so.name, apparel_gate_override=0))

	def test_gate_is_per_colour_for_lab_dip_and_bulk_fabric(self):
		pp, m = self.approve_everything(colour="Navy")
		m.insert().submit()
		black_item = next(i.item_code for i in self.so.items if i.apparel_colour == "Black")
		text = " | ".join(gate.get_bulk_gate(black_item, self.so.name)["blockers"])
		self.assertIn("Lab Dip (Black)", text)
		self.assertIn("Bulk Fabric (Black)", text)
		self.assertNotIn("Fit", text)

	def test_a_rejected_sample_blocks_even_when_others_are_approved(self):
		pp, m = self.approve_everything()
		m.insert().submit()
		self.sample("Strike Off", colour="Navy", decision="Rejected", comments=[{"round_no": 1, "comment": "Print off-register"}]).insert()
		self.assertTrue(any("Strike Off" in b for b in gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"]))

	def test_an_open_cutting_action_blocks_bulk(self):
		pp, m = self.approve_everything()
		self.sample("Size Set", decision="Approved with Comments",
					comments=[{"round_no": 1, "comment": "Armhole 0.5cm lower", "relevant_to_cutting": 1}]).insert()
		m.insert()
		m.get_buyer_comments()
		for a in m.actions:
			a.action_taken, a.action_owner, a.target_date = "Pattern corrected", MERCH_USER, add_days(nowdate(), 5)
		m.save()
		m.submit()
		self.assertTrue(any("cutting comment still open" in b for b in gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"]))
		m.actions[0].status = "Closed"
		m.save()
		self.assertEqual(gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"], [])

	def test_manager_override_with_a_reason_passes(self):
		def doc(**kw):
			return frappe._dict(production_item=self.navy_item, sales_order=self.so.name, apparel_gate_override=1,
								apparel_gate_override_reason=kw.get("reason"), is_new=lambda: True)

		frappe.set_user(MERCH_USER)
		with self.assertRaises(frappe.ValidationError):
			gate.validate(doc(reason="Buyer verbal OK"))  # not a manager
		frappe.set_user(MANAGER_USER)
		with self.assertRaises(frappe.ValidationError):
			gate.validate(doc(reason=None))  # no reason
		gate.validate(doc(reason="Buyer verbal OK"))
		gate.before_submit(doc(reason="Buyer verbal OK"))

	def test_gate_can_be_switched_off_and_ignores_other_items(self):
		frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 0)
		try:
			gate.before_submit(frappe._dict(production_item=self.navy_item, sales_order=self.so.name))
		finally:
			frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 1)
		plain = frappe.db.get_value("Item", {"variant_of": ["is", "not set"], "has_variants": 0}, "name")
		if plain:
			self.assertFalse(gate.get_bulk_gate(plain, self.so.name)["applies"])

	# ---- reports
	def test_tracker_report_shows_the_gate_per_colour(self):
		from arinox_apparel.arinox_apparel.report.sample_approval_tracker.sample_approval_tracker import execute

		pp, m = self.approve_everything(colour="Navy")
		m.insert().submit()
		_cols, data = execute({"sales_order": self.so.name})
		rows = {r["colour"]: r for r in data}
		self.assertEqual(rows["Navy"]["gate"], "Open")
		self.assertEqual(rows["Black"]["gate"], "Blocked")
		self.assertEqual(rows["Black"]["t_lab_dip"], "Missing")
		self.assertEqual(rows["Navy"]["t_pp"], "Approved")
		_cols, data = execute({"sales_order": self.so.name, "only_blocked": 1})
		self.assertEqual([r["colour"] for r in data], ["Black"])

	def test_factory_load_report_sums_by_line_and_week(self):
		from arinox_apparel.arinox_apparel.report.factory_load.factory_load import execute

		save_allocation(self.so.name, self.lines())
		_cols, data = execute({"factory": self.fa})
		self.assertEqual(sum(r["qty"] for r in data), 700)
		self.assertEqual(data[0]["line"], self.floors[self.fa][0])

	# ---- buyer-specific rules (generic: nothing here is tied to one customer)
	def test_a_customer_can_make_pp_optional(self):
		self.assertIn("PP:", self.blockers())
		self.requirement("PP", gate="No", remarks="Buyer asks for PP only on request")
		for stype in ("Fit", "Bulk Trim"):
			self.sample(stype).insert()
		for stype in ("Lab Dip", "Bulk Fabric"):
			self.sample(stype, colour="Navy").insert()
		self.assertNotIn("PP:", self.blockers())
		self.meeting(None).insert().submit()  # no PP sample needed for the meeting either
		self.assertEqual(self.blockers(), "")

	def test_the_most_specific_requirement_wins(self):
		self.requirement("PP", gate="No")
		self.assertNotIn("PP:", self.blockers())
		frappe.get_doc({"doctype": "Sample Requirement", "sample_type": "PP", "sales_order": self.so.name, "gate": "Required"}).insert()
		self.assertIn("PP:", self.blockers())
		self.assertNotIn("PP:", self.blockers(self.navy_item2, self.so2.name))  # the other order keeps the customer rule

	def test_split_po_exemption(self):
		self.requirement("Bulk Trim", split_po_exempt=1)
		self.assertIn("Bulk Trim", self.blockers())  # single destination: still required
		other = " | ".join(gate.get_bulk_gate(self.navy_item2, self.so2.name)["blockers"])
		self.assertNotIn("Bulk Trim", other)  # ships to two destinations: exempt

	def test_due_date_can_follow_the_in_warehouse_date(self):
		self.requirement("TOP", gate="If Raised", due_basis="In-Warehouse", days_before=10, qty=1, sample_size="S")
		top = self.sample("TOP", colour="Navy", decision=None).insert()
		in_wh = next(i.apparel_in_warehouse_date for i in self.so.items if i.apparel_colour == "Navy")
		self.assertEqual(top.due_date, add_days(in_wh, -10))
		self.assertEqual((top.sample_qty, top.sample_size), (1, "S"))

	def test_late_sample_shows_the_chargeback(self):
		self.requirement("TOP", due_basis="Ex-Factory", days_before=10, chargeback_amount=200)
		late = self.sample("TOP", colour="Navy", decision=None, due_date=add_days(nowdate(), -2)).insert()
		self.assertEqual(late.late_chargeback, 200)  # overdue and not sent
		late.append("rounds", {"sent_on": add_days(nowdate(), -5), "decision": "Pending"})
		late.save()
		self.assertEqual(late.late_chargeback, 0)  # went out before the due date
		on_time = self.sample("TOP", colour="Black", decision=None, due_date=add_days(nowdate(), 5)).insert()
		self.assertEqual(on_time.late_chargeback, 0)

	def test_samples_due_after_fit_approval_follow_the_fit(self):
		cs = self.sample("Customer Sample", decision=None).insert()
		self.assertFalse(cs.due_date)  # no fit approval yet
		self.sample("Fit").insert()
		cs.reload()
		self.assertEqual(str(cs.due_date), add_days(nowdate(), 10))
		later = self.sample("Customer Sample", decision=None).insert()  # raised after the fit was approved
		self.assertEqual(str(later.due_date), add_days(nowdate(), 10))

	# ---- measurements, shrinkage, test list
	def test_five_sample_readings_must_all_be_in_tolerance(self):
		ok = {"point_of_measure": "Chest", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 50, "reading_2": 50.5, "reading_3": 49.5}
		bad = {**ok, "point_of_measure": "Length", "spec": 70, "actual": 70, "reading_2": 70.4, "reading_3": 69.8, "reading_4": 68.5, "reading_5": 70}
		s = self.sample("Fit", decision=None, measurement_stage="Before Wash", measurements=[ok, bad]).insert()
		self.assertEqual([m.in_tolerance for m in s.measurements], [1, 0])
		self.assertEqual(s.measurements[1].deviation, -1.5)

	def test_fabric_shrinkage_is_calculated(self):
		s = self.sample("Bulk Fabric", colour="Navy", decision=None, shrinkage=[
			{"roll_no": "R1", "before_warp": 100, "after_warp": 97, "before_weft": 100, "after_weft": 98.5, "before_bias": 100, "after_bias": 100}]).insert()
		r = s.shrinkage[0]
		self.assertEqual((r.shrink_warp_pct, r.shrink_weft_pct, r.shrink_bias_pct), (-3, -1.5, 0))

	def test_standard_test_list_comes_from_settings(self):
		frappe.db.set_single_value("Apparel Settings", "gpt_test_list", "Seam strength\nColourfastness\n")
		s = self.sample("Garment Test (GPT)", decision=None).insert()
		s.load_standard_tests()
		self.assertEqual([t.test_property for t in s.tests], ["Seam strength", "Colourfastness"])

	# ---- allocation by ship-to and PO
	def ship_lines(self, dc1=500, dc2=200, black=500, **kw):
		pcd = add_days(nowdate(), 40)
		row = lambda colour, qty, factory, **x: {"style_item": self.style2, "colour": colour, "qty": qty, "factory": factory,
												  "line": self.floors[factory][0], "pcd": pcd, **x}
		return [row("Navy", dc1, self.fa, ship_to="DC1"), row("Navy", dc2, self.fb, ship_to="DC2", **kw), row("Black", black, self.fa)]

	def test_allocation_can_be_split_by_ship_to(self):
		fa = frappe.get_doc("Factory Allocation", save_allocation(self.so2.name, self.ship_lines()))
		self.assertEqual(fa.status, "Planned")
		self.assertEqual([(r.ship_to, r.order_qty) for r in fa.lines], [("DC1", 500), ("DC2", 200), (None, 500)])
		with self.assertRaises(frappe.ValidationError):  # DC2 order is 200 + 10%: 220
			save_allocation(self.so2.name, self.ship_lines(dc2=221))
		bad = self.ship_lines()
		bad[0]["ship_to"] = "DC9"
		with self.assertRaises(frappe.ValidationError):
			save_allocation(self.so2.name, bad)

	# ---- pilot run, departments, milestones
	def test_pilot_run_is_a_separate_meeting(self):
		pilot = self.meeting(None, meeting_type="Pilot Run", participants=[
			{"department": d, "attended": 1} for d in ("Cutting", "Sewing", "QC")])
		pilot.insert()
		with self.assertRaises(frappe.ValidationError):
			pilot.submit()  # CAD missing
		pilot.reload()
		pilot.append("participants", {"department": "CAD", "attended": 1})
		pilot.save()
		pilot.submit()  # no PP sample or buyer comments needed
		self.assertTrue(any("PP Meeting: not held" in b for b in gate.get_bulk_gate(self.navy_item, self.so.name)["blockers"]))

	def test_required_departments_come_from_settings(self):
		frappe.db.set_single_value("Apparel Settings", "pp_required_departments", "Planning\nQuality")
		try:
			pp = self.sample("PP", in_bulk_fabric=1).insert()
			m = self.meeting(pp, participants=[{"department": "Planning", "attended": 1}]).insert()
			with self.assertRaises(frappe.ValidationError):
				m.submit()
			m.reload()
			m.append("participants", {"department": "Quality", "attended": 1})
			m.save()
			m.submit()
		finally:
			frappe.db.set_single_value("Apparel Settings", "pp_required_departments", "Planning\nPurchasing\nCutting\nSewing\nQC")

	def test_sampling_milestones_for_the_wip_sheet(self):
		fit = self.sample("Fit", decision=None, rounds=[
			{"sent_on": add_days(nowdate(), -9), "decision": "Approved with Comments", "decision_on": add_days(nowdate(), -6)},
			{"sent_on": add_days(nowdate(), -4), "decision": "Approved", "decision_on": nowdate()}],
			comments=[{"round_no": 1, "comment": "Raise neckline"}]).insert()
		navy = next(r for r in get_sampling_milestones(self.so.name) if r["colour"] == "Navy")
		self.assertEqual(navy["samples"]["Fit"][0]["name"], fit.name)
		self.assertEqual([r["decision"] for r in navy["samples"]["Fit"][0]["rounds"]], ["Approved with Comments", "Approved"])
