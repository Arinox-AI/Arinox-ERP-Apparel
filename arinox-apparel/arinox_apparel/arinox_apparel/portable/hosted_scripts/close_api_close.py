# API arinox_close_commercial_close: production done, everything shipped invoiced, every customer invoice paid, no claim open; the claim windows may be waived with a reason.
# Closing sets the Sales Order to Closed.
def main():
    # include: lib_close.py
    sales_order = frappe.form_dict.get("sales_order")
    waive_reason = frappe.form_dict.get("waive_reason")
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if not [r for r in roles if r in ("Accounts Manager", "Apparel Merchandising Manager", "System Manager")]:
        frappe.throw("Only an accounts or merchandising manager closes an order commercially.")
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("write")
    failed = [r for r in checklist(sales_order) if not r[1]]
    hard = [r for r in failed if r[0] != "Claim windows over"]
    if hard:
        frappe.throw("<br>".join([("%s: %s" % (r[0], r[2])) if r[2] else r[0] for r in hard]), title="The order cannot be closed yet")
    if failed and not (waive_reason or "").strip():
        frappe.throw("A claim window is still open. Write why the order may close anyway.")
    frappe.call("erpnext.selling.doctype.sales_order.sales_order.update_status", status="Closed", name=sales_order)
    so.add_comment("Comment", "Closed commercially. %s" % (waive_reason or ""))
    frappe.flags.arinox_result = True


main()
