"""Number card queries for the Materials workspace."""

import frappe
from frappe.utils import add_days, nowdate


def _n(value, doctype):
	"""A count for a number card. Refused for a user who cannot read the documents being counted."""
	frappe.has_permission(doctype, "read", throw=True)
	return {"value": int(value or 0), "fieldtype": "Int"}


@frappe.whitelist()
def fabric_overdue():
	return _n(frappe.db.sql(
		"""select count(*) from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent where p.docstatus = 1
		and p.status not in ('Superseded', 'Cancelled') and c.net_qty > 0 and c.required_by < %s and c.accepted_qty < c.net_qty""", nowdate())[0][0], "Fabric Requisition")


@frappe.whitelist()
def rolls_awaiting_inspection():
	return _n(frappe.db.count("Batch", {"apparel_inspection_status": "Uninspected", "apparel_roll_no": ["!=", ""], "disabled": 0}), "Batch")


@frappe.whitelist()
def rejected_lots():
	return _n(frappe.db.count("Fabric Inspection", {"docstatus": 1, "lot_result": "Fail", "creation": [">=", add_days(nowdate(), -30)]}), "Fabric Inspection")


@frappe.whitelist()
def trim_lines_on_hold():
	return _n(frappe.db.sql(
		"""select count(*) from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent where p.docstatus = 1
		and p.status not in ('Superseded', 'Cancelled') and c.hold = 1 and c.ordered_qty = 0""")[0][0], "Trim Requisition")
