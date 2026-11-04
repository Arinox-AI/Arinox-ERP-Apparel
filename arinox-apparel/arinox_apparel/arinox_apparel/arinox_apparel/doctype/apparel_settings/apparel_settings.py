# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class ApparelSettings(Document):
	def validate(self):
		if cint(self.max_skus_per_contract) < 1:
			frappe.throw(_("Max SKUs per contract must be at least 1."))
		if self.quote_item and frappe.db.get_value("Item", self.quote_item, "has_variants"):
			frappe.throw(_("The quotation style item cannot be a template item."))
