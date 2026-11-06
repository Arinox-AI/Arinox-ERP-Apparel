import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_allocation import floors, lines, order, save


def requirement(stype, **kw):
	return frappe.get_doc({"doctype": "Sample Requirement", "sample_type": stype, "customer": fx.customer(), **kw}).insert()


def sample(so, stype, colour=None, decision="Approved", **kw):
	d = {"doctype": "Sample Approval", "sample_type": stype, "style_item": fx.item(), "sales_order": so.name if so else None, "colour": colour,
		 "material_description": "Jersey 180gsm" if stype.startswith("Bulk") else None}
	rounds = []
	if decision:
		rounds.append({"sent_on": add_days(nowdate(), -3), "decision": decision, "decision_on": nowdate() if decision != "Pending" else None})
	d.update(rounds=rounds)
	d.update(kw)
	return frappe.get_doc(d)


@test("samples")
def status_follows_the_last_round():
	so = order()
	s = sample(so, "Fit", decision=None).insert()
	eq(s.status, "Open")
	s.append("rounds", {"sent_on": add_days(nowdate(), -5), "decision": "Pending"})
	s.save()
	eq(s.status, "Submitted")
	s.rounds[0].decision = "Rejected"
	s.rounds[0].decision_on = nowdate()
	s.append("comments", {"round_no": 1, "category": "Fit", "comment": "Chest too tight"})
	s.save()
	eq(s.status, "Rejected")
	s.append("rounds", {"sent_on": nowdate(), "decision": "Approved", "decision_on": nowdate()})
	s.save()
	eq((s.status, str(s.approved_on), [r.round_no for r in s.rounds]), ("Approved", nowdate(), [1, 2]))


@test("samples")
def decision_with_comments_needs_a_comment():
	so = order()
	true(throws(lambda: sample(so, "Fit", decision="Approved with Comments").insert(), "add the buyer's comment"))
	true(throws(lambda: sample(so, "Fit", decision="Rejected").insert(), "add the buyer's comment"))
	s = sample(so, "Fit", decision="Approved with Comments", comments=[{"round_no": 1, "comment": "Shorten sleeve 1cm"}]).insert()
	eq(s.status, "Approved with Comments")


@test("samples")
def decision_needs_a_date_that_is_not_in_the_future():
	so = order()
	true(throws(lambda: sample(so, "Fit", rounds=[{"sent_on": nowdate(), "decision": "Approved"}]).insert(), "enter the decision date"))
	true(throws(lambda: sample(so, "Fit", rounds=[{"decision": "Approved", "decision_on": add_days(nowdate(), 3)}]).insert(), "in the future"))
	true(throws(lambda: sample(so, "Fit", rounds=[{"sent_on": nowdate(), "decision": "Approved", "decision_on": add_days(nowdate(), -1)}]).insert(), "before the sent date"))


@test("samples")
def washed_bulk_approval_follows_the_process():
	so = order()
	true(throws(lambda: sample(so, "Bulk Fabric", colour="Navy", is_washed=1).insert(), "tested after wash"))
	s = sample(so, "Bulk Fabric", colour="Navy", is_washed=1, rounds=[{"sent_on": add_days(nowdate(), -2), "decision": "Approved", "decision_on": nowdate(), "tested_after_wash": 1}])
	s.insert()
	eq(s.status, "Approved")


@test("samples")
def pp_must_be_in_bulk_fabric():
	so = order()
	true(throws(lambda: sample(so, "PP").insert(), "bulk fabric"))
	eq(sample(so, "PP", in_bulk_fabric=1).insert().status, "Approved")


@test("samples")
def a_bulk_approval_names_the_material_and_a_style_is_not_a_variant():
	so = order()
	true(throws(lambda: sample(so, "Bulk Trim", material_description=None).insert(), "Enter the material"))
	_t, variant = fx.variant_item("Navy", "M", code="HT-SMP-STYLE")
	true(throws(lambda: sample(so, "Fit", style_item=variant).insert(), "not a size or colour variant"))


