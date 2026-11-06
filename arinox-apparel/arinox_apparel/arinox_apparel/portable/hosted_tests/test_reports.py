import json

import frappe
from frappe.desk.query_report import run as run_report
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, true
from arinox_apparel.portable.hosted_tests.mat_world import call, fr, make_pos, received_fabric, tr, trim_item, world
from arinox_apparel.portable.hosted_tests import prod_world as pw
from arinox_apparel.portable.hosted_tests.test_inspect import make_fi, settings_ok
from arinox_apparel.portable.hosted_tests.test_samples import sample


def rows_of(res):
    return res["result"]


@test("reports")
def fabric_consumption_reconciles_issue_laid_cut_and_remnants():
    w = pw.setup()
    so = pw.order()
    c = pw.card(so, pw.navy_fabrics(w))
    rolls = []
    for i in range(3):
        b = pw.make_roll(w, 35 * 8.4 + 6, warehouse=w["store"])
        call("arinox_cutting_issue_fabric", card=c.name, rolls=json.dumps([{"batch_no": b, "qty": 35 * 8.4 + 6}]))
        rolls.append((b, 35))
    pw.lay(w, c, rolls, marker_efficiency_pct=80, submit=True)
    res = run_report("Fabric Consumption", filters={"production_card": c.name}, ignore_prepared_report=True)
    row = rows_of(res)[0]
    eq((row["issued_m"], row["returned_m"]), (900.0, 18.0))
    true(abs(row["laid_m"] - 882.0) < 0.01 and row["good_cut"] == 735, row)
    true(abs(row["lay_consumption"] - 1.2) < 0.0001, row["lay_consumption"])
    true(abs(row["actual_consumption"] - (900 - 18) / 735) < 0.0001, row["actual_consumption"])    # 1.2: nothing lost beyond the remnants
    true(abs(row["variance_pct"]) < 0.001 and abs(row["marker_efficiency"] - 80) < 0.001, row)
    true(abs(row["required_m"] - 735 * 1.2) < 0.01, row["required_m"])


@test("reports")
def material_status_and_running_stock_follow_the_purchase_chain():
    settings_ok()
    w = world()
    f = fr(w, colours=("Navy",))
    f.insert()
    f.submit()
    rows = rows_of(run_report("Material Status", filters={"sales_order": w["so"].name}, ignore_prepared_report=True))
    eq([(r["status"], r["type"], r["net"]) for r in rows][0][:2], ("Requested", "FR"))
    f2, po, pr = received_fabric(w)
    rows = rows_of(run_report("Material Status", filters={"sales_order": w["so"].name}, ignore_prepared_report=True))
    mine = [r for r in rows if r["requisition"] == f2.name][0]
    eq((mine["status"], mine["received"], mine["in_inspection"]), ("In House - QC Pending", 882, 882))
    true(mine["po"], "the purchase order is named")
    fi = make_fi(pr, inspect=10)
    fi.insert()
    fi.submit()
    rows = rows_of(run_report("Material Status", filters={"sales_order": w["so"].name, "status": "Accepted"}, ignore_prepared_report=True))
    true([r for r in rows if r["requisition"] == f2.name], "accepted after the inspection")
    true(not [r for r in rows if r["requisition"] == f.name], "the status filter works")
    stock = rows_of(run_report("Running Fabric Stock", filters={"sales_order": w["so"].name}, ignore_prepared_report=True))
    row = [r for r in stock if r["po"] == po.name][0]
    eq((row["received"], row["issued"], row["balance"]), (882, 0, 882))
    true(abs(row["over_short"]) < 0.01, row)


@test("reports")
def freight_allocation_shares_a_shipment_cost_over_its_contracts():
    from arinox_apparel.portable.hosted_tests.test_shipment import forwarder_bill, ready

    card, pl, sh = ready()
    forwarder_bill(sh.name, 1200)
    rows = rows_of(run_report("Freight Allocation", filters={"shipment": sh.name}, ignore_prepared_report=True))
    eq(len(rows), 1)
    eq((rows[0]["shipment"], rows[0]["basis"], rows[0]["share_pct"], rows[0]["cost"], rows[0]["actual"]), (sh.name, "CBM", 100.0, 1200, 1200))


@test("reports")
def the_sample_approval_tracker_shows_each_gating_type_per_colour_and_the_gate():
    from arinox_apparel.portable.hosted_tests.test_gate import gate_order

    so, template, navy, black = gate_order()
    sample(so, "Lab Dip", colour="Navy", style_item=template).insert()
    sample(so, "Fit", decision="Rejected", style_item=template, comments=[{"round_no": 1, "comment": "Too tight"}]).insert()
    res = run_report("Sample Approval Tracker", filters={"sales_order": so.name}, ignore_prepared_report=True)
    rows = rows_of(res)
    by = {r["colour"]: r for r in rows}
    eq(sorted(by), ["Black", "Navy"])
    eq((by["Navy"]["t_lab_dip"], by["Black"]["t_lab_dip"]), ("Approved", "Missing"))      # lab dip is per colour
    eq((by["Navy"]["t_fit"], by["Navy"]["gate"]), ("Rejected", "Blocked"))
    eq(len(rows_of(run_report("Sample Approval Tracker", filters={"sales_order": so.name, "only_blocked": 1}, ignore_prepared_report=True))), 2)


@test("reports")
def the_two_card_queries_count_overdue_fabric_lines_and_trim_lines_on_hold():
    w = world()
    start_fabric = rows_of(run_report("Fabric Overdue Lines", ignore_prepared_report=True))[0][0] if isinstance(rows_of(run_report("Fabric Overdue Lines", ignore_prepared_report=True))[0], (list, tuple)) \
        else rows_of(run_report("Fabric Overdue Lines", ignore_prepared_report=True))[0]["lines"]
    f = fr(w, colours=("Navy",))
    f.insert()
    f.submit()
    frappe.db.set_value("Fabric Requisition Item", {"parent": f.name}, "required_by", add_days(nowdate(), -3))
    res = rows_of(run_report("Fabric Overdue Lines", ignore_prepared_report=True))[0]
    now = res[0] if isinstance(res, (list, tuple)) else res["lines"]
    eq(now, start_fabric + 1)
    frappe.db.delete("Sample Approval", {"sample_type": "Bulk Trim", "style_item": w["template"]})
    label = trim_item("HT-LBL-CARD", "Main label", "Woven Label")
    t = tr(w, [{"trim_category": "Woven Label", "trim_item": label, "garment_qty": 100, "qty_per_garment": 1}])
    t.insert()
    t.submit()
    res = rows_of(run_report("Trim Lines On Hold Count", ignore_prepared_report=True))[0]
    held = res[0] if isinstance(res, (list, tuple)) else res["lines"]
    true(held >= 1, held)
    cards = frappe.get_all("Number Card", filters={"name": ["in", ["Fabric Overdue", "TR Lines On Hold"]]}, fields=["name", "type", "report_name", "report_field", "report_function"])
    eq(sorted((c.name, c.type, c.report_name, c.report_field, c.report_function) for c in cards),
       [("Fabric Overdue", "Report", "Fabric Overdue Lines", "lines", "Sum"), ("TR Lines On Hold", "Report", "Trim Lines On Hold Count", "lines", "Sum")])
