# Copyright (c) 2026, Arinox AI and contributors
"""Contract Trail: every document that carries the contract number, from the sales order to the payment, in one list."""

import frappe
from frappe import _

SOURCES = [
	("Sales Order", "apparel_sales_contract", "transaction_date", "status", "grand_total"),
	("Production Card", "sales_contract", "issue_date", "status", None),
	("Subcontract Challan", "sales_contract", "challan_date", "status", "total_qty"),
	("Subcontract Return", "sales_contract", "return_date", None, "total_good"),
	("Subcontract Settlement", "sales_contract", "settlement_date", None, "net_amount"),
	("Finishing Receipt", "sales_contract", "receipt_date", None, "total_qty"),
	("Packing List", "sales_contract", "packing_date", "status", "total_pieces"),
	("Final Inspection", "sales_contract", "inspection_date", "result", "offered_qty"),
	("Delivery Note", "apparel_sales_contract", "posting_date", "status", "total_qty"),
	("Sales Invoice", "apparel_sales_contract", "posting_date", "apparel_followup_status", "grand_total"),
	("Buyer Claim", "sales_contract", "reported_on", "status", "claimed_amount"),
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "doctype", "label": _("Document"), "fieldtype": "Data", "width": 150},
		{"fieldname": "name", "label": _("Number"), "fieldtype": "Dynamic Link", "options": "doctype", "width": 190},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "amount", "label": _("Qty / Amount"), "fieldtype": "Float", "width": 110},
		{"fieldname": "docstatus", "label": _("Doc"), "fieldtype": "Data", "width": 70},
	]
	if not filters.contract:
		return columns, []
	data = []
	for dt, field, date_f, status_f, amount_f in SOURCES:
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field(field):
			continue
		fields = ["name", f"{date_f} as date", "docstatus"] + ([f"{status_f} as status"] if status_f else []) + ([f"{amount_f} as amount"] if amount_f else [])
		for r in frappe.get_all(dt, {field: filters.contract}, fields, order_by="creation"):
			data.append({"doctype": dt, "name": r.name, "date": r.date, "status": r.get("status"), "amount": r.get("amount"),
						 "docstatus": {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}[r.docstatus]})
	for r in frappe.get_all("Shipment", {"apparel_contracts": ["like", f"%{filters.contract}%"]}, ["name", "apparel_etd as date", "apparel_ship_status as status", "docstatus"]):
		data.append({"doctype": "Shipment", "name": r.name, "date": r.date, "status": r.status, "amount": None, "docstatus": {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}[r.docstatus]})
	return columns, data
