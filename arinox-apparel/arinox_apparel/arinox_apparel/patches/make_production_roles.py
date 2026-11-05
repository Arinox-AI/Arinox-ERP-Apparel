"""Create the Phase D roles before doctypes that name them in their permissions are synced."""

import frappe


def execute():
	for role in ("Apparel Production Manager", "Apparel Production User", "Apparel QA"):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
