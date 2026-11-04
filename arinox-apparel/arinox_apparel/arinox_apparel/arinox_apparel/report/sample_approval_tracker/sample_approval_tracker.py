# Copyright (c) 2026, Arinox AI and contributors
"""One row per Sales Order x style x colour: the status of every gating sample type, the next due date,
overdue count and whether the bulk gate is open."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import get_order_lines
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import (
	GATE_OK,
	DEFAULT_RULES,
	effective_gate,
	get_rules,
	norm,
	scope_filters,
)
from arinox_apparel.overrides.work_order import get_bulk_gate


def key(stype):
	return "t_" + "".join(c if c.isalnum() else "_" for c in stype.lower())


def execute(filters=None):
	filters = frappe._dict(filters or {})
	base = get_rules()
	types = [t for t in base if base[t].gate != "No"] + [
		t for t in frappe.get_all("Sample Requirement", {"enabled": 1, "gate": ["in", ["Required", "If Raised"]]}, pluck="sample_type")
		if base.get(t) and base[t].gate == "No"
	]
	types = list(dict.fromkeys(types))
	columns = [
		{"fieldname": "sales_order", "label": _("Sales Order"), "fieldtype": "Link", "options": "Sales Order", "width": 140},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 130},
		{"fieldname": "style_item", "label": _("Style"), "fieldtype": "Link", "options": "Item", "width": 120},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 90},
	]
	columns += [{"fieldname": key(t), "label": _(t), "fieldtype": "Data", "width": 110} for t in types]
	columns += [
		{"fieldname": "next_due", "label": _("Next Due"), "fieldtype": "Date", "width": 100},
		{"fieldname": "overdue", "label": _("Overdue"), "fieldtype": "Int", "width": 70},
		{"fieldname": "gate", "label": _("Bulk Gate"), "fieldtype": "Data", "width": 90},
	]
	so_filters = {"docstatus": 1}
	if filters.sales_order:
		so_filters["name"] = filters.sales_order
	if filters.customer:
		so_filters["customer"] = filters.customer
	today, data = getdate(nowdate()), []
	for so in frappe.get_all("Sales Order", so_filters, ["name", "customer"], order_by="transaction_date desc", limit=200):
		item_of = {}
		for it in frappe.get_all("Sales Order Item", {"parent": so.name}, ["item_code", "apparel_colour"]):
			style = frappe.db.get_value("Item", it.item_code, "variant_of")
			if style:
				item_of.setdefault((style, (it.apparel_colour or "").strip()), it.item_code)
		for (style, colour), item_code in item_of.items():
			samples = frappe.get_all(
				"Sample Approval", scope_filters(so.name, style), ["name", "sample_type", "status", "colour", "due_date"]
			)
			row = {"sales_order": so.name, "customer": so.customer, "style_item": style, "colour": colour}
			dues, overdue = [], 0
			rules = get_rules(so.customer, so.name, style)
			for stype in types:
				rule = rules[stype]
				gate_type = effective_gate(rule, so.name)
				mine = [s for s in samples if s.sample_type == stype
						and (not rule.per_colour or not (s.colour or "").strip() or norm(s.colour) == norm(colour))]
				bad = [s for s in mine if s.status not in GATE_OK]
				row[key(stype)] = (bad[0].status if bad else "Approved" if mine else "Missing" if gate_type == "Required" else "-")
				for s in bad:
					if s.due_date:
						dues.append(getdate(s.due_date))
						overdue += getdate(s.due_date) < today
			gate = get_bulk_gate(item_code, so.name)
			row.update(next_due=min(dues) if dues else None, overdue=overdue, gate="Open" if not gate["blockers"] else "Blocked")
			if filters.only_blocked and row["gate"] == "Open":
				continue
			data.append(row)
	return columns, data
