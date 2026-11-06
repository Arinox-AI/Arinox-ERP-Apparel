import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import call
from arinox_apparel.portable.hosted_tests.prod_world import card, lay, navy_fabrics, order, rolls_for, setup, stage_total, totals
from arinox_apparel.portable.hosted_tests.test_allocation import floors

# four operations that add up to the C2027 sheet: 18.8 machine minutes + 5.6 manual minutes = 24.4
OPS = [{"seq": i + 1, "operation": "Op %s" % (i + 1), "part_group": "Body", "machine_type": "SNLS", "machine_sam": 4.7, "manual_sam": 1.4} for i in range(4)]


def start():
    """An issued card with Navy cut (105 plies S2 M3 L2 = 735 pieces) and the bulletins of the style cleared."""
    w = setup()
    so = order()
    c = card(so, navy_fabrics(w))
    f = floors()
    line = f["HT Factory A"][0]
    frappe.db.delete("Operation Bulletin", {"style_item": fx.item()})
    cut = lay(w, c, rolls_for(w), submit=True)
    return w, c, so, line, f


def ob(activate=True, **kw):
    d = {"doctype": "Operation Bulletin", "style_item": fx.item(), "operators": 28, "working_minutes": 480, "expected_efficiency_pct": 65, "operations": [dict(o) for o in OPS]}
    d.update(kw)
    doc = frappe.get_doc(d)
    doc.insert()
    if activate:
        call("arinox_operation_bulletin_activate", name=doc.name)
        doc.reload()
    return doc


def bundles(c, size="S", body=1, n=1, status=("Cut", "Back")):
    return frappe.get_all("Cut Bundle", filters={"production_card": c.name, "size": size, "body_no": body, "status": ["in", list(status)], "component": "Shell"},
                          fields=["name", "qty"], order_by="bundle_no", limit=n)


def load(c, line, bs, date=None, submit=True, **kw):
    d = {"doctype": "Line Input", "production_card": c.name, "line": line, "input_date": date or nowdate(), "bundles": [{"bundle": b.name if hasattr(b, "name") else b} for b in bs]}
    d.update(kw)
    doc = frappe.get_doc(d)
    doc.insert()
    if submit:
        doc.submit()
    return doc


def dlr(c, line, outputs, submit=True, **kw):
    d = {"doctype": "Daily Line Report", "report_date": nowdate(), "line": line, "operators_present": 28, "shift_minutes": 480,
         "outputs": [dict({"production_card": c.name, "colour": "Navy"}, **o) for o in outputs]}
    if "line_override" in kw:
        d["line"] = kw.pop("line_override")
    d.update(kw)
    doc = frappe.get_doc(d)
    doc.insert()
    if submit:
        doc.submit()
    return doc


@test("sewing")
def targets_match_the_company_sheet_and_activation_supersedes():
    w, c, so, line, f = start()
    b = ob()
    eq((b.total_sam, b.sewing_sam, b.manual_sam), (24.4, 18.8, 5.6))
    true(abs(b.target_per_day - 358.03) < 0.01 and abs(b.target_per_hour - 44.75) < 0.01, (b.target_per_day, b.target_per_hour))     # the sheet shows 37.69 (divides by 9.5 h)
    true(abs(b.pcs_per_machine - 12.7869) < 0.001, b.pcs_per_machine)     # stored to the field precision
    true(abs(b.pitch_time - 6.1) < 0.001, b.pitch_time)
    true(abs(b.operations[0].target_per_hr - 60 * 0.65 / 6.1) < 0.01, b.operations[0].target_per_hr)
    eq(b.status, "Active")
    second = ob(version=2)
    eq(frappe.db.get_value("Operation Bulletin", b.name, "status"), "Superseded")
    eq(frappe.db.get_value("Operation Bulletin", second.name, "status"), "Active")
    empty = ob(operations=[], activate=False)
    raises(lambda: call("arinox_operation_bulletin_activate", name=empty.name), "Add the operation times")
    ops = [dict(o) for o in OPS]
    ops[0].update(machine_sam=9.0, manual_sam=0)
    ops[1].update(machine_sam=1.0, manual_sam=0)
    flagged = ob(operations=ops, activate=False)
    eq((flagged.operations[0].pitch_flag, flagged.operations[1].pitch_flag), ("Above", "Below"))
    heading = ob(operations=[{"operation": "COLLAR"}] + [dict(o) for o in OPS], activate=False)
    eq((heading.operation_count, heading.total_sam), (4, 24.4))
    raises(lambda: ob(operators=0), "number of operators")
    raises(lambda: ob(operations=[dict(OPS[0], machine_sam=-1)]), "cannot be negative")


