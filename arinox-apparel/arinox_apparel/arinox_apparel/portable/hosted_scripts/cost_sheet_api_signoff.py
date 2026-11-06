# API arinox_cost_sheet_sign_off: record the current user against one sign-off step. Steps are signed in order; the last needs a Costing Manager.
def main():
    steps = ("Fabric Cost Checked", "First Costing Done", "Second Round Checked", "Final Checked & Approved")
    name = frappe.form_dict.get("name")
    step = frappe.form_dict.get("step")
    doc = frappe.get_doc("Cost Sheet", name)
    doc.check_permission("write")
    if doc.docstatus != 0:
        frappe.throw("Only a draft Cost Sheet can be signed off.")
    if step not in steps:
        frappe.throw("Unknown sign-off step %s." % step)
    rows = {}
    for r in doc.signoffs:
        rows[r.step] = r
    if step in rows and rows[step].signed_by:
        frappe.throw("%s is already signed by %s." % (step, rows[step].signed_by))
    for earlier in steps[:steps.index(step)]:
        if earlier not in rows or not rows[earlier].signed_by:
            frappe.throw("Sign %s first." % earlier)
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    if step == steps[-1] and "Apparel Costing Manager" not in mine:
        frappe.throw("Final approval needs the Apparel Costing Manager role.")
    if step not in rows:
        doc.append("signoffs", {"step": step})
        rows[step] = doc.signoffs[-1]
    rows[step].signed_by = frappe.session.user
    rows[step].signed_on = frappe.utils.now_datetime()
    if frappe.form_dict.get("remarks"):
        rows[step].remarks = frappe.form_dict.get("remarks")
    doc.save()
    frappe.flags.arinox_result = step


main()
