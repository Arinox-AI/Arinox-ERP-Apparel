# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Fabric Inspection: the 4-point inspection of the rolls received on one Purchase Receipt row. Submit writes the result
to every roll (Batch), makes the Quality Inspection and the Stock Entry that releases accepted rolls to the store and
moves rejected rolls to the rejected warehouse."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import MANAGER_ROLES
from arinox_apparel.materials import common as mc
from arinox_apparel.materials import inspection as ins


class FabricInspection(Document):
	def validate(self):
		self.ctx = ins.receipt_context(self.purchase_receipt, self.purchase_receipt_item, "Fabric")
		self.set_context()
		self.check_override()
		if not self.rolls:
			frappe.throw(_("Load the rolls first (Tools > Load Rolls from Receipt)."))
		self.check_rolls()
		self.compute_defects()
		self.compute_rolls()
		self.compute_shrinkage()
		self.compute_lot()

	def set_context(self):
		c = self.ctx
		self.company, self.supplier = c.pr.company, c.pr.supplier
		self.purchase_order, self.fabric_requisition = c.get("purchase_order"), c.requisition
		self.fabric_item, self.customer = c.row.item_code, c.customer
		self.sales_orders, self.style_nos = ", ".join(c.so_list), ", ".join(c.styles)
		self.colour = self.colour or c.get("colour")
		if not flt(self.required_width_cm):
			self.required_width_cm = flt(c.get("required_width")) or flt(frappe.db.get_value("Item", c.row.item_code, "apparel_fabric_width_cm"))
		s = mc.settings()
		self.points_basis = s.get("fabric_points_basis") or "Per 100 Linear Yards"
		if not flt(self.points_threshold):
			self.points_threshold = flt(c.terms.points_threshold) if c.terms and flt(c.terms.points_threshold) else flt(s.get("fabric_points_threshold") or 20)
		window = cint(c.terms.claim_window_days) if c.terms else 0
		self.claim_deadline = add_days(c.pr.posting_date, window) if window else None
		if not self.inspected_by:
			self.inspected_by = frappe.session.user

	def check_override(self):
		if cint(self.result_override):
			if not set(frappe.get_roles()) & set(MANAGER_ROLES):
				frappe.throw(_("Only an Apparel Merchandising Manager can override the inspection rules."))
			if not (self.override_reason or "").strip():
				frappe.throw(_("Enter the reason for overriding the inspection rules."))

	# ---- rolls --------------------------------------------------------------------------------------------------
	def row_batches(self):
		bundle = self.ctx.row.serial_and_batch_bundle
		if not bundle:
			return set()
		return {e.batch_no for e in frappe.get_all("Serial and Batch Entry", {"parent": bundle}, ["batch_no"]) if e.batch_no}

	def check_rolls(self):
		allowed = self.row_batches()
		seen = set()
		for r in self.rolls:
			if r.batch not in allowed:
				frappe.throw(_("Row {0}: batch {1} was not received on this receipt row.").format(r.idx, r.batch))
			if r.batch in seen:
				frappe.throw(_("Row {0}: batch {1} is listed twice.").format(r.idx, r.batch))
			seen.add(r.batch)
			b = frappe.db.get_value("Batch", r.batch, ["apparel_roll_no", "apparel_dye_lot", "apparel_ticket_length"], as_dict=True)
			r.roll_no, r.dye_lot, r.ticket_length = b.apparel_roll_no, b.apparel_dye_lot, flt(b.apparel_ticket_length)
			if not flt(r.actual_length):
				r.actual_length = r.ticket_length
			r.length_variance = flt(r.actual_length) - flt(r.ticket_length)
		self.total_rolls = len(self.rolls)
		self.total_received_m = sum(flt(r.ticket_length) for r in self.rolls)
		for d in self.defects:
			if d.roll_no not in {r.roll_no for r in self.rolls}:
				frappe.throw(_("Defect row {0}: roll {1} is not in the roll list.").format(d.idx, d.roll_no))

	def compute_defects(self):
		always = {c.name: cint(c.always_four_points) for c in frappe.get_all("Fabric Defect Code", fields=["name", "always_four_points"])}
		for d in self.defects:
			if flt(d.defect_length_in) <= 0 and not always.get(d.defect_code):
				frappe.throw(_("Defect row {0}: enter the defect length in inches.").format(d.idx))
			d.points = ins.defect_points(d.defect_length_in, always.get(d.defect_code))

	def compute_rolls(self):
		threshold = flt(self.points_threshold)
		square = self.points_basis == "Per 100 Square Yards"
		widths = []
		for r in self.rolls:
			if not cint(r.inspected):
				r.total_points = r.points_per_100 = 0
				r.roll_result = r.roll_result if r.roll_result == "Hold" else None
				continue
			if not flt(r.inspected_length_m):
				r.inspected_length_m = flt(r.actual_length)
			if flt(r.inspected_length_m) > flt(r.actual_length) + 0.005:
				frappe.throw(_("Row {0}: inspected length {1} m is more than the roll ({2} m).").format(r.idx, r.inspected_length_m, r.actual_length))
			mine = [(d.yard_position, d.points) for d in self.defects if d.roll_no == r.roll_no]
			r.total_points = ins.roll_points(mine)
			width = [flt(w) for w in (r.width_start_cm, r.width_middle_cm, r.width_end_cm) if flt(w)]
			avg_w = sum(width) / len(width) if width else 0
			if avg_w:
				widths.append(avg_w)
			r.width_required_cm = flt(r.width_required_cm) or flt(self.required_width_cm)
			r.width_ok = 1 if (not width or min(width) + 0.5 >= flt(r.width_required_cm)) else 0
			r.points_per_100 = flt(ins.points_per_100_square(r.total_points, r.inspected_length_m, avg_w or r.width_required_cm) if square
				else ins.points_per_100_linear(r.total_points, r.inspected_length_m), 2)
			auto = "Reject" if r.points_per_100 > threshold else "Accept"
			if r.roll_result == "Hold":
				pass
			elif auto == "Reject" or not r.roll_result:
				r.roll_result = auto  # a roll over the threshold cannot be accepted
		self.avg_actual_width_cm = flt(sum(widths) / len(widths), 1) if widths else 0

	def compute_shrinkage(self):
		limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
		over = []
		for r in self.shrinkage:
			for d in ("warp", "weft", "bias"):
				before, after = flt(r.get(f"before_{d}")), flt(r.get(f"after_{d}"))
				r.set(f"shrink_{d}_pct", round((after - before) / before * 100, 2) if before else 0)
			if limit and any(abs(flt(r.get(f"shrink_{d}_pct"))) > limit for d in ("warp", "weft")):
				over.append(r.roll_no or r.idx)
		if over:
			frappe.msgprint(_("Shrinkage above {0}% on: {1}").format(limit, ", ".join(map(str, over))), indicator="orange")

	# ---- lot ----------------------------------------------------------------------------------------------------
	def compute_lot(self):
		s = mc.settings()
		bands = s.get("fabric_sampling_bands") or []
		self.sampling_pct = ins.sampling_pct(bands, self.total_received_m)
		self.required_inspect_m = flt(self.total_received_m * self.sampling_pct / 100, 2)
		done = [r for r in self.rolls if cint(r.inspected)]
		self.inspected_rolls = len(done)
		self.inspected_m = flt(sum(flt(r.inspected_length_m) for r in done), 2)
		self.inspected_pct = flt(self.inspected_m * 100 / self.total_received_m, 2) if flt(self.total_received_m) else 0
		pts = sum(cint(r.total_points) for r in done)
		self.avg_points = flt(ins.points_per_100_linear(pts, self.inspected_m), 2)
		w = flt(self.avg_actual_width_cm) or flt(self.required_width_cm)
		self.avg_points_sq = flt(ins.points_per_100_square(pts, self.inspected_m, w), 2)
		self.rejected_rolls = len([r for r in done if r.roll_result == "Reject"])
		bands_found = sorted({(r.shade_band or "").strip() for r in self.rolls if (r.shade_band or "").strip()})
		self.shade_bands_found = ", ".join(bands_found)
		basis_value = self.avg_points_sq if self.points_basis == "Per 100 Square Yards" else self.avg_points
		self.lot_result = ins.lot_decision(basis_value, self.points_threshold, self.rejected_rolls, self.inspected_rolls, self.total_rolls,
			flt(s.get("max_rejected_rolls_pct") if s.get("max_rejected_rolls_pct") is not None else 10), cint(self.on_hold))
		accepted = hold = rejected = 0.0
		for r in self.rolls:
			disp = ins.roll_disposition(cint(r.inspected), r.roll_result, self.lot_result)
			if disp in ("Accepted", "Accepted by Lot"):
				accepted += flt(r.ticket_length)
			elif disp == "Rejected":
				rejected += flt(r.ticket_length)
			else:
				hold += flt(r.ticket_length)
		self.accepted_m, self.rejected_m, self.hold_m = flt(accepted, 2), flt(rejected, 2), flt(hold, 2)

	def before_submit(self):
		override = cint(self.result_override)
		if flt(self.inspected_m) + 0.005 < flt(self.required_inspect_m) and not override:
			frappe.throw(_("Inspect at least {0} m ({1}% of {2} m). {3} m inspected so far.").format(
				self.required_inspect_m, self.sampling_pct, flt(self.total_received_m, 2), self.inspected_m))
		if self.lot_result == "Re-inspect 100%" and not override:
			frappe.throw(_("The sample failed. Inspect every roll before submitting, or have a manager override."))

	# ---- submit -------------------------------------------------------------------------------------------------
	def on_submit(self):
		for r in self.rolls:
			disp = ins.roll_disposition(cint(r.inspected), r.roll_result, self.lot_result)
			frappe.db.set_value("Batch", r.batch, {
				"apparel_inspection_status": disp, "apparel_fabric_inspection": self.name, "apparel_shade_band": r.shade_band or "",
				"apparel_actual_length": r.actual_length, "apparel_points_per_100": r.points_per_100,
				"apparel_width_cm": flt(r.width_middle_cm) or flt(r.width_start_cm),
			}, update_modified=False)
		self.apply_shrinkage_to_batches()
		self.make_records()
		self.flag_requisition()
		from arinox_apparel.materials import purchasing

		if self.fabric_requisition:
			req = purchasing.refresh_requisition("FR", self.fabric_requisition)
			self.stamp(req)

	def apply_shrinkage_to_batches(self):
		by_roll = {r.roll_no: r.batch for r in self.rolls}
		for s in self.shrinkage:
			b = by_roll.get(s.roll_no)
			if b:
				frappe.db.set_value("Batch", b, {"apparel_shrinkage_warp_pct": s.shrink_warp_pct, "apparel_shrinkage_weft_pct": s.shrink_weft_pct}, update_modified=False)

	def make_records(self):
		accepted = self.lot_result == "Pass"
		worst = max((flt(r.points_per_100) for r in self.rolls if cint(r.inspected)), default=0)
		warp = max((abs(flt(s.shrink_warp_pct)) for s in self.shrinkage), default=0)
		weft = max((abs(flt(s.shrink_weft_pct)) for s in self.shrinkage), default=0)
		limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
		readings = [
			("Average Points per 100 Linear Yards", flt(self.avg_points, 2), "Accepted" if flt(self.avg_points) <= flt(self.points_threshold) else "Rejected"),
			("Worst Roll Points per 100", flt(worst, 2), "Accepted" if worst <= flt(self.points_threshold) else "Rejected"),
		]
		if self.avg_actual_width_cm:
			readings.append(("Average Width (cm)", self.avg_actual_width_cm, "Accepted" if flt(self.avg_actual_width_cm) >= flt(self.required_width_cm) - 0.5 else "Rejected"))
		if self.shrinkage:
			readings += [("Shrinkage Warp %", warp, "Rejected" if limit and warp > limit else "Accepted"), ("Shrinkage Weft %", weft, "Rejected" if limit and weft > limit else "Accepted")]
		qi = ins.make_quality_inspection(self.ctx, self.fabric_item, accepted, readings, self.inspected_rolls, self.remarks)
		store = mc.company_warehouse("store_warehouse_fabric", self.company)
		reject = mc.company_warehouse("rejected_warehouse", self.company)
		rows = []
		for r in self.rolls:
			disp = ins.roll_disposition(cint(r.inspected), r.roll_result, self.lot_result)
			if disp in ("Accepted", "Accepted by Lot"):
				rows.append({"item_code": self.fabric_item, "qty": r.ticket_length, "target": store, "batch_no": r.batch})
			elif disp == "Rejected":
				rows.append({"item_code": self.fabric_item, "qty": r.ticket_length, "target": reject, "batch_no": r.batch})
		se = ins.make_stock_entry(self.ctx, rows, "Fabric", cint(mc.settings().get("submit_inspection_stock_entry")))
		self.db_set({"quality_inspection": qi, "stock_entry": se})

	def flag_requisition(self):
		if not self.fabric_requisition:
			return
		short = ins.width_impact(self.avg_actual_width_cm, self.required_width_cm, self.accepted_m + self.rejected_m + self.hold_m)
		self.db_set("width_shortfall_m", flt(short, 2))
		if short > 0:
			ins.append_red_flag("FR", self.fabric_requisition, _("{0}: fabric is narrower ({1} cm vs {2} cm cuttable width). About {3} m more will be needed.").format(
				self.name, self.avg_actual_width_cm, self.required_width_cm, flt(short, 0)))
		if len(self.shade_bands_found.split(", ")) > 1:
			ins.append_red_flag("FR", self.fabric_requisition, _("{0}: more than one shade band ({1}). Cut by shade band.").format(self.name, self.shade_bands_found))

	def stamp(self, req):
		if not req:
			return
		need = mc.settings().get("material_gate_min_pct") or 100
		seen = {}
		for r in req.items:
			k = (r.sales_order, r.style_item, r.colour)
			done = flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * flt(need) / 100
			seen[k] = seen.get(k, True) and done
		for (so, style, colour), full in seen.items():
			if full or any(flt(r.accepted_qty) > 0 for r in req.items if (r.sales_order, r.style_item, r.colour) == (so, style, colour)):
				mc.stamp_safe(so, style, colour, "FABRIC_QC_PASSED", self.inspection_date, "Fabric Inspection", self.name, partial=not full)

	def on_cancel(self):
		ins.cancel_linked("Stock Entry", self.stock_entry)
		ins.cancel_linked("Quality Inspection", self.quality_inspection)
		for r in self.rolls:
			frappe.db.set_value("Batch", r.batch, {"apparel_inspection_status": "Uninspected", "apparel_fabric_inspection": None,
				"apparel_points_per_100": 0}, update_modified=False)
		self.db_set({"stock_entry": None, "quality_inspection": None})
		if self.fabric_requisition:
			from arinox_apparel.materials import purchasing

			purchasing.refresh_requisition("FR", self.fabric_requisition)
		mc.unstamp_safe("Fabric Inspection", self.name)

	# ---- buttons ------------------------------------------------------------------------------------------------
	@frappe.whitelist()
	def load_rolls(self):
		"""One roll row per batch received on the receipt row."""
		self.check_permission("write")
		ctx = ins.receipt_context(self.purchase_receipt, self.purchase_receipt_item, "Fabric")
		self.ctx = ctx
		have = {r.batch for r in self.rolls}
		for b in sorted(self.row_batches()):
			if b not in have:
				self.append("rolls", {"batch": b, "inspected": 1})
		self.check_rolls()
		return len(self.rolls)


