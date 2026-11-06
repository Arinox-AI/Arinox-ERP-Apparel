# Fabric Requisition, After Submit: approved. Material Requests (grouped by supplier, only the increase over earlier revisions), the previous revision is superseded,
# the FR_RAISED milestone is stamped.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    flt = frappe.utils.flt
    doc.db_set({"approved_by": frappe.session.user, "approved_on": frappe.utils.now_datetime()})
    chain = revision_chain("Fabric Requisition", "previous_fr", doc.name)[1:]
    lines = []
    for r in doc.items:
        if flt(r.net_qty) <= 0:
            continue
        key = fr_row_key(r)
        delta = flt(r.net_qty) - requested_so_far("FR", chain, key)
        if delta <= 0.0005:
            continue
        order_qty = round_up_to_pack(from_metres(delta, r.order_uom, r.gsm, r.cuttable_width_cm), r.pack_size)
        q = mr_line(r.fabric_item, delta, r.order_uom, order_qty)
        lines.append({"item_code": r.fabric_item, "qty": q[0], "uom": q[1], "conversion_factor": q[2], "supplier": r.supplier, "required_by": r.required_by, "key": key,
                      "style_no": r.style_no, "colour": r.colour, "sales_order": r.sales_order, "description": r.fabric_description,
                      "hold_reason": "Lab dip %s" % r.lab_dip_status if r.hold else None})
    create_material_requests(doc, lines, "FR", "Fabric")
    for r in doc.items:
        mri = frappe.db.sql("select i.name, i.parent from `tabMaterial Request Item` i where i.apparel_requisition_type = 'FR' and i.apparel_requisition = %s "
                            "and i.apparel_requisition_item = %s limit 1", (doc.name, fr_row_key(r)))
        if mri:
            r.db_set({"material_request": mri[0][1], "material_request_item": mri[0][0]})
    if doc.previous_fr:
        frappe.db.set_value("Fabric Requisition", doc.previous_fr, "status", "Superseded")
    stamp_safe_requisition(doc, "FR_RAISED")
    status = requisition_status(doc)
    doc.status = status
    doc.db_set("status", status, update_modified=False)


run(doc)
