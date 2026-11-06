# Trim Requisition, Before Cancel: not while one of its Material Requests is already on a Purchase Order.
def run(doc):
    for mri in frappe.db.sql("select i.parent, i.name from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent "
                             "where i.apparel_requisition_type = 'TR' and i.apparel_requisition = %s and m.docstatus = 1", (doc.name,)):
        po = frappe.db.sql("select distinct p.parent from `tabPurchase Order Item` p where p.material_request_item = %s and p.docstatus < 2", (mri[1],))
        if po:
            frappe.throw("Material Request %s is already on Purchase Order %s. Cancel the order first, or revise this requisition." % (mri[0], po[0][0]))


run(doc)
