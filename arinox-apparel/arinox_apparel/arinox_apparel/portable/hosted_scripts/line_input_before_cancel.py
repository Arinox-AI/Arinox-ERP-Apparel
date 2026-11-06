# Line Input, Before Cancel: not once its bundles have sewn output.
def run(doc):
    done = [r.bundle for r in doc.bundles if r.bundle and frappe.utils.cint(frappe.db.get_value("Cut Bundle", r.bundle, "sewn_qty")) > 0]
    if done:
        frappe.throw("Bundles %s already have sewn output. Cancel the line reports first." % ", ".join(done[:5]))


run(doc)
