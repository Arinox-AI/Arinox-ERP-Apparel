import json

import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import call
from arinox_apparel.portable.hosted_tests.prod_world import card, lay, make_roll, navy_fabrics, order, plan, rolls_for, setup, stage_total, totals


def start():
    w = setup()
    so = order()
    return w, card(so, navy_fabrics(w)), so


def bin_at(item, wh):
    return frappe.utils.flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))


@test("cutting")
def issue_moves_accepted_rolls_to_cutting_and_refuses_the_rest():
    w, c, so = start()
    b = make_roll(w, 300, warehouse=w["store"])
    name = call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([{"batch_no": b, "qty": 300}]))
    true(name)
    eq(bin_at(w["navy_fabric"], w["wip"]) >= 300, True)
    c.reload()
    eq(c.fabrics[0].issued_m, 300)
    listing = call("arinox_cutting_get_issuable_rolls", card=c.name)
    true(b not in [r["batch"] for r in listing], "issued rolls leave the store listing")
    b2 = make_roll(w, 120, warehouse=w["store"])
    true(b2 in [r["batch"] for r in call("arinox_cutting_get_issuable_rolls", card=c.name)])
    bad = make_roll(w, 100, warehouse=w["store"], status="Rejected")
    raises(lambda: call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([{"batch_no": bad, "qty": 100}])), "Only accepted rolls")
    raises(lambda: call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([{"batch_no": b, "qty": 0}])), "above zero")                 # a roll with no metres is refused
    raises(lambda: call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([])), "at least one roll")                        # an empty issue is refused, not made
    other = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [{"idx": 1, "fabric_description": "_ATQ-OTHER, x", "colour": "Navy", "gsm": 145, "cuttable_width_cm": 132}]}))["made"][0]
    b3 = make_roll(w, 100, warehouse=w["store"], item=other)
    raises(lambda: call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([{"batch_no": b3, "qty": 100}])), "not a fabric of production card")


@test("cutting")
def a_plan_matches_the_card_and_a_variance_needs_a_manager():
    w, c, so = start()
    p = plan(w, c)
    eq((p.lays[0].pieces_per_ply, p.lays[0].planned_pieces), (7, 735))
    true(abs(p.marker_consumption - 1.2) < 0.0001 and abs(p.fr_consumption - 1.2) < 0.0001)
    eq(p.variance_pct, 0)
    true("S: plan 210, lays 210 (+0)" in p.size_summary, p.size_summary)
    eq(call("arinox_cut_plan_release", name=p.name, doc=json.dumps(p.as_dict(), default=str)), "Released")
    p2 = plan(w, c, marker=9.4)                                                 # 1.343 m per piece vs 1.2
    true(p2.variance_pct > 5)
    eq(call("arinox_cut_plan_release", name=p2.name, doc=json.dumps(p2.as_dict(), default=str)), "Pending Approval")
    raises(lambda: call("arinox_cut_plan_approve", name=p2.name), "Write the reason")
    eq(call("arinox_cut_plan_approve", name=p2.name, note="Buyer accepted the heavier marker"), "Released")
    true(frappe.db.get_value("Cut Plan", p2.name, "approved_by"))


@test("cutting")
def plan_flags_validation_and_reopen_rules():
    w, c, so = start()
    p = plan(w, c, ratios=(("S", 2), ("M", 3)))
    true("Size L is on the card but in no lay" in p.red_flags, p.red_flags)
    p = plan(w, c, plies=130)
    true("more than planned" in p.red_flags, p.red_flags)
    raises(lambda: plan(w, c, ratios=(("XXL", 1),)), "not on the production card")
    dup = frappe.get_doc({"doctype": "Cut Plan", "production_card": c.name, "colour": "Navy", "fabric_item": w["navy_fabric"],
                          "lays": [{"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}, {"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}],
                          "ratios": [{"lay_no": 1, "size": "S", "ratio": 1}]})
    raises(lambda: dup.insert(), "appears twice")
    wrong = frappe.get_doc({"doctype": "Cut Plan", "production_card": c.name, "colour": "Navy", "fabric_item": w["black_fabric"],
                            "lays": [{"lay_no": 1, "marker_length_m": 5, "planned_plies": 1}], "ratios": [{"lay_no": 1, "size": "S", "ratio": 1}]})
    raises(lambda: wrong.insert(), "is not a fabric of colour")
    p = plan(w, c)
    call("arinox_cut_plan_release", name=p.name, doc=json.dumps(p.as_dict(), default=str))
    lay(w, c, rolls_for(w), cut_plan=p.name, submit=True)
    raises(lambda: call("arinox_cut_plan_reopen", name=p.name), "already cut from this plan")


