# API arinox_cut_plan_suggest_rolls: allocate the accepted rolls in Cutting WIP to the lays of a plan (nothing is saved).
def main():
    # include: lib_mat.py
    # include: lib_cutting.py
    name = frappe.form_dict.get("name") or frappe.form_dict.get("plan")
    frappe.get_doc("Cut Plan", name).check_permission("read")
    frappe.flags.arinox_result = suggest_rolls(name)


main()
