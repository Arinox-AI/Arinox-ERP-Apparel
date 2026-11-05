"""Masters the hosted tests need, built from ERPNext's own doctypes only."""

import frappe
from frappe.utils import add_days, nowdate

CUSTOMER = "HT Buyer"
STYLE = "HT-STYLE-1"


def company():
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



def delivery_chain(pcs=100, inspection="Accepted", tolerance=10):
	"""Card -> cut/sew/pack quantities in the ledger -> Packing List -> Final Inspection -> a draft Delivery Note for the packed pieces.
	Returns (card, packing_list, delivery_note)."""
	import json

	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", 20)   # ERPNext's own guard; ours is what is tested
	so = colour_so({("Navy", "S"): pcs}, tolerance=tolerance)
	card_doc = frappe.get_doc({"doctype": "Production Card", "company": company(), "customer": customer(), "sales_order": so.name,
							   "style_item": item(), "lines": [{"colour": "Navy", "size": "S"}]})
	card_doc.insert()
	card_doc.submit()
	for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A", "PACKED"):
		engine(action="post", card=card_doc.name, rows=json.dumps([{"stage": stage, "colour": "Navy", "size": "S", "qty": pcs}]),
			   source_doctype="Setup", source_name="S-" + stage, posting_date=nowdate(), check="0")
	pl = frappe.get_doc({"doctype": "Packing List", "production_card": card_doc.name, "packing_date": nowdate(), "pack_type": "Solid Colour Solid Size",
						 "pcs_per_carton": pcs, "status": "Open"}).insert()
	pl.submit()
	if inspection:
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": card_doc.name, "inspection_type": "Final", "inspection_date": nowdate(),
							 "result": inspection, "lots": [{"packing_list": pl.name}]}).insert()
		fi.submit()
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	dn = make_delivery_note(so.name)
	for it in dn.items:
		it.apparel_packing_list = pl.name
		it.qty = pcs
	dn.insert()
	return card_doc, pl, dn
