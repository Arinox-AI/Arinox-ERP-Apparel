# Copyright (c) 2026, Arinox AI and contributors
"""Phase C: T&A planning, auto-stamping, status, the WIP board data."""

from types import SimpleNamespace as NS

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import save_allocation
from arinox_apparel.arinox_apparel.doctype.tna_milestone.tna_milestone import get_events
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.test_inspection import InspectionBase
from arinox_apparel.tna import events
from arinox_apparel.tna.api import cell_class, get_tna, update_milestone, wip_board_data
from arinox_apparel.tna.planner import feasibility, plan_dates, replan, working_day
from arinox_apparel.tna.seed import TEMPLATE_ROWS
from arinox_apparel.tna.status import milestone_state, order_state, refresh_order_tna

D = getdate("2026-01-05")  # a Monday


def rows(**override):
	out = []
	for code, basis, after, offset, rule, daily in TEMPLATE_ROWS:
		out.append({"code": code, "basis": basis, "after": after, "offset_days": offset, "duration_rule": rule, "daily_output": daily})
	return out


def plan(**kw):
	args = dict(order_received=D, ex_factory=add_days(D, 90), qty=520, holidays=set())
	args.update(kw)
	dates, unresolved = plan_dates(rows(), args["order_received"], args["ex_factory"], args["qty"], args["holidays"], pcd=args.get("pcd"),
		overrides=args.get("overrides"), na=args.get("na", ()))
	return {c: v["planned"] for c, v in dates.items()}, unresolved


