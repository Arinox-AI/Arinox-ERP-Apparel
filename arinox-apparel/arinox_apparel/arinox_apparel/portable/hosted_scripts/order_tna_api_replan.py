# API arinox_order_tna_replan: recompute the plan after the PCD or the sewing window changed.
def main():
    # include: lib_samples.py
    # include: lib_tna.py
    # include: lib_tna_plan.py
    frappe.get_doc("Order TNA", frappe.form_dict.get("name")).check_permission("write")
    replan(frappe.form_dict.get("name"))
    frappe.flags.arinox_result = 1


main()
