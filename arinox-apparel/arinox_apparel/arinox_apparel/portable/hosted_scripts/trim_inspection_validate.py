# Trim Inspection, Before Save: the receipt row, the sampling plan sets the sample size, defects -> defective %, the result (Pass / Fail / Hold) and the accepted / rejected quantities.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_po.py
    # include: lib_matinsp.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    ctx = receipt_context(doc.purchase_receipt, doc.purchase_receipt_item, "Trim")
    doc.company = ctx["pr"].company
    doc.supplier = ctx["pr"].supplier
    doc.trim_item = ctx["row"].item_code
    doc.purchase_order = ctx["purchase_order"]
    doc.trim_requisition = ctx["requisition"]
    doc.customer = ctx["customer"]
    doc.style_nos = ", ".join(ctx["styles"])
    doc.received_qty = flt(ctx["row"].stock_qty)
    doc.material_description = doc.material_description or frappe.db.get_value("Item", doc.trim_item, "item_name")
    if cint(doc.result_override):
        if not is_manager():
            frappe.throw("Only an Apparel Merchandising Manager can override the inspection rules.")
        if not (doc.override_reason or "").strip():
            frappe.throw("Enter the reason for overriding the inspection rules.")
    plan_name = doc.sampling_plan or frappe.db.get_single_value("Apparel Settings", "default_trim_sampling_plan")
    if not plan_name:
        frappe.throw("Choose a sampling plan, or set a default in Apparel Settings.")
    doc.sampling_plan = plan_name
    plan = frappe.get_doc("Trim Sampling Plan", plan_name)
    sm = trim_sample(plan, doc.received_qty)
    doc.sample_size = sm[0]
    doc.accept_max = sm[1]
    doc.reject_min = sm[2]
    if flt(doc.inspected_qty) <= 0:
        frappe.throw("Enter the quantity inspected.")
    if flt(doc.inspected_qty) > doc.received_qty + 0.0001:
        frappe.throw("Inspected qty cannot be more than the received qty (%s)." % doc.received_qty)
    doc.defective_qty = sum([cint(d.count) for d in doc.defects])
    if flt(doc.defective_qty) > flt(doc.inspected_qty):
        frappe.throw("More defects (%s) than pieces inspected (%s)." % (doc.defective_qty, doc.inspected_qty))
    doc.defective_pct = flt(doc.defective_qty * 100 / flt(doc.inspected_qty), 2)
    mixup = len([d for d in doc.defects if (d.defect_type or "").lower().replace("-", " ") == "size mix up" and cint(d.count)]) > 0
    held = doc.result == "Hold"
    doc.result = "Hold" if held else trim_result(plan, doc.defective_qty, doc.inspected_qty, doc.reject_min, mixup)
    if doc.result == "Pass":
        doc.rejected_qty = flt(doc.defective_qty)
        doc.accepted_qty = flt(doc.received_qty - doc.defective_qty)
    elif doc.result == "Fail":
        doc.rejected_qty = flt(doc.received_qty)
        doc.accepted_qty = 0
    else:
        doc.rejected_qty = 0
        doc.accepted_qty = 0
    doc.rejected_pct = flt(doc.rejected_qty * 100 / doc.received_qty, 2) if doc.received_qty else 0


run(doc)
