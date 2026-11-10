import frappe
from frappe.utils import add_days, getdate, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_allocation import floors, lines, save
from arinox_apparel.portable.hosted_tests.test_gate import gate_order
from arinox_apparel.portable.hosted_tests.test_pp_meeting import meeting
from arinox_apparel.portable.hosted_tests.test_samples import sample


def tna_order(days=100):
	"""Navy 700 + Black 500 on a style with a Tech Pack; the T&A plans are made through the planner button."""
	so, template, navy, black = gate_order(days=days)
	tp = frappe.get_doc("Tech Pack", {"style_item": template})
	if tp.docstatus == 0:
		tp.submit()                                          # the plan picks up an accepted tech pack
	made = fx.engine_call("arinox_planner_make_order_tnas", sales_order=so.name)["arinox_result"]
	return so, template, made


def tnas(so):
	return {t.colour: t for t in frappe.get_all("Order TNA", filters={"sales_order": so.name}, fields=["*"])}


def ms(so, code, colour="Navy"):
	return frappe.get_doc("TNA Milestone", {"order_tna": tnas(so)[colour].name, "milestone_type": code})


def stamp(so, template, code, date, doctype, name, colour="Navy", **kw):
	return fx.engine_call("arinox_tna", action="stamp", sales_order=so.name, style_item=template, colour=colour, code=code, date=str(date), source_doctype=doctype,
						  source_name=name, partial=kw.get("partial", 0), planned=kw.get("planned", 0))


@test("tna")
def plans_are_made_per_colour_with_the_template_offsets():
	so, template, made = tna_order()
	t = tnas(so)
	eq(sorted(t), ["Black", "Navy"])
	eq(len(made), 2)
	navy = t["Navy"]
	eq((navy.order_qty, navy.baseline_locked, navy.style_item), (700, 0, template))
	true(navy.template, "the default template")
	n = frappe.db.count("TNA Milestone", {"order_tna": navy.name})
	true(n >= 25, "milestones made: %s" % n)
	d = getdate(navy.order_received_date)
	off = lambda code: (getdate(ms(so, code).planned_date) - d).days

	def near(codes, expected):
		# with no Holiday List only Sundays are off, so a date that lands on a Sunday moves to the Monday (the app's rule)
		for code, e in zip(codes, expected):
			true(off(code) in (e, e + 1), "%s: offset %s, expected %s (or the next day if that is a Sunday)" % (code, off(code), e))
			true(getdate(ms(so, code).planned_date).weekday() != 6, "%s is not on a Sunday" % code)
	near(("MINI_MARKER", "FR_RAISED", "TR_RAISED", "FIT", "LAB_DIP", "TRIMS_APPROVED"), [3, 6, 9, 12, 13, 19])
	near(("BULK_FABRIC_APPROVED", "PP_GPT", "PP_MEETING"), [31, 36, 39])
	true((getdate(ms(so, "PILOT_RUN").planned_date) - getdate(ms(so, "PCD").planned_date)).days in (3, 4))
	true((getdate(ms(so, "EX_FACTORY").planned_date) - getdate(navy.ex_factory_date)).days in (0, 1), "ex-factory, or the Monday after a Sunday")
	fr, booked = ms(so, "FR_RAISED"), ms(so, "FABRIC_BOOKED")
	eq(booked.depends_on_tasks, fr.name)                    # the Gantt draws this arrow
	true(navy.plan_feasible, navy.feasibility_note)


@test("tna")
def bulk_finish_follows_the_quantity_and_a_skipped_step_adds_no_days():
	so, template, made = tna_order()
	top = getdate(ms(so, "TOP").planned_date)
	days = (getdate(ms(so, "BULK_FINISH").planned_date) - top).days
	true(days in (3, 4), days)                               # 700 pcs / 300 a day = 2.33 -> 3 days (one more when that lands on a Sunday)
	d2 = (getdate(ms(so, "BULK_FINISH", "Black").planned_date) - getdate(ms(so, "TOP", "Black").planned_date)).days
	true(d2 in (2, 3), d2)                                   # 500 / 300 -> 2
	eq(ms(so, "WASH_FINISHED").not_applicable, 1)            # the test style has no wash
	eq(ms(so, "WASH_FINISHED").planned_date, ms(so, "BULK_FINISH").planned_date)     # it passes the date through
	true((getdate(ms(so, "PACK_FINISHED").planned_date) - getdate(ms(so, "BULK_FINISH").planned_date)).days in (3, 4))


