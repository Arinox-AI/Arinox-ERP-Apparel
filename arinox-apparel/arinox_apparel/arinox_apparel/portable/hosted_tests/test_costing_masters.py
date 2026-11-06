import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.test_contract import BANDS
from arinox_apparel.portable.hosted_tests.test_negotiation import quotation_of, submitted_cost_sheet
from arinox_apparel.portable.hosted_tests.test_tech_pack import tech_pack


@test("costing_masters")
def profit_must_be_a_percentage_and_scope_only_applies_to_material_heads():
	head = frappe.get_doc({"doctype": "Cost Head", "head_name": "HT Profit", "head_group": "Profit", "calc_type": "Per Piece", "sequence": 990, "enabled": 1})
	true(throws(lambda: head.insert(), "Profit must be a percentage"))
	head.calc_type = "Percent of Subtotal"
	head.material_scope = "Fabric"
	head.insert()
	eq(head.material_scope, None)                      # the scope only makes sense for heads priced from materials
	mat = frappe.get_doc({"doctype": "Cost Head", "head_name": "HT Cloth", "head_group": "Material", "calc_type": "From Materials", "material_scope": "Fabric", "sequence": 991,
						  "enabled": 1}).insert()
	eq(mat.material_scope, "Fabric")


@test("costing_masters")
def a_head_used_by_an_enabled_parameter_cannot_be_disabled():
	param = fx.costing_parameter()
	used = frappe.db.get_value("Costing Parameter Rate", {"parent": param}, "cost_head")
	head = frappe.get_doc("Cost Head", used)
	head.enabled = 0
	true(throws(lambda: head.save(), "is used by enabled Costing Parameter"))


@test("costing_masters")
def a_costing_parameter_checks_dates_rates_title_and_overlap():
	cust = fx.customer("HT Buyer 3")
	heads = frappe.get_all("Cost Head", filters={"calc_type": ["!=", "From Materials"], "enabled": 1}, pluck="name", limit=2)
	materials_head = frappe.db.get_value("Cost Head", {"calc_type": "From Materials"}, "name")

	def param(**kw):
		d = {"doctype": "Costing Parameter", "customer": cust, "product_type": fx.PRODUCT_TYPE, "currency": "USD", "effective_from": "2026-01-01", "margin_floor_pct": 10,
			 "rates": [{"cost_head": heads[0], "rate": 2}]}
		d.update(kw)
		return frappe.get_doc(d)

	true(throws(lambda: param(effective_to="2025-12-31").insert(), "Effective To is before"))
	true(throws(lambda: param(rates=[{"cost_head": heads[0], "rate": 1}, {"cost_head": heads[0], "rate": 2}]).insert(), "appears twice"))
	if materials_head:
		true(throws(lambda: param(rates=[{"cost_head": materials_head, "rate": 1}]).insert(), "priced from materials"))
	p = param(effective_to="2026-06-30", rates=[{"cost_head": heads[0], "rate": 5, "not_applicable": 1}]).insert()
	eq((p.title, p.rates[0].rate), ("HT Buyer 3 · %s · USD" % fx.PRODUCT_TYPE, 0))      # not applicable zeroes the rate
	true(throws(lambda: param(effective_from="2026-06-01", effective_to="2026-12-31").insert(), "Overlaps"))
	param(effective_from="2026-07-01").insert()                                           # starts after the first one ends
	param(effective_from="2026-06-01", enabled=0).insert()                                # a disabled one never overlaps


