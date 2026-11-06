import frappe
from frappe.utils import nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def plan():
	"""A one-row AQL plan with confirmed accept/reject numbers (the app's tests use the same shape)."""
	name = "HT Plan"
	if not frappe.db.exists("AQL Plan", name):
		frappe.get_doc({"doctype": "AQL Plan", "plan_name": name, "inspection_level": "General II", "aql_critical": "0", "aql_major": "2.5", "aql_minor": "4.0",
						"rows": [{"lot_from": 1, "lot_to": 99999999, "code_letter": "X", "sample_size": 80, "critical_ac": 0, "critical_re": 1, "major_ac": 3, "major_re": 4,
								  "minor_ac": 5, "minor_re": 6, "confirmed": 1}]}).insert()
	return name


def lot(pcs=100):
	card = fx.finished_card(pcs)
	return card, fx.packing_list(card, 24)


def draft(card, pl, **kw):
	body = {"doctype": "Final Inspection", "production_card": card.name, "inspection_type": "Final", "inspection_date": nowdate(), "aql_plan": plan(),
			"lots": [{"packing_list": pl.name}]}
	body.update(kw)
	return frappe.get_doc(body)


def pick(fi, seed=None):
	args = {"doc": frappe.as_json(fi.as_dict())}
	if seed:
		args["seed"] = seed
	res = fx.engine_call("arinox_final_inspection_api_pick", **args)["arinox_result"]["arinox_doc"]
	fi.set("cartons_picked", res["cartons_picked"])
	fi.draw_seed = res["draw_seed"]
	return res


def inspect(card, pl, **kw):
	fi = draft(card, pl, result=kw.pop("result", "Accepted"), **kw).insert()
	pick(fi)
	fi.save()
	fi.submit()
	return fi


@test("final")
def an_unconfirmed_aql_row_is_refused():
	card, pl = lot()
	fi = draft(card, pl, aql_plan="Garment AQL 2.5 / 4.0 Level II")           # a lot of 100 falls in a row QA has not confirmed
	true(throws(lambda: fi.insert(), "no confirmed row"))


@test("final")
def an_inspection_with_no_defects_is_accepted_and_the_list_points_at_it():
	card, pl = lot()
	fi = inspect(card, pl)
	true("-FI-" in fi.name, fi.name)
	eq((fi.sample_size, fi.major_re, fi.minor_re), (80, 4, 6))
	eq(len(fi.cartons_picked), fi.inspected_cartons)
	eq(frappe.db.get_value("Packing List", pl.name, "final_inspection"), fi.name)


@test("final")
def defects_that_reach_the_reject_number_fail_the_lot():
	card, pl = lot()
	major = frappe.db.get_value("Apparel Defect Code", {"severity": "Major"}, "name")
	fi = draft(card, pl, defects=[{"defect_code": major, "qty": 4}], result="Accepted")
	true(throws(lambda: fi.insert(), "fail the AQL plan"))                      # 4 majors reach the reject number of 4
	fi.result = "Rejected"
	fi.insert()
	eq(fi.computed_result, "Rejected")


@test("final")
def any_critical_defect_fails():
	card, pl = lot()
	critical = frappe.db.get_value("Apparel Defect Code", {"severity": "Critical"}, "name")
	fi = draft(card, pl, defects=[{"defect_code": critical, "qty": 1}]).insert()
	eq(fi.computed_result, "Rejected")


@test("final")
def a_failed_check_cannot_be_accepted_and_a_concession_needs_approval():
	card, pl = lot()
	fi = draft(card, pl, metal_detection_ok="No", result="Accepted")
	true(throws(lambda: fi.insert(), "cannot be Accepted"))
	fi.result = "Accepted with Concession"
	true(throws(lambda: fi.insert(), "buyer's approval"))
	fi.concession_ref = "Buyer email"
	fi.approved_by = "Buyer"
	fi.insert()


@test("final")
def cartons_must_be_drawn_before_submit():
	card, pl = lot()
	fi = draft(card, pl, result="Accepted").insert()
	true(throws(lambda: fi.submit(), "Draw the"))


@test("final")
def the_draw_is_repeatable_and_includes_the_tail_carton():
	card, pl = lot()
	fi = draft(card, pl).insert()
	a = pick(fi, seed=1234)
	b = pick(fi, seed=1234)
	eq(a["cartons_picked"], b["cartons_picked"])
	nos = {c["carton_no"] for c in a["cartons_picked"]}
	eq(len(nos), len(a["cartons_picked"]))
	tail_no = max(c.carton_to for c in pl.cartons)                              # the last carton is the mixed tail carton
	true(tail_no in nos, (tail_no, nos))


@test("final")
def a_small_share_packed_is_refused_for_a_final():
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24, quantities={"Navy|S": 40})
	fi = draft(card, pl)
	true(throws(lambda: fi.insert(), "of the order is packed"))
	pre = draft(card, pl, inspection_type="Pre-Final")
	pre.insert()                                                                 # an earlier look is allowed


@test("final")
def a_reinspection_names_what_it_follows_and_the_limit_needs_a_manager():
	card, pl = lot()
	again = draft(card, pl, inspection_type="Re-inspection")
	true(throws(lambda: again.insert(), "Name the inspection"))
	first = inspect(card, pl, result="Rejected")
	second = inspect(card, pl, inspection_type="Re-inspection", previous_inspection=first.name, result="Rejected")
	third = draft(card, pl, inspection_type="2nd Re-inspection", previous_inspection=second.name, result="Accepted")
	third.insert()                                                               # Administrator holds the manager role
	eq(third.docstatus, 0)
