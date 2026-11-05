# Copyright (c) 2026, Arinox AI and contributors
"""Production Adjustment: a manager's correction of a counting mistake. The ledger is append-only through documents,
so a wrong count is fixed by a signed adjustment with a reason, never by editing history."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from arinox_apparel.production import ledger

PROCESS_STAGES = ("SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY")


class ProductionAdjustment(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		if not flt(self.qty):
			frappe.throw(_("Enter a quantity other than zero."))
		if not (self.reason or "").strip():
			frappe.throw(_("Enter the reason for the adjustment."))
		if self.stage in PROCESS_STAGES and not self.subcontract_process:
			frappe.throw(_("Choose the process for stage {0}.").format(self.stage))
		if not frappe.db.exists("Production Card Line", {"parent": self.production_card, "colour": self.colour, "size": self.size}):
			frappe.throw(_("{0} {1} is not on production card {2}.").format(self.colour, self.size, self.production_card))

	def rows(self):
		return [{"stage": self.stage, "colour": self.colour, "size": self.size, "qty": flt(self.qty), "purpose": self.purpose or "Bulk",
				 "process": self.subcontract_process, "source_row": self.name}]

	def on_submit(self):
		if flt(self.qty) < 0:
			have = ledger.stage_total(self.production_card, self.stage, self.colour, self.size, self.purpose or "Bulk")
			if have + flt(self.qty) < -1e-9:
				frappe.throw(_("Only {0} recorded for {1}; cannot take off {2}.").format(have, self.stage, abs(flt(self.qty))))
		self.post_movements(check=False)

	def post_movements(self, check=False):
		ledger.post(self.production_card, self.rows(), "Production Adjustment", self.name, self.posting_date, check=False)

	def on_cancel(self):
		ledger.unpost("Production Adjustment", self.name)
