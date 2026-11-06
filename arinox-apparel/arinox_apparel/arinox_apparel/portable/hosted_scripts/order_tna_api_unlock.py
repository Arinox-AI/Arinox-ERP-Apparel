# API arinox_order_tna_unlock_baseline: only an Apparel Merchandising Manager can unlock the baseline.
def main():
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if not [r for r in roles if r in ("Apparel Merchandising Manager", "System Manager")]:
        frappe.throw("Only an Apparel Merchandising Manager can unlock the baseline.")
    frappe.get_doc("Order TNA", frappe.form_dict.get("name")).db_set("baseline_locked", 0)
    frappe.flags.arinox_result = 0


main()
