# Copyright (c) 2026, Arinox AI and contributors
"""Every signed SKU line with its three dates, so the shipping calendar is one list."""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate


def execute(filters=None):
	f = frappe._dict(filters or {})
	conds, vals = ["sc.docstatus = 1"], {}
	if f.customer:
		conds.append("sc.customer = %(customer)s"); vals["customer"] = f.customer
	if f.from_date and f.to_date:
		conds.append("i.ex_factory_date between %(from_date)s and %(to_date)s"); vals.update(from_date=f.from_date, to_date=f.to_date)
	if not f.include_ordered:
		conds.append("ifnull(sc.sales_order, '') = ''")
	rows = frappe.db.sql(
		f"""select sc.name as contract, sc.customer, sc.currency, sc.sales_order, i.style_no, i.style_item, i.colour,
			i.qty, i.tolerance_pct, i.rate, i.amount, i.ex_factory_date, i.etd, i.in_warehouse_date, sc.incoterm,
			sc.port_of_loading, sc.shipment_mode
		from `tabSales Contract Item` i join `tabSales Contract` sc on sc.name = i.parent
		where {' and '.join(conds)} order by i.ex_factory_date, sc.name""",
		vals, as_dict=True,
	)
	today = getdate(nowdate())
	for r in rows:
		r.days_to_ex_factory = date_diff(r.ex_factory_date, today) if r.ex_factory_date else None
	cols = [
		{"label": _("Contract"), "fieldname": "contract", "fieldtype": "Link", "options": "Sales Contract", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
		{"label": _("Style"), "fieldname": "style_no", "fieldtype": "Data", "width": 100},
		{"label": _("Colour"), "fieldname": "colour", "fieldtype": "Data", "width": 90},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Int", "width": 75},
		{"label": _("Tol ±%"), "fieldname": "tolerance_pct", "fieldtype": "Percent", "width": 65},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 105},
		{"label": _("Ex-Factory"), "fieldname": "ex_factory_date", "fieldtype": "Date", "width": 95},
		{"label": _("Days Left"), "fieldname": "days_to_ex_factory", "fieldtype": "Int", "width": 75},
		{"label": _("ETD"), "fieldname": "etd", "fieldtype": "Date", "width": 95},
		{"label": _("In-Warehouse"), "fieldname": "in_warehouse_date", "fieldtype": "Date", "width": 100},
		{"label": _("Incoterm"), "fieldname": "incoterm", "fieldtype": "Data", "width": 70},
		{"label": _("Mode"), "fieldname": "shipment_mode", "fieldtype": "Data", "width": 65},
		{"label": _("Port of Loading"), "fieldname": "port_of_loading", "fieldtype": "Data", "width": 110},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 130},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
	]
	return cols, rows
