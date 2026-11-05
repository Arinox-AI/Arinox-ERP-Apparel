# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""The time-and-action plan of one style x colour x ex-factory date of a Sales Order."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import MANAGER_ROLES


class OrderTNA(Document):
	def validate(self):
		so = frappe.db.get_value("Sales Order", self.sales_order, ["docstatus", "customer", "company"], as_dict=True)
		if not so or so.docstatus != 1:
			frappe.throw(_("Sales Order {0} must be submitted.").format(self.sales_order))
		self.customer, self.company = so.customer, so.company
		clash = frappe.db.exists("Order TNA", {"sales_order": self.sales_order, "style_item": self.style_item, "colour": self.colour or "",
			"ex_factory_date": getdate(self.ex_factory_date), "status": ["!=", "Cancelled"], "name": ["!=", self.name or ""]})
		if clash:
			frappe.throw(_("{0} already plans this style, colour and ex-factory date.").format(clash))
		if not self.template:
			self.template = frappe.db.get_single_value("Apparel Settings", "default_tna_template")

	@frappe.whitelist()
	def lock_baseline(self):
		"""Freeze the planned dates. From now on a change goes in the Revised Date with a reason."""
		self.check_permission("write")
		self.db_set("baseline_locked", 1)
		return 1

	@frappe.whitelist()
	def unlock_baseline(self):
		if not set(frappe.get_roles()) & set(MANAGER_ROLES):
			frappe.throw(_("Only an Apparel Merchandising Manager can unlock the baseline."))
		self.db_set("baseline_locked", 0)
		return 0

	@frappe.whitelist()
	def replan(self):
		from arinox_apparel.tna.planner import replan

		self.check_permission("write")
		replan(self.name)
		return 1
