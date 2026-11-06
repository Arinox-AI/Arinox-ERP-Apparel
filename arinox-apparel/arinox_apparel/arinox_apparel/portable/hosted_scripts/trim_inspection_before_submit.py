# Trim Inspection, Before Submit: at least the sample size was inspected (unless a manager overrides).
def run(doc):
    flt = frappe.utils.flt
    if flt(doc.inspected_qty) + 0.0001 < flt(doc.sample_size) and not frappe.utils.cint(doc.result_override):
        frappe.throw("Inspect at least %s pieces for this lot (%s inspected)." % (flt(doc.sample_size), flt(doc.inspected_qty)))


run(doc)