@test("tna")
def applicability_follows_the_rules_and_the_tech_pack():
	so, template, made = tna_order()
	eq(ms(so, "TOP").not_applicable, 1)                      # the TOP gate is No by default
	for code in ("FIT", "LAB_DIP", "TRIMS_APPROVED", "BULK_FABRIC_APPROVED", "PP_GPT", "FPT_PASSED"):
		eq(ms(so, code).not_applicable, 0)


@test("tna")
def order_and_tech_pack_are_stamped_from_history_and_calling_again_changes_nothing():
	so, template, made = tna_order()
	eq(ms(so, "ORDER_RECEIVED").status, "Done")
	tp = ms(so, "TECH_PACK_RECEIVED")
	eq((tp.status, tp.source_doctype), ("Done", "Tech Pack"))
	again = fx.engine_call("arinox_planner_make_order_tnas", sales_order=so.name)["arinox_result"]
	eq(again, [])
	eq(len(tnas(so)), 2)


@test("tna")
def an_actual_is_never_overwritten_by_a_later_document_and_cancel_unstamps():
	so, template, made = tna_order()
	stamp(so, template, "FR_RAISED", add_days(nowdate(), -2), "Fabric Requisition", "FR-A")
	first = ms(so, "FR_RAISED")
	eq((first.status, first.source_doctype, first.source_name), ("Done", "Fabric Requisition", "FR-A"))
	stamp(so, template, "FR_RAISED", add_days(nowdate(), -1), "Fabric Requisition", "FR-B")
	again = ms(so, "FR_RAISED")
	eq((again.actual_date, again.source_name), (first.actual_date, "FR-A"))
	stamp(so, template, "FR_RAISED", add_days(nowdate(), -2), "Fabric Requisition", "FR-A")      # the same source may restamp
	fx.engine_call("arinox_tna", action="unstamp", source_doctype="Fabric Requisition", source_name="FR-A")
	again = ms(so, "FR_RAISED")
	eq((again.actual_date, again.source_name), (None, None))
	eq(again.status in ("Not Started", "Late"), True)


@test("tna")
def a_partial_stamp_is_in_progress_and_a_planned_etd_moves_only_the_revised_date():
	so, template, made = tna_order()
	stamp(so, template, "FABRIC_IN_HOUSE", nowdate(), "Purchase Receipt", "PR-X", partial=1)
	m = ms(so, "FABRIC_IN_HOUSE")
	eq((m.status, m.partial, m.actual_date), ("In Progress", 1, None))
	planned = ms(so, "FABRIC_ETD").planned_date
	later = add_days(planned, 9)
	stamp(so, template, "FABRIC_ETD", later, "Purchase Order", "PO-X", planned=1)
	m = ms(so, "FABRIC_ETD")
	eq((m.planned_date, str(m.revised_date), m.actual_date), (planned, str(later), None))
	true(m.revision_reason)


@test("tna")
def sample_approval_stamps_per_colour_and_a_resubmit_clears():
	so, template, made = tna_order()
	s = sample(so, "Lab Dip", colour="Navy", style_item=template).insert()
	eq(ms(so, "LAB_DIP").status, "Done")
	true(ms(so, "LAB_DIP", "Black").status != "Done", "per colour")
	s.rounds[0].decision = "Resubmit"
	s.append("comments", {"round_no": 1, "category": "Colour", "comment": "Too light"})
	s.save()
	true(ms(so, "LAB_DIP").status != "Done")


@test("tna")
def a_pp_meeting_stamps_and_cancelling_it_clears():
	so, template, made = tna_order()
	pp = sample(so, "PP", in_bulk_fabric=1, style_item=template).insert()
	m = meeting(so, pp, style_item=template).insert()
	m.submit()
	eq(ms(so, "PP_MEETING").status, "Done")
	m.cancel()
	true(ms(so, "PP_MEETING").status != "Done")


