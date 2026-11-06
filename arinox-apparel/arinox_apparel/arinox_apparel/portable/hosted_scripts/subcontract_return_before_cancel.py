# Subcontract Return, Before Cancel: not once the settlement stands.
def run(doc):
    if frappe.db.exists("Subcontract Settlement", {"challan": doc.challan, "docstatus": 1}):
        frappe.throw("Cancel the settlement of challan %s first." % doc.challan)
    if frappe.db.exists("Finishing Receipt", {"production_card": doc.production_card, "docstatus": 1}):
        frappe.msgprint("Finishing receipts exist for this card; the flow check will stop the cancel if they used these pieces.", indicator="orange")


run(doc)