class TestPlanner(IntegrationTestCase):
	def test_offsets_from_the_company_sheet(self):
		d, unresolved = plan()
		self.assertEqual(unresolved, [])
		off = lambda code: (d[code] - D).days
		self.assertEqual([off(c) for c in ("MINI_MARKER", "FR_RAISED", "TR_RAISED", "FIT", "LAB_DIP", "TRIMS_APPROVED", "BULK_FABRIC_READY_MILL", "FPT_PASSED")], [3, 6, 9, 12, 13, 19, 28, 29])
		self.assertEqual([off(c) for c in ("BULK_FABRIC_APPROVED", "PP_GPT", "PP_MEETING", "PCD")], [31, 36, 39, 41])
		self.assertEqual((d["PILOT_RUN"] - d["PCD"]).days, 3)
		self.assertEqual((d["TOP"] - d["PCD"]).days, 4)
		self.assertEqual(d["EX_FACTORY"], add_days(D, 90))

	def test_bulk_finish_is_quantity_over_daily_output(self):
		d, _u = plan(qty=520)  # 520 / 300 = 1.73 -> 2 days
		self.assertEqual((d["BULK_FINISH"] - d["TOP"]).days, 2)
		d, _u = plan(qty=1800)  # 6 days exactly
		self.assertEqual((d["BULK_FINISH"] - d["TOP"]).days, 6)
		d, _u = plan(qty=1)
		self.assertEqual((d["BULK_FINISH"] - d["TOP"]).days, 1)  # at least a day

	def test_after_chain(self):
		d, _u = plan()
		self.assertEqual((d["WASH_FINISHED"] - d["BULK_FINISH"]).days, 3)
		self.assertEqual((d["PACK_FINISHED"] - d["WASH_FINISHED"]).days, 3)
		self.assertEqual((d["FINAL_INSPECTION"] - d["PACK_FINISHED"]).days, 2)
		self.assertEqual((d["FREIGHT_BOOKING"] - d["FINAL_INSPECTION"]).days, 3)
		self.assertEqual((d["FABRIC_ETD"] - d["BULK_FABRIC_READY_MILL"]).days, 2)

	def test_not_applicable_milestone_adds_no_days(self):
		d, _u = plan(na={"WASH_FINISHED"})
		self.assertEqual(d["WASH_FINISHED"], d["BULK_FINISH"])  # passes the date through
		self.assertEqual((d["PACK_FINISHED"] - d["BULK_FINISH"]).days, 3)  # not 6

	def test_holidays_and_sundays(self):
		hol = {add_days(D, 6)}  # the FR day
		d, _u = plan(holidays=hol)
		self.assertEqual(d["FR_RAISED"], add_days(D, 7))
		self.assertEqual(working_day(getdate("2026-01-11"), None), getdate("2026-01-12"))  # no list: Sundays are off
		self.assertEqual(working_day(getdate("2026-01-11"), set()), getdate("2026-01-11"))  # a list with no holidays
		self.assertEqual(working_day(add_days(D, 6), hol, -1), add_days(D, 5))  # backward for offsets before a date
		many = {add_days(D, i) for i in range(6, 10)}
		self.assertEqual(working_day(add_days(D, 6), many), add_days(D, 10))

	def test_pcd_pinned_by_the_factory_allocation_and_dependents_follow(self):
		pcd = add_days(D, 50)
		d, _u = plan(pcd=pcd)
		self.assertEqual(d["PCD"], pcd)
		self.assertEqual((d["TOP"] - pcd).days, 4)
		self.assertEqual(d["PP_MEETING"], add_days(D, 39))  # before PCD, still on the template

	def test_sewing_end_override(self):
		end = add_days(D, 70)
		d, _u = plan(overrides={"BULK_FINISH": end})
		self.assertEqual(d["BULK_FINISH"], end)
		self.assertEqual((d["PACK_FINISHED"] - end).days, 6)

	def test_ex_factory_basis_counts_back(self):
		r = [{"code": "EX_FACTORY", "basis": "Ex-Factory", "after": None, "offset_days": 0}, {"code": "BOOK", "basis": "Ex-Factory", "after": None, "offset_days": -10}]
		dates, _u = plan_dates(r, D, add_days(D, 60), 100, set())
		self.assertEqual(dates["BOOK"]["planned"], add_days(D, 50))

	def test_unresolved_rows_are_reported(self):
		r = [{"code": "A", "basis": "After Milestone", "after": "NOPE", "offset_days": 1}, {"code": "B", "basis": "Order Received", "after": None, "offset_days": 1}]
		dates, unresolved = plan_dates(r, D, add_days(D, 60), 1, set())
		self.assertEqual(unresolved, ["A"])
		self.assertIn("B", dates)

	def test_feasibility(self):
		d = {"PCD": add_days(D, 41), "FREIGHT_BOOKING": add_days(D, 57), "EX_FACTORY": add_days(D, 90)}
		self.assertEqual(feasibility(d, add_days(D, 90)), (True, None))
		ok, note = feasibility(d, add_days(D, 50))
		self.assertFalse(ok)
		self.assertIn("7 days late", note)

	def test_template_rules(self):
		def tpl(milestones):
			return frappe.get_doc({"doctype": "TNA Template", "template_name": "_AT tpl " + frappe.generate_hash(length=4), "milestones": milestones})
		a = {"milestone_type": "FR_RAISED", "basis": "After Milestone", "after_milestone": "TR_RAISED", "offset_days": 1}
		b = {"milestone_type": "TR_RAISED", "basis": "After Milestone", "after_milestone": "FR_RAISED", "offset_days": 1}
		self.assertRaises(frappe.ValidationError, tpl([a, b]).insert)  # loop
		self.assertRaises(frappe.ValidationError, tpl([a, a]).insert)  # duplicate
		self.assertRaises(frappe.ValidationError, tpl([{**a, "after_milestone": "PCD"}]).insert)  # not in the template
		self.assertRaises(frappe.ValidationError, tpl([{"milestone_type": "BULK_FINISH", "basis": "Order Received", "duration_rule": "Qty / Daily Output"}]).insert)