@test("costing_masters")
def make_sales_contract_from_a_quotation_prefills_lines_sizes_and_terms():
	cust = fx.customer()
	frappe.get_doc({"doctype": "Sales Contract Template", "template_name": "HT QC Template", "customer": cust, "enabled": 1, "is_default": 1,
					"incoterm": frappe.db.get_value("Incoterm", {}, "name"), "port_of_loading": "Cat Lai", "payment_basis": "Days after Receipt of Goods (ROG)",
					"payment_days": 15, "tolerance_bands": BANDS}).insert()
	tp = tech_pack("HT-QC-1", colours=("Navy", "Black"), sizes=("S", "M"))
	frappe.db.set_single_value("Apparel Settings", "style_item_group", frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
	item = fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp.name)["arinox_result"]
	cs = submitted_cost_sheet(style_no="HT-QC-1", tech_pack=tp.name, style_item=item)
	q = quotation_of(cs)
	q.insert()
	true(throws(lambda: fx.engine_call("arinox_sales_contract_make_sales_contract", source_name=q.name), "Submit the Quotation first"))
	q.submit()
	sc = fx.engine_call("arinox_sales_contract_make_sales_contract", source_name=q.name)["arinox_result"]
	eq((sc["customer"], sc["quotation"], sc["currency"], sc["contract_template"]), (cust, q.name, "USD", "HT QC Template"))
	eq((sc["port_of_loading"], sc["payment_basis"], sc["payment_days"], len(sc["tolerance_bands"])), ("Cat Lai", "Days after Receipt of Goods (ROG)", 15, 4))
	eq(sorted((i["colour"], i["style_item"], i["rate"], i["tech_pack"]) for i in sc["items"]), [("Black", item, q.items[0].rate, tp.name), ("Navy", item, q.items[0].rate, tp.name)])
	eq(sorted((s["colour"], s["size"], s["qty"]) for s in sc["sizes"]), [("Black", "M", 0), ("Black", "S", 0), ("Navy", "M", 0), ("Navy", "S", 0)])


@test("costing_masters")
def make_sales_contract_needs_a_customer_quotation():
	cs = submitted_cost_sheet()
	q = quotation_of(cs)
	q.insert()
	q.submit()
	frappe.db.set_value("Quotation", q.name, "quotation_to", "Lead")
	true(throws(lambda: fx.engine_call("arinox_sales_contract_make_sales_contract", source_name=q.name), "addressed to a Customer"))


@test("costing_masters")
def make_sales_contract_carries_the_customers_earlier_terms_when_there_is_no_template():
	"""A Quotation holds few of a contract's fields. With no template, the buyer's most recent earlier contract supplies its terms, bands, brand,
	division, contact and merchant, and nothing already set on the new contract is overwritten."""
	from arinox_apparel.portable.hosted_tests.test_contract import contract

	cust = fx.customer()
	for t in frappe.get_all("Sales Contract Template", {"customer": cust}, pluck="name"):
		frappe.db.set_value("Sales Contract Template", t, "enabled", 0)
	frappe.db.set_single_value("Apparel Settings", "default_contract_template", None)
	contract(700, brand="HT BRAND", division="HT WOMENS", buyer_contact="HT BUYER", merchant="HT MERCH", port_of_discharge="Los Angeles",
			 quality_claim_days=60, aql_level="2.5", packing_instructions="PACK#5", documents_list="Invoice, Packing List").insert()
	tp = tech_pack("HT-QC-3", colours=("Navy",), sizes=("S", "M"))
	frappe.db.set_single_value("Apparel Settings", "style_item_group", frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
	item = fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp.name)["arinox_result"]
	cs = submitted_cost_sheet(style_no="HT-QC-3", tech_pack=tp.name, style_item=item)
	q = quotation_of(cs)
	q.insert()
	q.submit()
	sc = fx.engine_call("arinox_sales_contract_make_sales_contract", source_name=q.name)["arinox_result"]
	true(not sc["contract_template"])
	eq((sc["brand"], sc["division"], sc["buyer_contact"]), ("HT BRAND", "HT WOMENS", "HT BUYER"))
	eq(sc["merchant"], frappe.db.get_value("User", q.owner, "full_name"))          # the merchandiser is whoever raised the quotation, not the earlier contract's
	eq((sc["port_of_discharge"], sc["port_of_loading"], sc["quality_claim_days"], sc["aql_level"], sc["packing_instructions"]), ("Los Angeles", "Cat Lai", 60, "2.5", "PACK#5"))
	eq((sc["payment_basis"], sc["payment_days"], sc["documents_list"]), ("Days after Receipt of Goods (ROG)", 15, "Invoice, Packing List"))
	eq(len(sc["tolerance_bands"]), 4)
	eq(sc["customer_name"], frappe.db.get_value("Customer", cust, "customer_name"))
	eq((sc["quotation"], sc["currency"]), (q.name, "USD"))
	eq(len(sc["items"]), 1)
	# the form opens with prices and totals already worked out (they used to appear only after a save)
	line = sc["items"][0]
	true(line["qty"] and line["rate"])
	eq(line["amount"], round(line["qty"] * line["rate"], 2))
	eq((sc["total_qty"], sc["total_amount"], sc["sku_count"]), (line["qty"], line["amount"], 1))
	band = [b["tolerance_pct"] for b in BANDS if b["from_qty"] <= line["qty"] <= b["to_qty"]]
	eq(line["tolerance_pct"], band[0] if band else 0)                  # the tolerance of the carried band that covers the quantity (0 above the top band)
	# no earlier contract has this style, so the size rows follow the Tech Pack ratios (S and M, 1 each): they add up to the line, not to 0
	true(all(z["qty"] > 0 for z in sc["sizes"]))
	eq(sum(z["qty"] for z in sc["sizes"]), line["qty"])


