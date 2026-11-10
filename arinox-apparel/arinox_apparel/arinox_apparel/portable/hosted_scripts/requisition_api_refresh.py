# API arinox_fabric_requisition_refresh_quantities: recompute ordered, received, accepted and rejected quantities and the status of one approved requisition
# (requisition_type FR or TR, name). The tower runs the after-submit rules of an inspection on a read of the ERP made before that submit, so the
# quantities a rule computes from the submitted inspections are stale; this runs afterwards, when the inspection is in the database.
def main():
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    requisition_type = frappe.form_dict.get("requisition_type")
    name = frappe.form_dict.get("name")
    dt = "Fabric Requisition" if requisition_type == "FR" else "Trim Requisition"
    if not frappe.db.exists(dt, name):
        frappe.throw("%s %s does not exist." % (dt, name))
    frappe.get_doc(dt, name).check_permission("write")
    doc = refresh_requisition(requisition_type, name)
    if not doc:
        frappe.throw("Only an approved requisition has quantities to refresh.")
    frappe.flags.arinox_result = {"name": doc.name, "status": doc.status, "lines": [{"accepted": r.accepted_qty, "received": r.received_qty, "ordered": r.ordered_qty, "rejected": r.rejected_qty} for r in doc.items]}


main()