class TestStatus(IntegrationTestCase):
	def test_milestone_state(self):
		t = "2026-03-10"
		self.assertEqual(milestone_state(0, None, 0, "2026-03-20", None, t), ("Not Started", 0, 0))
		self.assertEqual(milestone_state(0, None, 1, "2026-03-20", None, t), ("In Progress", 0, 50))
		self.assertEqual(milestone_state(0, None, 0, "2026-03-05", None, t), ("Late", 5, 0))
		self.assertEqual(milestone_state(0, "2026-03-04", 0, "2026-03-05", None, t), ("Done", 0, 100))
		self.assertEqual(milestone_state(0, "2026-03-08", 0, "2026-03-05", None, t), ("Done", 3, 100))
		self.assertEqual(milestone_state(1, None, 0, "2026-03-05", None, t), ("Not Applicable", 0, 0))
		# revised past the baseline: not late until the revised date passes, but the slip shows
		self.assertEqual(milestone_state(0, None, 0, "2026-03-05", "2026-03-15", t), ("Not Started", 10, 0))
		self.assertEqual(milestone_state(0, None, 0, "2026-03-05", "2026-03-09", t), ("Late", 5, 0))

	def test_order_state(self):
		t = "2026-03-10"
		m = lambda **k: {"planned_date": "2026-03-20", "is_critical": 1, "not_applicable": 0, **k}
		self.assertEqual(order_state([m()], 1, today=t)[0], "On Track")
		self.assertEqual(order_state([m(planned_date="2026-03-12")], 1, today=t)[0], "At Risk")  # critical due in 2 days
		self.assertEqual(order_state([m(planned_date="2026-03-05")], 1, today=t), ("Late", 5))
		self.assertEqual(order_state([m(is_critical=0, planned_date="2026-03-05")], 1, today=t)[0], "At Risk")
		self.assertEqual(order_state([m()], 0, today=t)[0], "At Risk")  # plan does not fit ex-factory
		self.assertEqual(order_state([m(actual_date="2026-03-01"), m(not_applicable=1)], 1, today=t)[0], "Completed")
		self.assertEqual(order_state([m()], 1, cancelled=True, today=t)[0], "Cancelled")

	def test_cell_classes(self):
		t = "2026-03-10"
		self.assertEqual(cell_class({"not_applicable": 1}, t), "na")
		self.assertEqual(cell_class({"actual_date": "2026-03-04", "planned_date": "2026-03-05"}, t), "done")
		self.assertEqual(cell_class({"actual_date": "2026-03-08", "planned_date": "2026-03-05"}, t), "done_late")
		self.assertEqual(cell_class({"planned_date": "2026-03-05"}, t), "late")
		self.assertEqual(cell_class({"planned_date": "2026-03-15"}, t), "soon")
		self.assertEqual(cell_class({"planned_date": "2026-04-15"}, t), "future")


class TnaBase(InspectionBase):
	def setUp(self):
		# a fresh order per test: stamps from one test must not show in the next
		self.so, self.style, self.sc = u.make_order("_AT-T" + frappe.generate_hash(length=6))
		super().setUp()

	def tnas(self, so=None):
		return {t.colour: t for t in frappe.get_all("Order TNA", {"sales_order": (so or self.so).name}, ["*"])}

	def ms(self, code, colour="Navy", so=None):
		t = self.tnas(so)[colour]
		return frappe.get_doc("TNA Milestone", {"order_tna": t.name, "milestone_type": code})