@test("tna")
def the_factory_allocation_sets_pcd_and_factory_and_moves_the_plan():
	so, template, made = tna_order()
	f = floors()
	pcd = add_days(nowdate(), 30)
	rows = lines(f, navy=700, black=500)
	rows[0]["style_item"] = template
	rows[1]["style_item"] = template
	rows[0]["pcd"] = rows[1]["pcd"] = pcd
	save(so, rows)
	navy = tnas(so)["Navy"]
	eq((str(navy.pcd), navy.factory), (str(pcd), list(f)[0]))
	eq(ms(so, "PILOT_RUN").factory, navy.factory)
	eq(str(ms(so, "PCD").planned_date), str(pcd))             # unlocked baseline: the plan itself moves
	eq(str(ms(so, "PILOT_RUN").planned_date), str(add_days(pcd, 3)))


@test("tna")
def a_locked_baseline_moves_only_the_revised_dates():
	so, template, made = tna_order()
	f = floors()
	rows = lines(f)
	rows[0]["style_item"] = rows[1]["style_item"] = template
	rows[0]["pcd"] = rows[1]["pcd"] = add_days(nowdate(), 30)
	save(so, rows)
	fx.engine_call("arinox_order_tna_lock_baseline", name=tnas(so)["Navy"].name)
	before = ms(so, "PCD").planned_date
	rows[0]["pcd"] = rows[1]["pcd"] = add_days(nowdate(), 36)
	save(so, rows)
	m = ms(so, "PCD")
	eq(m.planned_date, before)
	eq(str(m.revised_date), str(add_days(nowdate(), 36)))
	true(m.revision_reason)


@test("tna")
def baseline_lock_rules_and_the_actual_date_rule():
	so, template, made = tna_order()
	fx.engine_call("arinox_order_tna_lock_baseline", name=tnas(so)["Navy"].name)
	m = ms(so, "MINI_MARKER")
	m.planned_date = add_days(m.planned_date, 2)
	true(throws(lambda: m.save(), "baseline is locked"))
	m = ms(so, "MINI_MARKER")
	m.revised_date = add_days(m.planned_date, 2)
	true(throws(lambda: m.save(), "reason for the revised date"))
	m = ms(so, "MINI_MARKER")
	m.revised_date = add_days(m.planned_date, 2)
	m.revision_reason = "Buyer sent the tech pack late"
	m.save()
	eq(ms(so, "MINI_MARKER").status, "Not Started")
	m = ms(so, "FIT")
	m.actual_date = add_days(nowdate(), 3)
	true(throws(lambda: m.save(), "cannot be in the future"))
	merch = fx.user("ht_merch@example.com", ["Apparel Merchandiser"])
	try:
		frappe.set_user(merch)
		true(throws(lambda: fx.engine_call("arinox_order_tna_unlock_baseline", name=tnas(so)["Navy"].name), "Only an Apparel Merchandising Manager"))
	finally:
		frappe.set_user("Administrator")
	eq(fx.engine_call("arinox_order_tna_unlock_baseline", name=tnas(so)["Navy"].name)["arinox_result"], 0)


@test("tna")
def status_is_right_without_the_scheduler_and_the_order_completes():
	so, template, made = tna_order()
	m = ms(so, "FR_RAISED")
	frappe.db.set_value("TNA Milestone", m.name, {"planned_date": add_days(nowdate(), -6), "planned_start": add_days(nowdate(), -6)}, update_modified=False)
	data = fx.engine_call("arinox_api_wip_board_data", filters=json_of({"sales_order": so.name}))["arinox_result"]
	navy = [o for o in data["orders"] if o.colour == "Navy"][0]
	eq(navy.status_live, "Late")                              # computed now, though the stored value is stale
	true(navy.critical_delay_days >= 6)
	cell = data["milestones"][navy.name]["FR_RAISED"]
	eq((cell["status"], cell["cell"]), ("Late", "late"))
	fx.engine_call("arinox_tna", action="refresh", order_tna=navy.name)
	eq(frappe.db.get_value("Order TNA", navy.name, "status"), "Late")        # and the stored value follows
	t = tnas(so)["Black"]
	for name, na in frappe.get_all("TNA Milestone", filters={"order_tna": t.name}, fields=["name", "not_applicable"], as_list=True):
		if not na:
			frappe.db.set_value("TNA Milestone", name, "actual_date", nowdate(), update_modified=False)
	fx.engine_call("arinox_tna", action="refresh", order_tna=t.name)
	eq(frappe.db.get_value("Order TNA", t.name, "status"), "Completed")


