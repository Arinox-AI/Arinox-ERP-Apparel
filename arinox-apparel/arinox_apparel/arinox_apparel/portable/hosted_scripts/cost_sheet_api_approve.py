# API arinox_cost_sheet_approve: a Costing Manager approves a margin below the floor.
def main():
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    if "Apparel Costing Manager" not in mine and "System Manager" not in mine:
        frappe.throw("Only a Costing Manager can approve a margin.")
    doc = frappe.get_doc("Cost Sheet", frappe.form_dict.get("name"))
    if doc.docstatus != 0:
        frappe.throw("Only a draft Cost Sheet can be approved.")
    if not doc.below_floor:
        frappe.throw("This Cost Sheet is above the margin floor; no approval is needed.")
    doc.approval_remarks = frappe.form_dict.get("remarks")
    doc.approval_status = "Approved"
    doc.approved_by = frappe.session.user
    doc.approved_on = frappe.utils.now_datetime()
    doc.approved_price = doc.quoted_price
    doc.save()
    frappe.flags.arinox_result = doc.approval_status


main()
