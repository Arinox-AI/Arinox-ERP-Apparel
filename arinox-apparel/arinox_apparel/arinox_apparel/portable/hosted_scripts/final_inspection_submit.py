# Final Inspection, Before Submit: a result is chosen and the cartons to open have been drawn (once each, from the lot).
def run(doc):
    cint = frappe.utils.cint
    if not doc.result:
        frappe.throw("Choose the result.")
    if doc.inspection_type in ("Final", "Re-inspection", "2nd Re-inspection") and len(doc.cartons_picked) < min(cint(doc.inspected_cartons), cint(doc.total_cartons)):
        frappe.throw("Draw the %s cartons to inspect (Pick Cartons) before submitting." % doc.inspected_cartons)
    seen = []
    in_lot = [l.packing_list for l in doc.lots]
    for c in doc.cartons_picked:
        k = (c.packing_list, c.carton_no)
        if k in seen:
            frappe.throw("Carton %s of %s is drawn twice." % (c.carton_no, c.packing_list))
        seen.append(k)
        if c.packing_list not in in_lot:
            frappe.throw("Carton %s: %s is not in the lot." % (c.carton_no, c.packing_list))


run(doc)
