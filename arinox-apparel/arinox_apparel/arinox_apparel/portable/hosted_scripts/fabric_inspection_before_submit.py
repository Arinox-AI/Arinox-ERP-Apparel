# Fabric Inspection, Before Submit: the required sample was inspected and a failed sample went to 100% (unless a manager overrides).
def run(doc):
    flt = frappe.utils.flt
    override = frappe.utils.cint(doc.result_override)
    if flt(doc.inspected_m) + 0.005 < flt(doc.required_inspect_m) and not override:
        frappe.throw("Inspect at least %s m (%s%% of %s m). %s m inspected so far." % (doc.required_inspect_m, doc.sampling_pct, flt(doc.total_received_m, 2), doc.inspected_m))
    if doc.lot_result == "Re-inspect 100%" and not override:
        frappe.throw("The sample failed. Inspect every roll before submitting, or have a manager override.")


run(doc)
