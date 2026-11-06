# Subcontract Settlement, Before Submit: the rate per piece is needed.
def run(doc):
    if not doc.rate:
        frappe.throw("Enter the rate per piece.")


run(doc)