@test("sewing")
def a_line_input_posts_sew_in_marks_bundles_and_cancel_restores_unless_sewn():
    w, c, so, line, f = start()
    bs = bundles(c, "S", 1, 2)
    li = load(c, line, bs)
    eq(li.total_qty, sum(x.qty for x in bs))
    eq(stage_total(c, "SEW_IN", "Navy", "S"), li.total_qty)
    eq((frappe.db.get_value("Cut Bundle", bs[0].name, "status"), frappe.db.get_value("Cut Bundle", bs[0].name, "line")), ("Issued", line))
    eq(frappe.db.get_value("Production Card", c.name, "status"), "In Sewing")
    raises(lambda: load(c, line, bs[:1]), "only cut bundles")
    li.cancel()
    eq(frappe.db.get_value("Cut Bundle", bs[0].name, "status"), "Cut")
    eq(stage_total(c, "SEW_IN", "Navy", "S"), 0)
    li = load(c, line, bs[:1])
    frappe.db.set_value("Cut Bundle", bs[0].name, "sewn_qty", 5)
    raises(lambda: li.cancel(), "already have sewn output")


@test("sewing")
def bundle_rules_purpose_duplicates_before_sewing_process_kits_and_no_bundle_mode():
    w, c, so, line, f = start()
    frappe.db.set_single_value("Apparel Settings", "require_bundle_on_input", 0)
    d = frappe.get_doc({"doctype": "Line Input", "production_card": c.name, "line": line, "bundles": [{"colour": "Navy", "size": "M", "qty": 50}]})
    d.insert()
    d.submit()
    eq(stage_total(c, "SEW_IN", "Navy", "M"), 50)
    frappe.db.set_single_value("Apparel Settings", "require_bundle_on_input", 1)
    raises(lambda: frappe.get_doc({"doctype": "Line Input", "production_card": c.name, "line": line, "bundles": [{"colour": "Navy", "size": "S", "qty": 5}]}).insert(), "choose the bundle")
    b = bundles(c, "S", 1, 1)
    raises(lambda: load(c, line, b, purpose="Pilot"), "this input is Pilot")
    dup = frappe.get_doc({"doctype": "Line Input", "production_card": c.name, "line": line, "bundles": [{"bundle": bundles(c, "M", 1, 1)[0].name}] * 2})
    raises(lambda: dup.insert(), "appears twice")
    frappe.get_doc({"doctype": "Production Card Process", "parent": c.name, "parenttype": "Production Card", "parentfield": "processes", "subcontract_process": "Embroidery",
                    "position": "Before Sewing", "item_state": "Cut Panels", "idx": 1}).db_insert()
    raises(lambda: load(c, line, b), "must go to Embroidery")
    frappe.db.set_value("Cut Bundle", b[0].name, "status", "Back")
    fx.engine(action="post", card=c.name, rows=json.dumps([dict(stage="SC_OUT", colour="Navy", size="S", qty=b[0].qty, process="Embroidery"),
                                                           dict(stage="SC_BACK_GOOD", colour="Navy", size="S", qty=b[0].qty, process="Embroidery")]),
              source_doctype="Production Adjustment", source_name="HT-E1", posting_date=nowdate(), check="0")
    load(c, line, b)


@test("sewing")
def efficiency_and_target_follow_the_bulletin_and_the_learning_curve():
    w, c, so, line, f = start()
    ob()
    li = load(c, line, bundles(c, "S", 1, 6) + bundles(c, "M", 1, 6), date=add_days(nowdate(), -3))        # day 4 of the style on the line
    d = dlr(c, line, [{"size": "S", "qty": 100}, {"size": "M", "qty": 100}])
    eq(d.total_output, 200)
    true(abs(d.produced_minutes - 200 * 24.4) < 0.1 and abs(d.available_minutes - 28 * 480) < 0.1)
    true(abs(d.efficiency_pct - 200 * 24.4 / (28 * 480) * 100) < 0.1, d.efficiency_pct)
    eq(d.learning_day, 4)
    true(abs(d.learning_factor_pct - 92.31) < 0.01, d.learning_factor_pct)                                # day 4: 60 % planned efficiency against 65 %
    true(abs(d.target_qty - 358.03 * 0.9231) < 1, d.target_qty)
    true(abs(d.variance_to_target - (200 - d.target_qty)) < 0.2)
    eq(stage_total(c, "SEW_OUT", "Navy", "S"), 100)
    over = dlr(c, line, [{"size": "S", "qty": 3}], overtime_minutes=60, downtime_minutes=30, downtime_reason="Power")
    eq(over.available_minutes, 28 * (480 + 60 - 30))
    h = dlr(c, line, [{"size": "S", "qty": 1}], operators_present=21, helpers_present=7, submit=False)
    eq(h.available_minutes, 28 * 480)                                                                    # the sheet's 21 operators + 7 helpers
    raises(lambda: dlr(c, line, [{"size": "S", "qty": 10}], downtime_minutes=15, downtime_reason=""), "downtime reason")
    total_s = stage_total(c, "SEW_IN", "Navy", "S")
    raises(lambda: dlr(c, line, [{"size": "S", "qty": total_s + 1}]), "")


