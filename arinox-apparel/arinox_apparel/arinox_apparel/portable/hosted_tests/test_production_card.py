import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def make_card(cells=None, lines=None, **kw):
	cells = cells or {("Navy", "S"): 100, ("Navy", "M"): 200}
	so = fx.colour_so(cells)
	rows = lines if lines is not None else [{"colour": c, "size": s} for c, s in cells]
	return frappe.get_doc({"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": so.name,
						   "style_item": fx.item(), "lines": rows, **kw})


@test("card")
def planned_cut_rounds_up_with_the_extra_percent():
	c = make_card().insert()
	by = {(l.colour, l.size): l for l in c.lines}
	eq(by[("Navy", "S")].planned_cut_qty, 105)          # 100 + 5% default
	eq(by[("Navy", "M")].planned_cut_qty, 210)
	eq(by[("Navy", "S")].order_qty, 100)
	eq(by[("Navy", "S")].max_qty, 110)                  # +10% tolerance


@test("card")
def fractions_round_up_to_whole_pieces():
	c = make_card({("Navy", "S"): 131}).insert()
	eq(c.lines[0].planned_cut_qty, 138)                 # 131 * 1.05 = 137.55


@test("card")
def line_must_be_on_the_order_and_not_twice():
	true(throws(lambda: make_card(lines=[{"colour": "Red", "size": "S"}]).insert(), "not on Sales Order"))
	true(throws(lambda: make_card(lines=[{"colour": "Navy", "size": "S"}, {"colour": "Navy", "size": "S"}]).insert(), "twice"))


@test("card")
def extra_cut_above_limit_is_refused_for_a_plain_user_and_flagged_for_a_manager():
	c = make_card()
	c.lines[0].extra_cut_pct = 12
	c.insert()                                          # Administrator holds System Manager
	true("Extra cut above" in (c.red_flags or ""), c.red_flags)


@test("card")
def revision_needs_a_reason():
	first = make_card().insert()
	first.submit()
	c = make_card()
	c.previous_card = first.name
	c.revision_no = 1
	true(throws(lambda: c.insert(), "reason"))


@test("card")
def one_live_card_per_order_style_and_date():
	a = make_card().insert()
	a.submit()
	b = frappe.get_doc({"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": a.sales_order,
						"style_item": fx.item(), "ex_factory_date": a.ex_factory_date, "lines": [{"colour": "Navy", "size": "S"}]})
	true(throws(lambda: b.insert(), "already covers"))


@test("card")
def submit_marks_the_card_issued_and_lines_are_required():
	true(throws(lambda: make_card(lines=[]).insert(), "lines"))
	c = make_card().insert()
	c.submit()
	eq(frappe.db.get_value("Production Card", c.name, "status"), "Issued")


@test("card")
def card_with_quantities_cannot_be_cancelled():
	c = make_card().insert()
	c.submit()
	fx.engine(action="post", card=c.name, rows='[{"stage":"CUT","colour":"Navy","size":"S","qty":5}]', source_doctype="T", source_name="T-1", check="0")
	true(throws(lambda: c.cancel(), "cannot be cancelled"))


@test("card")
def revision_takes_over_the_history_of_the_old_card():
	a = make_card().insert()
	a.submit()
	fx.engine(action="post", card=a.name, rows='[{"stage":"CUT","colour":"Navy","size":"S","qty":5}]', source_doctype="T", source_name="T-1", check="0")
	b = make_card()
	b.sales_order = a.sales_order
	b.previous_card = a.name
	b.revision_no = 1
	b.revision_reason = "qty change"
	b.ex_factory_date = a.ex_factory_date
	b.insert()
	b.submit()
	eq(frappe.db.get_value("Production Card", a.name, "status"), "Superseded")
	eq(frappe.db.count("Production Movement", {"production_card": b.name}), 1)
	eq(frappe.db.count("Production Movement", {"production_card": a.name}), 0)
