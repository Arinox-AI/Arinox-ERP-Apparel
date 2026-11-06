# Fabric Requisition, After Cancel: its Material Requests are cancelled, the previous revision is current again, the milestone is cleared.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    done = []
    for m in frappe.db.sql("select distinct i.parent from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent "
                           "where i.apparel_requisition_type = 'FR' and i.apparel_requisition = %s and m.docstatus = 1", (doc.name,)):
        if m[0] in done:
            continue
        done.append(m[0])
        mr = frappe.get_doc("Material Request", m[0])
        mr.flags.ignore_permissions = True
        mr.cancel()
    if doc.previous_fr:
        frappe.db.set_value("Fabric Requisition", doc.previous_fr, "status", "Approved")
        prev = frappe.get_doc("Fabric Requisition", doc.previous_fr)
        prev.status = "Approved"
        frappe.db.set_value("Fabric Requisition", doc.previous_fr, "status", requisition_status(prev), update_modified=False)
    unstamp_safe("Fabric Requisition", doc.name)
    doc.db_set("status", "Cancelled")


run(doc)
