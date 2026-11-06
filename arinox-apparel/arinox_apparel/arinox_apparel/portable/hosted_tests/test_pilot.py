import json

import frappe
from frappe.utils import nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, true
from arinox_apparel.portable.hosted_tests.prod_world import card, navy_fabrics, order, setup


def start():
    w = setup()
    so = order()
    frappe.db.set_single_value("Apparel Settings", "pilot_min_order_qty", 100)       # a pilot is asked for from 100 pieces
    c = card(so, navy_fabrics(w))
    return w, c, so


def post(c, rows, name):
    fx.engine(action="post", card=c.name, rows=json.dumps(rows), source_doctype="Production Adjustment", source_name=name, posting_date=nowdate(), check="0")


def pieces(c, cut=30, sewn=30, washed=0, tag="1"):
    post(c, [dict(stage="CUT", colour="Navy", size="S", qty=cut, purpose="Pilot"), dict(stage="SEW_IN", colour="Navy", size="S", qty=cut, purpose="Pilot"),
             dict(stage="SEW_OUT", colour="Navy", size="S", qty=sewn, purpose="Pilot")], "HT-PILOT-" + tag)
    if washed:
        post(c, [dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=washed, purpose="Pilot", process="Wash")], "HT-PILOT-W" + tag)


def run_doc(c, **kw):
    d = {"doctype": "Pilot Run", "production_card": c.name, "run_date": nowdate(), "colours": [{"colour": "Navy", "sizes_run": "S"}],
         "checks": [{"check_item": "Construction", "result": "Yes"}, {"check_item": "Packing", "result": "Yes"}], "decision": "Approved"}
    d.update(kw)
    return frappe.get_doc(d)


def pilot_blockers(w, so, colour="Navy", stage="bulk"):
    res = fx.engine(action="bulk_gate", sales_order=so.name, style=fx.item(), colour=colour, stage=stage)["arinox_result"]
    return [b for b in res["blockers"] if b.startswith("Pilot Run")]


@test("pilot")
def pieces_come_from_the_ledger_and_a_meeting_is_needed_when_required():
    w, c, so = start()
    pieces(c, cut=30, sewn=28, washed=27)
    post(c, [dict(stage="CUT_REJECT", colour="Navy", size="S", qty=2, purpose="Pilot")], "HT-PILOT-3")
    d = run_doc(c)
    d.insert()
    r = d.colours[0]
    eq((r.cut_qty, r.sewn_qty, r.washed_qty, r.rejected_qty), (28, 28, 27, 2))
    frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)
    raises(lambda: run_doc(c).insert(), "PP Meeting for this style has not been held")
    frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)
    raises(lambda: run_doc(c, colours=[{"colour": "Pink"}]).insert(), "is not on production card")
    raises(lambda: run_doc(c, colours=[{"colour": "Navy"}, {"colour": "Navy"}]).insert(), "appears twice")


@test("pilot")
def approval_rules_checks_pieces_wash_measurements_notes_and_role():
    w, c, so = start()
    d = run_doc(c)
    d.insert()
    raises(lambda: d.submit(), "No pilot pieces have been sewn")
    pieces(c)
    d = run_doc(c, checks=[{"check_item": "Construction"}])
    d.insert()
    raises(lambda: d.submit(), "Answer every check")
    d = run_doc(c, checks=[{"check_item": "Construction", "result": "No"}])
    d.insert()
    raises(lambda: d.submit(), "action taken")
    d.reload()
    d.checks[0].action_taken = "Pattern corrected"
    d.save()
    d.submit()
    eq(d.status, "Approved")
    d = run_doc(c, checks=[])
    d.insert()
    raises(lambda: d.submit(), "Record the pilot run checks")
    d = run_doc(c, measurements=[{"point_of_measure": "Chest", "size": "M", "spec": 50, "tol_plus": 1, "tol_minus": 1, "actual": 52}])
    d.insert()
    eq(d.measurements[0].in_tolerance, 0)
    raises(lambda: d.submit(), "out of tolerance")
    d.reload()
    d.measurement_note = "Buyer accepted +2 on chest"
    d.save()
    d.submit()
    d = run_doc(c, decision="Rejected")
    d.insert()
    raises(lambda: d.submit(), "Write the notes")
    d.reload()
    d.result_notes = "Collar wavy"
    d.save()
    d.submit()
    eq(d.status, "Rejected")
    d = run_doc(c, decision=None)
    d.insert()
    raises(lambda: d.submit(), "Choose the decision")
    d.reload()
    d.decision = "Approved"
    d.save()
    floor = fx.user("ht_floor@example.com", ["Apparel Production User"])
    try:
        frappe.set_user(floor)
        d.flags.ignore_permissions = True
        raises(lambda: d.submit(), "Only Apparel QA or a production manager")
    finally:
        frappe.set_user("Administrator")


@test("pilot")
def a_washed_style_needs_washed_pilot_pieces():
    w, c, so = start()
    frappe.db.set_value("Production Card", c.name, "is_washed", 1)
    pieces(c, washed=0)
    d = run_doc(c)
    d.insert()
    raises(lambda: d.submit(), "must come back from the wash")
    post(c, [dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=25, purpose="Pilot", process="Wash")], "HT-PILOT-4")
    d = run_doc(c)
    d.insert()
    d.submit()
    eq(d.status, "Approved")


@test("pilot")
def the_gate_asks_for_an_approved_pilot_per_colour_and_waiver_small_order_and_cancel_work():
    w, c, so = start()
    eq(len(pilot_blockers(w, so)), 1)                                          # none recorded
    pieces(c)
    rej = run_doc(c, decision="Rejected", result_notes="Bad")
    rej.insert()
    rej.submit()
    eq(len(pilot_blockers(w, so)), 1)                                          # rejected does not open the gate
    ok = run_doc(c)
    ok.insert()
    ok.submit()
    eq(pilot_blockers(w, so, "Navy"), [])
    eq(len(pilot_blockers(w, so, "Black")), 1)                                 # Navy's approval does not cover Black
    eq(pilot_blockers(w, so, "Black", "pilot"), [])                            # the pilot-stage gate never asks for a pilot
    ok.cancel()
    eq(len(pilot_blockers(w, so)), 1)                                          # cancel reopens the gate
    frappe.db.set_value("Production Card", c.name, {"pilot_waiver": 1, "pilot_waiver_reason": "Repeat style"})
    eq(pilot_blockers(w, so), [])
    frappe.db.set_value("Production Card", c.name, {"pilot_waiver": 0, "pilot_required": 0})
    eq(pilot_blockers(w, so), [])
