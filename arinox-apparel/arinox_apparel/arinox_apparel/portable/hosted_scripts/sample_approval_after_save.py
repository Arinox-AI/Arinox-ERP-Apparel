# Sample Approval, After Save: an approved Fit starts the clock on samples due "after fit approval".
def run(doc):
    # include: lib_samples.py
    if doc.sample_type != "Fit" or doc.status not in APPROVED:
        return
    f = scope_filters(doc.sales_order, doc.style_item)
    f["due_date"] = ["is", "not set"]
    f["name"] = ["!=", doc.name]
    for s in frappe.get_all("Sample Approval", filters=f, fields=["name", "sample_type", "customer"]):
        rule = get_rules(s.customer, doc.sales_order, doc.style_item).get(s.sample_type)
        if rule and rule["due_basis"] == "After Fit Approval" and doc.approved_on:
            frappe.db.set_value("Sample Approval", s.name, "due_date", frappe.utils.add_days(doc.approved_on, rule["days_before"]))


run(doc)