def json_of(d):
	import json
	return json.dumps(d)


@test("tna")
def board_shape_filters_calendar_update_and_agent_api():
	so, template, made = tna_order()
	data = fx.engine_call("arinox_api_wip_board_data", filters=json_of({"sales_order": so.name}))["arinox_result"]
	eq(len(data["orders"]), 2)
	eq(data["types"][0]["code"], "ORDER_RECEIVED")
	eq(fx.engine_call("arinox_api_wip_board_data", filters=json_of({"sales_order": so.name, "customer": "Nobody"}))["arinox_result"]["orders"], [])
	eq(len(fx.engine_call("arinox_api_wip_board_data", filters=json_of({"sales_order": so.name, "late_only": 1}))["arinox_result"]["orders"]), 0)
	ev = fx.engine_call("arinox_tna_milestone_get_events", start=str(add_days(nowdate(), -1)), end=str(add_days(nowdate(), 365)),
						filters=json_of([["sales_order", "=", so.name]]))["arinox_result"]
	true(len(ev) > 40, len(ev))
	true(all(e["color"] for e in ev))
	true(not [e for e in ev if "Washing" in e["title"]], "not applicable ones are hidden")
	m = ms(so, "MINI_MARKER")
	out = fx.engine_call("arinox_api_update_milestone", name=m.name, revised_date=str(add_days(m.planned_date, 1)), reason="Waiting for the grade sheet")["arinox_result"]
	eq(out["status"], "Not Started")
	other = ms(so, "FR_RAISED")
	true(throws(lambda: fx.engine_call("arinox_api_update_milestone", name=other.name, revised_date=str(add_days(other.planned_date, 2))), "reason for the revised date"))
	out = fx.engine_call("arinox_api_update_milestone", name=m.name, actual_date=nowdate())["arinox_result"]
	eq(out["status"], "Done")
	eq(frappe.db.get_value("TNA Milestone", m.name, "source_doctype"), "Manual")
	agent = fx.engine_call("arinox_api_get_tna", sales_order=so.name)["arinox_result"]
	eq(len(agent), 2)
	true(len(agent[0]["milestones"]) >= 25)


@test("tna")
def cancelling_the_order_cancels_its_plans():
	so, template, made = tna_order()
	so.reload()
	so.cancel()
	eq({t.status for t in frappe.get_all("Order TNA", filters={"sales_order": so.name}, fields=["status"])}, {"Cancelled"})


@test("tna")
def template_rules():
	def tpl(milestones):
		return frappe.get_doc({"doctype": "TNA Template", "template_name": "HT tpl " + frappe.generate_hash(length=4), "milestones": milestones})
	a = {"milestone_type": "FR_RAISED", "basis": "After Milestone", "after_milestone": "TR_RAISED", "offset_days": 1}
	b = {"milestone_type": "TR_RAISED", "basis": "After Milestone", "after_milestone": "FR_RAISED", "offset_days": 1}
	true(throws(lambda: tpl([a, b]).insert(), "loop"))
	true(throws(lambda: tpl([a, a]).insert(), "only once"))
	true(throws(lambda: tpl([dict(a, after_milestone="PCD")]).insert(), "is not in this template"))
	true(throws(lambda: tpl([{"milestone_type": "BULK_FINISH", "basis": "Order Received", "duration_rule": "Qty / Daily Output"}]).insert(), "daily output"))
	first = tpl([{"milestone_type": "FR_RAISED", "basis": "Order Received", "offset_days": 1}])
	first.is_default = 1
	first.insert()
	second = tpl([{"milestone_type": "FR_RAISED", "basis": "Order Received", "offset_days": 2}])
	second.is_default = 1
	second.insert()
	eq(frappe.db.get_value("TNA Template", first.name, "is_default"), 0)      # one default only


