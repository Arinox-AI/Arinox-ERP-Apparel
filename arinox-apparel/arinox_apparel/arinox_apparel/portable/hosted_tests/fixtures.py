"""Masters the hosted tests need, built from ERPNext's own doctypes only."""

import json

import frappe
from frappe.utils import add_days, nowdate

CUSTOMER = "HT Buyer"
STYLE = "HT-STYLE-1"


def company():
	"""The test company from the setup wizard (other companies may exist on the site, for example from importing sample orders)."""
	if frappe.db.exists("Company", "Arinox Test Co"):
		return "Arinox Test Co"
	return frappe.db.get_value("Company", {}, "name")


def customer(name=CUSTOMER):
	if not frappe.db.exists("Customer", name):
		frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
						"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"), "default_currency": "USD"}).insert()
	return name


def item(code=STYLE):
	if not frappe.db.exists("Item", code):
		frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code, "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
						"stock_uom": "Nos", "is_stock_item": 1, "valuation_rate": 5, "allow_zero_valuation_rate": 1}).insert()
	return code


def contract_fields(**kw):
	d = {"doctype": "Sales Contract", "customer": customer(), "contract_date": nowdate(), "currency": "USD", "company": company(),
		 "items": [{"style_item": item(), "colour": "Navy", "qty": 100, "rate": 10, "ex_factory_date": add_days(nowdate(), 60)}]}
	d.update(kw)
	return d


def sales_order(qty=100):
	"""A submitted ERPNext Sales Order for the style item (the app's Production Card hangs off it)."""
	cust = customer()
	it = item()
	wh = frappe.db.get_value("Warehouse", {"company": company(), "is_group": 0}, "name")
	so = frappe.get_doc({"doctype": "Sales Order", "customer": cust, "company": company(), "delivery_date": add_days(nowdate(), 60),
						 "items": [{"item_code": it, "qty": qty, "rate": 10, "delivery_date": add_days(nowdate(), 60), "warehouse": wh}]})
	so.insert()
	so.submit()
	return so


def card(colours=(("Navy", "S", 100), ("Navy", "M", 100)), **kw):
	"""An issued Production Card; each tuple is (colour, size, order qty). The script computes the planned cut."""
	so = colour_so({(c, s): q for c, s, q in colours})
	doc = frappe.get_doc({"doctype": "Production Card", "company": company(), "customer": customer(), "sales_order": so.name,
						  "style_item": item(), "lines": [{"colour": c, "size": s} for c, s, q in colours], **kw})
	doc.insert()
	doc.submit()
	return doc


def engine(**kw):
	"""Call the engine script the way run_script does and return what it left in frappe.flags."""
	form = frappe.local.form_dict
	saved = form.copy()
	form.update(kw)
	try:
		return frappe.get_doc("Server Script", "arinox_engine").execute_method()
	finally:
		frappe.local.form_dict = saved


def colour_so(qty_by_cell, tolerance=10):
	"""A submitted Sales Order with one line per (colour, size), carrying the apparel_* fields the card reads."""
	cust = customer()
	wh = frappe.db.get_value("Warehouse", {"company": company(), "is_group": 0}, "name")
	rows = []
	for (colour, size), q in qty_by_cell.items():
		rows.append({"item_code": item(), "qty": q, "rate": 10, "delivery_date": add_days(nowdate(), 60), "warehouse": wh,
					 "apparel_colour": colour, "apparel_size": size, "apparel_qty_tolerance_pct": tolerance})
	so = frappe.get_doc({"doctype": "Sales Order", "customer": cust, "company": company(), "delivery_date": add_days(nowdate(), 60), "items": rows})
	so.insert()
	so.submit()
	return so



def finished_card(pcs=100, cells=(("Navy", "S"),), tolerance=10):
	"""An issued card whose pieces have been cut, sewn and finished as A-grade (nothing packed yet). Returns the card."""
	import json

	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", 20)   # ERPNext's own guard; ours is what is tested
	so = colour_so({c: pcs for c in cells}, tolerance=tolerance)
	card_doc = frappe.get_doc({"doctype": "Production Card", "company": company(), "customer": customer(), "sales_order": so.name,
							   "style_item": item(), "lines": [{"colour": c[0], "size": c[1]} for c in cells]})
	card_doc.insert()
	card_doc.submit()
	for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A"):
		rows = [{"stage": stage, "colour": c[0], "size": c[1], "qty": pcs} for c in cells]
		engine(action="post", card=card_doc.name, rows=json.dumps(rows), source_doctype="Setup", source_name="S-" + stage, posting_date=nowdate(), check="0")
	return card_doc


