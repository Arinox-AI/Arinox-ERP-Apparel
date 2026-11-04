# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CostHead(Document):
	def validate(self):
		if self.calc_type != "From Materials":
			self.material_scope = None
		if self.head_group == "Profit" and self.calc_type not in ("Percent of Subtotal", "Percent of Product Cost", "Percent of Price"):
			frappe.throw(
				_("Profit must be a percentage: Percent of Subtotal (markup on cost, as on the costing sheet), Percent of Product Cost, or Percent of Price.")
			)
		if not self.enabled and not self.is_new():
			used = frappe.db.sql(
				"""select p.name from `tabCosting Parameter Rate` r
				join `tabCosting Parameter` p on p.name = r.parent
				where r.cost_head = %s and p.enabled = 1 limit 1""",
				self.name,
			)
			if used:
				frappe.throw(_("Cost head is used by enabled Costing Parameter {0}.").format(used[0][0]))