@test("costing_masters")
def the_line_quantity_is_split_across_sizes_like_the_buyers_earlier_contract():
	"""A line of N pieces gets size rows adding up to exactly N, in the proportions of the buyer's most recent earlier contract for the same style
	(a Quotation carries no size breakdown, so every size used to be 0 and no Sales Order could be made)."""
	cust = fx.customer()
	for t in frappe.get_all("Sales Contract Template", {"customer": cust}, pluck="name"):
		frappe.db.set_value("Sales Contract Template", t, "enabled", 0)
	frappe.db.set_single_value("Apparel Settings", "default_contract_template", None)
	tp = tech_pack("HT-QC-4", colours=("Navy",), sizes=("S", "M", "L"))
	frappe.db.set_single_value("Apparel Settings", "style_item_group", frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
	item = fx.engine_call("arinox_tech_pack_create_style_item", tech_pack=tp.name)["arinox_result"]
	from arinox_apparel.portable.hosted_tests.test_contract import contract

	# the buyer's earlier order of this style: 100 S, 300 M, 100 L  (20 % / 60 % / 20 %)
	contract(500, items=[{"style_item": item, "colour": "Navy", "qty": 500, "rate": 10, "ex_factory_date": add_days(nowdate(), 60)}],
			 sizes=[{"style_item": item, "colour": "Navy", "size": "S", "qty": 100}, {"style_item": item, "colour": "Navy", "size": "M", "qty": 300},
					{"style_item": item, "colour": "Navy", "size": "L", "qty": 100}]).insert()
	cs = submitted_cost_sheet(style_no="HT-QC-4", tech_pack=tp.name, style_item=item)
	q = quotation_of(cs)
	q.items[0].qty = 1001                      # not a round number: the split must still add up exactly
	q.insert()
	q.submit()
	sc = fx.engine_call("arinox_sales_contract_make_sales_contract", source_name=q.name)["arinox_result"]
	by = {z["size"]: z["qty"] for z in sc["sizes"]}
	eq(sum(by.values()), 1001)
	eq((by["S"], by["M"], by["L"]), (200, 601, 200))          # 200.2 / 600.6 / 200.2 -> the biggest remainder takes the spare piece
	# the earlier order shipped ex-factory 60 days after its contract date, so this one gets the same lead time; ETD and in-warehouse follow the terms
	line = sc["items"][0]
	eq(str(line["ex_factory_date"]), add_days(str(sc["contract_date"]), 60))
	eq(str(line["etd"]), add_days(str(line["ex_factory_date"]), sc["days_ex_factory_to_etd"]))
	eq(str(line["in_warehouse_date"]), add_days(str(line["etd"]), sc["transit_days"]))
