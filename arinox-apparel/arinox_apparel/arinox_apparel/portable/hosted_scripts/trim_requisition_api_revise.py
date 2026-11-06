# API arinox_trim_requisition_revise_trim_requisition: a new draft revision of an approved requisition (unsaved). Quantities are refreshed from the order on save;
# only the increase is requested again when it is submitted.
def main():
    # include: lib_samples.py
    # include: lib_allocation.py
    # include: lib_mat.py
    # include: lib_requisition.py
    def trim_qty_for(r):
        total = 0
        for it in frappe.get_all("Sales Order Item", filters={"parent": r.sales_order}, fields=["item_code", "qty", "apparel_colour", "apparel_size"]):
            if style_of(it.item_code) != r.style_item:
                continue
            if r.colour and (it.apparel_colour or "").strip().upper() != r.colour.strip().upper():
                continue
            if r.size and (it.apparel_size or "").strip().upper() != r.size.strip().upper():
                continue
            total = total + frappe.utils.cint(it.qty)
        return total

    src = frappe.get_doc("Trim Requisition", frappe.form_dict.get("source_name"))
    src.check_permission("read")
    if src.docstatus != 1 or src.status in ("Superseded", "Cancelled"):
        frappe.throw("Only an approved, current requisition can be revised.")
    new = frappe.copy_doc(src)
    new.docstatus = 0
    for child in new.get_all_children():
        child.docstatus = 0
    new.previous_tr = src.name
    new.revision_no = frappe.utils.cint(src.revision_no) + 1
    new.status = "Draft"
    new.arinox_name = None            # a revision gets a new number
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
        r.garment_qty = trim_qty_for(r) or r.garment_qty
    frappe.flags.arinox_result = new.as_dict()


main()
