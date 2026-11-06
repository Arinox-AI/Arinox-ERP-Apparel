# Trim Requisition, Before Submit: every line has its trim item and a supplier (or is buyer supplied).
def run(doc):
    for r in doc.items:
        if not r.trim_item:
            frappe.throw("Row %s: choose or create the trim item before approving." % r.idx)
        if not r.supplier and not frappe.utils.cint(r.customer_provided):
            frappe.throw("Row %s: choose a supplier, or mark the trim as buyer supplied." % r.idx)


run(doc)