@test("cutting")
def suggest_rolls_groups_by_shade_and_uses_longest_first_and_reports_a_short_lay():
    w, c, so = start()
    a1, a2 = make_roll(w, 300, shade="Z1"), make_roll(w, 200, shade="Z1")
    make_roll(w, 500, shade="Z2")
    p = plan(w, c, plies=40, shade="Z1")                                        # 40 plies x 8.4 m = 336 m, shade Z1
    res = call("arinox_cut_plan_suggest_rolls", name=p.name)
    lay_ = res["lays"][0]
    eq([r["batch"] for r in lay_["rolls"]], [a1, a2])
    eq(lay_["rolls"][0]["plies"], 35)                                           # 294 m
    true(all(r["shade"] == "Z1" for r in lay_["rolls"]))
    eq(res["short"], [])
    make_roll(w, 100, shade="Z9")
    res = call("arinox_cut_plan_suggest_rolls", name=plan(w, c, plies=40, shade="Z9").name)
    eq(res["short"][0]["lay_no"], 1)


@test("cutting")
def submitting_a_lay_posts_pieces_numbers_plies_and_returns_remnants_and_cancel_reverses():
    w, c, so = start()
    before = bin_at(w["navy_fabric"], w["store"])
    lay_ = lay(w, c, rolls_for(w), submit=True)
    eq((lay_.total_plies, lay_.pieces_cut), (105, 735))
    true(abs(lay_.laid_m - 882.0) < 0.001 and abs(lay_.lay_consumption - 1.2) < 0.0001)
    t = totals(c)
    eq((t["Navy|S|CUT"], t["Navy|M|CUT"], t["Navy|L|CUT"]), (210, 315, 210))
    bundles = frappe.get_all("Cut Bundle", filters={"lay_report": lay_.name}, fields=["size", "body_no", "ply_from", "ply_to", "qty", "bundle_no", "is_short", "status"], order_by="bundle_no")
    eq(len(bundles), 42)                                                        # S 2 bodies x 6 + M 3 x 6 + L 2 x 6
    eq((min(b.ply_from for b in bundles), max(b.ply_to for b in bundles), sum(b.qty for b in bundles)), (1, 105, 735))
    true(all(b.status == "Cut" for b in bundles))
    last = [b for b in bundles if b.size == "S" and b.body_no == 1][-1]
    eq((last.ply_from, last.ply_to, last.qty, last.is_short), (101, 105, 5, 1))      # the short bundle
    eq(len({b.bundle_no for b in bundles}), 42)
    true(lay_.remnant_entry)
    true(abs(bin_at(w["navy_fabric"], w["store"]) - before - 18.0) < 0.01)          # each roll had 6 m left: returned as a remnant
    eq(frappe.db.get_value("Production Card", c.name, "status"), "In Cutting")
    remnant = lay_.remnant_entry
    lay_.cancel()
    eq(totals(c), {})
    eq(frappe.db.count("Cut Bundle", {"lay_report": lay_.name, "status": "Voided"}), 42)
    eq(frappe.db.get_value("Stock Entry", remnant, "docstatus"), 2)
    eq(frappe.db.get_value("Production Card", c.name, "status"), "Issued")


