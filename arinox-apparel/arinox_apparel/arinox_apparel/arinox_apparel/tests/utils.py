"""Shared fixtures for the Phase 1 tests. Everything is prefixed _AT so it never touches real data.

The costing fixture reproduces "APPAREL_COSTING_DETAILED_REVISED.xlsx" from the reference documents:
5,500 pcs, FOB 14.3748 USD, 359,370 VND.
"""

import frappe
from frappe.utils import add_days, nowdate

CUSTOMER = "_AT Buyer"
OTHER_CUSTOMER = "_AT Other Buyer"
PRODUCT_TYPE = "_AT Knit Top"
CURRENCY = "USD"
TEMPLATE = "_AT Standard"

# head -> (rate, not_applicable). Percentages are on product cost; profit is a markup on the cost so far.
RATES = {
	"Fabric Export Cost": (0.25, 0),  # per metre of fabric
	"Fabric Import Cost": (0.25, 0),
	"Stitching (CMT)": (5, 0),  # per piece
	"Washing": (0, 1),
	"Printing": (0, 1),
	"Embellishment": (0, 1),
	"Testing": (0, 1),
	"Rejection Allowance": (3, 0),
	"Finance": (1, 0),
	"Bank Charges": (1, 0),
	"Freight": (2, 0),  # freight / local charges to FOB port
	"Overhead": (15, 0),
	"Buying Agent Commission": (0, 1),
	"Profit": (15, 0),
}

# Reference values for the costing above (per piece)
FOB_UNROUNDED = 14.37478725
COST_BEFORE_PROFIT = 12.499815

# Sized so the quoted FOB clears the 10% margin floor, and a price that does not.
AGREED_PRICE = 14.20
BELOW_FLOOR_PRICE = 12.80


def setup_masters():
	from arinox_apparel.setup.install import after_migrate
	from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import get_default_company

	after_migrate()
	company = get_default_company()
	for name in (CUSTOMER, OTHER_CUSTOMER):
		if not frappe.db.exists("Customer", name):
			frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_group": frappe.db.get_value(
				"Customer Group", {"is_group": 0}, "name"), "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"default_currency": CURRENCY}).insert()
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	if not frappe.db.exists("Product Type", PRODUCT_TYPE):
		frappe.get_doc({"doctype": "Product Type", "product_type": PRODUCT_TYPE, "item_group": group, "default_sam": 12}).insert()
	settings = frappe.get_single("Apparel Settings")
	settings.style_item_group = group
	settings.default_margin_floor_pct = 10
	settings.approval_tolerance_pct = 0.5
	settings.max_skus_per_contract = 8
	settings.require_costing_signoff = 0
	settings.fg_warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	settings.save()

	rates = [{"cost_head": h, "rate": r, "not_applicable": na} for h, (r, na) in RATES.items()]
	name = frappe.db.get_value("Costing Parameter", {"customer": CUSTOMER, "product_type": PRODUCT_TYPE})
	if name:  # a parameter from an earlier run may already be on a submitted Cost Sheet, so update it in place
		param = frappe.get_doc("Costing Parameter", name)
		param.set("rates", rates)
		param.margin_floor_pct = 10
		param.enabled = 1
		param.effective_to = None
		param.save()
	else:
		frappe.get_doc({
			"doctype": "Costing Parameter", "customer": CUSTOMER, "product_type": PRODUCT_TYPE, "currency": CURRENCY,
			"effective_from": add_days(nowdate(), -30), "margin_floor_pct": 10, "rates": rates,
		}).insert()
	for uom in ("Nos", "Meter", "Yard"):
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert()
	make_contract_template()
	return company