@test("samples")
def gpt_cannot_pass_with_a_failed_test_and_the_standard_list_comes_from_settings():
	so = order()
	s = sample(so, "Garment Test (GPT)", tests=[{"test_property": "Seam Strength", "result": "Pass"}, {"test_property": "Dimensional stability", "result": "Fail"}])
	true(throws(lambda: s.insert(), "Dimensional stability"))
	s = sample(so, "Garment Test (GPT)", tests=[{"test_property": "Seam Strength", "result": "Pass"}]).insert()
	eq(s.status, "Approved")
	frappe.db.set_single_value("Apparel Settings", "gpt_test_list", "Seam strength\nColourfastness\n")
	import json
	res = fx.engine_call("arinox_sample_approval_load_standard_tests", name=s.name, doc=json.dumps(s.as_dict(), default=str))["arinox_result"]
	tests = res["arinox_doc"]["tests"]
	eq([t["test_property"] for t in tests], ["Seam Strength", "Seam strength", "Colourfastness"])
	eq(tests[0].get("result"), "Pass")                  # rows already on the form keep their results


@test("samples")
def per_colour_types_need_a_colour():
	so = order()
	true(throws(lambda: sample(so, "Lab Dip", colour=None).insert(), "approved per colour"))


@test("samples")
def waiver_needs_the_manager_role_and_a_reason():
	so = order()
	merch = fx.user("ht_merch@example.com", ["Apparel Merchandiser"])
	manager = fx.user("ht_manager@example.com", ["Apparel Merchandiser", "Apparel Merchandising Manager"])
	try:
		frappe.set_user(merch)
		true(throws(lambda: sample(so, "Fit", decision=None, waived=1, waiver_reason="Carry over style").insert(), "Only an Apparel Merchandising Manager"))
		frappe.set_user(manager)
		true(throws(lambda: sample(so, "Fit", decision=None, waived=1).insert(), "Enter the reason"))
		s = sample(so, "Fit", decision=None, waived=1, waiver_reason="Carry over style").insert()
		eq((s.status, s.waived_by), ("Not Required", manager))
	finally:
		frappe.set_user("Administrator")


@test("samples")
def due_date_comes_from_the_pcd_and_the_rule():
	f = floors()
	so = order()
	save(so, lines(f))
	pcd = frappe.utils.getdate(add_days(nowdate(), 40))
	s = sample(so, "PP", in_bulk_fabric=1).insert()
	eq(s.due_date, add_days(pcd, -14))
	top = sample(so, "TOP", colour="Navy", decision=None).insert()                # TOP is due before ex-factory
	eq(top.due_date, add_days(frappe.utils.getdate(add_days(nowdate(), 60)), -10))


@test("samples")
def measurements_are_checked_against_tolerance_with_up_to_five_readings():
	so = order()
	s = sample(so, "Fit", decision=None, measurements=[
		{"point_of_measure": "Chest", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 50.5},
		{"point_of_measure": "Length", "spec": 70, "tol_plus": 1, "tol_minus": 1, "actual": 72}]).insert()
	eq([m.in_tolerance for m in s.measurements], [1, 0])
	eq(s.measurements[1].deviation, 2)
	ok = {"point_of_measure": "Chest", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 50, "reading_2": 50.5, "reading_3": 49.5}
	bad = dict(ok, point_of_measure="Length", spec=70, actual=70, reading_2=70.4, reading_3=69.8, reading_4=68.5, reading_5=70)
	s = sample(so, "Fit", decision=None, measurement_stage="Before Wash", measurements=[ok, bad]).insert()
	eq([m.in_tolerance for m in s.measurements], [1, 0])
	eq(s.measurements[1].deviation, -1.5)


@test("samples")
def fabric_shrinkage_is_calculated():
	so = order()
	s = sample(so, "Bulk Fabric", colour="Navy", decision=None, shrinkage=[
		{"roll_no": "R1", "before_warp": 100, "after_warp": 97, "before_weft": 100, "after_weft": 98.5, "before_bias": 100, "after_bias": 100}]).insert()
	r = s.shrinkage[0]
	eq((r.shrink_warp_pct, r.shrink_weft_pct, r.shrink_bias_pct), (-3, -1.5, 0))


@test("samples")
def requirements_override_the_rule_and_the_most_specific_wins():
	so = order()
	rules = fx.engine_call("arinox_sample_approval_get_sample_rules", customer=fx.customer(), sales_order=so.name, style_item=fx.item())["arinox_result"]
	eq((rules["PP"]["gate"], rules["Lab Dip"]["per_colour"], rules["TOP"]["due_basis"]), ("Required", 1, "Ex-Factory"))
	requirement("PP", gate="No")
	eq(fx.engine_call("arinox_sample_approval_get_sample_rules", customer=fx.customer(), sales_order=so.name, style_item=fx.item())["arinox_result"]["PP"]["gate"], "No")
	frappe.get_doc({"doctype": "Sample Requirement", "sample_type": "PP", "sales_order": so.name, "gate": "Required"}).insert()
	eq(fx.engine_call("arinox_sample_approval_get_sample_rules", customer=fx.customer(), sales_order=so.name, style_item=fx.item())["arinox_result"]["PP"]["gate"], "Required")
	other = order()
	eq(fx.engine_call("arinox_sample_approval_get_sample_rules", customer=fx.customer(), sales_order=other.name, style_item=fx.item())["arinox_result"]["PP"]["gate"], "No")


