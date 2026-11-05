# Copyright (c) 2026, Arinox AI and contributors
"""Final Inspection: AQL inspection of a packed lot (one or more Packing Lists of one order). Follows the company's form.
Sample size and accept/reject numbers come from the AQL Plan; a row that QA has not confirmed cannot be used. Any critical
defect fails. The Delivery Note will not submit unless every packing list on it is in a lot that passed."""

import random

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.production import maths, packing
from arinox_apparel.shipping import common

FINAL_TYPES = ("Final", "Re-inspection", "2nd Re-inspection")
PASS = ("Accepted", "Accepted with Concession")
CHECKS = ("fpt", "gpt", "azo", "wash_care_ok", "fibre_ok", "sealer_style", "sealer_material", "sealer_colour", "sealer_construction",
		  "metal_detection_ok", "measurement_ok", "drop_test_ok", "barcode_ok", "packing_ok")


def aql_row(plan, lot_size):
	"""The plan row whose lot range holds `lot_size`, or None."""
	for r in frappe.get_all("AQL Plan Row", {"parent": plan}, ["*"], order_by="lot_from"):
		if cint(r.lot_from) <= lot_size <= cint(r.lot_to):
			return r
	return None


class FinalInspection(Document):
	def autoname(self):
		self.name = common.next_serial(common.card_root(self.production_card), "FI")

	def validate(self):
		self.inspection_type = self.inspection_type or "Final"
		card = common.require_open_card(self.production_card)
		self.sales_contract, self.sales_order, self.customer, self.style_item = card.sales_contract, card.sales_order, card.customer, card.style_item
		self.set_lot()
		self.set_sampling()
		self.count_defects()
		self.check_chain()
		self.check_result()

	def set_lot(self):
		if not self.lots:
			frappe.throw(_("Add the packing lists in the lot."))
		seen, pieces, cartons = set(), 0, 0
		for l in self.lots:
			pl = frappe.db.get_value("Packing List", l.packing_list, ["docstatus", "production_card", "total_pieces", "total_cartons"], as_dict=True)
			if not pl or pl.docstatus != 1:
				frappe.throw(_("Packing list {0} must be submitted.").format(l.packing_list))
			if pl.production_card != self.production_card:
				frappe.throw(_("Packing list {0} belongs to another production card.").format(l.packing_list))
			if l.packing_list in seen:
				frappe.throw(_("Packing list {0} is in the lot twice.").format(l.packing_list))
			seen.add(l.packing_list)
			l.pieces, l.cartons = pl.total_pieces, pl.total_cartons
			pieces += cint(pl.total_pieces)
			cartons += cint(pl.total_cartons)
		self.offered_qty, self.total_cartons = pieces, cartons
		self.po_qty = sum(cint(r.order_qty) for r in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["order_qty"]))
		self.packed_pct = round(maths.pct(pieces, self.po_qty) or 0, 2)
		if self.inspection_type in FINAL_TYPES and self.docstatus == 0:
			blocked_below = flt(common.settings_value("final_block_packed_pct", 50))
			warn_below = flt(common.settings_value("final_min_packed_pct", 80))
			if self.packed_pct < blocked_below:
				frappe.throw(_("Only {0} % of the order is packed. A final inspection needs at least {1} %; use Pre-Final for an earlier look.").format(self.packed_pct, blocked_below))
			if self.packed_pct < warn_below:
				frappe.msgprint(_("Only {0} % of the order is packed ({1} % is expected for a final inspection).").format(self.packed_pct, warn_below), indicator="orange")

	def set_sampling(self):
		self.aql_plan = self.aql_plan or common.settings_value("final_inspection_plan")
		if not self.aql_plan:
			frappe.throw(_("Choose the AQL Plan, or set one in Apparel Settings."))
		self.inspection_level = frappe.db.get_value("AQL Plan", self.aql_plan, "inspection_level")
		row = aql_row(self.aql_plan, cint(self.offered_qty))
		if not row or not cint(row.confirmed):
			frappe.throw(_("The AQL plan has no confirmed row for a lot of {0} pieces. QA must fill in and confirm that row from ISO 2859-1 Table 2-A first.").format(self.offered_qty))
		self.sample_size = cint(row.sample_size)
		self.critical_ac, self.critical_re = cint(row.critical_ac), cint(row.critical_re) or 1
		self.major_ac, self.major_re, self.minor_ac, self.minor_re = cint(row.major_ac), cint(row.major_re), cint(row.minor_ac), cint(row.minor_re)
		self.inspected_cartons = maths.inspect_cartons(cint(self.total_cartons), common.settings_value("carton_pick_rule", "Square Root"), 10)
		if self.sample_size > cint(self.offered_qty):
			self.sample_size = cint(self.offered_qty)

	def count_defects(self):
		tot = {"Critical": 0, "Major": 0, "Minor": 0}
		for d in self.defects:
			d.qty = cint(d.qty)
			if d.qty <= 0:
				frappe.throw(_("Defect {0}: enter a quantity above zero.").format(d.defect_code))
			sev = frappe.db.get_value("Apparel Defect Code", d.defect_code, "severity") or "Minor"
			d.severity = sev
			tot[sev] = tot.get(sev, 0) + d.qty
		self.critical_found, self.major_found, self.minor_found = tot["Critical"], tot["Major"], tot["Minor"]
		if self.critical_found >= self.critical_re or self.major_found >= self.major_re or self.minor_found >= self.minor_re:
			self.computed_result = "Rejected"
		else:
			self.computed_result = "Accepted"

	def check_chain(self):
		"""A re-inspection follows a rejected or on-hold inspection of the same lot; too many needs a manager."""
		if self.inspection_type in ("Re-inspection", "2nd Re-inspection") and not self.previous_inspection:
			frappe.throw(_("Name the inspection this one follows."))
		n, prev, seen = 0, self.previous_inspection, set()
		while prev and prev not in seen:
			seen.add(prev)
			n += 1
			prev = frappe.db.get_value("Final Inspection", prev, "previous_inspection")
		limit = cint(common.settings_value("reinspection_limit", 2))
		if n >= limit and not ({"Apparel Production Manager", "System Manager"} & set(frappe.get_roles())):
			frappe.throw(_("This lot has already been inspected {0} times. A Production Manager must approve another.").format(n))

	def check_result(self):
		if not self.result:
			return
		if self.result == "Accepted":
			if self.computed_result == "Rejected":
				frappe.throw(_("The defects found fail the AQL plan ({0} critical, {1} major, {2} minor). Choose Rejected, On Hold, or Accepted with Concession.").format(self.critical_found, self.major_found, self.minor_found))
			failed = [self.meta.get_label(c) for c in CHECKS if self.get(c) == "No"]
			if failed:
				frappe.throw(_("These checks failed: {0}. They cannot be Accepted without a concession.").format(", ".join(failed)))
		if self.result == "Accepted with Concession":
			if not (self.concession_ref or "").strip() or not (self.approved_by or "").strip():
				frappe.throw(_("A concession needs the buyer's approval reference and who approved it."))

	@frappe.whitelist()
	def pick_cartons(self):
		"""Draw the cartons to open, at random from the lot's own carton numbers. The seed is stored so the draw can be repeated."""
		if self.docstatus != 0:
			frappe.throw(_("Cartons can only be drawn on a draft."))
		self.set_lot()
		self.set_sampling()
		pool = []
		for l in self.lots:
			for c in frappe.get_all("Packing List Carton", {"parent": l.packing_list}, ["carton_from", "carton_to", "tail"]):
				for n in range(cint(c.carton_from), cint(c.carton_to) + 1):
					pool.append((l.packing_list, n, cint(c.tail)))
		self.draw_seed = random.SystemRandom().randint(1, 2**31 - 1)
		picked = packing.draw_cartons(pool, self.inspected_cartons, self.draw_seed)
		sscc = {(r.parent, r.carton_no): r.sscc for r in frappe.get_all("Packing List SSCC", {"parent": ["in", [l.packing_list for l in self.lots]]}, ["parent", "carton_no", "sscc"])}
		self.set("cartons_picked", [])
		for pl, n, _t in picked:
			self.append("cartons_picked", {"packing_list": pl, "carton_no": n, "sscc": sscc.get((pl, n))})
		return len(picked)

	def before_submit(self):
		if not self.result:
			frappe.throw(_("Choose the result."))
		if self.inspection_type in FINAL_TYPES and len(self.cartons_picked) < min(cint(self.inspected_cartons), cint(self.total_cartons)):
			frappe.throw(_("Draw the {0} cartons to inspect (Pick Cartons) before submitting.").format(self.inspected_cartons))
		seen = set()
		for c in self.cartons_picked:
			if (c.packing_list, c.carton_no) in seen:
				frappe.throw(_("Carton {0} of {1} is drawn twice.").format(c.carton_no, c.packing_list))
			seen.add((c.packing_list, c.carton_no))
			if c.packing_list not in {l.packing_list for l in self.lots}:
				frappe.throw(_("Carton {0}: {1} is not in the lot.").format(c.carton_no, c.packing_list))

	def on_submit(self):
		for l in self.lots:
			frappe.db.set_value("Packing List", l.packing_list, "final_inspection", self.name, update_modified=False)
		if self.result in PASS and self.inspection_type in FINAL_TYPES:
			common.stamp_card(self.production_card, "FINAL_INSPECTION", self.inspection_date, "Final Inspection", self.name)
		if self.result == "Rejected":
			frappe.msgprint(_("Rejected: {0} critical, {1} major, {2} minor. Repack or rework, then inspect again.").format(self.critical_found, self.major_found, self.minor_found), indicator="red")

	def on_cancel(self):
		for l in self.lots:
			if frappe.db.get_value("Packing List", l.packing_list, "final_inspection") == self.name:
				frappe.db.set_value("Packing List", l.packing_list, "final_inspection", None, update_modified=False)
		common.unstamp_doc("Final Inspection", self.name)


def gate_problems(packing_lists):
	"""Reasons a set of packing lists may not ship: no accepted final inspection. The latest Final or Re-inspection that
	covers the list decides; a pre-final never opens the gate."""
	out = []
	for pl in sorted(set(packing_lists)):
		rows = frappe.db.sql(
			"""select i.name, i.result from `tabFinal Inspection` i join `tabFinal Inspection Lot` l on l.parent = i.name
			where l.packing_list = %s and i.docstatus = 1 and i.inspection_type in ('Final', 'Re-inspection', '2nd Re-inspection')
			order by i.inspection_date desc, i.creation desc limit 1""", pl, as_dict=True)
		if not rows:
			out.append(_("{0} has no final inspection.").format(pl))
		elif rows[0].result not in PASS:
			out.append(_("{0}: the latest inspection {1} is {2}.").format(pl, rows[0].name, rows[0].result or _("undecided")))
	return out
