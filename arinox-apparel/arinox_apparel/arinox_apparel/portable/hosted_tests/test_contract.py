import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true

BANDS = [{"from_qty": 0, "to_qty": 500, "tolerance_pct": 15}, {"from_qty": 501, "to_qty": 800, "tolerance_pct": 10},
		 {"from_qty": 801, "to_qty": 1600, "tolerance_pct": 7.5}, {"from_qty": 1601, "to_qty": 3000, "tolerance_pct": 5}]


def contract(qty=700, bands=BANDS, **kw):
	frappe.db.set_value("Company", fx.company(), "default_bank_account", None)     # the setup wizard named one that was never created
	d = fx.contract_fields(tolerance_bands=bands, incoterm=frappe.db.get_value("Incoterm", {}, "name"), port_of_loading="Cat Lai",
						   payment_basis="Days after Receipt of Goods (ROG)", payment_days=15, days_ex_factory_to_etd=7, transit_days=30,
						   sizes=[{"style_item": fx.item(), "colour": "Navy", "size": "S", "qty": qty}])
	d.update(kw)
	d["items"][0]["qty"] = qty
	return frappe.get_doc(d)


@test("contract")
def band_sets_the_tolerance_and_dates_follow_the_terms():
	sc = contract(700).insert()
	line = sc.items[0]
	eq(line.tolerance_pct, 10)
	eq(str(line.etd), add_days(line.ex_factory_date, 7))
	eq(str(line.in_warehouse_date), add_days(line.etd, 30))
	eq(sc.total_qty, 700)
	eq(sc.total_amount, 7000)


@test("contract")
def overlapping_bands_are_refused():
	bands = [{"from_qty": 0, "to_qty": 600, "tolerance_pct": 15}, {"from_qty": 500, "to_qty": 800, "tolerance_pct": 10}]
	true(throws(lambda: contract(bands=bands).insert(), "overlap"))


@test("contract")
def one_line_per_style_colour_and_po():
	sc = contract()
	sc.append("items", {"style_item": fx.item(), "colour": "navy", "qty": 10, "rate": 10})
	true(throws(lambda: sc.insert(), "already on this contract"))


@test("contract")
def the_same_style_and_colour_may_repeat_on_different_pos():
	"""A real contract: several lines, same style and colour, one per buyer PO."""
	sc = contract(300)
	sc.items[0].buyer_po_code = "PO-A/1"
	sc.sizes[0].buyer_po_no = "PO-A/1"
	sc.append("items", {"style_item": fx.item(), "colour": "Navy", "qty": 200, "rate": 10, "buyer_po_code": "PO-B/2", "ex_factory_date": add_days(nowdate(), 60)})
	sc.append("sizes", {"style_item": fx.item(), "colour": "Navy", "size": "S", "qty": 200, "buyer_po_no": "PO-B/2"})
	sc.insert()
	sc.submit()                                                # sizes add up per PO line, not per style and colour
	eq(len(sc.items), 2)


@test("contract")
def too_many_skus_are_refused():
	frappe.db.set_single_value("Apparel Settings", "max_skus_per_contract", 1)
	sc = contract()
	sc.append("items", {"style_item": fx.item(), "colour": "Black", "qty": 10, "rate": 10})
	true(throws(lambda: sc.insert(), "maximum is 1"))


@test("contract")
def signing_needs_the_size_breakdown_to_match():
	sc = contract(700).insert()
	sc.sizes[0].qty = 600
	sc.save()
	true(throws(lambda: sc.submit(), "size breakdown totals 600"))


@test("contract")
def a_complete_contract_signs():
	sc = contract(700).insert()
	sc.submit()
	eq(frappe.db.get_value("Sales Contract", sc.name, "status"), "Signed")


@test("contract")
def a_placeholder_blocks_signing():
	sc = contract(700, buyer_po_no="TBA").insert()
	true(throws(lambda: sc.submit(), "placeholder"))


@test("contract")
def payment_terms_are_required_to_sign():
	sc = contract(700, payment_basis=None, payment_days=0).insert()
	true(throws(lambda: sc.submit(), "Payment terms"))


@test("contract")
def a_contract_with_an_order_cannot_be_cancelled_first():
	sc = contract(700).insert()
	sc.submit()
	so = fx.sales_order()
	frappe.db.set_value("Sales Contract", sc.name, "sales_order", so.name)
	sc.reload()
	true(throws(lambda: sc.cancel(), "Cancel Sales Order"))


@test("contract")
def shipping_marks_may_stay_tba_but_other_placeholders_still_block():
	sc = contract(700, shipping_marks="TBA").insert()
	sc.submit()                                                # the marks are advised at booking
	other = contract(700, port_of_discharge="TBA").insert()
	true(throws(lambda: other.submit(), "placeholder"))


@test("contract")
def a_size_row_without_a_po_is_refused_when_several_lines_share_the_style_and_colour():
	sc = contract(300)
	sc.items[0].buyer_po_code = "PO-A/1"
	sc.append("items", {"style_item": fx.item(), "colour": "Navy", "qty": 200, "rate": 10, "buyer_po_code": "PO-B/2", "ex_factory_date": add_days(nowdate(), 60)})
	sc.sizes[0].buyer_po_no = ""                               # which line is this size for?
	true(throws(lambda: sc.insert(), "several lines"))