def packing_list(card_doc, pcs_per_carton=24, submit=True, quantities=None, pack_type="Solid Colour Solid Size", ratios=None, tail_rule="Mixed Colour and Size", **kw):
	"""A Packing List built from the generator API (the Generate Cartons button), with weights on every row."""
	form = {"production_card": card_doc.name, "pack_type": pack_type, "pcs_per_carton": pcs_per_carton, "tail_carton_rule": tail_rule, "carton_start": 1, "ratios": ratios or []}
	args = {"doc": frappe.as_json(form)}
	if quantities:
		args["quantities"] = json.dumps(quantities)
	res = engine_call("arinox_packing_list_api_generate", **args)["arinox_result"]
	cartons = res["arinox_doc"]["cartons"]
	for c in cartons:
		c.update({"gross_weight_kg": 5, "net_weight_kg": 4.5, "length_cm": 60, "width_cm": 40, "height_cm": 30})
	body = {"doctype": "Packing List", "production_card": card_doc.name, "packing_date": nowdate(), "pack_type": pack_type, "pcs_per_carton": pcs_per_carton,
			"tail_carton_rule": tail_rule, "ratios": [{"colour": r.get("colour"), "size": r["size"], "pieces_per_pack": r["pieces_per_pack"]} for r in (ratios or [])],
			"cartons": cartons, "contents": res["arinox_doc"]["contents"], "status": "Open"}
	body.update(kw)
	doc = frappe.get_doc(body).insert()
	if submit:
		doc.submit()
	return doc


def aql_plan():
	"""A one-row AQL plan with confirmed accept/reject numbers (the app's tests use the same shape)."""
	name = "HT Plan"
	if not frappe.db.exists("AQL Plan", name):
		frappe.get_doc({"doctype": "AQL Plan", "plan_name": name, "inspection_level": "General II", "aql_critical": "0", "aql_major": "2.5", "aql_minor": "4.0",
						"rows": [{"lot_from": 1, "lot_to": 99999999, "code_letter": "X", "sample_size": 80, "critical_ac": 0, "critical_re": 1, "major_ac": 3, "major_re": 4,
								  "minor_ac": 5, "minor_re": 6, "confirmed": 1}]}).insert()
	return name


def inspect_lot(card_doc, pl, result="Accepted", **kw):
	"""A submitted Final Inspection of one packing list: confirmed plan, cartons drawn by the API."""
	body = {"doctype": "Final Inspection", "production_card": card_doc.name, "inspection_type": "Final", "inspection_date": nowdate(), "aql_plan": aql_plan(),
			"lots": [{"packing_list": pl.name}], "result": result}
	body.update(kw)
	fi = frappe.get_doc(body).insert()
	res = engine_call("arinox_final_inspection_pick_cartons", doc=frappe.as_json(fi.as_dict()))["arinox_result"]["arinox_doc"]
	fi.set("cartons_picked", res["cartons_picked"])
	fi.draw_seed = res["draw_seed"]
	fi.save()
	fi.submit()
	return fi


def delivery_chain(pcs=100, inspection="Accepted", tolerance=10):
	"""Card -> finished pieces -> a submitted Packing List -> Final Inspection -> a draft Delivery Note for the packed pieces.
	Returns (card, packing_list, delivery_note)."""
	card_doc = finished_card(pcs, tolerance=tolerance)
	pl = packing_list(card_doc, pcs_per_carton=24)
	if inspection:
		inspect_lot(card_doc, pl, inspection)
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	dn = make_delivery_note(card_doc.sales_order)
	for it in dn.items:
		it.apparel_packing_list = pl.name
		it.qty = pcs
	dn.insert()
	return card_doc, pl, dn

RATES = {   # cost head -> (rate, not applicable): the reference costing sheet (tests/utils.py in the app)
	"Fabric Export Cost": (0.25, 0), "Fabric Import Cost": (0.25, 0), "Stitching (CMT)": (5, 0), "Washing": (0, 1), "Printing": (0, 1), "Embellishment": (0, 1),
	"Testing": (0, 1), "Rejection Allowance": (3, 0), "Finance": (1, 0), "Bank Charges": (1, 0), "Freight": (2, 0), "Overhead": (15, 0),
	"Buying Agent Commission": (0, 1), "Profit": (15, 0),
}
PRODUCT_TYPE = "Knit Top"


def costing_parameter():
	"""The customer's costing parameter with the reference rates (idempotent)."""
	name = frappe.db.get_value("Costing Parameter", {"customer": customer(), "product_type": PRODUCT_TYPE})
	rates = [{"cost_head": h, "rate": r, "not_applicable": na} for h, (r, na) in RATES.items()]
	if name:
		return name
	return frappe.get_doc({"doctype": "Costing Parameter", "customer": customer(), "product_type": PRODUCT_TYPE, "currency": "USD",
						   "effective_from": add_days(nowdate(), -30), "margin_floor_pct": 10, "rates": rates}).insert().name


