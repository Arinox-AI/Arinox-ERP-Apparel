# Copyright (c) 2026, Arinox AI and contributors
"""Daily Cutting Report: cut quantity per production card x colour x size, with a column for each day of the range
(the company's DAILY CUTTING REPORT). Read from the production ledger."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

MAX_DAYS = 31


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.to_date or nowdate())
	from_date = getdate(filters.from_date or add_days(to_date, -6))
	if (to_date - from_date).days >= MAX_DAYS:
		frappe.throw(_("Choose at most {0} days.").format(MAX_DAYS))
	days = [add_days(from_date, i) for i in range((to_date - from_date).days + 1)]
	cond, args = ["c.docstatus = 1", "c.status not in ('Superseded', 'Cancelled')"], {}
	for key in ("production_card", "sales_order", "customer"):
		if filters.get(key):
			cond.append(f"c.{'name' if key == 'production_card' else key} = %({key})s")
			args[key] = filters[key]
	cards = frappe.db.sql(f"select c.name, c.style_no, c.sales_order from `tabProduction Card` c where {' and '.join(cond)} order by c.creation desc limit 200", args, as_dict=True)
	columns = [
		{"fieldname": "production_card", "label": _("Production Card"), "fieldtype": "Link", "options": "Production Card", "width": 130},
		{"fieldname": "style_no", "label": _("Style"), "fieldtype": "Data", "width": 110},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 90},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 60},
		{"fieldname": "order_qty", "label": _("Order Qty"), "fieldtype": "Int", "width": 80},
		{"fieldname": "planned", "label": _("Planned Cut"), "fieldtype": "Int", "width": 90},
	] + [{"fieldname": f"d{i}", "label": d.strftime("%d %b"), "fieldtype": "Int", "width": 62} for i, d in enumerate(days)] + [
		{"fieldname": "cut", "label": _("Cut (total)"), "fieldtype": "Int", "width": 90},
		{"fieldname": "reject", "label": _("Rejected"), "fieldtype": "Int", "width": 80},
		{"fieldname": "balance", "label": _("Balance to Cut"), "fieldtype": "Int", "width": 100},
		{"fieldname": "cut_pct", "label": _("Cut % of Plan"), "fieldtype": "Percent", "width": 100},
	]
	if not cards:
		return columns, []
	names = [c.name for c in cards]
	by_day = {}
	for card, colour, size, d, qty in frappe.db.sql(
		"select production_card, colour, size, posting_date, sum(qty) from `tabProduction Movement` where production_card in %s and stage = 'CUT' and purpose != 'Re-cut' group by 1, 2, 3, 4", (tuple(names),)):
		by_day[(card, colour, size, getdate(d))] = qty
	totals = {}
	for card, colour, size, stage, qty in frappe.db.sql("select production_card, colour, size, stage, sum(qty) from `tabProduction Movement` where production_card in %s and stage in ('CUT', 'CUT_REJECT') group by 1, 2, 3, 4", (tuple(names),)):
		totals[(card, colour, size, stage)] = qty
	data = []
	for c in cards:
		for l in frappe.get_all("Production Card Line", {"parent": c.name}, ["colour", "size", "order_qty", "planned_cut_qty"], order_by="idx"):
			cut = flt(totals.get((c.name, l.colour, l.size, "CUT")))
			row = {"production_card": c.name, "style_no": c.style_no, "colour": l.colour, "size": l.size, "order_qty": l.order_qty, "planned": l.planned_cut_qty,
				   "cut": cut, "reject": flt(totals.get((c.name, l.colour, l.size, "CUT_REJECT"))), "balance": flt(l.planned_cut_qty) - cut,
				   "cut_pct": cut * 100 / flt(l.planned_cut_qty) if flt(l.planned_cut_qty) else 0}
			for i, d in enumerate(days):
				row[f"d{i}"] = by_day.get((c.name, l.colour, l.size, d)) or None
			data.append(row)
	return columns, data
