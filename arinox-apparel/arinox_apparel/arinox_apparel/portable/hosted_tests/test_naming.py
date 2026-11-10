import re

import frappe
from frappe.utils import getdate, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, true


@test("naming")
def contract_number_has_prefix_year_month_and_counter():
	frappe.db.set_value("Company", fx.company(), "apparel_contract_prefix", None)
	sc = frappe.get_doc(fx.contract_fields()).insert()
	d = getdate(nowdate())
	yy, mm = str(d.year)[2:], ("0" + str(d.month))[-2:]
	prefix = frappe.db.get_single_value("Apparel Settings", "contract_prefix") or "SC"
	frappe.db.set_value("Company", fx.company(), "apparel_contract_prefix", None)
	true(re.fullmatch(rf"{prefix}{yy}\.{mm}\.\d{{3,}}", sc.name), sc.name)


@test("naming")
def contract_counter_never_repeats():
	a = frappe.get_doc(fx.contract_fields()).insert().name
	b = frappe.get_doc(fx.contract_fields()).insert().name
	true(a != b and int(b[-3:]) == int(a[-3:]) + 1, f"{a} {b}")


@test("naming")
def company_prefix_is_used():
	frappe.db.set_value("Company", fx.company(), "apparel_contract_prefix", "CTXGVN")
	sc = frappe.get_doc(fx.contract_fields()).insert()
	true(sc.name.startswith("CTXGVN"), sc.name)
