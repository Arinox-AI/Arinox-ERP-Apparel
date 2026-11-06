# API arinox_subcontract_challan_short_close: accept that the rest will not come back. Production Manager only; the gap shows as Short on the settlement.
def main():
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if "Apparel Production Manager" not in roles and "System Manager" not in roles:
        frappe.throw("Only a Production Manager can short-close a challan.")
    reason = frappe.form_dict.get("reason")
    if not (reason or "").strip():
        frappe.throw("Write the reason.")
    name = frappe.form_dict.get("challan") or frappe.form_dict.get("name")
    doc = frappe.get_doc("Subcontract Challan", name)
    doc.check_permission("read")
    if doc.docstatus != 1:
        frappe.throw("Only a submitted challan can be short-closed.")
    frappe.db.set_value("Subcontract Challan", name, {"status": "Short Closed", "short_close_reason": reason})
    frappe.flags.arinox_result = "Short Closed"


main()
