# Copyright (c) 2026, Arinox AI and contributors
"""Allocated pieces per factory and line, by week of planned cut date."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "factory", "label": _("Factory"), "fieldtype": "Link", "options": "Plant Floor", "width": 150},
		{"fieldname": "line", "label": _("Line"), "fieldtype": "Link", "options": "Workstation", "width": 170},
		{"fieldname": "week_start", "label": _("PCD Week Of"), "fieldtype": "Date", "width": 110},
		{"fieldname": "orders", "label": _("Orders"), "fieldtype": "Int", "width": 70},
		{"fieldname": "styles", "label": _("Style x Colour"), "fieldtype": "Int", "width": 100},
		{"fieldname": "qty", "label": _("Pieces"), "fieldtype": "Int", "width": 90},
		{"fieldname": "capacity", "label": _("Line Capacity"), "fieldtype": "Int", "width": 100},
	]
	cond, values = "", {}
	if filters.factory:
		cond += " and l.factory = %(factory)s"
		values["factory"] = filters.factory
	if filters.from_date:
		cond += " and l.pcd >= %(from_date)s"
		values["from_date"] = filters.from_date
	if filters.to_date:
		cond += " and l.pcd <= %(to_date)s"
		values["to_date"] = filters.to_date
	data = frappe.db.sql(
		f"""select l.factory, l.line, date_sub(l.pcd, interval weekday(l.pcd) day) as week_start,
			count(distinct l.parent) as orders, count(*) as styles, sum(l.qty) as qty, max(w.production_capacity) as capacity
		from `tabFactory Allocation Line` l left join `tabWorkstation` w on w.name = l.line
		where l.pcd is not null {cond}
		group by l.factory, l.line, week_start order by week_start, l.factory, l.line""",
		values, as_dict=True,
	)
	return columns, data
