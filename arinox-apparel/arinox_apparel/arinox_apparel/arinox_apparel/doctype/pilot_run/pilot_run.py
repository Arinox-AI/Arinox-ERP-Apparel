# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Pilot Run: the production record that releases bulk cutting. The pieces are not typed here; they come from the
movement ledger (purpose Pilot). The PP Meeting of type Pilot Run stays the review meeting (Phase B)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from arinox_apparel.arinox_apparel.doctype.pp_meeting.pp_meeting import cutting_actions_open
from arinox_apparel.production import measurements

APPROVE = ("Approved", "Approved with Comments")
APPROVER_ROLES = {"Apparel QA", "Apparel Production Manager", "System Manager"}


class PilotRun(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status", "sales_order", "style_item"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		if frappe.db.get_single_value("Apparel Settings", "require_pp_meeting") and self.is_new():
			meetings, _open = cutting_actions_open(card.sales_order, card.style_item)
			if not meetings:
				frappe.throw(_("The PP Meeting for this style has not been held yet. A pilot run follows the PP meeting."))
		card_colours = {(l.colour or "").strip().upper() for l in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["colour"])}
		seen = set()
		for r in self.colours:
			key = (r.colour or "").strip().upper()
			if key not in card_colours:
				frappe.throw(_("Row {0}: colour {1} is not on production card {2}.").format(r.idx, r.colour, self.production_card))
			if key in seen:
				frappe.throw(_("Colour {0} appears twice.").format(r.colour))
			seen.add(key)
		self.fill_pieces()
		measurements.compute(self.measurements)
		self.compute_sam()

	def fill_pieces(self):
		"""Cut, sewn, washed and rejected pilot pieces per colour, read from the ledger."""
		for r in self.colours:
			def total(stages, process=None):
				cond = " and subcontract_process = %s" if process else ""
				args = [self.production_card, r.colour, "Pilot", *stages] + ([process] if process else [])
				return cint(frappe.db.sql(
					f"select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and colour=%s and purpose=%s and stage in ({', '.join(['%s'] * len(stages))}){cond}", args)[0][0])

			r.cut_qty = total(["CUT"]) - total(["CUT_REJECT"])
			r.sewn_qty = total(["SEW_OUT"])
			r.washed_qty = total(["SC_BACK_GOOD"], "Wash")
			r.rejected_qty = total(["CUT_REJECT", "SEW_REJECT", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_REJECT"])

	def compute_sam(self):
		planned = sum(flt(o.planned_sam) for o in self.operations)
		actual = sum(flt(o.actual_sam) for o in self.operations if flt(o.actual_sam))
		timed = sum(flt(o.planned_sam) for o in self.operations if flt(o.actual_sam))
		self.achieved_efficiency_pct = round(timed / actual * 100, 2) if actual else 0
		self.bottleneck_count = sum(1 for o in self.operations if cint(o.bottleneck))

	def before_submit(self):
		if not self.decision:
			frappe.throw(_("Choose the decision (Approved, Approved with Comments, Rejected or Re-run) before submitting."))
		if not (APPROVER_ROLES & set(frappe.get_roles())):
			frappe.throw(_("Only Apparel QA or a production manager can submit a pilot run decision."))
		if self.decision in APPROVE:
			self.check_can_approve()
		elif not (self.result_notes or "").strip():
			frappe.throw(_("Write the notes that explain why the pilot run was {0}.").format(self.decision.lower()))

	def check_can_approve(self):
		if not self.checks:
			frappe.throw(_("Record the pilot run checks before approving."))
		unanswered = [c.check_item for c in self.checks if not c.result]
		if unanswered:
			frappe.throw(_("Answer every check before approving: {0}").format(", ".join(unanswered)))
		no_action = [c.check_item for c in self.checks if c.result == "No" and not (c.action_taken or "").strip()]
		if no_action:
			frappe.throw(_("Write the action taken for each failed check: {0}").format(", ".join(no_action)))
		if not any(cint(r.sewn_qty) for r in self.colours):
			frappe.throw(_("No pilot pieces have been sewn for these colours yet (post them through a Lay Report and Daily Line Report with purpose Pilot)."))
		is_washed = cint(frappe.db.get_value("Production Card", self.production_card, "is_washed"))
		if is_washed:
			dry = [r.colour for r in self.colours if cint(r.sewn_qty) and not cint(r.washed_qty)]
			if dry:
				frappe.throw(_("The style is washed: the pilot pieces must come back from the wash before approval. Not washed: {0}").format(", ".join(dry)))
		off = [m.point_of_measure for m in self.measurements if m.actual not in (None, "") and not cint(m.in_tolerance)]
		if off and not (self.measurement_note or "").strip():
			frappe.throw(_("Measurements are out of tolerance ({0}). Write the reason, or choose Re-run.").format(", ".join(off)))

	def on_submit(self):
		self.db_set({"status": self.decision, "approved_by": frappe.session.user, "approved_on": now_datetime()})
		if self.decision in APPROVE:
			stamp_pilot(self)

	def on_cancel(self):
		from arinox_apparel.tna.events import unstamp

		self.db_set("status", "Draft")
		unstamp("Pilot Run", self.name)


def stamp_pilot(doc):
	try:
		from arinox_apparel.tna.events import stamp

		card = frappe.db.get_value("Production Card", doc.production_card, ["sales_order", "style_item"], as_dict=True)
		for r in doc.colours:
			stamp(card.sales_order, card.style_item, r.colour, "PILOT_RUN", doc.run_date, "Pilot Run", doc.name)
	except Exception:
		frappe.log_error(title="T&A hook pilot run failed", message=frappe.get_traceback())
