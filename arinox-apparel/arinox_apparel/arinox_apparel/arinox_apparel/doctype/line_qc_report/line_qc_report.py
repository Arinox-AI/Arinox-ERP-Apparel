# Copyright (c) 2026, Arinox AI and contributors
"""Line QC Report: the end-line audit and the finishing inspection are the same hourly form (checked, passed, defects by
code), plus the inline traffic-light rounds. DHU = defects x 100 / checked. RFT = pieces passed first time / checked;
a repaired piece never counts toward RFT. Rejects and B-grade post to the production ledger."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.production import ledger, maths

END, FINISH, INLINE = "End-line", "Finishing", "Inline (Traffic Light)"


class LineQCReport(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		for h in self.hours:
			if cint(h.checked) < 0 or cint(h.passed) < 0 or cint(h.passed) > cint(h.checked):
				frappe.throw(_("Hour {0}: passed cannot be more than checked, and neither can be negative.").format(h.hour_slot))
		self.total_checked = sum(cint(h.checked) for h in self.hours)
		self.total_passed = sum(cint(h.passed) for h in self.hours)
		self.total_defects = sum(cint(d.qty) for d in self.defects)
		for d in self.defects:
			if cint(d.qty) <= 0:
				frappe.throw(_("Defect {0}: enter a quantity above zero.").format(d.defect_code))
		self.dhu = round(maths.dhu(self.total_defects, self.total_checked) or 0, 2)
		self.defect_pct = round(maths.pct(self.total_checked - self.total_passed, self.total_checked) or 0, 2)
		self.rft_pct = round(maths.rft(self.total_passed, self.total_checked) or 0, 2)
		if self.dhu > flt(frappe.db.get_single_value("Apparel Settings", "dhu_alert_threshold") or 5) and self.docstatus == 0:
			frappe.msgprint(_("DHU {0} is above the alert level.").format(self.dhu), indicator="orange")
		self.check_dispositions()
		self.check_passes()
		self.check_traffic()

	def check_dispositions(self):
		for r in self.dispositions:
			r.production_card = self.production_card
			if cint(r.qty) <= 0:
				frappe.throw(_("Disposition row {0}: enter a quantity above zero.").format(r.idx))
			if not frappe.db.exists("Production Card Line", {"parent": self.production_card, "colour": r.colour, "size": r.size}):
				frappe.throw(_("Disposition row {0}: {1} {2} is not on production card {3}.").format(r.idx, r.colour, r.size, self.production_card))
			if r.disposition == "B-Grade" and self.audit_type != FINISH:
				frappe.throw(_("Disposition row {0}: B-grade is decided at finishing, not at {1}.").format(r.idx, self.audit_type))
			if cint(r.replace) and r.disposition != "Reject":
				frappe.throw(_("Disposition row {0}: only a rejected piece needs a re-cut.").format(r.idx))
			if cint(r.replace) and not r.defect_code:
				frappe.throw(_("Disposition row {0}: choose the defect to raise the re-cut request.").format(r.idx))
		if self.audit_type == INLINE and any(r.disposition in ("Reject", "B-Grade") for r in self.dispositions):
			pass  # pieces found scrap during an inline round are still scrap

	def check_passes(self):
		if self.audit_type != FINISH:
			return
		total = sum(cint(p.qty) for p in self.passes)
		for p in self.passes:
			if not frappe.db.exists("Production Card Line", {"parent": self.production_card, "colour": p.colour, "size": p.size}):
				frappe.throw(_("Passed row {0}: {1} {2} is not on production card {3}.").format(p.idx, p.colour, p.size, self.production_card))
		if self.hours and total != self.total_passed:
			frappe.throw(_("The A-grade pieces by colour and size ({0}) must equal the pieces passed in the hourly check ({1}).").format(total, self.total_passed))

	def check_traffic(self):
		rules = [(r.colour, r.defects_from) for r in frappe.get_all("Traffic Light Rule", {"parent": "Apparel Settings", "parentfield": "traffic_light_rules"}, ["colour", "defects_from"])]
		reds = 0
		for t in self.traffic:
			t.light = maths.traffic_colour(cint(t.defects), rules)
			reds += 1 if t.light == "Red" else 0
		if reds and self.docstatus == 0:
			frappe.msgprint(_("{0} operator(s) are red. Retrain or re-set the operation before the next round.").format(reds), indicator="red")

	def rows(self):
		out = []
		if self.audit_type == FINISH:
			for p in self.passes:
				out.append({"stage": "FIN_A", "colour": p.colour, "size": p.size, "qty": cint(p.qty), "line": self.line, "source_row": p.name})
		for r in self.dispositions:
			stage = None
			if r.disposition == "Reject":
				stage = "FIN_REJECT" if self.audit_type == FINISH else "SEW_REJECT"
			elif r.disposition == "B-Grade":
				stage = "FIN_B"
			if stage:
				out.append({"stage": stage, "colour": r.colour, "size": r.size, "qty": cint(r.qty), "line": self.line, "fault_source": r.fault_source, "source_row": r.name})
		return out

	def post_movements(self, check=False):
		ledger.post(self.production_card, self.rows(), "Line QC Report", self.name, self.report_date, check=check)

	def on_submit(self):
		self.post_movements(check=True)
		self.raise_recuts()

	def raise_recuts(self):
		wanted = {}
		for r in self.dispositions:
			if cint(r.replace) and r.disposition == "Reject":
				k = (r.colour, r.size, r.defect_code)
				wanted[k] = wanted.get(k, 0) + cint(r.qty)
		for (colour, size, defect), qty in wanted.items():
			d = frappe.get_doc({"doctype": "Recut Request", "production_card": self.production_card, "colour": colour, "size": size, "qty": qty,
								"reason": defect, "remarks": _("Raised by {0}").format(self.name)})
			d.flags.ignore_permissions = True
			try:
				d.insert()
			except frappe.ValidationError:
				frappe.log_error(title="Recut request from QC report failed", message=frappe.get_traceback())

	def on_cancel(self):
		ledger.unpost("Line QC Report", self.name)