def reference_materials():
	def row(material_type, description, consumption, rate, uom="Nos", wastage=0, **kw):
		d = {"material_type": material_type, "description": description, "consumption": consumption, "rate": rate, "uom": uom, "is_selected": 1}
		if wastage:
			d.update(wastage_pct=wastage, wastage_reason="Cutting wastage")
		d.update(kw)
		return d

	return [row("Fabric", "Main fabric", 0.6, 3, "Meter", 5), row("Contrast Fabric", "Trim / contrast fabric", 0.6, 3, "Meter", 5), row("Label", "Main label", 1, 0.05),
			row("Label", "Wash care label", 1, 0.05), row("Trim", "Hang tag", 2, 0.05), row("Packaging", "Poly bag", 1, 0.05), row("Packaging", "Tissue paper", 6, 0.02),
			row("Thread", "Thread", 200, 0.001, "Meter"), row("Packaging", "Carton", 1, 0.15, per_carton=1), row("Trim", "Tape", 0.5, 0.1, "Meter"),
			row("Trim", "Zipper", 1, 0.1), row("Trim", "Button", 1, 0.1), *[row("Other", "Others", 0.01, 0.3) for _ in range(4)]]


def cost_sheet(quoted_price=None, **kw):
	costing_parameter()
	d = {"doctype": "Cost Sheet", "naming_series": "CS-.YYYY.-", "customer": customer(), "style_no": "HT-COST-1", "product_type": PRODUCT_TYPE, "costing_date": nowdate(),
		 "currency": "USD", "sam": 12, "order_qty": 5500, "pcs_per_carton": 40, "fob_port": "HCM", "local_currency": "VND", "local_exchange_rate": 25000,
		 "materials": reference_materials()}
	if quoted_price:
		d["quoted_price"] = quoted_price
	d.update(kw)
	return frappe.get_doc(d).insert()


def engine_call(script, **kw):
	"""Run an API Server Script by name with the given form values; returns what it left in frappe.flags."""
	form = frappe.local.form_dict
	saved = form.copy()
	form.update(kw)
	try:
		name = frappe.db.get_value("Server Script", {"api_method": script}, "name") or script       # a button's API method name, or the record name
		return frappe.get_doc("Server Script", name).execute_method()
	finally:
		frappe.local.form_dict = saved


def variant_item(colour="Navy", size="M", code="HT-VAR-STYLE"):
	"""A template item with Colour and Size attributes and one variant; returns (template code, variant code)."""
	from erpnext.controllers.item_variant import create_variant

	for attr, val in (("Colour", colour), ("Size", size)):
		doc = frappe.get_doc("Item Attribute", attr)
		if val.upper() not in {v.attribute_value.upper() for v in doc.item_attribute_values}:
			doc.append("item_attribute_values", {"attribute_value": val, "abbr": val[:4].upper()})
			doc.save()
	if not frappe.db.exists("Item", code):
		frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code, "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"), "stock_uom": "Nos",
						"is_stock_item": 1, "has_variants": 1, "variant_based_on": "Item Attribute", "attributes": [{"attribute": "Colour"}, {"attribute": "Size"}]}).insert()
	v = create_variant(code, {"Colour": colour, "Size": size})
	v.valuation_rate = 5
	if not frappe.db.exists("Item", v.item_code):
		v.insert()
	return code, v.item_code


def shipment(dns, **kw):
	"""An ERPNext Shipment carrying the given (submitted) delivery notes."""
	body = {"doctype": "Shipment", "pickup_from_type": "Company", "pickup_company": company(), "delivery_to_type": "Customer", "delivery_customer": customer(),
			"pickup_type": "Pickup", "pickup_date": nowdate(), "description_of_content": "Garments", "apparel_mode": "Sea LCL", "apparel_booking_no": "HT-BK-" + frappe.generate_hash(length=5),
			"shipment_parcel": [{"length": 60, "width": 40, "height": 30, "weight": 5, "count": 5}],
			"shipment_delivery_note": [{"delivery_note": dn.name} for dn in dns]}
	body.update(kw)
	return frappe.get_doc(body).insert()


def trading_company():
	"""A second company in the group (it bills the buyer; the factory bills it)."""
	name = "HT Trading Co"
	if not frappe.db.exists("Company", name):
		frappe.get_doc({"doctype": "Company", "company_name": name, "abbr": "HTT", "default_currency": "USD", "country": "United States",
						"create_chart_of_accounts_based_on": "Standard Template", "chart_of_accounts": "Standard"}).insert()
	if not frappe.db.exists("Customer", name):
		frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
						"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"), "is_internal_customer": 1, "represents_company": name,
						"companies": [{"company": company()}], "default_currency": "USD"}).insert()
	return name


def run_scheduled(script):
	"""Run a Scheduler Event Server Script once, as the scheduler would."""
	frappe.get_doc("Server Script", script).execute_scheduled_method()


def user(email, roles):
    """A user holding the given roles (idempotent). Switch with frappe.set_user(email) and back to "Administrator" in a finally."""
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "HT", "send_welcome_email": 0}).insert()
    u = frappe.get_doc("User", email)
    u.add_roles(*roles)
    return email