@test("cutting")
def roll_rules_end_bit_shade_width_accepted_issued_and_length():
    w, c, so = start()
    b = make_roll(w, 35 * 8.4 + 3)                                              # 3 m left, minimum is 5
    d = lay(w, c, [(b, 35)], sizes=(("S", 2),))
    eq(d.rolls[0].balance_returned_m, 0)
    true(abs(d.rolls[0].end_bit_m - 3.0) < 0.001)
    a, b2 = make_roll(w, 300, shade="A"), make_roll(w, 300, shade="B")
    raises(lambda: lay(w, c, [(a, 10), (b2, 10)]), "one shade band")
    a, b2 = make_roll(w, 300, width=132), make_roll(w, 300, width=135)
    raises(lambda: lay(w, c, [(a, 10), (b2, 10)]), "within")
    raises(lambda: lay(w, c, [(a, 10)], marker_width_cm=140), "narrower than")
    raises(lambda: lay(w, c, [(make_roll(w, 300, status="Hold"), 10)]), "Only accepted rolls")
    raises(lambda: lay(w, c, [(make_roll(w, 300, warehouse=w["store"]), 10)]), "Issue the roll to cutting")
    one = make_roll(w, 300)
    lay(w, c, [(one, 30)], submit=True)                                         # 252 m used, 48 m returned
    raises(lambda: lay(w, c, [(one, 30)], lay_no=2), "Issue the roll to cutting")
    other = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": [{"idx": 1, "fabric_description": "_ATQ-OTHER2, x", "colour": "Navy", "gsm": 145, "cuttable_width_cm": 132}]}))["made"][0]
    raises(lambda: lay(w, c, [(make_roll(w, 300, item=other), 10)]), "not %s" % w["navy_fabric"])


@test("cutting")
def the_bulk_gate_blocks_a_lay_unless_a_manager_overrides_with_a_reason():
    w, c, so = start()
    rolls = rolls_for(w)
    d = lay(w, c, rolls, gate_override=0, gate_override_reason=None)
    raises(lambda: d.submit(), "Cutting is blocked")
    raises(lambda: lay(w, c, rolls_for(w), gate_override_reason=""), "reason for the override")
    p = plan(w, c)
    raises(lambda: lay(w, c, rolls_for(w), cut_plan=p.name), "Release it before bulk cutting")
    call("arinox_cut_plan_release", name=p.name, doc=json.dumps(p.as_dict(), default=str))
    d = lay(w, c, rolls_for(w), cut_plan=p.name)
    eq(d.marker_ref, "M1")
    raises(lambda: lay(w, c, rolls_for(w), cut_plan=p.name, sizes=(("S", 3), ("M", 3), ("L", 2))), "the ratio is")
    d = lay(w, c, rolls_for(w), cut_plan=p.name, sizes=())                      # sizes come from the plan
    eq({s.size: s.ratio for s in d.sizes}, {"S": 2, "M": 3, "L": 2})
    raises(lambda: lay(w, c, rolls_for(w, plies=35), sizes=(("XXL", 1),)), "is not on production card")


@test("cutting")
def a_pilot_lay_is_tracked_apart_and_panel_rejects_post_cut_reject():
    w, c, so = start()
    b = make_roll(w, 35 * 8.4 + 6)
    lay(w, c, [(b, 3)], sizes=(("S", 1), ("M", 1)), purpose="Pilot", submit=True)
    eq(stage_total(c, "CUT", "Navy", "S", "Pilot"), 3)
    eq(stage_total(c, "CUT", "Navy", "S", "Bulk"), 0)
    rolls = rolls_for(w, plies=35)
    d = lay(w, c, rolls, sizes=(("S", 2),), panel_rejects=[{"size": "S", "qty": 4, "defect_code": "Cutting Damage", "fault_source": "Cutting"}], submit=True)
    eq(d.sizes[0].panels_rejected, 4)
    eq(stage_total(c, "CUT_REJECT", "Navy", "S"), 4)
    raises(lambda: lay(w, c, rolls_for(w, plies=35), sizes=(("S", 2),), lay_no=2, panel_rejects=[{"size": "M", "qty": 1, "defect_code": "Cutting Damage"}]), "not cut in this lay")


@test("cutting")
def cancel_is_blocked_once_a_bundle_left_cutting_and_ply_numbers_never_repeat():
    w, c, so = start()
    d = lay(w, c, rolls_for(w), submit=True)
    n = frappe.get_all("Cut Bundle", filters={"lay_report": d.name}, pluck="name")[0]
    frappe.db.set_value("Cut Bundle", n, "status", "Issued")
    raises(lambda: d.cancel(), "left the cutting room")
    w, c, so = start()
    first = lay(w, c, rolls_for(w, plies=70), sizes=(("S", 2),), submit=True)
    second = lay(w, c, [(make_roll(w, 35 * 8.4 + 6), 35)], sizes=(("M", 3),), lay_no=2, submit=True)
    s = frappe.db.sql("select max(ply_to) from `tabCut Bundle` where lay_report = %s", (first.name,))[0][0]
    m = frappe.db.sql("select min(ply_from) from `tabCut Bundle` where lay_report = %s", (second.name,))[0][0]
    eq((s, m), (70, 71))


