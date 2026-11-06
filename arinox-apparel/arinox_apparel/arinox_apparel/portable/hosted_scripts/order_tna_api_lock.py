# API arinox_order_tna_lock_baseline: freeze the planned dates. From now on a change goes in the Revised Date with a reason.
def main():
    doc = frappe.get_doc("Order TNA", frappe.form_dict.get("name"))
    doc.check_permission("write")
    doc.db_set("baseline_locked", 1)
    frappe.flags.arinox_result = 1


main()
