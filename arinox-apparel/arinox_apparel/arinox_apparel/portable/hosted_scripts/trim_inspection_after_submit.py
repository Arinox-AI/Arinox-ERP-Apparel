# Trim Inspection, After Submit: the Quality Inspection and the Stock Entry (accepted to store, rejected to the rejected warehouse), then the requisition is refreshed and TRIMS_QC_PASSED stamped.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_matinsp.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    ctx = receipt_context(doc.purchase_receipt, doc.purchase_receipt_item, "Trim")
    ok = doc.result == "Pass"
    mixup = len([d for d in doc.defects if (d.defect_type or "").lower().replace("-", " ") == "size mix up" and cint(d.count)]) > 0
    qi = make_quality_inspection(ctx, doc.trim_item, ok, [["Trim Defective %", doc.defective_pct, "Accepted" if ok else "Rejected"],
                                                          ["Trim Size Mix-up", "Yes" if mixup else "No", "Rejected" if mixup else "Accepted"]], doc.inspected_qty, doc.remarks)
    store = company_warehouse("store_warehouse_trim", doc.company)
    reject = company_warehouse("rejected_warehouse", doc.company)
    se = make_stock_entry(ctx, [{"item_code": doc.trim_item, "qty": doc.accepted_qty, "target": store}, {"item_code": doc.trim_item, "qty": doc.rejected_qty, "target": reject}],
                          cint(frappe.db.get_single_value("Apparel Settings", "submit_inspection_stock_entry")))
    doc.db_set({"quality_inspection": qi, "stock_entry": se})
    if not doc.trim_requisition:
        return
    req = refresh_requisition("TR", doc.trim_requisition)
    if not req:
        return
    need = frappe.db.get_single_value("Apparel Settings", "material_gate_min_pct") or 100
    full = {}
    keys = []
    vals = {}
    for r in req.items:
        k = "%s|%s|%s" % (r.sales_order, r.style_item, (r.colour or "").strip())
        if k not in keys:
            keys.append(k)
            full[k] = True
            vals[k] = [r.sales_order, r.style_item, (r.colour or "").strip()]
        full[k] = full[k] and flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * flt(need) / 100
    for k in keys:
        stamp_safe(vals[k][0], vals[k][1], vals[k][2] or None, "TRIMS_QC_PASSED", doc.received_date, "Trim Inspection", doc.name, not full[k], False)


run(doc)