@test("sewing")
def the_first_day_on_a_line_is_scaled_by_the_learning_curve():
    w, c, so, line, f = start()
    ob()
    load(c, line, bundles(c, "S", 1, 6), date=nowdate())
    d = dlr(c, line, [{"size": "S", "qty": 60}], submit=False)
    eq(d.learning_day, 1)
    true(abs(d.target_qty - 358.03 * 0.5385) < 1, d.target_qty)


@test("sewing")
def bundle_completion_matching_and_missing_bulletin():
    w, c, so, line, f = start()
    ob()
    load(c, line, bundles(c, "S", 1, 6) + bundles(c, "M", 1, 6))
    b = frappe.get_all("Cut Bundle", filters={"production_card": c.name, "size": "S", "body_no": 1, "status": "Issued", "component": "Shell"}, fields=["name", "qty"], order_by="bundle_no", limit=1)[0]
    dlr(c, line, [{"size": "S", "qty": b.qty - 5, "bundle": b.name}])
    eq(frappe.db.get_value("Cut Bundle", b.name, "status"), "Issued")
    d2 = dlr(c, line, [{"size": "S", "qty": 5, "bundle": b.name}])
    eq(frappe.db.get_value("Cut Bundle", b.name, "status"), "Complete")
    raises(lambda: dlr(c, line, [{"size": "S", "qty": 1, "bundle": b.name}]), "only a bundle loaded on a line")       # nothing left on the bundle
    d2.cancel()
    eq((frappe.db.get_value("Cut Bundle", b.name, "status"), frappe.db.get_value("Cut Bundle", b.name, "sewn_qty")), ("Issued", b.qty - 5))
    raises(lambda: dlr(c, line, [{"size": "M", "qty": 5, "bundle": b.name}]), "is not Navy M")
    raises(lambda: dlr(c, line, [{"size": "S", "qty": 5, "bundle": b.name}], line_override=f["HT Factory A"][1]), "is on line")
    raises(lambda: dlr(c, line, [{"size": "S", "qty": 10}], operators_present=0), "operators present")
    raises(lambda: dlr(c, line, [{"size": "S", "qty": 0}]), "above zero")
    raises(lambda: dlr(c, line, [{"size": "XXL", "qty": 5}]), "is not on production card")
    raises(lambda: dlr(c, line, []), "Enter the output")
    frappe.db.delete("Operation Bulletin", {"style_item": fx.item()})
    d = dlr(c, line, [{"size": "S", "qty": 10}])
    eq((d.produced_minutes, d.target_qty), (0, 0))


def qc(c, line, submit=False, **kw):
    d = {"doctype": "Line QC Report", "audit_type": "End-line", "report_date": nowdate(), "line": line, "production_card": c.name,
         "hours": [{"hour_slot": "7.30-8.30", "checked": 70, "passed": 66}, {"hour_slot": "8.30-9.30", "checked": 70, "passed": 64}],
         "defects": [{"hour_slot": "7.30-8.30", "defect_code": "Puckering", "qty": 4}, {"hour_slot": "8.30-9.30", "defect_code": "Open Seam or Raw Edge", "qty": 3}]}
    d.update(kw)
    doc = frappe.get_doc(d)
    doc.insert()
    if submit:
        doc.submit()
    return doc


