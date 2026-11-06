# API arinox_fabric_requisition_revise_fabric_requisition: a new draft revision of an approved requisition (unsaved). Quantities are refreshed from the order on save;
# only the increase is requested again when it is submitted.
def main():
    # include: lib_samples.py
    # include: lib_allocation.py
    # include: lib_requisition.py
    src = frappe.get_doc("Fabric Requisition", frappe.form_dict.get("source_name"))
    src.check_permission("read")
    if src.docstatus != 1 or src.status in ("Superseded", "Cancelled"):
        frappe.throw("Only an approved, current requisition can be revised.")
    new = frappe.copy_doc(src)
    new.docstatus = 0
    for child in new.get_all_children():
        child.docstatus = 0
    new.previous_fr = src.name
    new.revision_no = frappe.utils.cint(src.revision_no) + 1
    new.status = "Draft"
    new.arinox_name = None            # a revision gets a new number
    new.set("summary", [])
    new.revision_reason = None
    new.approved_by = None
    new.approved_on = None
    for r in new.items:
        r.material_request = None
        r.material_request_item = None
        r.ordered_qty = 0
        r.received_qty = 0
        r.accepted_qty = 0
        r.rejected_qty = 0
        r.garment_qty = order_colour_qty(r.sales_order, r.style_item, r.colour) or r.garment_qty
    frappe.flags.arinox_result = new.as_dict()


main()
