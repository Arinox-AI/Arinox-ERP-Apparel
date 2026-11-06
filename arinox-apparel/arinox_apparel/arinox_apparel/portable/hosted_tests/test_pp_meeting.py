import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_allocation import order
from arinox_apparel.portable.hosted_tests.test_samples import sample

DEPTS = ("Planning", "Purchasing", "Cutting", "Sewing", "QC")


def meeting(so, pp, **kw):
	d = {"doctype": "PP Meeting", "sales_order": so.name, "style_item": fx.item(), "meeting_date": nowdate(), "production_card_issued_on": add_days(nowdate(), -2),
		 "pp_sample": pp.name if pp else None, "participants": [{"department": x, "participant_name": x, "attended": 1} for x in DEPTS]}
	d.update(kw)
	return frappe.get_doc(d)


def call(button, m):
	return fx.engine_call(button, name=m.name, doc=json.dumps(m.as_dict(), default=str))["arinox_result"]


@test("pp_meeting")
def a_meeting_needs_an_approved_pp_sample():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1, decision="Rejected", comments=[{"round_no": 1, "comment": "Hem uneven"}]).insert()
	m = meeting(so, pp).insert()
	true(throws(lambda: m.submit(), "PP sample must be buyer approved"))
	# a PP sample of another type or style is refused at save
	fit = sample(so, "Fit").insert()
	true(throws(lambda: meeting(so, fit).insert(), "is not a PP sample"))


@test("pp_meeting")
def a_meeting_reviews_every_buyer_comment():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	sample(so, "Fit", decision="Approved with Comments", comments=[{"round_no": 1, "category": "Fit", "comment": "Lengthen body 1cm", "relevant_to_cutting": 1}]).insert()
	m = meeting(so, pp).insert()
	true(throws(lambda: m.submit(), "Every buyer comment must be reviewed"))                 # the Fit comment is not in the action list
	m = frappe.get_doc("PP Meeting", m.name)
	res = call("arinox_pp_meeting_get_buyer_comments", m)
	eq(res["count"], 1)
	eq(len(res["arinox_doc"]["actions"]), 1)
	m.set("actions", res["arinox_doc"]["actions"])
	m.save()
	true(throws(lambda: m.submit(), "needs the action, an owner and a target date"))        # no action taken, no owner, no date
	m = frappe.get_doc("PP Meeting", m.name)
	a = m.actions[0]
	eq((a.source, a.relevant_to_cutting, a.comment[:5]), ("Buyer Comment", 1, "[Fit]"))
	a.action_taken = "Pattern corrected"
	a.action_owner = "Administrator"
	a.target_date = add_days(nowdate(), 5)
	m.save()
	m.submit()
	eq(m.status, "Open Actions")
	eq(call("arinox_pp_meeting_get_buyer_comments", frappe.get_doc("PP Meeting", m.name))["count"], 0)    # already listed


@test("pp_meeting")
def a_meeting_needs_the_departments():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	m = meeting(so, pp, participants=[{"department": "Planning", "attended": 1}]).insert()
	true(throws(lambda: m.submit(), "must attend"))
	m2 = meeting(so, pp, is_washed=1).insert()                                              # washing must attend too
	m2.set("participants", [{"department": x, "attended": 1} for x in DEPTS])
	true(throws(lambda: m2.submit(), "Washing"))


@test("pp_meeting")
def the_production_card_must_be_issued_before_the_meeting():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	true(throws(lambda: meeting(so, pp, production_card_issued_on=None).insert().submit(), "Enter the date the production card was issued"))
	true(throws(lambda: meeting(so, pp, production_card_issued_on=add_days(nowdate(), 2)).insert().submit(), "before the production card was issued"))


