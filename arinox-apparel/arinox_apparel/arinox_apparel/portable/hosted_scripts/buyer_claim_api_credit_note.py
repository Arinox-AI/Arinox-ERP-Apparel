# API arinox_buyer_claim_make_credit_note: draft the credit note for an accepted claim against the customer invoice (the accountant submits it). Answers its name.
def main():
    flt = frappe.utils.flt
    frappe.new_doc("Sales Invoice").check_permission("create")
    c = frappe.get_doc("Buyer Claim", frappe.form_dict.get("claim") or frappe.form_dict.get("name"))
    c.check_permission("read")
    if c.docstatus != 1 or c.settlement != "Credit Note" or flt(c.accepted_amount) <= 0:
        frappe.throw("Only a submitted claim settled by credit note can be credited.")
    if c.credit_note:
        frappe.flags.arinox_result = c.credit_note
        return
    cn = frappe.call("erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return", source_name=c.sales_invoice)
    item = cn.items[0]
    cn.set("items", [{"item_code": item.item_code, "item_name": item.item_name, "description": "Claim %s: %s" % (c.name, c.claim_type), "qty": -1, "uom": item.uom,
                      "rate": flt(c.accepted_amount), "income_account": item.income_account, "cost_center": item.cost_center}])
    cn.update_stock = 0
    cn.run_method("calculate_taxes_and_totals")
    cn.insert()
    c.db_set("credit_note", cn.name)
    frappe.flags.arinox_result = cn.name


main()
