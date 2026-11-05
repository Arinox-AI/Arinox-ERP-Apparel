# Copyright (c) 2026, Arinox AI and contributors
"""Lay Report: one lay (a stack of plies under one marker) cut at one table. Submitting posts the cut pieces to the
production ledger, numbers the plies into Cut Bundles and returns what is left of each roll to the store.

The bulk gate is checked here, at the first bulk lay, not when the production card is issued."""

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from arinox_apparel.production import cutting, gate, ledger
from arinox_apparel.production.stock import cancel_entry, make_transfer, roll_available, setting

MANAGER_ROLES = {"Apparel Production Manager", "Apparel Merchandising Manager", "System Manager"}


class LayReport(Document):
	# ---- validation ------------------------------------------------------------------------------------------------
	def validate(self):
		self.check_card()
		self.apply_plan()
		self.check_override_fields()
		self.check_rolls()
		self.compute_sizes()
		self.check_panel_rejects()
		self.check_purpose()
		self.check_pairing()
		self.compute_totals()

	def check_card(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status", "style_item", "sales_order", "company"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		self.card = card
		lines = frappe.get_all("Production Card Line", {"parent": self.production_card, "colour": self.colour}, ["size"], pluck="size")
		if not lines:
			frappe.throw(_("Colour {0} is not on production card {1}.").format(self.colour, self.production_card))
		self.card_sizes = set(lines)
		if not frappe.db.exists("Production Card Fabric", {"parent": self.production_card, "colour": self.colour, "fabric_item": self.fabric_item}):
			frappe.throw(_("{0} is not a fabric of colour {1} on production card {2}.").format(self.fabric_item, self.colour, self.production_card))

	def apply_plan(self):
		self.plan_lay = None
		if not self.cut_plan:
			if self.purpose == "Bulk" and self.component == "Shell":
				frappe.msgprint(_("No cut plan chosen. Ratios and the marker are taken from what you enter here."), indicator="orange")
			return
		plan = frappe.get_doc("Cut Plan", self.cut_plan)
		if plan.production_card != self.production_card or (plan.colour or "").strip().upper() != (self.colour or "").strip().upper():
			frappe.throw(_("Cut plan {0} is for another production card or colour.").format(plan.name))
		if self.purpose == "Bulk" and plan.status != "Released":
			frappe.throw(_("Cut plan {0} is {1}. Release it before bulk cutting.").format(plan.name, plan.status))
		lay = next((l for l in plan.lays if l.lay_no == self.lay_no), None)
		if not lay:
			frappe.throw(_("Lay {0} is not in cut plan {1}.").format(self.lay_no, plan.name))
		self.plan_lay = lay
		ratios = {r.size: cint(r.ratio) for r in plan.ratios if r.lay_no == self.lay_no}
		if not self.marker_length_m:
			self.marker_length_m = lay.marker_length_m
		if not self.marker_width_cm:
			self.marker_width_cm = lay.marker_width_cm
		self.marker_ref = self.marker_ref or lay.marker_ref
		self.marker_efficiency_pct = self.marker_efficiency_pct or lay.marker_efficiency_pct
		if not self.sizes:
			for s, r in ratios.items():
				self.append("sizes", {"size": s, "ratio": r})
		for s in self.sizes:
			if s.size not in ratios:
				frappe.throw(_("Size {0} is not in the ratios of lay {1} of the cut plan.").format(s.size, self.lay_no))
			if cint(s.ratio) != ratios[s.size]:
				frappe.throw(_("Size {0}: the ratio is {1} in the cut plan, not {2}.").format(s.size, ratios[s.size], s.ratio))

	def check_override_fields(self):
		if cint(self.gate_override):
			if not self.is_new() and not self.has_value_changed("gate_override"):
				return
			if not (MANAGER_ROLES & set(frappe.get_roles())):
				frappe.throw(_("Only a production manager can override the bulk gate."))
			if not (self.gate_override_reason or "").strip():
				frappe.throw(_("Enter the reason for the override."))

	def check_rolls(self):
		if not self.rolls:
			frappe.throw(_("Add the rolls laid."))
		wh = setting("cutting_wip_warehouse")
		spread_w = flt(setting("max_width_spread_cm") or 1)
		spread_s = flt(setting("max_shrinkage_spread_pct") or 3)
		washed = cint(frappe.db.get_value("Production Card", self.production_card, "is_washed"))
		remnant_min = flt(setting("remnant_min_m") or 5)
		seen, shades, widths, warp, weft = set(), set(), [], [], []
		for r in self.rolls:
			if r.batch in seen:
				frappe.throw(_("Roll {0} appears twice in this lay.").format(r.batch))
			seen.add(r.batch)
			info = cutting.roll_info(r.batch)
			if info.item != self.fabric_item:
				frappe.throw(_("Row {0}: roll {1} is {2}, not {3}.").format(r.idx, info.apparel_roll_no or r.batch, info.item, self.fabric_item))
			if info.apparel_inspection_status not in cutting.OK_STATUS:
				frappe.throw(_("Row {0}: roll {1} is {2}. Only accepted rolls can be cut.").format(r.idx, info.apparel_roll_no or r.batch, info.apparel_inspection_status or _("not inspected")))
			r.roll_no, r.dye_lot, r.shade_band, r.width_cm = info.apparel_roll_no, info.apparel_dye_lot, info.apparel_shade_band or "", flt(info.apparel_width_cm)
			shades.add(r.shade_band or "")
			if r.width_cm:
				widths.append(r.width_cm)
			warp.append(flt(info.apparel_shrinkage_warp_pct))
			weft.append(flt(info.apparel_shrinkage_weft_pct))
			if cint(r.plies) <= 0:
				frappe.throw(_("Row {0}: enter the number of plies.").format(r.idx))
			r.length_laid_m = round(cint(r.plies) * flt(self.marker_length_m), 3)
			avail = self.available(r.batch, wh)
			r.roll_length_m = avail
			used = r.length_laid_m + flt(r.end_bit_m) + flt(r.damage_m)
			if wh and used > avail + 1e-6:
				frappe.throw(_("Row {0}: roll {1} has {2} m left in {3}, but this lay uses {4} m. Issue the roll to cutting first.").format(r.idx, info.apparel_roll_no or r.batch, round(avail, 3), wh, round(used, 3)))
			balance = round(max(avail - used, 0), 3) if wh else 0
			if 0 < balance < remnant_min:  # too short to keep: it becomes end bit
				r.end_bit_m = round(flt(r.end_bit_m) + balance, 3)
				balance = 0
			r.balance_returned_m = balance
			if flt(self.marker_width_cm) and r.width_cm and r.width_cm < flt(self.marker_width_cm):
				frappe.throw(_("Row {0}: roll {1} is {2} cm wide, narrower than the {3} cm marker.").format(r.idx, info.apparel_roll_no or r.batch, r.width_cm, self.marker_width_cm))
		if len(shades) > 1:
			frappe.throw(_("One lay holds one shade band. This lay mixes: {0}. Cut each shade band in its own lay.").format(", ".join(sorted(s or _("(none)") for s in shades))))
		self.shade_band = next(iter(shades)) if shades else ""
		if self.plan_lay and (self.plan_lay.shade_band or "").strip() and self.shade_band != self.plan_lay.shade_band:
			frappe.throw(_("The cut plan wants shade {0} in this lay; the rolls are shade {1}.").format(self.plan_lay.shade_band, self.shade_band or _("(none)")))
		if widths and max(widths) - min(widths) > spread_w:
			frappe.throw(_("The rolls in one lay must be within {0} cm of each other in width (now {1} to {2} cm).").format(spread_w, min(widths), max(widths)))
		if warp and (max(warp) - min(warp) > spread_s or max(weft) - min(weft) > spread_s):
			msg = _("Shrinkage of the rolls differs by more than {0}%. Cut rolls of similar shrinkage together.").format(spread_s)
			if washed:
				frappe.throw(msg)
			frappe.msgprint(msg, indicator="orange")

	def available(self, batch, wh):
		"""Metres of a roll still free for a lay: what is in the Cutting WIP warehouse less what submitted lays already used."""
		stock = roll_available(batch, wh, self.fabric_item)
		used = frappe.db.sql(
			"""select ifnull(sum(r.length_laid_m + ifnull(r.end_bit_m, 0) + ifnull(r.damage_m, 0)), 0) from `tabLay Roll` r
			join `tabLay Report` l on l.name = r.parent where r.batch = %s and l.docstatus = 1 and l.name != %s""", (batch, self.name or ""))[0][0]
		return round(max(stock - flt(used), 0), 3) if wh else 0

	def compute_sizes(self):
		if not self.sizes:
			frappe.throw(_("Add the sizes and ratios cut."))
		total_plies = sum(cint(r.plies) for r in self.rolls)
		seen = set()
		for s in self.sizes:
			if s.size not in self.card_sizes:
				frappe.throw(_("Size {0} is not on production card {1} for {2}.").format(s.size, self.production_card, self.colour))
			if s.size in seen:
				frappe.throw(_("Size {0} appears twice.").format(s.size))
			seen.add(s.size)
			if cint(s.ratio) <= 0:
				frappe.throw(_("Size {0}: pieces per ply must be above zero.").format(s.size))
			s.pieces_cut = total_plies * cint(s.ratio)

	def check_panel_rejects(self):
		rejected = {}
		for r in self.panel_rejects:
			if r.size not in {s.size for s in self.sizes}:
				frappe.throw(_("Rejected panels: size {0} is not cut in this lay.").format(r.size))
			if cint(r.qty) <= 0:
				frappe.throw(_("Rejected panels: enter the quantity."))
			rejected[r.size] = rejected.get(r.size, 0) + cint(r.qty)
		min_pct = flt(setting("panel_inspection_pct") or 100)
		for s in self.sizes:
			s.panels_rejected = rejected.get(s.size, 0)
			if cint(s.panels_rejected) > cint(s.pieces_cut):
				frappe.throw(_("Size {0}: more panels rejected than cut.").format(s.size))
			if cint(s.panels_checked) and cint(s.panels_checked) < cint(s.panels_rejected):
				frappe.throw(_("Size {0}: panels checked cannot be fewer than panels rejected.").format(s.size))
			need = math.ceil(cint(s.pieces_cut) * min_pct / 100.0)
			if self.docstatus == 0 and cint(s.panels_checked) and cint(s.panels_checked) < need:
				frappe.msgprint(_("Size {0}: {1} panels checked, the setting asks for {2}.").format(s.size, s.panels_checked, need), indicator="orange")

	def check_purpose(self):
		if self.purpose == "Re-cut":
			if not self.recut_request:
				frappe.throw(_("A re-cut lay needs its Re-cut Request."))
			req = frappe.db.get_value("Recut Request", self.recut_request, ["docstatus", "production_card", "colour", "size", "qty", "status", "source_roll"], as_dict=True)
			if not req or req.docstatus != 1 or req.status != "Open":
				frappe.throw(_("Re-cut Request {0} must be submitted and open.").format(self.recut_request))
			if req.production_card != self.production_card or req.colour != self.colour:
				frappe.throw(_("Re-cut Request {0} is for another card or colour.").format(self.recut_request))
			if [s.size for s in self.sizes] != [req.size] or sum(cint(s.pieces_cut) for s in self.sizes) > cint(req.qty):
				frappe.throw(_("The re-cut lay must cut only size {0}, at most {1} pieces.").format(req.size, req.qty))
			if req.source_roll and any(r.batch != req.source_roll for r in self.rolls) and not frappe.db.get_value("Recut Request", req.name, "different_roll_approved"):
				frappe.throw(_("The request names roll {0}; cutting from another roll needs the approval box ticked on the request.").format(req.source_roll))
		elif self.recut_request:
			frappe.throw(_("Only a re-cut lay can name a Re-cut Request."))

	def check_pairing(self):
		if self.component == "Shell":
			if self.paired_with:
				frappe.throw(_("A shell lay is not paired with another lay."))
			return
		if not self.paired_with:
			frappe.throw(_("A {0} lay must be paired with its shell lay (so the ply numbers match).").format(self.component))
		shell = frappe.get_doc("Lay Report", self.paired_with)
		if shell.docstatus != 1 or shell.component != "Shell" or shell.production_card != self.production_card or shell.colour != self.colour:
			frappe.throw(_("Paired lay {0} must be a submitted shell lay of the same card and colour.").format(self.paired_with))
		if cint(shell.total_plies) != sum(cint(r.plies) for r in self.rolls):
			frappe.throw(_("Paired lay {0} has {1} plies; this lay has {2}. They must match.").format(shell.name, shell.total_plies, sum(cint(r.plies) for r in self.rolls)))
		mine = {s.size: cint(s.ratio) for s in self.sizes}
		theirs = {s.size: cint(s.ratio) for s in shell.sizes}
		if mine != theirs:
			frappe.throw(_("Size ratios must match the shell lay {0}.").format(shell.name))

	def compute_totals(self):
		self.total_plies = sum(cint(r.plies) for r in self.rolls)
		self.laid_m = round(sum(flt(r.length_laid_m) for r in self.rolls), 3)
		self.pieces_cut = sum(cint(s.pieces_cut) for s in self.sizes)
		self.rejected_pieces = sum(cint(r.qty) for r in self.panel_rejects)
		per_ply = sum(cint(s.ratio) for s in self.sizes)
		self.lay_consumption = round(self.laid_m / self.pieces_cut, 4) if self.pieces_cut else 0
		self.cad_consumption = round(flt(self.marker_length_m) / per_ply, 4) if per_ply else 0
		self.consumption_difference = round(self.lay_consumption - self.cad_consumption, 4)

	# ---- submit / cancel -------------------------------------------------------------------------------------------
	def before_submit(self):
		if self.card_status_blocked():
			frappe.throw(_("Production card {0} is not open for cutting.").format(self.production_card))
		stage = "bulk" if self.purpose == "Bulk" else "pilot"
		res = gate.bulk_gate_for(self.card.sales_order, self.card.style_item, self.colour, stage=stage)
		for w in res.get("warnings") or []:
			frappe.msgprint(w, indicator="orange", title=_("Materials"))
		if res["blockers"] and not (cint(self.gate_override) and (MANAGER_ROLES & set(frappe.get_roles())) and (self.gate_override_reason or "").strip()):
			frappe.throw(_("Cutting is blocked until the buyer approvals, the PP meeting, the materials and the pilot run are complete:") + "<br>• " + "<br>• ".join(res["blockers"]),
						 title=_("Bulk Gate"))

	def card_status_blocked(self):
		return self.card.status in ("Superseded", "Cancelled", "Closed")

	def on_submit(self):
		self.post_movements(check=True)
		cutting.make_bundles(self)
		self.return_remnants()
		if frappe.db.get_value("Production Card", self.production_card, "status") == "Issued":
			frappe.db.set_value("Production Card", self.production_card, "status", "In Cutting", update_modified=False)
		if self.purpose == "Re-cut" and self.recut_request:
			frappe.db.set_value("Recut Request", self.recut_request, "status", "Cut")
		if self.purpose == "Bulk" and self.component == "Shell":
			self.stamp_pcd()

	def rows(self):
		out = []
		if self.component != "Shell":  # the garment count follows the shell fabric
			return out
		for s in self.sizes:
			out.append({"stage": "CUT", "colour": self.colour, "size": s.size, "qty": cint(s.pieces_cut), "purpose": self.purpose, "shade_band": self.shade_band,
						"line": self.line, "source_row": s.name})
		for r in self.panel_rejects:
			out.append({"stage": "CUT_REJECT", "colour": self.colour, "size": r.size, "qty": cint(r.qty), "purpose": self.purpose, "shade_band": self.shade_band,
						"fault_source": r.fault_source, "source_row": r.name})
		return out

	def post_movements(self, check=False):
		override = bool(cint(self.gate_override) and (self.gate_override_reason or "").strip())
		ledger.post(self.production_card, self.rows(), "Lay Report", self.name, self.lay_date, override=override, check=check)

	def return_remnants(self):
		wh_cut, wh_store = setting("cutting_wip_warehouse"), setting("store_warehouse_fabric")
		if not wh_cut or not wh_store:
			return
		rows = [{"item_code": self.fabric_item, "qty": flt(r.balance_returned_m), "s_warehouse": wh_cut, "t_warehouse": wh_store, "batch_no": r.batch}
				for r in self.rolls if flt(r.balance_returned_m) > 0]
		name = make_transfer(self.card.company, rows, "Remnant Return", self.production_card, _("Remnants of {0}").format(self.name), submit=True)
		if name:
			self.db_set("remnant_entry", name)

	def stamp_pcd(self):
		try:
			from arinox_apparel.tna.events import stamp

			stamp(self.card.sales_order, self.card.style_item, self.colour, "PCD", self.lay_date, "Lay Report", self.name)
		except Exception:
			frappe.log_error(title="T&A hook lay report failed", message=frappe.get_traceback())

	def on_cancel(self):
		cutting.void_bundles(self.name)
		ledger.unpost("Lay Report", self.name)
		if self.remnant_entry:
			cancel_entry(self.remnant_entry)
			self.db_set("remnant_entry", None)
		if self.purpose == "Re-cut" and self.recut_request:
			frappe.db.set_value("Recut Request", self.recut_request, "status", "Open")
		try:
			from arinox_apparel.tna.events import unstamp

			unstamp("Lay Report", self.name)
		except Exception:
			frappe.log_error(title="T&A hook lay report cancel failed", message=frappe.get_traceback())
