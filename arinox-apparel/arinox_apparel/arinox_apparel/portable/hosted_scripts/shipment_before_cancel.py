# Shipment, Before Cancel: not while its delivery notes are submitted.
def run(doc):
    if frappe.db.exists("Delivery Note", {"apparel_shipment": doc.name, "docstatus": 1}):
        frappe.throw("Delivery notes of this shipment are submitted. Cancel them first.")


run(doc)
