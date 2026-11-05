# Production Card, Before Cancel: a card with quantities cannot be cancelled.
def run(doc):
    if frappe.db.exists("Production Movement", {"production_card": doc.name}):
        frappe.throw("Production card %s already has cutting, sewing or packing quantities and cannot be cancelled. "
                     "Use Revise, or a Production Adjustment to correct a count." % doc.name)


run(doc)