@test("tna")
def milestone_state_through_real_milestones():
	so, template, made = tna_order()
	t = tnas(so)["Navy"].name

	def state(**kw):
		m = ms(so, "MINI_MARKER")
		for k in ("actual_date", "partial", "revised_date", "revision_reason", "not_applicable"):
			setattr(m, k, None if k.endswith("date") else 0)
		m.revision_reason = None
		m.planned_date = m.planned_start = add_days(nowdate(), kw.pop("planned"))
		for k in kw:
			setattr(m, k, kw[k])
		m.save()
		return (m.status, m.delay_days, m.progress)
	eq(state(planned=10), ("Not Started", 0, 0))
	eq(state(planned=10, partial=1), ("In Progress", 0, 50))
	eq(state(planned=-5), ("Late", 5, 0))
	eq(state(planned=-1, actual_date=add_days(nowdate(), -2)), ("Done", 0, 100))
	eq(state(planned=-5, actual_date=add_days(nowdate(), -2)), ("Done", 3, 100))
	eq(state(planned=-5, not_applicable=1), ("Not Applicable", 0, 0))
	eq(state(planned=-5, revised_date=add_days(nowdate(), 5), revision_reason="x"), ("Not Started", 10, 0))
	eq(state(planned=-5, revised_date=add_days(nowdate(), -1), revision_reason="x"), ("Late", 5, 0))


@test("tna")
def the_vocabulary_carries_the_towers_checkpoints_next_to_the_erps_own():
	# 33 types of the ERP plus one type for every other milestone of the tower's 61-milestone template (TNA plan section 5.3)
	codes = set(frappe.get_all("TNA Milestone Type", pluck="code"))
	true(len(codes) >= 66, "the vocabulary has %s types" % len(codes))
	for code in ("ORDER_RECEIVED", "BULK_FINISH", "EX_FACTORY", "SEW_START", "CUT_START", "CUT_END", "QC_INLINE", "WASH_SEND", "PACK_START", "CARTON_AUDIT", "SHIP_READY", "ORDER_CLOSURE"):
		true(code in codes, code)
	eq(frappe.db.get_value("TNA Milestone Type", "CUT_START", "auto_source"), "Manual")
	true(frappe.db.get_value("TNA Milestone Type", "CUT_START", "department"))


@test("tna")
def a_plan_computed_by_the_tower_is_written_in_one_call_and_respects_the_lock():
	so, template, made = tna_order()
	t = tnas(so)["Navy"]
	d1, d2 = str(add_days(nowdate(), 40)), str(add_days(nowdate(), 45))
	rows = [{"milestone_type": "MINI_MARKER", "planned_date": d1, "planned_start": d1, "sequence": 50, "is_critical": 0},
			{"milestone_type": "CUT_START", "planned_date": d2, "planned_start": d2, "sequence": 3300, "is_critical": 1}]    # CUT_START is a tower checkpoint the template did not make
	r = fx.engine_call("arinox_tna_apply_plan", order_tna=t.name, rows=rows, plan_feasible=0, feasibility_note="infeasible by 4 working days", critical_delay_days=4)["arinox_result"]
	eq((r["made"], r["moved"], r["locked"]), (1, 1, 0))
	eq(str(getdate(ms(so, "MINI_MARKER").planned_date)), d1)
	eq(str(getdate(ms(so, "CUT_START").planned_date)), d2)
	eq(frappe.db.get_value("Order TNA", t.name, ["plan_feasible", "critical_delay_days"]), (0, 4))
	again = fx.engine_call("arinox_tna_apply_plan", order_tna=t.name, rows=rows)["arinox_result"]
	eq((again["made"], again["moved"]), (0, 0))                        # idempotent: nothing is made or moved twice
	fx.engine_call("arinox_order_tna_lock_baseline", name=t.name)
	moved = [{"milestone_type": "MINI_MARKER", "planned_date": str(add_days(nowdate(), 70)), "revised_date": str(add_days(nowdate(), 50))}]
	locked = fx.engine_call("arinox_tna_apply_plan", order_tna=t.name, rows=moved, reason="Fabric supplier slipped")["arinox_result"]
	eq((locked["moved"], locked["revised"], locked["locked"]), (0, 1, 1))
	eq(str(getdate(ms(so, "MINI_MARKER").planned_date)), d1)           # the baseline did not move
	eq(str(getdate(ms(so, "MINI_MARKER").revised_date)), str(add_days(nowdate(), 50)))
	true(throws(lambda: fx.engine_call("arinox_tna_apply_plan", order_tna=t.name, rows=[{"milestone_type": "FR_RAISED", "planned_date": d1, "revised_date": str(add_days(nowdate(), 90))}]), "reason"))   # a revised date needs its reason
