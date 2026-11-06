# API arinox_cost_sheet_set_charges_from_parameter: the charge rows a Cost Sheet should have, from its costing parameter.
# The form sends the unsaved document as JSON; the answer is applied to the form by the client shim (arinox_doc).
def main():
    # include: lib_costing.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    param = d.get("costing_parameter") or find_costing_parameter(d.get("customer"), d.get("product_type"), d.get("costing_date"), d.get("currency"))
    frappe.flags.arinox_result = {"arinox_doc": {"charges": charge_rows(param), "costing_parameter": param}}


main()
