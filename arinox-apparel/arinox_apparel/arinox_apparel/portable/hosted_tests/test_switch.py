import frappe

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_contract import contract


@test("switch")
def the_kill_switch_turns_the_rules_off_and_on_but_keeps_naming():
	frappe.db.set_single_value("Apparel Settings", "max_skus_per_contract", 1)
	two = contract()
	two.append("items", {"style_item": fx.item(), "colour": "Black", "qty": 10, "rate": 10})
	true(throws(lambda: two.insert(), "maximum is 1"))                 # a rule that lives only in a script
	status = fx.engine_call("arinox_scripts_switch", state="status")["arinox_result"]
	true(status["rule_scripts"] > 40 and status["off"] == 0, status)
	try:
		off = fx.engine_call("arinox_scripts_switch", state="off")["arinox_result"]
		eq(off["on"], 0)
		again = contract()
		again.append("items", {"style_item": fx.item(), "colour": "Black", "qty": 10, "rate": 10})
		again.insert()                                                  # the rule is off, naming still works
		true(again.name.startswith("CTXGVN") or again.name.startswith("SC"), again.name)
	finally:
		fx.engine_call("arinox_scripts_switch", state="on")
	back = fx.engine_call("arinox_scripts_switch", state="status")["arinox_result"]
	eq(back["off"], 0)
	third = contract()
	third.append("items", {"style_item": fx.item(), "colour": "Black", "qty": 10, "rate": 10})
	true(throws(lambda: third.insert(), "maximum is 1"))               # and it enforces again
