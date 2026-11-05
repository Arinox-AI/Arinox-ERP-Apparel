# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class TNATemplate(Document):
	def validate(self):
		codes = [r.milestone_type for r in self.milestones]
		if len(set(codes)) != len(codes):
			frappe.throw(_("A milestone can appear only once in a template."))
		for r in self.milestones:
			if r.basis == "After Milestone":
				if not r.after_milestone:
					frappe.throw(_("Row {0}: choose the milestone this one follows.").format(r.idx))
				if r.after_milestone == r.milestone_type:
					frappe.throw(_("Row {0}: a milestone cannot follow itself.").format(r.idx))
				if r.after_milestone not in codes:
					frappe.throw(_("Row {0}: {1} is not in this template.").format(r.idx, r.after_milestone))
			if r.duration_rule == "Qty / Daily Output" and cint(r.daily_output) <= 0:
				frappe.throw(_("Row {0}: enter the daily output.").format(r.idx))
		self.check_no_loop()
		if cint(self.is_default):
			for other in frappe.get_all("TNA Template", {"is_default": 1, "name": ["!=", self.name or ""]}, pluck="name"):
				frappe.db.set_value("TNA Template", other, "is_default", 0)

	def check_no_loop(self):
		after = {r.milestone_type: r.after_milestone for r in self.milestones if r.basis == "After Milestone"}
		for start in after:
			seen, cur = set(), start
			while cur in after:
				if cur in seen:
					frappe.throw(_("The milestones {0} follow each other in a loop.").format(", ".join(sorted(seen))))
				seen.add(cur)
				cur = after[cur]
