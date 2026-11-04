# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class SalesContractTemplate(Document):
	def validate(self):
		validate_bands(self.tolerance_bands)
		if self.is_default and not self.customer:
			frappe.throw(_("Default is per customer. Set the Apparel Settings default for all customers."))
		if self.is_default and self.customer:
			frappe.db.sql(
				"""update `tabSales Contract Template` set is_default = 0
				where customer = %s and name != %s""",
				(self.customer, self.name),
			)


def validate_bands(bands):
	rows = sorted(bands, key=lambda b: cint(b.from_qty))
	for b in rows:
		if cint(b.to_qty) and cint(b.to_qty) < cint(b.from_qty):
			frappe.throw(_("Tolerance band row {0}: To Qty is below From Qty.").format(b.idx))
	for a, b in zip(rows, rows[1:]):
		if not cint(a.to_qty) or cint(a.to_qty) >= cint(b.from_qty):
			frappe.throw(_("Tolerance bands {0} and {1} overlap.").format(a.idx, b.idx))
