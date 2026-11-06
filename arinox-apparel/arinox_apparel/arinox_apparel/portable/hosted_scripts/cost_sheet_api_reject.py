# API arinox_cost_sheet_reject: a Costing Manager rejects the costing.
def main():
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    if "Apparel Costing Manager" not in mine and "System Manager" not in mine:
        frappe.throw("Only a Costing Manager can reject a costing.")
    doc = frappe.get_doc("Cost Sheet", frappe.form_dict.get("name"))
    if doc.docstatus != 0:
        frappe.throw("Only a draft Cost Sheet can be rejected.")
    frappe.db.set_value("Cost Sheet", doc.name, {"approval_status": "Rejected", "approval_remarks": frappe.form_dict.get("remarks")})
    frappe.flags.arinox_result = "Rejected"


main()
