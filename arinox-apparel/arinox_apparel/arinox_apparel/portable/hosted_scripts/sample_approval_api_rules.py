# API arinox_sample_approval_get_sample_rules: the rule of every sample type for a customer / order / style.
def main():
    # include: lib_samples.py
    frappe.new_doc("Sample Approval").check_permission("read")
    frappe.flags.arinox_result = get_rules(frappe.form_dict.get("customer"), frappe.form_dict.get("sales_order"), frappe.form_dict.get("style_item"))


main()
