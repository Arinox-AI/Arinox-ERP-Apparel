# Copyright (c) 2026, Arinox AI and contributors
"""Line Loading: garments loaded onto each line per day and cumulative (the company's LINE LOADING REPORT)."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.to_date or nowdate())
	from_date = getdate(filters.from_date or add_days(to_date, -6))
	columns = [
		{"fieldname": "line", "label": _("Line"), "fieldtype": "Link", "options": "Workstation", "width": 160},
		{"fieldname": "style_no", "label": _("Style"), "fieldtype": "Data", "width": 120},
		{"fieldname": "production_card", "label": _("Production Card"), "fieldtype": "Link", "options": "Production Card", "width": 130},
		{"fieldname": "loaded", "label": _("Loaded in Period"), "fieldtype": "Int", "width": 120},
		{"fieldname": "cumulative", "label": _("Cumulative"), "fieldtype": "Int", "width": 100},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 200},
	]
	cond, args = "", {"f": from_date, "t": to_date}
	if filters.line:
		cond += " and m.line = %(line)s"
		args["line"] = filters.line
	if filters.production_card:
		cond += " and m.production_card = %(production_card)s"
		args["production_card"] = filters.production_card
	rows = frappe.db.sql(
		f"""select m.line, c.style_no, m.production_card,
		sum(case when m.posting_date between %(f)s and %(t)s then m.qty else 0 end) loaded, sum(case when m.posting_date <= %(t)s then m.qty else 0 end) cumulative
		from `tabProduction Movement` m join `tabProduction Card` c on c.name = m.production_card
		where m.stage = 'SEW_IN' and m.line is not null{cond} group by m.line, m.production_card order by m.line, c.style_no""", args, as_dict=True)
	return columns, [r for r in rows if r.loaded or r.cumulative]