@test("cutting")
def a_lining_lay_mirrors_the_shell_ply_numbers():
    w = setup()
    so = order()
    c = card(so, [{"colour": "Navy", "fabric_item": w["navy_fabric"], "material_role": "Shell", "consumption": 1.2, "consumption_uom": "Meter", "consumption_source": "Manual"},
                  {"colour": "Navy", "fabric_item": w["black_fabric"], "material_role": "Lining", "consumption": 0.5, "consumption_uom": "Meter", "consumption_source": "Manual"}])
    shell = lay(w, c, rolls_for(w, plies=35), sizes=(("S", 1),), submit=True)
    lr = make_roll(w, 35 * 3 + 6, item=w["black_fabric"])
    kw = dict(sizes=(("S", 1),), marker_length_m=3, fabric_item=w["black_fabric"], component="Lining", lay_no=2)
    raises(lambda: lay(w, c, [(lr, 35)], **kw), "must be paired with its shell lay")
    raises(lambda: lay(w, c, [(lr, 30)], paired_with=shell.name, **kw), "They must match")
    lining = lay(w, c, [(lr, 35)], paired_with=shell.name, submit=True, **kw)
    s_b = frappe.get_all("Cut Bundle", filters={"lay_report": shell.name}, fields=["kit_key", "ply_from", "ply_to"], order_by="bundle_no")
    l_b = frappe.get_all("Cut Bundle", filters={"lay_report": lining.name}, fields=["kit_key", "ply_from", "ply_to", "component"], order_by="bundle_no")
    eq([(b.kit_key, b.ply_from, b.ply_to) for b in s_b], [(b.kit_key, b.ply_from, b.ply_to) for b in l_b])
    true(all(b.component == "Lining" for b in l_b))
    eq(stage_total(c, "CUT", "Navy", "S"), 35)                                  # the lining lay adds no garments


def reject(w, c, n=4):
    lay(w, c, rolls_for(w, plies=35), sizes=(("S", 2),), panel_rejects=[{"size": "S", "qty": n, "defect_code": "Cutting Damage"}], submit=True)


def request(c, qty=3, **kw):
    d = frappe.get_doc(dict({"doctype": "Recut Request", "production_card": c.name, "colour": "Navy", "size": "S", "qty": qty, "reason": "Cutting Damage"}, **kw))
    d.insert()
    return d


@test("cutting")
def a_recut_is_limited_by_rejects_and_closes_the_loop():
    w, c, so = start()
    reject(w, c, 4)
    raises(lambda: request(c, 5), "Only 4")
    req = request(c, 3)
    req.submit()
    raises(lambda: request(c, 2), "Only 1")
    roll = make_roll(w, 40)
    raises(lambda: lay(w, c, [(roll, 3)], sizes=(("M", 1),), purpose="Re-cut", recut_request=req.name), "must cut only size")
    d = lay(w, c, [(roll, 3)], sizes=(("S", 1),), purpose="Re-cut", recut_request=req.name, marker_length_m=1.2, submit=True)
    eq(frappe.db.get_value("Recut Request", req.name, "status"), "Cut")
    eq(stage_total(c, "CUT", "Navy", "S", "Re-cut"), 3)
    d.cancel()
    eq(frappe.db.get_value("Recut Request", req.name, "status"), "Open")
    req.reload()
    req.cancel()
    eq(frappe.db.get_value("Recut Request", req.name, "status"), "Closed")


@test("cutting")
def a_different_shade_for_a_recut_needs_manager_approval():
    w, c, so = start()
    reject(w, c, 4)
    orig = frappe.get_all("Lay Report", filters={"production_card": c.name}, pluck="name")[0]
    other = make_roll(w, 40, shade="B")
    raises(lambda: request(c, 2, replaces_lay=orig, source_roll=other), "Cut from the same roll")
    d = request(c, 2, replaces_lay=orig, source_roll=other, different_roll_approved=1)
    eq(d.approved_by, frappe.session.user)
    n = frappe.get_all("Cut Bundle", filters={"production_card": c.name}, pluck="name")[0]
    b = frappe.get_doc("Cut Bundle", n)
    b.qty = b.qty + 1
    raises(lambda: b.save(), "bundle quantity cannot be changed")
