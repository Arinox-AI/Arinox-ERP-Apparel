# API arinox_cost_sheet_make_quotation: a submitted Cost Sheet -> Quotation (unsaved), at its quoted price.
def main():
    # include: lib_quotation.py
    cs = frappe.get_doc("Cost Sheet", frappe.form_dict.get("source_name"))
    if cs.docstatus != 1:
        frappe.throw("Submit the Cost Sheet before quoting it.")
    lines = [{"cost_sheet": cs.name, "qty": cs.order_qty or 1, "rate": cs.quoted_price}]
    frappe.flags.arinox_result = build_quotation(cs.customer, cs.currency, cs.opportunity, lines, None).as_dict()


main()
