# Copyright (c) 2026, Arinox AI and contributors
"""Sewing WIP: pieces loaded, sewn and rejected per line and production card; WIP = loaded - sewn - rejected."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "line", "label": _("Line"), "fieldtype": "Link", "options": "Workstation", "width": 160},
		{"fieldname": "production_card", "label": _("Production Card"), "fieldtype": "Link", "options": "Production Card", "width": 130},
		{"fieldname": "style_no", "label": _("Style"), "fieldtype": "Data", "width": 110},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 90},
		{"fieldname": "loaded", "label": _("Loaded"), "fieldtype": "Int", "width": 80},
		{"fieldname": "sewn", "label": _("Sewn"), "fieldtype": "Int", "width": 80},
		{"fieldname": "rejected", "label": _("Rejected"), "fieldtype": "Int", "width": 80},
		{"fieldname": "wip", "label": _("WIP"), "fieldtype": "Int", "width": 80},
	]
	cond, args = "", {}
	for key in ("line", "production_card"):
		if filters.get(key):
			cond += f" and m.{key} = %({key})s"
			args[key] = filters[key]
	rows = frappe.db.sql(
		f"""select m.line, m.production_card, c.style_no, m.colour,
		sum(case when m.stage = 'SEW_IN' then m.qty else 0 end) loaded, sum(case when m.stage = 'SEW_OUT' then m.qty else 0 end) sewn,
		sum(case when m.stage = 'SEW_REJECT' then m.qty else 0 end) rejected
		from `tabProduction Movement` m join `tabProduction Card` c on c.name = m.production_card
		where m.stage in ('SEW_IN', 'SEW_OUT', 'SEW_REJECT') and m.line is not null{cond}
		group by m.line, m.production_card, m.colour order by m.line, c.style_no, m.colour""", args, as_dict=True)
	for r in rows:
		r.wip = r.loaded - r.sewn - r.rejected
	return columns, [r for r in rows if r.loaded or r.wip]
