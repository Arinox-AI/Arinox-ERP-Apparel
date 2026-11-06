# Fabric Requisition, Before Submit: every line has its fabric item.
def run(doc):
    for r in doc.items:
        if not r.fabric_item:
            frappe.throw("Row %s: choose or create the fabric item before approving." % r.idx)


run(doc)
