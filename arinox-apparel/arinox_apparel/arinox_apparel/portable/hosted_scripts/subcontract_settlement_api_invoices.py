# API arinox_subcontract_settlement_make_invoices: draft the vendor's Purchase Invoice (and a debit note for the penalty). Accounts submits them.
def main():
    doc = frappe.get_doc("Subcontract Settlement", frappe.form_dict.get("settlement") or frappe.form_dict.get("name"))
    doc.check_permission("read")
    frappe.new_doc("Purchase Invoice").check_permission("create")
    if doc.docstatus != 1:
        frappe.throw("Submit the settlement first.")
    item = frappe.db.get_value("Subcontract Process", doc.subcontract_process, "service_item")
    if not item:
        frappe.throw("Set the Service Item on process %s first." % doc.subcontract_process)
    company = frappe.db.get_value("Production Card", doc.production_card, "company")
    if not doc.purchase_invoice and doc.payable_qty:
        pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": company, "supplier": doc.supplier, "bill_no": doc.vendor_invoice_ref, "posting_date": doc.settlement_date,
                             "items": [{"item_code": item, "qty": doc.payable_qty, "rate": doc.rate}]})
        pi.insert()
        doc.db_set("purchase_invoice", pi.name)
    if not doc.debit_note and doc.penalty_amount:
        dn = frappe.get_doc({"doctype": "Purchase Invoice", "company": company, "supplier": doc.supplier, "is_return": 1, "posting_date": doc.settlement_date,
                             "items": [{"item_code": item, "qty": -1, "rate": doc.penalty_amount, "description": "Damage penalty, challan %s" % doc.challan}]})
        dn.insert()
        doc.db_set("debit_note", dn.name)
    frappe.flags.arinox_result = {"purchase_invoice": doc.purchase_invoice or None, "debit_note": doc.debit_note or None}


main()
