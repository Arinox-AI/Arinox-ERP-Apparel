# API arinox_cut_plan_reopen: back to draft, unless a lay was already cut from the plan.
def main():
    name = frappe.form_dict.get("name")
    used = frappe.db.exists("Lay Report", {"cut_plan": name, "docstatus": 1})
    if used:
        frappe.throw("Lay %s is already cut from this plan. Make a new plan instead." % used)
    frappe.get_doc("Cut Plan", name).db_set({"status": "Draft", "approved_by": None, "approved_on": None})
    frappe.flags.arinox_result = "Draft"


main()
