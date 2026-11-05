# Copyright (c) 2026, Arinox AI and contributors
"""Recut Request: replacement panels for pieces rejected at cutting or sewing. The re-cut itself is a Lay Report with
purpose Re-cut that names this request. Panels are cut from the same roll, or from the same dye lot only when a manager
approves."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from arinox_apparel.production.flow import REJECT_STAGES

MANAGERS = {"Apparel Production Manager", "System Manager"}


class RecutRequest(Document):
	def validate(self):
		card = frappe.db.get_value("Production Card", self.production_card, ["docstatus", "status"], as_dict=True)
		if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
			frappe.throw(_("Production card {0} must be issued and open.").format(self.production_card))
		if not frappe.db.exists("Production Card Line", {"parent": self.production_card, "colour": self.colour, "size": self.size}):
			frappe.throw(_("{0} {1} is not on production card {2}.").format(self.colour, self.size, self.production_card))
		if cint(self.qty) <= 0:
			frappe.throw(_("Enter the quantity to re-cut."))
		lost = sum(frappe.db.sql(
			f"select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card=%s and colour=%s and size=%s and stage in ({', '.join(['%s'] * len(REJECT_STAGES))})",
			(self.production_card, self.colour, self.size, *REJECT_STAGES))[0])
		asked = cint(frappe.db.sql("select ifnull(sum(qty), 0) from `tabRecut Request` where production_card=%s and colour=%s and size=%s and docstatus=1 and name != %s",
								   (self.production_card, self.colour, self.size, self.name or ""))[0][0])
		if cint(self.qty) > lost - asked:
			frappe.throw(_("Only {0} {1} {2} pieces are rejected and not yet replaced; cannot re-cut {3}.").format(max(lost - asked, 0), self.colour, self.size, self.qty))
		self.check_roll()

	def check_roll(self):
		if not self.source_roll:
			return
		original = None
		if self.replaces_lay:
			original = frappe.db.get_value("Lay Report", self.replaces_lay, "shade_band")
		if self.replaces_bundle:
			original = frappe.db.get_value("Cut Bundle", self.replaces_bundle, "shade_band") or original
		shade = frappe.db.get_value("Batch", self.source_roll, "apparel_shade_band")
		if original and shade and shade != original:
			if not cint(self.different_roll_approved):
				frappe.throw(_("Roll {0} is shade {1} but the original panels are shade {2}. Cut from the same roll, or have a manager approve a different roll.").format(self.source_roll, shade, original))
			if not (MANAGERS & set(frappe.get_roles())):
				frappe.throw(_("Only a production manager can approve a roll of a different shade."))
		if cint(self.different_roll_approved):
			self.approved_by = frappe.session.user

	def on_cancel(self):
		self.db_set("status", "Closed")