@test("samples")
def due_date_can_follow_the_in_warehouse_date_and_the_rule_sets_quantity_and_size():
	so = order()
	requirement("TOP", gate="If Raised", due_basis="In-Warehouse", days_before=10, qty=1, sample_size="S")
	top = sample(so, "TOP", colour="Navy", decision=None).insert()
	eq(top.due_date, add_days(frappe.utils.getdate(add_days(nowdate(), 90)), -10))
	eq((top.sample_qty, top.sample_size), (1, "S"))


@test("samples")
def late_sample_shows_the_chargeback():
	so = order()
	requirement("TOP", due_basis="Ex-Factory", days_before=10, chargeback_amount=200)
	late = sample(so, "TOP", colour="Navy", decision=None, due_date=add_days(nowdate(), -2)).insert()
	eq(late.late_chargeback, 200)                       # overdue and not sent
	late.append("rounds", {"sent_on": add_days(nowdate(), -5), "decision": "Pending"})
	late.save()
	eq(late.late_chargeback, 0)                         # went out before the due date
	on_time = sample(so, "TOP", colour="Black", decision=None, due_date=add_days(nowdate(), 5)).insert()
	eq(on_time.late_chargeback, 0)


@test("samples")
def samples_due_after_fit_approval_follow_the_fit():
	so = order()
	cs = sample(so, "Customer Sample", decision=None).insert()
	true(not cs.due_date, "no fit approval yet")
	sample(so, "Fit").insert()
	cs.reload()
	eq(str(cs.due_date), add_days(nowdate(), 10))
	later = sample(so, "Customer Sample", decision=None).insert()      # raised after the fit was approved
	eq(str(later.due_date), add_days(nowdate(), 10))


@test("samples")
def load_spec_from_the_tech_pack_gives_the_rows_of_the_sample_size():
	import json
	from arinox_apparel.portable.hosted_tests.test_tech_pack import tech_pack
	tp = tech_pack("HT-SMP-SPEC")
	so = order()
	s = sample(so, "Fit", decision=None, tech_pack=tp.name, sample_size="M").insert()
	res = fx.engine_call("arinox_sample_approval_load_spec_from_tech_pack", name=s.name, doc=json.dumps(s.as_dict(), default=str))["arinox_result"]
	rows = res["arinox_doc"]["measurements"]
	eq([(r["point_of_measure"], r["size"], r["spec"], r["tol_plus"], r["tol_minus"]) for r in rows], [("Chest", "M", 52, 1, 1)])
	s.sample_size = "XXL"
	true(throws(lambda: fx.engine_call("arinox_sample_approval_load_spec_from_tech_pack", name=s.name, doc=json.dumps(s.as_dict(), default=str)), "no measurements for size"))
	s.tech_pack = None
	true(throws(lambda: fx.engine_call("arinox_sample_approval_load_spec_from_tech_pack", name=s.name, doc=json.dumps(s.as_dict(), default=str)), "Select the Tech Pack"))


@test("samples")
def sampling_milestones_for_the_wip_sheet():
	so = order()
	fit = sample(so, "Fit", decision=None, rounds=[
		{"sent_on": add_days(nowdate(), -9), "decision": "Approved with Comments", "decision_on": add_days(nowdate(), -6)},
		{"sent_on": add_days(nowdate(), -4), "decision": "Approved", "decision_on": nowdate()}],
		comments=[{"round_no": 1, "comment": "Raise neckline"}]).insert()
	rows = fx.engine_call("arinox_sample_approval_get_sampling_milestones", sales_order=so.name)["arinox_result"]
	navy = [r for r in rows if r["colour"] == "Navy"][0]
	eq(navy["samples"]["Fit"][0]["name"], fit.name)
	eq([r["decision"] for r in navy["samples"]["Fit"][0]["rounds"]], ["Approved with Comments", "Approved"])
