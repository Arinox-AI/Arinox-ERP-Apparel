# Subcontract Challan, Before Cancel: not while a return or the settlement stands.
def run(doc):
    if frappe.db.exists("Subcontract Return", {"challan": doc.name, "docstatus": 1}):
        frappe.throw("Cancel the returns against this challan first.")
    if frappe.db.exists("Subcontract Settlement", {"challan": doc.name, "docstatus": 1}):
        frappe.throw("Cancel the settlement of this challan first.")


run(doc)