@test("sewing")
def line_qc_dhu_rft_dispositions_recut_and_traffic_lights():
    w, c, so, line, f = start()
    ob()
    load(c, line, bundles(c, "S", 1, 6))
    d = qc(c, line)
    eq((d.total_checked, d.total_passed, d.total_defects), (140, 130, 7))
    true(abs(d.dhu - 5.0) < 0.01 and abs(d.defect_pct - 7.14) < 0.01 and abs(d.rft_pct - 92.86) < 0.01, (d.dhu, d.defect_pct, d.rft_pct))
    raises(lambda: qc(c, line, hours=[{"hour_slot": "7.30-8.30", "checked": 10, "passed": 11}]), "passed cannot be more than checked")
    d = qc(c, line, dispositions=[{"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 3, "defect_code": "Holes", "replace": 1},
                                 {"colour": "Navy", "size": "S", "disposition": "Rework", "qty": 5, "defect_code": "Puckering"}], submit=True)
    eq(stage_total(c, "SEW_REJECT", "Navy", "S"), 3)
    req = frappe.get_all("Recut Request", filters={"production_card": c.name, "remarks": ["like", "%" + d.name + "%"]}, fields=["qty", "reason", "docstatus", "size"])
    eq([(r.qty, r.reason, r.docstatus, r.size) for r in req], [(3, "Holes", 0, "S")])           # a draft the cutting supervisor reviews
    d.cancel()
    eq(stage_total(c, "SEW_REJECT", "Navy", "S"), 0)
    raises(lambda: qc(c, line, dispositions=[{"colour": "Navy", "size": "S", "disposition": "B-Grade", "qty": 1}]), "B-grade is decided at finishing")
    raises(lambda: qc(c, line, dispositions=[{"colour": "Navy", "size": "S", "disposition": "Rework", "qty": 1, "defect_code": "Holes", "replace": 1}]), "only a rejected piece")
    raises(lambda: qc(c, line, dispositions=[{"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 1, "replace": 1}]), "choose the defect")
    raises(lambda: qc(c, line, dispositions=[{"colour": "Pink", "size": "S", "disposition": "Reject", "qty": 1}]), "is not on production card")
    t = qc(c, line, audit_type="Inline (Traffic Light)", traffic=[{"operator": "A", "round_no": 1, "pieces_checked": 5, "defects": 0}, {"operator": "B", "round_no": 1, "pieces_checked": 5, "defects": 1},
                                                                  {"operator": "C", "round_no": 1, "pieces_checked": 5, "defects": 3}])
    eq([x.light for x in t.traffic], ["Green", "Yellow", "Red"])


@test("sewing")
def finishing_posts_a_grade_b_grade_and_rejects_within_what_was_received():
    w, c, so, line, f = start()
    ob()
    load(c, line, bundles(c, "S", 1, 6))
    dlr(c, line, [{"size": "S", "qty": 100}])
    fx.engine(action="post", card=c.name, rows=json.dumps([dict(stage="FIN_IN", colour="Navy", size="S", qty=100)]), source_doctype="Production Adjustment", source_name="HT-F1",
              posting_date=nowdate(), check="0")
    raises(lambda: qc(c, line, audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 100, "passed": 94}], passes=[{"colour": "Navy", "size": "S", "qty": 90}], defects=[]),
           "must equal the pieces passed")
    qc(c, line, audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 100, "passed": 94}], passes=[{"colour": "Navy", "size": "S", "qty": 94}], defects=[],
       dispositions=[{"colour": "Navy", "size": "S", "disposition": "B-Grade", "qty": 4, "defect_code": "Stains"}, {"colour": "Navy", "size": "S", "disposition": "Reject", "qty": 2, "defect_code": "Holes"}],
       submit=True)
    eq((stage_total(c, "FIN_A", "Navy", "S"), stage_total(c, "FIN_B", "Navy", "S"), stage_total(c, "FIN_REJECT", "Navy", "S")), (94, 4, 2))
    raises(lambda: qc(c, line, audit_type="Finishing", hours=[{"hour_slot": "9", "checked": 10, "passed": 10}], passes=[{"colour": "Navy", "size": "S", "qty": 10}], defects=[], submit=True), "")


@test("sewing")
def a_finishing_receipt_posts_fin_in_within_the_route_and_a_vendor_return_names_the_vendor():
    w, c, so, line, f = start()
    ob()
    load(c, line, bundles(c, "S", 1, 6))
    dlr(c, line, [{"size": "S", "qty": 100}])
    r = frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "receipt_date": nowdate(), "line": line, "rows": [{"colour": "Navy", "size": "S", "qty": 60}]})
    r.insert()
    eq(r.total_qty, 60)
    r.submit()
    eq(stage_total(c, "FIN_IN", "Navy", "S"), 60)
    r.cancel()
    eq(stage_total(c, "FIN_IN", "Navy", "S"), 0)
    raises(lambda: frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "receipt_date": nowdate(), "rows": [{"colour": "Pink", "size": "S", "qty": 1}]}).insert(), "is not on production card")
    raises(lambda: frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "receipt_date": nowdate(), "source": "Subcontract Return", "rows": [{"colour": "Navy", "size": "S", "qty": 1}]}).insert(),
           "Name the vendor")
    raises(lambda: frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "receipt_date": nowdate(), "rows": []}).insert(), "Add the pieces")
    r2 = frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "receipt_date": nowdate(), "rows": [{"colour": "Navy", "size": "S", "qty": 500}]})
    r2.insert()
    raises(lambda: r2.submit(), "")                                                                       # more than sewing released
    nd = frappe.get_doc({"doctype": "Needle Detector Log", "check_date": nowdate(), "line": line, "result": "Fail"})
    raises(lambda: nd.insert(), "needs the action taken")
    nd = frappe.get_doc({"doctype": "Needle Detector Log", "check_date": nowdate(), "line": line, "result": "Fail", "action": "Re-scan", "rescan_done": 1})
    raises(lambda: nd.insert(), "how many garments")
