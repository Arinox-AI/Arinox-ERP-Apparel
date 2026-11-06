import json

import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, true
from arinox_apparel.portable.hosted_tests.mat_world import call
from arinox_apparel.portable.hosted_tests.prod_world import card, navy_fabrics, order, setup
from arinox_apparel.portable.hosted_tests.test_negotiation import submitted_cost_sheet


@test("agent")
def the_production_agent_endpoints_give_context_save_a_draft_and_report_status():
    w = setup()
    so = order()
    ctx = call("arinox_production_card_get_production_context", sales_order=so.name)
    eq(len(ctx["styles"]), 1)
    st = ctx["styles"][0]
    eq((st["style_item"], st["card"], len(st["lines"])), (fx.item(), None, 6))
    eq(sorted((l["colour"], l["size"], l["order_qty"]) for l in st["lines"])[0], ("Black", "L", 150))
    true(ctx["defaults"]["bundle_size"] >= 1)
    data = {"company": fx.company(), "customer": fx.customer(), "sales_order": so.name, "style_item": fx.item(), "lines": [{"colour": l["colour"], "size": l["size"]} for l in st["lines"]]}
    res = call("arinox_production_card_save_production_card", data=json.dumps(data))
    true(res["name"] and res["planned_cut_total"] > 0, res)
    eq(frappe.db.get_value("Production Card", res["name"], "docstatus"), 0)
    again = call("arinox_production_card_save_production_card", data=json.dumps({"name": res["name"], "remarks": "agent draft"}))
    eq(again["name"], res["name"])
    c = frappe.get_doc("Production Card", res["name"])
    c.submit()
    raises(lambda: call("arinox_production_card_save_production_card", data=json.dumps({"name": res["name"], "remarks": "x"})), "Only a draft")
    status = call("arinox_production_card_get_production_status", sales_order=so.name)
    eq((len(status), status[0]["card"], len(status[0]["rows"])), (1, c.name, 6))


@test("agent")
def the_costing_agent_endpoints_give_the_parameter_previous_costings_and_a_copyable_sheet():
    cs = submitted_cost_sheet()
    ctx = call("arinox_cost_sheet_get_costing_context", customer=fx.customer(), product_type=fx.PRODUCT_TYPE, style_no=cs.style_no, currency="USD")
    true(ctx["costing_parameter"] and ctx["cost_heads"], "parameter and cost heads")
    eq(ctx["margin_floor_pct"], 10)
    eq([p["name"] for p in ctx["previous_costings"]][:1], [cs.name])
    true(ctx["previous_costings"][0]["same_style"])
    prev = call("arinox_cost_sheet_get_previous_costing", cost_sheet=cs.name)
    eq(len(prev["materials"]), len(cs.materials))
    true(all(c["source"] == "Previous Costing" for c in prev["charges"]) and "name" not in prev["materials"][0], prev["charges"][:1])
    eq(prev["sam"], cs.sam)
