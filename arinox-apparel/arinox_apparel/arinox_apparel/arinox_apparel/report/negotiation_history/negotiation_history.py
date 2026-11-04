# Copyright (c) 2026, Arinox AI and contributors
"""Every offer and counter, oldest first, with the margin each price leaves."""

import frappe
from frappe import _


def execute(filters=None):
	f = frappe._dict(filters or {})
	conds, vals = ["1=1"], {}
	for key, col in (("customer", "pn.customer"), ("price_negotiation", "pn.name"), ("cost_sheet", "r.cost_sheet"),
					 ("direction", "r.direction")):
		if f.get(key):
			conds.append(f"{col} = %({key})s"); vals[key] = f.get(key)
	if f.style_no:
		conds.append("r.style_no like %(style_no)s"); vals["style_no"] = f"%{f.style_no}%"
	if f.from_date and f.to_date:
		conds.append("r.round_date between %(from_date)s and %(to_date)s"); vals.update(from_date=f.from_date, to_date=f.to_date)
	rows = frappe.db.sql(
		f"""select r.round_date, pn.name as price_negotiation, pn.customer, pn.currency, r.style_no, r.cost_sheet,
			r.direction, r.price, r.qty, r.margin_pct, r.below_floor, r.channel, r.quotation, r.remarks,
			r.recorded_by, r.recorded_by_ai, cs.quoted_price as costed_fob
		from `tabPrice Negotiation Round` r
		join `tabPrice Negotiation` pn on pn.name = r.parent and r.parenttype = 'Price Negotiation'
		left join `tabCost Sheet` cs on cs.name = r.cost_sheet
		where {' and '.join(conds)}
		order by pn.name, r.style_no, r.round_date, r.idx""",
		vals, as_dict=True,
	)
	cols = [
		{"label": _("Date"), "fieldname": "round_date", "fieldtype": "Date", "width": 95},
		{"label": _("Negotiation"), "fieldname": "price_negotiation", "fieldtype": "Link", "options": "Price Negotiation", "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
		{"label": _("Style"), "fieldname": "style_no", "fieldtype": "Data", "width": 100},
		{"label": _("Cost Sheet"), "fieldname": "cost_sheet", "fieldtype": "Link", "options": "Cost Sheet", "width": 130},
		{"label": _("Who / What"), "fieldname": "direction", "fieldtype": "Data", "width": 110},
		{"label": _("Price"), "fieldname": "price", "fieldtype": "Currency", "options": "currency", "width": 90},
		{"label": _("Costed FOB"), "fieldname": "costed_fob", "fieldtype": "Currency", "options": "currency", "width": 95},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Int", "width": 70},
		{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 80},
		{"label": _("Below Floor"), "fieldname": "below_floor", "fieldtype": "Check", "width": 85},
		{"label": _("Channel"), "fieldname": "channel", "fieldtype": "Data", "width": 80},
		{"label": _("Quotation"), "fieldname": "quotation", "fieldtype": "Link", "options": "Quotation", "width": 130},
		{"label": _("By AI"), "fieldname": "recorded_by_ai", "fieldtype": "Check", "width": 60},
		{"label": _("Recorded By"), "fieldname": "recorded_by", "fieldtype": "Link", "options": "User", "width": 130},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 220},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
	]
	return cols, rows
