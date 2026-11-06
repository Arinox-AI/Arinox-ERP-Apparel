# Shipment, After Save: the shipment's dates (on board, arrival, delivery) move the expected due date of its invoices.
def run(doc):
    # include: lib_followup.py
    for name in frappe.get_all("Sales Invoice", {"apparel_shipment": doc.name, "docstatus": ["<", 2]}, pluck="name"):
        refresh_invoice(name)


run(doc)
