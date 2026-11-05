# Copyright (c) 2026, Arinox AI and contributors
"""Cut Bundle: a ticketed group of panels (one size, consecutive plies, one component). Made by the Lay Report; the line
input, the subcontract challans and the daily line report move its status."""

import frappe
from frappe import _
from frappe.model.document import Document


class CutBundle(Document):
	def validate(self):
		if not self.is_new() and self.has_value_changed("qty") and self.status != "Voided":
			frappe.throw(_("A bundle quantity cannot be changed. Void the lay and cut it again."))
