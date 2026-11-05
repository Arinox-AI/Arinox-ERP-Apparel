# Copyright (c) 2026, Arinox AI and contributors
"""Daily Production Report: cut, sewn, sent to and received from subcontractors, finished, packed and shipped per
production card x colour for a date, with running totals. Replaces the company's DAILY PROD REPORT sheet; read from the ledger."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

STAGES = [("cut", "CUT", _("Cut")), ("sew", "SEW_OUT", _("Sewn")), ("sent", "SC_OUT", _("Sent Out")), ("back", "SC_BACK_GOOD", _("Received Back")),
		  ("fin", "FIN_A", _("Finished A")), ("packed", "PACKED", _("Packed")), ("shipped", "SHIPPED", _("Shipped"))]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	day = getdate(filters.date or nowdate())
	columns = [
		{"fieldname": "production_card", "label": _("Production Card"), "fieldtype": "Link", "options": "Production Card", "width": 130},
		{"fieldname": "customer", "label": _("Buyer"), "fieldtype": "Data", "width": 110},
		{"fieldname": "style_no", "label": _("Style"), "fieldtype": "Data", "width": 110},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 90},
		{"fieldname": "order_qty", "label": _("Order Qty"), "fieldtype": "Int", "width": 80},
	]
	for key, _stage, label in STAGES:
		columns.append({"fieldname": f"{key}_today", "label": _("{0} Today").format(label), "fieldtype": "Int", "width": 90})
		columns.append({"fieldname": f"{key}_total", "label": _("{0} Total").format(label), "fieldtype": "Int", "width": 90})
	columns += [
		{"fieldname": "rejects", "label": _("Rejects"), "fieldtype": "Int", "width": 80},
		{"fieldname": "rejection_pct", "label": _("Rejection %"), "fieldtype": "Percent", "width": 95},
		{"fieldname": "cut_to_ship", "label": _("Cut to Ship"), "fieldtype": "Percent", "width": 90},
	]
	cond, args = ["c.docstatus = 1", "c.status not in ('Superseded', 'Cancelled', 'Closed')"], {}
	for key, col in (("production_card", "c.name"), ("customer", "c.customer"), ("sales_order", "c.sales_order")):
		if filters.get(key):
			cond.append(f"{col} = %({key})s")
			args[key] = filters[key]
	cards = frappe.db.sql(f"select c.name, c.customer, c.style_no from `tabProduction Card` c where {' and '.join(cond)} order by c.creation desc limit 200", args, as_dict=True)
	data = []
	for c in cards:
		colours = frappe.db.sql("select colour, sum(order_qty) from `tabProduction Card Line` where parent = %s group by colour order by min(idx)", c.name)
		for colour, order_qty in colours:
			row = {"production_card": c.name, "customer": c.customer, "style_no": c.style_no, "colour": colour, "order_qty": order_qty}
			for key, stage, _label in STAGES:
				tot, today = frappe.db.sql(
					"select ifnull(sum(qty), 0), ifnull(sum(case when posting_date = %s then qty else 0 end), 0) from `tabProduction Movement` where production_card = %s and colour = %s and stage = %s and purpose != 'Pilot'",
					(day, c.name, colour, stage))[0]
				row[f"{key}_total"], row[f"{key}_today"] = tot, today
			rej = flt(frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card = %s and colour = %s and stage in ('CUT_REJECT', 'SEW_REJECT', 'SC_BACK_REJECT_VENDOR', 'SC_BACK_REJECT_FACTORY', 'FIN_REJECT')", (c.name, colour))[0][0])
			row["rejects"] = rej
			row["rejection_pct"] = rej * 100 / row["cut_total"] if row["cut_total"] else None
			row["cut_to_ship"] = row["shipped_total"] * 100 / row["cut_total"] if row["cut_total"] else None
			if any(row[f"{k}_total"] for k, _s, _l in STAGES):
				data.append(row)
	return columns, data
