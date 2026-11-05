import json

import frappe
from frappe.utils import nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def total(card, stage, colour="Navy", size="S"):
	return frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card = %s and stage = %s and colour = %s and size = %s",
						 (card, stage, colour, size))[0][0]


def post(card, stage, qty, colour="Navy", size="S", check=1, **kw):
	rows = [dict(stage=stage, colour=colour, size=size, qty=qty, **kw)]
	return fx.engine(action="post", card=card, rows=json.dumps(rows), source_doctype="Test", source_name="T-1", posting_date=nowdate(), check=str(check))


@test("ledger")
def card_is_named_and_issued():
	c = fx.card()
	true(c.name.startswith("PC") or "." in c.name, c.name)
	eq(c.docstatus, 1)


@test("ledger")
def cut_is_capped_at_plan_plus_extra():
	c = fx.card()
	cap = c.lines[0].planned_cut_qty + 3        # plan + 3 extra pieces
	post(c.name, "CUT", cap)
	eq(total(c.name, "CUT"), cap)
	true(throws(lambda: post(c.name, "CUT", 1), "available"))


@test("ledger")
def sewing_input_cannot_exceed_good_cut():
	c = fx.card()
	post(c.name, "CUT", 40)
	post(c.name, "CUT_REJECT", 5)
	true(throws(lambda: post(c.name, "SEW_IN", 36), "35 available"))
	post(c.name, "SEW_IN", 35)
	eq(total(c.name, "SEW_IN"), 35)


@test("ledger")
def rows_of_one_document_count_together():
	c = fx.card()
	post(c.name, "CUT", 20)
	rows = [dict(stage="SEW_IN", colour="Navy", size="S", qty=12), dict(stage="SEW_IN", colour="Navy", size="S", qty=12)]
	true(throws(lambda: fx.engine(action="check", card=c.name, rows=json.dumps(rows)), "available"))


@test("ledger")
def override_skips_the_check():
	c = fx.card()
	post(c.name, "SEW_IN", 5, override=0, check=0)
	eq(total(c.name, "SEW_IN"), 5)


@test("ledger")
def card_status_follows_the_furthest_stage():
	c = fx.card()
	post(c.name, "CUT", 10)
	eq(frappe.db.get_value("Production Card", c.name, "status"), "In Cutting")
	post(c.name, "SEW_IN", 10)
	eq(frappe.db.get_value("Production Card", c.name, "status"), "In Sewing")


@test("ledger")
def unpost_removes_what_a_document_wrote():
	c = fx.card()
	post(c.name, "CUT", 10)
	fx.engine(action="unpost", source_doctype="Test", source_name="T-1")
	eq(total(c.name, "CUT"), 0)
	eq(frappe.db.get_value("Production Card", c.name, "status"), "Issued")


def adjustment(c, qty, stage="CUT", reason="recount", **kw):
	return frappe.get_doc({"doctype": "Production Adjustment", "production_card": c.name, "posting_date": nowdate(), "stage": stage,
						   "colour": "Navy", "size": "S", "qty": qty, "reason": reason, **kw})


@test("adjustment")
def adjustment_posts_on_submit_and_unposts_on_cancel():
	c = fx.card()
	a = adjustment(c, 7).insert()
	a.submit()
	eq(total(c.name, "CUT"), 7)
	a.cancel()
	eq(total(c.name, "CUT"), 0)


@test("adjustment")
def adjustment_needs_reason_quantity_and_a_line_on_the_card():
	c = fx.card()
	true(throws(lambda: adjustment(c, 5, reason="").insert(), "reason"))
	true(throws(lambda: adjustment(c, 0).insert(), "quantity"))
	a = adjustment(c, 5)
	a.size = "XL"
	true(throws(lambda: a.insert(), "not on production card"))


@test("adjustment")
def negative_adjustment_cannot_take_off_more_than_recorded():
	c = fx.card()
	adjustment(c, 4).insert().submit()
	a = adjustment(c, -5).insert()
	true(throws(lambda: a.submit(), "cannot take off"))
	b = adjustment(c, -3).insert()
	b.submit()
	eq(total(c.name, "CUT"), 1)