@test("pp_meeting")
def closing_an_action_closes_the_buyer_comment_and_cancelling_reopens_it():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	fit = sample(so, "Fit", decision="Approved with Comments", comments=[{"round_no": 1, "comment": "Lengthen body 1cm", "relevant_to_cutting": 1}]).insert()
	m = meeting(so, pp).insert()
	m.set("actions", call("arinox_pp_meeting_get_buyer_comments", m)["arinox_doc"]["actions"])
	a = m.actions[0]
	a.action_taken = "Pattern corrected"
	a.action_owner = "Administrator"
	a.target_date = add_days(nowdate(), 5)
	m.save()
	m.submit()
	fit.reload()
	eq(fit.comments[0].status, "Open")
	m.actions[0].status = "Closed"
	m.save()                                                                                # action rows stay editable after submit
	fit.reload()
	eq((fit.comments[0].status, fit.comments[0].closed_in), ("Closed", m.name))
	eq((m.status, str(m.actions[0].closed_on)), ("Closed", nowdate()))
	m.cancel()
	fit.reload()
	eq((fit.comments[0].status, fit.comments[0].closed_in), ("Open", None))


@test("pp_meeting")
def an_action_edited_after_submit_still_needs_its_owner_and_date():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	m = meeting(so, pp, actions=[{"source": "Meeting", "comment": "Check labels", "action_taken": "Done", "action_owner": "Administrator", "target_date": add_days(nowdate(), 3)}]).insert()
	m.submit()
	m.actions[0].action_owner = None
	true(throws(lambda: m.save(), "needs the action, an owner and a target date"))


@test("pp_meeting")
def a_pilot_run_meeting_is_separate_and_needs_cad():
	so = order()
	pilot = meeting(so, None, meeting_type="Pilot Run", participants=[{"department": x, "attended": 1} for x in ("Cutting", "Sewing", "QC")]).insert()
	true(throws(lambda: pilot.submit(), "CAD"))
	pilot = frappe.get_doc("PP Meeting", pilot.name)
	pilot.append("participants", {"department": "CAD", "attended": 1})
	pilot.save()
	pilot.submit()                                                                         # no PP sample or buyer comments needed
	eq(frappe.db.get_value("PP Meeting", pilot.name, "docstatus"), 1)


@test("pp_meeting")
def a_buyer_that_waives_pp_needs_no_pp_sample():
	so = order()
	true(throws(lambda: meeting(so, None).insert().submit(), "PP sample must be buyer approved"))      # the default rule requires one
	fx_req = frappe.get_doc({"doctype": "Sample Requirement", "sample_type": "PP", "customer": fx.customer(), "gate": "No"}).insert()
	meeting(so, None).insert().submit()
	true(fx_req.name)


@test("pp_meeting")
def required_departments_come_from_settings():
	so = order()
	frappe.db.set_single_value("Apparel Settings", "pp_required_departments", "Planning\nQuality")
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	m = meeting(so, pp, participants=[{"department": "Planning", "attended": 1}]).insert()
	true(throws(lambda: m.submit(), "Quality"))
	m = frappe.get_doc("PP Meeting", m.name)
	m.append("participants", {"department": "Quality", "attended": 1})
	m.save()
	m.submit()
	# the button adds what is missing, once
	m2 = meeting(so, pp, participants=[{"department": "Planning", "attended": 1}]).insert()
	rows = call("arinox_pp_meeting_add_standard_participants", m2)["arinox_doc"]["participants"]
	eq(sorted(r["department"] for r in rows), ["Planning", "Quality"])


@test("pp_meeting")
def the_meeting_takes_factory_line_and_pcd_from_the_allocation():
	from arinox_apparel.portable.hosted_tests.test_allocation import floors, lines, save
	f = floors()
	so = order()
	save(so, lines(f))
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	m = meeting(so, pp).insert()
	true(m.factory in f and m.line in f[m.factory], "a factory and one of its own lines (both rows share the PCD, so which comes first is a tie)")
	eq((str(m.pcd), m.order_qty, m.customer), (add_days(nowdate(), 40), 1200, fx.customer()))
	eq(m.status, "Draft")


@test("pp_meeting")
def load_from_requisitions_runs_on_an_order_with_no_requisitions():
	so = order()
	pp = sample(so, "PP", in_bulk_fabric=1).insert()
	m = meeting(so, pp).insert()
	res = call("arinox_pp_meeting_load_from_requisitions", m)
	eq((res["count"], res["arinox_doc"]["colours"]), (0, []))
	true("sewing_trims" not in res["arinox_doc"], "no trim requisitions, nothing to report")
