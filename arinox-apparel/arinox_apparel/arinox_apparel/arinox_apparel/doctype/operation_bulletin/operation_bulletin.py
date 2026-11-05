# Copyright (c) 2026, Arinox AI and contributors
"""Operation Bulletin (OB): the operations of a style with their times (SAM). It sets the daily target of a line and
the capacity used to load orders. Targets are computed from the working minutes stored here; the company's sheet divides
the hourly target by 9.5 hours whatever the working time, which this does not copy."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.production import maths

BAND = 0.15  # an operation within +-15 % of the pitch time is balanced


class OperationBulletin(Document):
	def validate(self):
		if cint(self.operators) <= 0:
			frappe.throw(_("Enter the number of operators."))
		minutes = cint(self.working_minutes) or cint(frappe.db.get_single_value("Apparel Settings", "work_minutes_per_day") or 480)
		eff = flt(self.expected_efficiency_pct) or flt(frappe.db.get_single_value("Apparel Settings", "planned_efficiency_pct") or 65)
		self.working_minutes, self.expected_efficiency_pct = minutes, eff
		timed = []
		for o in self.operations:
			if flt(o.machine_sam) < 0 or flt(o.manual_sam) < 0:
				frappe.throw(_("Row {0}: a time cannot be negative.").format(o.idx))
			if flt(o.machine_sam) + flt(o.manual_sam) > 0:
				timed.append(o)
		self.operation_count = len(timed)
		self.sewing_sam = round(sum(flt(o.machine_sam) for o in timed), 3)
		self.manual_sam = round(sum(flt(o.manual_sam) for o in timed), 3)
		self.total_sam = round(self.sewing_sam + self.manual_sam, 3)
		self.target_per_day = round(maths.day_target(self.operators, minutes, eff, self.total_sam), 2)
		self.target_per_hour = round(maths.hour_target(self.operators, minutes, eff, self.total_sam), 2)
		self.pcs_per_machine = round(maths.pcs_per_machine_per_day(minutes, eff, self.total_sam), 4)
		self.pitch_time = round(self.total_sam / len(timed), 3) if timed else 0
		for o in self.operations:
			sam = flt(o.machine_sam) + flt(o.manual_sam)
			if sam <= 0:
				o.target_per_hr, o.operators_needed, o.pitch_flag = 0, 0, ""
				continue
			o.target_per_hr = round(maths.operation_target_per_hour(sam, eff), 2)
			o.operators_needed = round(self.target_per_hour / o.target_per_hr, 2) if o.target_per_hr else 0
			o.pitch_flag = "Above" if sam > self.pitch_time * (1 + BAND) else ("Below" if sam < self.pitch_time * (1 - BAND) else "")

	@frappe.whitelist()
	def activate(self):
		if flt(self.total_sam) <= 0:
			frappe.throw(_("Add the operation times before activating."))
		for n in frappe.get_all("Operation Bulletin", {"style_item": self.style_item, "status": "Active", "name": ["!=", self.name]}, pluck="name"):
			frappe.db.set_value("Operation Bulletin", n, "status", "Superseded")
		self.db_set("status", "Active")
		return "Active"
