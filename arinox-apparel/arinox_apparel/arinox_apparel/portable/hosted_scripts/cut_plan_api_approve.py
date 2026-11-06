# API arinox_cut_plan_approve: a production or merchandising manager accepts the marker consumption, with a reason.
def main():
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if not [r for r in roles if r in ("Apparel Production Manager", "Apparel Merchandising Manager", "System Manager")]:
        frappe.throw("Only a production or merchandising manager can approve the marker consumption.")
    plan = frappe.get_doc("Cut Plan", frappe.form_dict.get("name"))
    note = frappe.form_dict.get("note")
    if not (note or plan.approval_note or "").strip():
        frappe.throw("Write the reason for accepting this marker consumption.")
    plan.db_set({"approved_by": frappe.session.user, "approved_on": frappe.utils.now_datetime(), "approval_note": note or plan.approval_note, "status": "Released"})
    frappe.flags.arinox_result = "Released"


main()
