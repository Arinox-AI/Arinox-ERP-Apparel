# Trim Requisition, After Submit: approved. Material Requests (grouped by supplier, only the increase over earlier revisions), previous revision superseded, TR_RAISED stamped.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    doc.db_set({"approved_by": frappe.session.user, "approved_on": frappe.utils.now_datetime()})
    chain = revision_chain("Trim Requisition", "previous_tr", doc.name)[1:]
    lines = []
    for r in doc.items:
        if flt(r.net_qty) <= 0:
            continue
        key = tr_row_key(r)
        delta = flt(r.net_qty) - requested_so_far("TR", chain, key)
        if delta <= 0.0005:
            continue
        stock_uom = frappe.db.get_value("Item", r.trim_item, "stock_uom")
        order_qty = delta if r.order_uom == stock_uom else round_up_to_pack(delta, r.pack_size)
        q = mr_line(r.trim_item, delta, r.order_uom, order_qty)
        qty = q[0]
        if q[2] == 1 and q[1] == stock_uom:
            qty = frappe.utils.ceil(round(delta, 4)) if r.calc_basis != "By Length" else flt(delta, 2)
        lines.append({"item_code": r.trim_item, "qty": qty, "uom": q[1], "conversion_factor": q[2], "supplier": r.supplier, "required_by": r.required_by, "key": key,
                      "style_no": r.style_no, "colour": r.colour, "sales_order": r.sales_order, "description": r.description, "customer_provided": cint(r.customer_provided),
                      "hold_reason": "Trim approval %s" % r.approval_status if r.hold else None})
    create_material_requests(doc, lines, "TR", "Trim")
    for r in doc.items:
        mri = frappe.db.sql("select i.name, i.parent from `tabMaterial Request Item` i where i.apparel_requisition_type = 'TR' and i.apparel_requisition = %s "
                            "and i.apparel_requisition_item = %s limit 1", (doc.name, tr_row_key(r)))
        if mri:
            r.db_set({"material_request": mri[0][1], "material_request_item": mri[0][0]})
    if doc.previous_tr:
        frappe.db.set_value("Trim Requisition", doc.previous_tr, "status", "Superseded")
    stamp_safe_requisition(doc, "TR_RAISED")
    status = requisition_status(doc)
    doc.status = status
    doc.db_set("status", status, update_modified=False)


run(doc)
