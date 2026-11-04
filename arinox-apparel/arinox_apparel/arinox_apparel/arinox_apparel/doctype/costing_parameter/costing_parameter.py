# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Effective-dated costing rates for a customer x product type. Nothing in costing is hardcoded."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class CostingParameter(Document):
	def validate(self):
		if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
			frappe.throw(_("Effective To is before Effective From."))
		seen = set()
		for r in self.rates:
			if r.cost_head in seen:
				frappe.throw(_("Cost head {0} appears twice.").format(r.cost_head))
			seen.add(r.cost_head)
			if frappe.db.get_value("Cost Head", r.cost_head, "calc_type") == "From Materials":
				frappe.throw(_("{0} is priced from materials and takes no rate here.").format(r.cost_head))
			if r.not_applicable:
				r.rate = 0
		self.title = " · ".join(
			[self.customer or _("All customers"), self.product_type or _("All product types"), self.currency]
		)
		if self.enabled:
			self.check_overlap()

	def check_overlap(self):
		far = "9999-12-31"
		for o in frappe.get_all(
			"Costing Parameter",
			filters={
				"enabled": 1,
				"name": ("!=", self.name),
				"currency": self.currency,
				"customer": self.customer or ("is", "not set"),
				"product_type": self.product_type or ("is", "not set"),
			},
			fields=["name", "effective_from", "effective_to"],
		):
			if getdate(o.effective_from) <= getdate(self.effective_to or far) and getdate(self.effective_from) <= getdate(
				o.effective_to or far
			):
				frappe.throw(
					_("Overlaps {0} for the same customer, product type and currency. Close that one with an Effective To date first.").format(o.name)
				)
