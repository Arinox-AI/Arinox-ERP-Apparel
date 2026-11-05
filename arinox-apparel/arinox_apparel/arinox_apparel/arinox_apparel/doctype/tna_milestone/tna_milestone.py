# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""One milestone of one Order TNA. A plain doctype (not a child table) so the Calendar, Gantt, Kanban and Report views work on it."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate

from arinox_apparel.tna.status import COLOURS, milestone_state, refresh_order_tna


class TNAMilestone(Document):
	def validate(self):
		tna = frappe.db.get_value("Order TNA", self.order_tna, ["sales_order", "style_no", "colour", "factory", "baseline_locked", "customer", "status"], as_dict=True)
		if not tna:
			frappe.throw(_("Order T&A {0} does not exist.").format(self.order_tna))
		self.sales_order, self.style_no, self.colour, self.factory, self.customer = tna.sales_order, tna.style_no, tna.colour, tna.factory, tna.customer
		mt = frappe.get_cached_doc("TNA Milestone Type", self.milestone_type)
		self.label = self.label or mt.label
		self.department = self.department or mt.department
		if self.planned_date and not self.planned_start:
			self.planned_start = self.planned_date
		if self.planned_start and self.planned_date and getdate(self.planned_start) > getdate(self.planned_date):
			self.planned_start = self.planned_date
		if cint(tna.baseline_locked) and not self.is_new() and self.has_value_changed("planned_date") and not self.flags.baseline_move:
			frappe.throw(_("The baseline is locked. Use the Revised Date (with a reason) to move this milestone."))
		if self.revised_date and self.planned_date and getdate(self.revised_date) != getdate(self.planned_date) and not (self.revision_reason or "").strip() and not self.actual_date:
			frappe.throw(_("Enter the reason for the revised date."))
		if self.actual_date and getdate(self.actual_date) > getdate(frappe.utils.nowdate()):
			frappe.throw(_("The actual date cannot be in the future."))
		self.status, self.delay_days, self.progress = milestone_state(self.not_applicable, self.actual_date, self.partial, self.planned_date, self.revised_date)
		self.color = COLOURS[self.status]

	def on_update(self):
		refresh_order_tna(self.order_tna)

	def on_trash(self):
		refresh_order_tna(self.order_tna)


@frappe.whitelist()
def get_events(start, end, filters=None):
	"""Calendar events for the Calendar view: one per milestone, coloured by its current status."""
	import json

	flt_ = json.loads(filters) if isinstance(filters, str) and filters else (filters or [])
	rows = frappe.get_list("TNA Milestone", filters=[*flt_, ["planned_date", "<=", end], ["planned_date", ">=", start]],
		fields=["name", "label", "style_no", "colour", "planned_start", "planned_date", "revised_date", "actual_date", "status", "color", "not_applicable"])
	out = []
	for r in rows:
		if cint(r.not_applicable):
			continue
		date = r.actual_date or r.revised_date or r.planned_date
		out.append({"name": r.name, "title": f"{r.style_no or ''} {r.colour or ''}: {r.label}".strip(), "start": str(date), "end": str(date), "allDay": 1,
			"color": r.color or COLOURS.get(r.status), "status": r.status})
	return out
