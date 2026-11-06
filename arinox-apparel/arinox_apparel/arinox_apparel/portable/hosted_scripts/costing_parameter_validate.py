# Costing Parameter, Before Save: dates in order, one rate per cost head and none for heads priced from materials, a title, and no overlap with another enabled
# parameter for the same customer, product type and currency.
def run(doc):
    getdate = frappe.utils.getdate
    if doc.effective_to and getdate(doc.effective_to) < getdate(doc.effective_from):
        frappe.throw("Effective To is before Effective From.")
    seen = []
    for r in doc.rates:
        if r.cost_head in seen:
            frappe.throw("Cost head %s appears twice." % r.cost_head)
        seen.append(r.cost_head)
        if frappe.db.get_value("Cost Head", r.cost_head, "calc_type") == "From Materials":
            frappe.throw("%s is priced from materials and takes no rate here." % r.cost_head)
        if r.not_applicable:
            r.rate = 0
    doc.title = " · ".join([doc.customer or "All customers", doc.product_type or "All product types", doc.currency])
    if doc.enabled:
        far = "9999-12-31"
        others = frappe.get_all("Costing Parameter", fields=["name", "effective_from", "effective_to"],
                                filters={"enabled": 1, "name": ("!=", doc.name), "currency": doc.currency, "customer": doc.customer or ("is", "not set"),
                                         "product_type": doc.product_type or ("is", "not set")})
        for o in others:
            if getdate(o.effective_from) <= getdate(doc.effective_to or far) and getdate(doc.effective_from) <= getdate(o.effective_to or far):
                frappe.throw("Overlaps %s for the same customer, product type and currency. Close that one with an Effective To date first." % o.name)


run(doc)