@frappe.whitelist()
def make_inspection(purchase_receipt, purchase_receipt_item):
	"""A new Fabric Inspection for one received fabric row, with its rolls loaded."""
	frappe.has_permission("Fabric Inspection", "create", throw=True)
	frappe.has_permission("Purchase Receipt", "read", purchase_receipt, throw=True)
	doc = frappe.new_doc("Fabric Inspection")
	doc.purchase_receipt, doc.purchase_receipt_item = purchase_receipt, purchase_receipt_item
	doc.load_rolls()
	return doc


@frappe.whitelist()
def make_purchase_return(inspection):
	"""Purchase return of the rejected rolls, taken from the rejected warehouse. Returns the draft return."""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	fi = frappe.get_doc("Fabric Inspection", inspection)
	fi.check_permission("read")
	frappe.has_permission("Purchase Receipt", "create", throw=True)
	if fi.docstatus != 1:
		frappe.throw(_("Submit the inspection first."))
	rejected = [r for r in fi.rolls if ins.roll_disposition(cint(r.inspected), r.roll_result, fi.lot_result) == "Rejected"]
	if not rejected:
		frappe.throw(_("No rolls were rejected."))
	ret = make_return_doc("Purchase Receipt", fi.purchase_receipt)
	template = next((i for i in ret.items if i.item_code == fi.fabric_item), None)
	if not template:
		frappe.throw(_("The fabric item is not on the receipt."))
	proto = template.as_dict()
	ret.set("items", [])
	reject_wh = mc.company_warehouse("rejected_warehouse", fi.company)
	for r in rejected:
		line = dict(proto)
		for k in ("name", "idx", "serial_and_batch_bundle", "rejected_serial_and_batch_bundle", "creation", "modified"):
			line.pop(k, None)
		line.update({"qty": -flt(r.ticket_length), "received_qty": -flt(r.ticket_length), "stock_qty": -flt(r.ticket_length), "batch_no": r.batch,
			"use_serial_batch_fields": 1, "warehouse": reject_wh, "rejected_qty": 0, "rejected_warehouse": None})
		ret.append("items", line)
	return ret
