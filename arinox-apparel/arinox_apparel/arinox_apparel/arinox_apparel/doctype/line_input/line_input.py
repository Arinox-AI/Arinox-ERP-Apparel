# Copyright (c) 2026, Arinox AI and contributors
"""Line Input: cut bundles loaded onto a sewing line (the company's line loading). Submitting posts SEW_IN to the
ledger and marks the bundles Issued."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from arinox_apparel.production import cutting, ledger

LOADABLE = ("Cut", "Back")


class LineInput(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status", "sales_order", "style_item"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		self.card = card
		require = cint(frappe.db.get_single_value("Apparel Settings", "require_bundle_on_input"))
		seen = set()
		for r in self.bundles:
			if r.bundle:
				self.fill_from_bundle(r, seen)
			elif require:
				frappe.throw(_("Row {0}: choose the bundle (Apparel Settings asks for bundles on every line input).").format(r.idx))
			else:
				if not (r.colour and r.size and cint(r.qty) > 0):
					frappe.throw(_("Row {0}: enter colour, size and quantity.").format(r.idx))
				if not frappe.db.exists("Production Card Line", {"parent": self.production_card, "colour": r.colour, "size": r.size}):
					frappe.throw(_("Row {0}: {1} {2} is not on production card {3}.").format(r.idx, r.colour, r.size, self.production_card))
		self.total_qty = sum(cint(r.qty) for r in self.bundles if (r.component or "Shell") == "Shell")
		self.check_line()
		self.check_kits()

	def fill_from_bundle(self, r, seen):
		if r.bundle in seen:
			frappe.throw(_("Bundle {0} appears twice.").format(r.bundle))
		seen.add(r.bundle)
		b = frappe.db.get_value("Cut Bundle", r.bundle, ["production_card", "colour", "size", "qty", "component", "shade_band", "status", "purpose", "sewn_qty"], as_dict=True)
		if not b or b.production_card != self.production_card:
			frappe.throw(_("Row {0}: bundle {1} belongs to another production card.").format(r.idx, r.bundle))
		if b.status not in LOADABLE and not (self.docstatus == 1):
			frappe.throw(_("Row {0}: bundle {1} is {2}; only cut bundles (or bundles back from a panel process) can be loaded.").format(r.idx, r.bundle, b.status))
		if b.purpose != self.purpose:
			frappe.throw(_("Row {0}: bundle {1} is a {2} bundle; this input is {3}.").format(r.idx, r.bundle, b.purpose, self.purpose))
		before = [p for p in frappe.get_all("Production Card Process", {"parent": self.production_card, "position": "Before Sewing"}, ["subcontract_process", "colour"])
				  if not (p.colour or "").strip() or (p.colour or "").strip().upper() == (b.colour or "").strip().upper()]
		if before and b.status != "Back":
			frappe.throw(_("Row {0}: bundle {1} must go to {2} and come back before it is loaded.").format(r.idx, r.bundle, ", ".join(p.subcontract_process for p in before)))
		r.colour, r.size, r.qty, r.component, r.shade_band = b.colour, b.size, b.qty, b.component, b.shade_band

	def check_line(self):
		fa = frappe.db.get_value("Factory Allocation", {"sales_order": self.card.sales_order}, "name")
		if not fa:
			return
		lines = {r.line for r in frappe.get_all("Factory Allocation Line", {"parent": fa, "style_item": self.card.style_item}, ["line"]) if r.line}
		if lines and self.line not in lines and self.docstatus == 0:
			frappe.msgprint(_("Line {0} is not the line allocated to this style ({1}).").format(self.line, ", ".join(sorted(lines))), indicator="orange")

	def check_kits(self):
		mode = frappe.db.get_single_value("Apparel Settings", "kit_check") or "Warn"
		if mode == "Off":
			return
		missing = cutting.kit_missing([r.bundle for r in self.bundles if r.bundle])
		if missing:
			msg = _("Matching lining / pocketing bundles are missing for: {0}").format(", ".join(missing[:6]))
			if mode == "Block":
				frappe.throw(msg)
			frappe.msgprint(msg, indicator="orange")

	def rows(self):
		out = []
		for r in self.bundles:
			if (r.component or "Shell") != "Shell":
				continue
			out.append({"stage": "SEW_IN", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": self.purpose, "line": self.line,
						"shade_band": r.shade_band, "source_row": r.name})
		return out

	def on_submit(self):
		self.post_movements(check=True)
		for r in self.bundles:
			if r.bundle:
				frappe.db.set_value("Cut Bundle", r.bundle, {"status": "Issued", "line": self.line})

	def post_movements(self, check=False):
		ledger.post(self.production_card, self.rows(), "Line Input", self.name, self.input_date, check=check)

	def on_cancel(self):
		done = [r.bundle for r in self.bundles if r.bundle and cint(frappe.db.get_value("Cut Bundle", r.bundle, "sewn_qty")) > 0]
		if done:
			frappe.throw(_("Bundles {0} already have sewn output. Cancel the line reports first.").format(", ".join(done[:5])))
		ledger.unpost("Line Input", self.name)
		for r in self.bundles:
			if r.bundle:
				back = frappe.db.exists("Production Card Process", {"parent": self.production_card, "position": "Before Sewing"})
				frappe.db.set_value("Cut Bundle", r.bundle, {"status": "Back" if back else "Cut", "line": None})
