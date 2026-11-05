# Copyright (c) 2026, Arinox AI and contributors
"""Needle Detector Log: one row per calibration check of the metal detector. A failed check means everything passed
since the last good check is scanned again; until that is logged, nothing from the line may be packed."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate


class NeedleDetectorLog(Document):
	def validate(self):
		if self.result == "Fail":
			if not (self.action or "").strip():
				frappe.throw(_("A failed check needs the action taken."))
			if self.rescan_done and not cint(self.garments_rescanned):
				frappe.throw(_("Enter how many garments were scanned again."))
		else:
			self.rescan_done = 0


def needle_problems(line, on_date):
	"""Reasons packing on `on_date` must wait, for a line. Empty when the detector record is in order."""
	mode = frappe.db.get_single_value("Apparel Settings", "needle_check_required") or "Off"
	if mode == "Off":
		return [], mode
	day = getdate(on_date)
	filters = {"line": line} if line else {}
	problems = []
	if not frappe.db.exists("Needle Detector Log", dict(filters, check_date=day, result="Pass")):
		problems.append(_("No passing needle detector check is logged for {0} on {1}.").format(line or _("any line"), day))
	failed = frappe.get_all("Needle Detector Log", dict(filters, result="Fail", rescan_done=0, check_date=[">=", add_days(day, -7)]), pluck="name")
	if failed:
		problems.append(_("Failed detector check(s) {0} have no re-scan logged.").format(", ".join(failed)))
	return problems, mode