class TestOrderTna(TnaBase):
	def test_made_automatically_when_the_order_is_submitted(self):
		t = self.tnas()
		self.assertEqual(set(t), {"Navy", "Black"})
		navy = t["Navy"]
		self.assertEqual((navy.order_qty, navy.template, navy.baseline_locked), (700, "Standard 60-Day (forward)", 0))
		self.assertEqual(frappe.db.count("TNA Milestone", {"order_tna": navy.name}), 30)
		self.assertTrue(navy.plan_feasible)
		fr, booked = self.ms("FR_RAISED"), self.ms("FABRIC_BOOKED")
		self.assertEqual(booked.depends_on_tasks, fr.name)  # the Gantt draws this arrow

	def test_applicability_follows_the_rules_and_the_tech_pack(self):
		self.assertEqual(self.ms("WASH_FINISHED").not_applicable, 1)  # the test style has no wash
		self.assertEqual(self.ms("TOP").not_applicable, 1)  # TOP gate is No by default
		for code in ("FIT", "LAB_DIP", "TRIMS_APPROVED", "BULK_FABRIC_APPROVED", "PP_GPT", "FPT_PASSED"):
			self.assertEqual(self.ms(code).not_applicable, 0, code)

	def test_order_and_tech_pack_are_stamped_from_history(self):
		self.assertEqual(self.ms("ORDER_RECEIVED").status, "Done")
		tp = self.ms("TECH_PACK_RECEIVED")
		self.assertEqual((tp.status, tp.source_doctype), ("Done", "Tech Pack"))

	def test_calling_it_again_changes_nothing(self):
		from arinox_apparel.tna.planner import make_order_tnas

		before = set(self.tnas())
		self.assertEqual(make_order_tnas(self.so.name), [])
		self.assertEqual(set(self.tnas()), before)

	def test_requisitions_stamp_and_cancel_unstamps(self):
		fr = self.fr()
		fr.insert()
		fr.submit()
		m = self.ms("FR_RAISED")
		self.assertEqual((m.status, m.source_doctype, m.source_name), ("Done", "Fabric Requisition", fr.name))
		fr.cancel()
		m.reload()
		self.assertEqual((m.status, m.actual_date), ("Not Started", None))

	def test_an_actual_is_never_overwritten_by_a_later_document(self):
		fr = self.fr()
		fr.insert()
		fr.submit()
		first = self.ms("FR_RAISED")
		events.stamp(self.so.name, self.style, "Navy", "FR_RAISED", add_days(nowdate(), -1), "Fabric Requisition", "OTHER-FR")
		again = self.ms("FR_RAISED")
		self.assertEqual((again.actual_date, again.source_name), (first.actual_date, fr.name))

	def test_cancel_finds_another_document_that_proves_it(self):
		a = self.fr()
		a.insert()
		a.submit()
		b = self.fr()
		b.insert()
		b.submit()
		self.assertEqual(self.ms("FR_RAISED").source_name, a.name)
		a.cancel()
		self.assertEqual(self.ms("FR_RAISED").source_name, b.name)  # recomputed from the remaining document

	def test_receipt_inspection_and_booking_milestones(self):
		fr, po, pr = self.received_fabric()
		self.assertEqual(self.ms("FABRIC_BOOKED").status, "Done")
		self.assertEqual(self.ms("FABRIC_IN_HOUSE").status, "Done")
		qc = self.ms("FABRIC_QC_PASSED")
		self.assertNotEqual(qc.status, "Done")
		fi = self.inspection(pr, inspect=10)
		fi.insert()
		fi.submit()
		self.assertEqual(self.ms("FABRIC_QC_PASSED").status, "Done")
		fi.cancel()
		self.assertNotEqual(self.ms("FABRIC_QC_PASSED").status, "Done")

	def test_partial_receipt_is_in_progress(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
		from arinox_apparel.materials.rolls import import_roll_list

		fr, po, pr = self.received_fabric(rolls=10)
		# a second order, half received
		so2, style2, _sc = u.make_order("_AT-T" + frappe.generate_hash(length=6))
		self.so, self.style = so2, style2
		fr2 = self.fr()
		fr2.items = [r for r in fr2.items if r.colour == "Navy"]
		fr2.insert()
		fr2.submit()
		from arinox_apparel.overrides.purchase_order import make_purchase_orders

		po2 = frappe.get_doc("Purchase Order", make_purchase_orders("FR", fr2.name)[0])
		po2.transaction_date = add_days(nowdate(), -20)
		po2.schedule_date = add_days(nowdate(), -1)
		for i in po2.items:
			i.rate, i.schedule_date = 3, add_days(nowdate(), -1)
		po2.save()
		po2.submit()
		pr2 = make_purchase_receipt(po2.name)
		pr2.items[0].qty = 441
		pr2.items[0].received_qty = 441
		pr2.insert()
		import_roll_list(pr2.name, pr2.items[0].name, [{"roll_no": f"P{i}", "dye_lot": "L", "length": 88.2} for i in range(5)])
		pr2.reload()
		pr2.submit()
		m = self.ms("FABRIC_IN_HOUSE", so=so2)
		self.assertEqual((m.status, m.partial), ("In Progress", 1))

	def test_sample_approval_stamps_and_a_resubmit_clears(self):
		so, style, _sc = u.make_order("_AT-T" + frappe.generate_hash(length=6))
		sample = frappe.get_doc({"doctype": "Sample Approval", "sample_type": "Lab Dip", "style_item": style, "sales_order": so.name, "colour": "Navy",
			"material_description": "Jersey", "rounds": [{"sent_on": add_days(nowdate(), -3), "decision": "Approved", "decision_on": nowdate()}]}).insert()
		self.assertEqual(self.ms("LAB_DIP", "Navy", so).status, "Done")
		self.assertNotEqual(self.ms("LAB_DIP", "Black", so).status, "Done")  # per colour
		sample.rounds[0].decision = "Resubmit"
		sample.append("comments", {"round_no": 1, "category": "Colour", "comment": "Too light"})
		sample.save()
		self.assertNotEqual(self.ms("LAB_DIP", "Navy", so).status, "Done")

	def test_pp_meeting_and_pilot_run_documents(self):
		doc = NS(name="PPM-X", sales_order=self.so.name, style_item=self.style, meeting_date=nowdate(), meeting_type="PP Meeting")
		events.on_pp_meeting(doc, "on_submit")
		self.assertEqual(self.ms("PP_MEETING").status, "Done")
		events.on_pp_meeting(NS(**{**doc.__dict__, "name": "PPM-Y", "meeting_type": "Pilot Run"}), "on_submit")
		self.assertEqual(self.ms("PILOT_RUN").status, "Done")
		events.on_pp_meeting(doc, "on_cancel")
		self.assertNotEqual(self.ms("PP_MEETING").status, "Done")

	def test_a_failing_hook_never_blocks_the_caller(self):
		bad = NS(name="X", sales_order=None, style_item=None, meeting_date=None, meeting_type=None)
		events.on_pp_meeting(bad, "on_submit")  # must not raise
		events.on_work_order(NS(sales_order="NOPE", actual_start_date=nowdate(), production_item="NOPE", name="W"), "on_update")

	def test_planned_etd_moves_the_revised_date_only(self):
		planned = self.ms("FABRIC_ETD").planned_date
		later = add_days(planned, 9)
		events.stamp(self.so.name, self.style, "Navy", "FABRIC_ETD", later, "Purchase Order", "PO-X", planned=True)
		m = self.ms("FABRIC_ETD")
		self.assertEqual((m.planned_date, m.revised_date, m.actual_date), (planned, later, None))
		self.assertTrue(m.revision_reason)


class TestBaselineAndAllocation(TnaBase):
	def allocate(self, pcd):
		floors = u.make_floors()
		fa, fb = list(floors)
		lines = [{"style_item": self.style, "colour": "Navy", "qty": 700, "factory": fa, "line": floors[fa][0], "pcd": pcd},
			{"style_item": self.style, "colour": "Black", "qty": 500, "factory": fb, "line": floors[fb][0], "pcd": pcd}]
		return save_allocation(self.so.name, lines, "test")

	def test_allocation_sets_pcd_factory_and_moves_the_plan(self):
		pcd = add_days(nowdate(), 30)
		self.allocate(pcd)
		navy = self.tnas()["Navy"]
		pcd_ms = self.ms("PCD")
		self.assertEqual(getdate(navy.pcd), getdate(pcd))
		self.assertEqual(navy.factory, list(u.make_floors())[0])  # Navy goes to factory A
		self.assertEqual(self.ms("PILOT_RUN").factory, navy.factory)
		self.assertEqual(getdate(pcd_ms.planned_date), getdate(pcd))  # unlocked baseline: the plan itself moves
		self.assertEqual(getdate(self.ms("PILOT_RUN").planned_date), getdate(add_days(pcd, 3)))
		self.assertEqual(getdate(self.ms("TOP").planned_date), getdate(pcd))  # TOP is not applicable here: it passes the date through

	def test_locked_baseline_moves_only_the_revised_dates(self):
		pcd = add_days(nowdate(), 30)
		self.allocate(pcd)
		t = frappe.get_doc("Order TNA", self.tnas()["Navy"].name)
		t.lock_baseline()
		before = getdate(self.ms("PCD").planned_date)
		self.allocate(add_days(nowdate(), 36))
		m = self.ms("PCD")
		self.assertEqual(getdate(m.planned_date), before)
		self.assertEqual(getdate(m.revised_date), getdate(add_days(nowdate(), 36)))
		self.assertTrue(m.revision_reason)

	def test_baseline_lock_rules(self):
		t = frappe.get_doc("Order TNA", self.tnas()["Navy"].name)
		t.lock_baseline()
		m = self.ms("MINI_MARKER")
		m.planned_date = add_days(m.planned_date, 2)
		self.assertRaises(frappe.ValidationError, m.save)
		m.reload()
		m.revised_date = add_days(m.planned_date, 2)
		self.assertRaises(frappe.ValidationError, m.save)  # needs a reason
		m.reload()
		m.revised_date = add_days(m.planned_date, 2)
		m.revision_reason = "Buyer sent the tech pack late"
		m.save()
		m.reload()
		self.assertEqual(m.status, "Not Started")

	def test_actual_date_rules(self):
		m = self.ms("MINI_MARKER")
		m.actual_date = add_days(nowdate(), 3)
		self.assertRaises(frappe.ValidationError, m.save)


class TestBoard(TnaBase):
	def test_status_is_right_without_the_scheduler(self):
		m = self.ms("FR_RAISED")
		frappe.db.set_value("TNA Milestone", m.name, {"planned_date": add_days(nowdate(), -6), "planned_start": add_days(nowdate(), -6)}, update_modified=False)
		data = wip_board_data({"sales_order": self.so.name})
		navy = next(o for o in data["orders"] if o.colour == "Navy")
		self.assertEqual(navy.status_live, "Late")  # computed now, though the stored value is stale
		self.assertGreaterEqual(navy.critical_delay_days, 6)
		cell = data["milestones"][navy.name]["FR_RAISED"]
		self.assertEqual((cell["status"], cell["cell"]), ("Late", "late"))
		refresh_order_tna(navy.name)
		self.assertEqual(frappe.db.get_value("Order TNA", navy.name, "status"), "Late")  # and the stored value follows

	def test_board_shape_and_filters(self):
		data = wip_board_data({"sales_order": self.so.name})
		self.assertEqual(len(data["orders"]), 2)
		self.assertEqual(data["types"][0]["code"], "ORDER_RECEIVED")
		self.assertEqual(len(data["types"]), 30)
		self.assertEqual(wip_board_data({"sales_order": self.so.name, "customer": u.OTHER_CUSTOMER})["orders"], [])
		self.assertEqual(len(wip_board_data({"sales_order": self.so.name, "late_only": 1})["orders"]), 0)  # fresh order: nothing late

	def test_one_query_per_table_not_per_cell(self):
		with self.assertQueryCount(30):
			wip_board_data({"sales_order": self.so.name})

	def test_calendar_events(self):
		ev = get_events(add_days(nowdate(), -1), add_days(nowdate(), 365), '[["sales_order", "=", "%s"]]' % self.so.name)
		self.assertGreater(len(ev), 40)
		self.assertTrue(all(e["color"] for e in ev))
		self.assertFalse(any("Washing" in e["title"] for e in ev))  # not applicable ones are hidden

	def test_update_milestone_api_follows_the_form_rules(self):
		m = self.ms("MINI_MARKER")
		out = update_milestone(m.name, revised_date=add_days(m.planned_date, 1), reason="Waiting for the grade sheet")
		self.assertEqual(out["status"], "Not Started")
		other = self.ms("FR_RAISED")
		self.assertRaises(frappe.ValidationError, update_milestone, other.name, revised_date=add_days(other.planned_date, 2))  # no reason
		out = update_milestone(m.name, actual_date=nowdate())
		self.assertEqual(out["status"], "Done")
		self.assertEqual(frappe.db.get_value("TNA Milestone", m.name, "source_doctype"), "Manual")

	def test_agent_api(self):
		out = get_tna(self.so.name)
		self.assertEqual(len(out), 2)
		self.assertEqual(len(out[0]["milestones"]), 30)

	def test_completed_when_every_applicable_milestone_is_done(self):
		t = self.tnas()["Navy"]
		for name, na in frappe.get_all("TNA Milestone", {"order_tna": t.name}, ["name", "not_applicable"], as_list=True):
			if not na:
				frappe.db.set_value("TNA Milestone", name, "actual_date", nowdate(), update_modified=False)
		refresh_order_tna(t.name)
		self.assertEqual(frappe.db.get_value("Order TNA", t.name, "status"), "Completed")

	def test_cancelling_the_order_cancels_its_plans(self):
		so, style, sc = u.make_order("_AT-T" + frappe.generate_hash(length=6))
		so.cancel()
		self.assertEqual({t.status for t in frappe.get_all("Order TNA", {"sales_order": so.name}, ["status"])}, {"Cancelled"})
