# Delivery Note, Before Cancel: submitted invoices of the shipment must be cancelled first.
def run(doc):
    has_lists = False
    for it in doc.items:
        if it.get("apparel_packing_list"):
            has_lists = True
    if not has_lists:
        return
    if frappe.db.exists("Sales Invoice Item", {"delivery_note": doc.name, "docstatus": 1}) or (
            doc.get("apparel_shipment") and frappe.db.exists("Sales Invoice", {"apparel_shipment": doc.apparel_shipment, "docstatus": 1})):
        frappe.throw("Invoices of this shipment are submitted. Cancel them before cancelling the Delivery Note.")


run(doc)
