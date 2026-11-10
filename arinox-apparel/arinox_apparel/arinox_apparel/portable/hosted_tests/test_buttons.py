import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_contract import BANDS


def finished_goods_warehouse():
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	frappe.db.set_single_value("Apparel Settings", "fg_warehouse", wh)
	return wh


def variant_contract():
	"""A signed contract on a template style with two colours/sizes, one line per PO."""
	finished_goods_warehouse()
	template, _variant = fx.variant_item("Navy", "M", code="HT-BTN-STYLE")
	for colour in ("Navy", "Black"):
		for size in ("S", "M"):
			fx.variant_item(colour, size, code="HT-BTN-STYLE")
	frappe.db.set_value("Company", fx.company(), "default_bank_account", None)
	d = fx.contract_fields(tolerance_bands=BANDS, incoterm=frappe.db.get_value("Incoterm", {}, "name"), port_of_loading="Cat Lai", payment_basis="Days after Receipt of Goods (ROG)",
						   payment_days=15, days_ex_factory_to_etd=7, transit_days=30)
	d["items"] = [{"style_item": template, "colour": "Navy", "qty": 300, "rate": 12.5, "buyer_po_code": "PO-A/1", "ex_factory_date": add_days(nowdate(), 60)},
				  {"style_item": template, "colour": "Black", "qty": 200, "rate": 12.5, "buyer_po_code": "PO-B/2", "ex_factory_date": add_days(nowdate(), 60)}]
	d["sizes"] = [{"style_item": template, "colour": "Navy", "size": "S", "qty": 100, "buyer_po_no": "PO-A/1"}, {"style_item": template, "colour": "Navy", "size": "M", "qty": 200, "buyer_po_no": "PO-A/1"},
				  {"style_item": template, "colour": "Black", "size": "S", "qty": 80, "buyer_po_no": "PO-B/2"}, {"style_item": template, "colour": "Black", "size": "M", "qty": 120, "buyer_po_no": "PO-B/2"}]
	sc = frappe.get_doc(d).insert()
	sc.submit()
	return sc, template


@test("buttons")
def make_sales_order_builds_one_row_per_size_with_the_variant_and_the_line_price():
	sc, template = variant_contract()
	so = fx.engine_call("arinox_sales_contract_make_sales_order", source_name=sc.name)["arinox_result"]
	rows = so["items"]
	eq(len(rows), 4)
	eq(sorted((r["apparel_colour"], r["apparel_size"], r["qty"], r["apparel_buyer_po"]) for r in rows),
	   [("Black", "M", 120, "PO-B/2"), ("Black", "S", 80, "PO-B/2"), ("Navy", "M", 200, "PO-A/1"), ("Navy", "S", 100, "PO-A/1")])
	true(all(r["rate"] == 12.5 for r in rows))
	true(all(r["item_code"] != template for r in rows), "rows carry variants, not the template")
	eq(so["apparel_sales_contract"], sc.name)
	doc = frappe.get_doc({k: v for k, v in so.items() if k not in ("name", "__islocal", "__unsaved")})
	doc.insert()                                                          # the unsaved order the form opens can be saved
	doc.submit()
	eq(frappe.db.get_value("Sales Contract", sc.name, "status"), "Ordered")


@test("buttons")
def make_sales_order_skips_a_size_nobody_orders_and_says_so_when_nothing_is_ordered():
	sc, template = variant_contract()
	sc.sizes[0].db_set("qty", 0)                                          # the buyer listed a size and ordered none of it
	so = fx.engine_call("arinox_sales_contract_make_sales_order", source_name=sc.name)["arinox_result"]
	eq(len(so["items"]), 3)
	true(all(r["qty"] > 0 for r in so["items"]), "no zero-quantity line is ever sent")
	for row in sc.sizes:
		row.db_set("qty", 0)
	true(throws(lambda: fx.engine_call("arinox_sales_contract_make_sales_order", source_name=sc.name), "nothing to order"))


@test("buttons")
def make_sales_order_asks_for_the_finished_goods_warehouse():
	sc, template = variant_contract()
	frappe.db.set_single_value("Apparel Settings", "fg_warehouse", None)
	frappe.db.set_single_value("Stock Settings", "default_warehouse", None)
	true(throws(lambda: fx.engine_call("arinox_sales_contract_make_sales_order", source_name=sc.name), "Finished Goods warehouse"))


@test("buttons")
def make_sales_order_needs_a_signed_contract_with_no_live_order():
	template, _v = fx.variant_item("Navy", "M", code="HT-BTN-STYLE2")
	frappe.db.set_value("Company", fx.company(), "default_bank_account", None)
	d = fx.contract_fields(tolerance_bands=BANDS, incoterm=frappe.db.get_value("Incoterm", {}, "name"), port_of_loading="Cat Lai", payment_basis="Days after Receipt of Goods (ROG)", payment_days=15)
	d["items"] = [{"style_item": template, "colour": "Navy", "qty": 10, "rate": 10, "ex_factory_date": add_days(nowdate(), 60)}]
	d["sizes"] = [{"style_item": template, "colour": "Navy", "size": "M", "qty": 10}]
	sc = frappe.get_doc(d).insert()
	true(throws(lambda: fx.engine_call("arinox_sales_contract_make_sales_order", source_name=sc.name), "Submit (sign)"))


@test("buttons")
def apply_template_returns_the_terms_and_bands():
	tpl = frappe.get_doc({"doctype": "Sales Contract Template", "template_name": "HT Template", "customer": fx.customer(), "enabled": 1, "is_default": 1, "incoterm": frappe.db.get_value("Incoterm", {}, "name"),
						  "port_of_loading": "Cat Lai", "payment_basis": "Days after Receipt of Goods (ROG)", "payment_days": 15, "tolerance_bands": BANDS}).insert()
	out = fx.engine_call("arinox_sales_contract_apply_template", doc=frappe.as_json({"contract_template": tpl.name}))["arinox_result"]["arinox_doc"]
	eq(out["port_of_loading"], "Cat Lai")
	eq(len(out["tolerance_bands"]), 4)


@test("buttons")
def the_production_card_helpers_list_styles_lines_and_a_summary():
	card = fx.card()
	styles = fx.engine_call("arinox_production_card_get_order_styles", sales_order=card.sales_order)["arinox_result"]
	eq(styles, [fx.item()])
	lines = fx.engine_call("arinox_production_card_get_card_lines", sales_order=card.sales_order, style_item=fx.item())["arinox_result"]
	eq([(l["colour"], l["size"], l["order_qty"]) for l in lines["lines"]], [("Navy", "M", 100), ("Navy", "S", 100)])
	fx.engine(action="post", card=card.name, rows='[{"stage":"CUT","colour":"Navy","size":"S","qty":10}]', source_doctype="T", source_name="T-1", check="0")
	summary = fx.engine_call("arinox_production_card_get_summary", name=card.name)["arinox_result"]
	cut = [r for r in summary["rows"] if r["size"] == "S"][0]
	eq(cut["CUT"], 10)
	eq(cut["planned_cut_qty"], 105)


@test("buttons")
def revise_gives_a_draft_that_points_at_the_old_card():
	card = fx.card()
	new = fx.engine_call("arinox_production_card_revise_production_card", source_name=card.name)["arinox_result"]
	eq(new["previous_card"], card.name)
	eq(new["revision_no"], 1)
	eq(new["status"], "Draft")
	true(all(not l.get("planned_cut_qty") for l in new["lines"]))
