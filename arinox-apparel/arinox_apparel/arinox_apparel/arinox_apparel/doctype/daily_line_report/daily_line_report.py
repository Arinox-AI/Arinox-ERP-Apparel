# Copyright (c) 2026, Arinox AI and contributors
"""Daily Line Report: what a sewing line passed at the end of the line in a day, with the manpower and time. Efficiency
is always computed from the operation bulletin: produced minutes = output x SAM, available minutes = operators x
(shift + overtime - downtime). Submitting posts SEW_OUT to the ledger."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.production import ledger, maths, sewing


class DailyLineReport(Document):
	def validate(self):
		if cint(self.operators_present) <= 0:
			frappe.throw(_("Enter the operators present."))
		if min(cint(self.overtime_minutes), cint(self.downtime_minutes), cint(self.helpers_present)) < 0:
			frappe.throw(_("Overtime, downtime and helpers cannot be negative."))
		if cint(self.downtime_minutes) and not self.downtime_reason:
			frappe.throw(_("Choose the downtime reason."))
		if not self.outputs:
			frappe.throw(_("Enter the output."))
		styles, cards = {}, {}
		for r in self.outputs:
			if cint(r.qty) <= 0:
				frappe.throw(_("Row {0}: enter a quantity above zero.").format(r.idx))
			card = cards.get(r.production_card) or frappe.db.get_value("Production Card", r.production_card, ["docstatus", "status", "style_item"], as_dict=True)
			cards[r.production_card] = card
			if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
				frappe.throw(_("Row {0}: production card {1} must be issued and open.").format(r.idx, r.production_card))
			if not frappe.db.exists("Production Card Line", {"parent": r.production_card, "colour": r.colour, "size": r.size}):
				frappe.throw(_("Row {0}: {1} {2} is not on production card {3}.").format(r.idx, r.colour, r.size, r.production_card))
			styles[card.style_item] = styles.get(card.style_item, 0) + cint(r.qty)
			self.check_bundle(r)
		self.compute(styles)

	def check_bundle(self, r):
		require = cint(frappe.db.get_single_value("Apparel Settings", "require_bundle_on_output"))
		if not r.bundle:
			if require:
				frappe.throw(_("Row {0}: choose the bundle (Apparel Settings asks for bundles on output).").format(r.idx))
			return
		b = frappe.db.get_value("Cut Bundle", r.bundle, ["production_card", "colour", "size", "qty", "sewn_qty", "rejected_qty", "status", "line", "component"], as_dict=True)
		if not b or b.production_card != r.production_card or b.colour != r.colour or b.size != r.size:
			frappe.throw(_("Row {0}: bundle {1} is not {2} {3} of card {4}.").format(r.idx, r.bundle, r.colour, r.size, r.production_card))
		if b.status != "Issued" and self.docstatus == 0:
			frappe.throw(_("Row {0}: bundle {1} is {2}; only a bundle loaded on a line can be reported.").format(r.idx, r.bundle, b.status))
		if b.line and b.line != self.line:
			frappe.throw(_("Row {0}: bundle {1} is on line {2}, not {3}.").format(r.idx, r.bundle, b.line, self.line))
		if cint(b.sewn_qty) + cint(b.rejected_qty) + cint(r.qty) > cint(b.qty) and self.docstatus == 0:
			frappe.throw(_("Row {0}: bundle {1} has {2} pieces; {3} already reported.").format(r.idx, r.bundle, b.qty, cint(b.sewn_qty) + cint(b.rejected_qty)))

	def compute(self, styles):
		first_style = next(iter(styles))
		ob = sewing.active_ob(first_style)
		settings_minutes = cint(frappe.db.get_single_value("Apparel Settings", "work_minutes_per_day") or 480)
		self.shift_minutes = cint(self.shift_minutes) or (cint(ob.working_minutes) if ob else 0) or settings_minutes
		worked = max(self.shift_minutes + cint(self.overtime_minutes) - cint(self.downtime_minutes), 0)
		self.total_output = sum(cint(r.qty) for r in self.outputs)
		produced, missing = 0.0, []
		for style, qty in styles.items():
			o = sewing.active_ob(style)
			if not o or not flt(o.total_sam):
				missing.append(style)
				continue
			produced += qty * flt(o.total_sam)
		self.produced_minutes = round(produced, 2)
		workers = cint(self.operators_present) + cint(self.helpers_present)  # the OB total SAM includes helper time
		self.available_minutes = round(workers * worked, 2)
		self.efficiency_pct = round(maths.efficiency_pct(produced, self.available_minutes) or 0, 2)
		if missing and self.docstatus == 0:
			frappe.msgprint(_("No active Operation Bulletin for {0}: efficiency cannot include its output.").format(", ".join(missing)), indicator="orange")
		eff_plan = flt(ob.expected_efficiency_pct) if ob and flt(ob.expected_efficiency_pct) else flt(frappe.db.get_single_value("Apparel Settings", "planned_efficiency_pct") or 65)
		self.learning_day = sewing.learning_day(self.line, first_style, self.report_date)
		factor = maths.learning_factor(self.learning_day, sewing.curve())
		self.learning_factor_pct = round(factor * 100, 2)
		self.target_qty = round(maths.day_target(workers, worked, eff_plan, flt(ob.total_sam)) * factor, 1) if ob and flt(ob.total_sam) else 0
		self.variance_to_target = round(self.total_output - flt(self.target_qty), 1)
		hourly = sum(cint(h.output_qty) for h in self.hours)
		if self.hours and hourly != self.total_output and self.docstatus == 0:
			frappe.msgprint(_("The hourly output ({0}) does not add up to the day's output ({1}).").format(hourly, self.total_output), indicator="orange")

	def rows(self):
		return [{"stage": "SEW_OUT", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": r.purpose or "Bulk", "line": self.line, "source_row": r.name}
				for r in self.outputs]

	def post_movements(self, check=False):
		by_card = {}
		for r, row in zip(self.outputs, self.rows()):
			by_card.setdefault(r.production_card, []).append(row)
		for card, rows in by_card.items():
			ledger.post(card, rows, "Daily Line Report", self.name, self.report_date, check=check)

	def on_submit(self):
		self.post_movements(check=True)
		for r in self.outputs:
			if r.bundle:
				self.move_bundle(r.bundle, cint(r.qty))

	def move_bundle(self, name, qty):
		b = frappe.db.get_value("Cut Bundle", name, ["qty", "sewn_qty", "rejected_qty"], as_dict=True)
		sewn = max(cint(b.sewn_qty) + qty, 0)
		vals = {"sewn_qty": sewn}
		vals["status"] = "Complete" if sewn + cint(b.rejected_qty) >= cint(b.qty) else "Issued"
		frappe.db.set_value("Cut Bundle", name, vals)

	def on_cancel(self):
		ledger.unpost("Daily Line Report", self.name)
		for r in self.outputs:
			if r.bundle:
				self.move_bundle(r.bundle, -cint(r.qty))