def make_payment_terms():
	name = "_AT 30 Days"
	if not frappe.db.exists("Payment Terms Template", name):
		frappe.get_doc({"doctype": "Payment Terms Template", "template_name": name, "terms": [
			{"invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30}]}).insert()
	return name


def make_contract_template():
	"""Terms and quantity-allowance bands typical of a garment sales contract."""
	fields = {
		"customer": CUSTOMER, "is_default": 1, "enabled": 1, "incoterm": frappe.db.get_value("Incoterm", {}, "name"),
		"named_place": "Ho Chi Minh", "port_of_loading": "Cat Lai", "port_of_discharge": "Los Angeles",
		"shipment_mode": "Sea", "days_ex_factory_to_etd": 7, "transit_days": 30, "country_of_origin": "India",
		"freight_by": "Seller", "insurance_by": "Seller", "delay_days_allowed": 4, "aql_level": "2.5",
		"payment_basis": "Days after Receipt of Goods (ROG)", "payment_days": 15,
		"payment_terms_template": make_payment_terms(),
	}
	bands = [
		{"from_qty": 0, "to_qty": 500, "tolerance_pct": 15},
		{"from_qty": 501, "to_qty": 800, "tolerance_pct": 10},
		{"from_qty": 801, "to_qty": 1600, "tolerance_pct": 7.5},
		{"from_qty": 1601, "to_qty": 3000, "tolerance_pct": 5},
	]
	if frappe.db.exists("Sales Contract Template", TEMPLATE):
		tpl = frappe.get_doc("Sales Contract Template", TEMPLATE)
		tpl.update(fields)
		tpl.set("tolerance_bands", bands)
		tpl.save()
	else:
		frappe.get_doc({"doctype": "Sales Contract Template", "template_name": TEMPLATE, **fields,
						"tolerance_bands": bands}).insert()


def make_tech_pack(style_no="_AT-STY-1", colours=("Navy", "Black"), sizes=("S", "M", "L"), submit=True):
	tp = frappe.get_doc({
		"doctype": "Tech Pack", "customer": CUSTOMER, "style_no": style_no, "style_name": "Test Tee",
		"product_type": PRODUCT_TYPE, "season": "_AT26",
		"sizes": [{"size": s, "ratio": 1, "is_base_size": 1 if s == "M" else 0} for s in sizes],
		"colours": [{"colour": c} for c in colours],
		"measurements": [{"pom_code": "A", "point_of_measure": "Chest", "size": s, "value": 50 + i * 2,
						  "tolerance_plus": 1, "tolerance_minus": 1} for i, s in enumerate(sizes)],
		"materials": [
			{"material_type": "Fabric", "description": "Jersey 180gsm", "consumption": 1.2, "uom": "Meter"},
			{"material_type": "Trim", "description": "Neck label", "consumption": 1, "uom": "Nos"},
		],
	}).insert()
	if submit:
		tp.submit()
	return tp


def reference_materials():
	"""Raw-material rows of the reference costing sheet (usage, wastage 5% on fabrics, rate in USD)."""
	def row(material_type, description, consumption, rate, uom="Nos", wastage=0, **kw):
		d = {"material_type": material_type, "description": description, "consumption": consumption, "rate": rate,
			 "uom": uom, "is_selected": 1}
		if wastage:
			d.update(wastage_pct=wastage, wastage_reason="Cutting wastage")
		d.update(kw)
		return d

	return [
		row("Fabric", "Main fabric", 0.6, 3, "Meter", 5),
		row("Contrast Fabric", "Trim / contrast fabric", 0.6, 3, "Meter", 5),
		row("Label", "Main label", 1, 0.05),
		row("Label", "Wash care label", 1, 0.05),
		row("Trim", "Hang tag", 2, 0.05),
		row("Packaging", "Poly bag", 1, 0.05),
		row("Packaging", "Tissue paper", 6, 0.02),
		row("Thread", "Thread", 200, 0.001, "Meter"),
		row("Packaging", "Carton", 1, 0.15, per_carton=1),
		row("Trim", "Tape", 0.5, 0.1, "Meter"),
		row("Trim", "Zipper", 1, 0.1),
		row("Trim", "Button", 1, 0.1),
		*[row("Other", "Others", 0.01, 0.3) for _ in range(4)],
	]


def make_cost_sheet(tech_pack=None, submit=False, quoted_price=None, **overrides):
	from arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack import make_cost_sheet as map_cs

	tp = tech_pack or make_tech_pack()
	cs = map_cs(tp.name)
	cs.currency = CURRENCY
	cs.sam = 12
	cs.order_qty = 5500
	cs.pcs_per_carton = 40
	cs.fob_port = "HCM"
	cs.local_currency = "VND"
	cs.local_exchange_rate = 25000
	cs.set("materials", reference_materials())
	if quoted_price:
		cs.quoted_price = quoted_price
	cs.update(overrides)
	cs.insert()
	if submit:
		cs.submit()
	return cs


def make_order(style_no, navy=700, black=500, ship_split=False):
	"""Tech pack -> costing -> negotiation -> quotation -> signed contract -> submitted Sales Order.
	Returns (sales_order, style_item_template, contract)."""
	from frappe.utils import add_days, nowdate
	from arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet import make_price_negotiation
	from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import make_quotation
	from arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract import make_sales_contract, make_sales_order
	from arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack import create_style_item

	tp = make_tech_pack(style_no=style_no)
	create_style_item(tp.name)
	tp.reload()
	cs = make_cost_sheet(tech_pack=tp, submit=True)
	pn = frappe.get_doc("Price Negotiation", make_price_negotiation(cs.name))
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Agreed", "price": AGREED_PRICE, "qty": 1200})
	pn.save()
	q = make_quotation(pn.name)
	q.insert()
	q.submit()
	sc = make_sales_contract(q.name)
	ex = add_days(nowdate(), 90)
	for it in sc.items:
		it.qty = navy if it.colour == "Navy" else black
		it.ex_factory_date = ex
		it.pcd = add_days(ex, -30)
	for colour, qtys in {"Navy": [200, 300, 200], "Black": [150, 200, 150]}.items():
		for s, qty in zip([s for s in sc.sizes if s.colour == colour], qtys):
			s.qty = qty
	sc.buyer_po_no = "PO-" + style_no
	if ship_split:  # Navy 500 pcs to DC1 and 200 to DC2
		for s, dest in zip([s for s in sc.sizes if s.colour == "Navy"], ["DC1", "DC1", "DC2"]):
			s.ship_to = dest
	sc.insert()
	sc.submit()
	so = make_sales_order(sc.name)
	so.insert()
	so.submit()
	return so, tp.style_item, sc


def make_floors():
	"""Two factories with two lines each."""
	from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import get_default_company

	company = get_default_company()
	wh = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	out = {}
	for floor in ("_AT Factory A", "_AT Factory B"):
		if not frappe.db.exists("Plant Floor", floor):
			frappe.get_doc({"doctype": "Plant Floor", "floor_name": floor, "company": company, "warehouse": wh}).insert()
		out[floor] = []
		for n in (1, 2):
			ws = f"{floor} Line {n}"
			if not frappe.db.exists("Workstation", ws):
				frappe.get_doc({"doctype": "Workstation", "workstation_name": ws, "plant_floor": floor, "production_capacity": 1}).insert()
			out[floor].append(ws)
	return out
