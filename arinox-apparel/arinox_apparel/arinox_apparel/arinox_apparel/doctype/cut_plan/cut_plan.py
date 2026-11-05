# Copyright (c) 2026, Arinox AI and contributors
"""Cut Plan (lay plan): which markers, size ratios and plies make up the cut quantity of one colour and fabric. A plan
whose marker consumption differs from the card's by more than the setting needs a manager before it is released."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from arinox_apparel.materials import common as mc
from arinox_apparel.production import cutting

MANAGERS = {"Apparel Production Manager", "Apparel Merchandising Manager", "System Manager"}


class CutPlan(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		fabric = frappe.db.get_value("Production Card Fabric", {"parent": self.production_card, "colour": self.colour, "fabric_item": self.fabric_item},
									 ["consumption", "consumption_uom"], as_dict=True)
		if not fabric:
			frappe.throw(_("{0} is not a fabric of colour {1} on production card {2}.").format(self.fabric_item, self.colour, self.production_card))
		self.fr_consumption = mc.to_metres(flt(fabric.consumption), fabric.consumption_uom or "Meter")
		sizes = {l.size: l for l in frappe.get_all("Production Card Line", {"parent": self.production_card, "colour": self.colour}, ["size", "planned_cut_qty"])}
		if not sizes:
			frappe.throw(_("Colour {0} is not on production card {1}.").format(self.colour, self.production_card))
		lay_nos = [l.lay_no for l in self.lays]
		if len(set(lay_nos)) != len(lay_nos):
			frappe.throw(_("A lay number appears twice."))
		by_lay = {}
		for r in self.ratios:
			if r.size not in sizes:
				frappe.throw(_("Ratio row {0}: size {1} is not on the production card for {2}.").format(r.idx, r.size, self.colour))
			if cint(r.ratio) <= 0:
				frappe.throw(_("Ratio row {0}: pieces per ply must be above zero.").format(r.idx))
			if r.lay_no not in lay_nos:
				frappe.throw(_("Ratio row {0}: lay {1} is not in the lay list.").format(r.idx, r.lay_no))
			d = by_lay.setdefault(r.lay_no, {})
			if r.size in d:
				frappe.throw(_("Lay {0} lists size {1} twice.").format(r.lay_no, r.size))
			d[r.size] = cint(r.ratio)
		flags, output = [], {s: 0 for s in sizes}
		laid = pieces = 0.0
		for l in self.lays:
			if flt(l.marker_length_m) <= 0 or cint(l.planned_plies) <= 0:
				frappe.throw(_("Lay {0}: marker length and plies must be above zero.").format(l.lay_no))
			ratios = by_lay.get(l.lay_no)
			if not ratios:
				frappe.throw(_("Lay {0} has no size ratios.").format(l.lay_no))
			l.pieces_per_ply = sum(ratios.values())
			l.planned_pieces = l.pieces_per_ply * cint(l.planned_plies)
			laid += flt(l.marker_length_m) * cint(l.planned_plies)
			pieces += l.planned_pieces
			for s, n in ratios.items():
				output[s] += n * cint(l.planned_plies)
		self.marker_consumption = round(laid / pieces, 4) if pieces else 0
		self.variance_pct = round((self.marker_consumption - self.fr_consumption) / self.fr_consumption * 100, 2) if self.fr_consumption and pieces else 0
		extra = cint(frappe.db.get_single_value("Apparel Settings", "cut_cap_extra_pcs") or 3)
		text = []
		for s, line in sorted(sizes.items()):
			plan_q, got = cint(line.planned_cut_qty), output[s]
			text.append(f"{s}: plan {plan_q}, lays {got} ({got - plan_q:+d})")
			if self.lays and got == 0:
				flags.append(_("Size {0} is on the card but in no lay.").format(s))
			elif got > plan_q + extra:
				flags.append(_("Size {0}: lays cut {1} more than planned ({2}).").format(s, got - plan_q, got))
			elif self.lays and got < plan_q:
				flags.append(_("Size {0}: lays cut {1} fewer than planned.").format(s, plan_q - got))
		self.size_summary = "\n".join(text)
		limit = flt(frappe.db.get_single_value("Apparel Settings", "marker_variance_pct") or 5)
		if abs(flt(self.variance_pct)) > limit:
			flags.append(_("Marker consumption {0} differs from the card's {1} by {2}% (limit {3}%).").format(self.marker_consumption, round(self.fr_consumption, 4), self.variance_pct, limit))
		self.red_flags = "\n".join(flags)

	@frappe.whitelist()
	def release(self):
		"""Release the plan. A variance above the limit sends it to a manager instead."""
		self.save()
		limit = flt(frappe.db.get_single_value("Apparel Settings", "marker_variance_pct") or 5)
		if not self.lays:
			frappe.throw(_("Add at least one lay."))
		if abs(flt(self.variance_pct)) > limit and not self.approved_by:
			self.db_set("status", "Pending Approval")
			frappe.msgprint(_("Marker consumption is outside the {0}% limit. A manager must approve the plan.").format(limit), indicator="orange")
		else:
			self.db_set("status", "Released")
		return self.status

	@frappe.whitelist()
	def approve(self, note=None):
		if not (MANAGERS & set(frappe.get_roles())):
			frappe.throw(_("Only a production or merchandising manager can approve the marker consumption."))
		if not (note or self.approval_note or "").strip():
			frappe.throw(_("Write the reason for accepting this marker consumption."))
		self.db_set({"approved_by": frappe.session.user, "approved_on": now_datetime(), "approval_note": note or self.approval_note, "status": "Released"})
		return "Released"

	@frappe.whitelist()
	def reopen(self):
		used = frappe.db.exists("Lay Report", {"cut_plan": self.name, "docstatus": 1})
		if used:
			frappe.throw(_("Lay {0} is already cut from this plan. Make a new plan instead.").format(used))
		self.db_set({"status": "Draft", "approved_by": None, "approved_on": None})

	@frappe.whitelist()
	def suggest_rolls(self):
		return cutting.suggest_rolls(self.name)
