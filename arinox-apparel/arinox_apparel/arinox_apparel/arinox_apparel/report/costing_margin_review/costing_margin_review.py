# Copyright (c) 2026, Arinox AI and contributors
"""Every costing with its margin against the floor. The backstop for the margin gate."""

import frappe
from frappe import _


def execute(filters=None):
	f = frappe._dict(filters or {})
	cond = {"docstatus": ("<", 2)}
	if f.customer: cond["customer"] = f.customer
	if f.product_type: cond["product_type"] = f.product_type
	if f.from_date and f.to_date: cond["costing_date"] = ("between", [f.from_date, f.to_date])
	if f.below_floor: cond["below_floor"] = 1
	if f.approval_status: cond["approval_status"] = f.approval_status
	rows = frappe.get_all(
		"Cost Sheet", filters=cond, order_by="costing_date desc",
		fields=["name", "customer", "style_no", "product_type", "costing_date", "revision_no", "currency",
				"material_cost", "conversion_cost", "subtotal", "computed_price", "quoted_price", "margin_pct",
				"margin_floor_pct", "below_floor", "approval_status", "approved_by", "docstatus", "order_qty", "order_value"],
	)
	for r in rows:
		r.state = {0: _("Draft"), 1: _("Submitted")}[r.docstatus]
	cols = [
		{"label": _("Cost Sheet"), "fieldname": "name", "fieldtype": "Link", "options": "Cost Sheet", "width": 140},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
		{"label": _("Style"), "fieldname": "style_no", "fieldtype": "Data", "width": 110},
		{"label": _("Product Type"), "fieldname": "product_type", "fieldtype": "Data", "width": 100},
		{"label": _("Date"), "fieldname": "costing_date", "fieldtype": "Date", "width": 95},
		{"label": _("Rev"), "fieldname": "revision_no", "fieldtype": "Int", "width": 50},
		{"label": _("State"), "fieldname": "state", "fieldtype": "Data", "width": 85},
		{"label": _("Material"), "fieldname": "material_cost", "fieldtype": "Currency", "options": "currency", "width": 95},
		{"label": _("Other Heads"), "fieldname": "conversion_cost", "fieldtype": "Currency", "options": "currency", "width": 95},
		{"label": _("Computed FOB"), "fieldname": "computed_price", "fieldtype": "Currency", "options": "currency", "width": 105},
		{"label": _("Quoted FOB"), "fieldname": "quoted_price", "fieldtype": "Currency", "options": "currency", "width": 100},
		{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 85},
		{"label": _("Floor %"), "fieldname": "margin_floor_pct", "fieldtype": "Percent", "width": 75},
		{"label": _("Below Floor"), "fieldname": "below_floor", "fieldtype": "Check", "width": 90},
		{"label": _("Approval"), "fieldname": "approval_status", "fieldtype": "Data", "width": 95},
		{"label": _("Approved By"), "fieldname": "approved_by", "fieldtype": "Link", "options": "User", "width": 130},
		{"label": _("Order Qty"), "fieldname": "order_qty", "fieldtype": "Int", "width": 85},
		{"label": _("Order Value"), "fieldname": "order_value", "fieldtype": "Currency", "options": "currency", "width": 115},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
	]
	top = rows[:15]
	chart = {
		"data": {"labels": [r.style_no for r in top],
				 "datasets": [{"name": _("Margin %"), "values": [r.margin_pct for r in top]},
							  {"name": _("Floor %"), "values": [r.margin_floor_pct for r in top]}]},
		"type": "bar", "colors": ["#e8590c", "#16120f"],
	}
	return cols, rows, None, chart
