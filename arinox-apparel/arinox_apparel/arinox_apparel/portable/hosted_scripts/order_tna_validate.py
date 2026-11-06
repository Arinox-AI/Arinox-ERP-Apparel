# Order TNA, Before Save: the Sales Order is submitted, one plan per style x colour x ex-factory date, the default template.
def run(doc):
    so = frappe.db.get_value("Sales Order", doc.sales_order, ["docstatus", "customer", "company"], as_dict=True)
    if not so or so.docstatus != 1:
        frappe.throw("Sales Order %s must be submitted." % doc.sales_order)
    doc.customer = so.customer
    doc.company = so.company
    clash = frappe.db.exists("Order TNA", {"sales_order": doc.sales_order, "style_item": doc.style_item, "colour": doc.colour or "",
                                           "ex_factory_date": frappe.utils.getdate(doc.ex_factory_date), "status": ["!=", "Cancelled"], "name": ["!=", doc.name or ""]})
    if clash:
        frappe.throw("%s already plans this style, colour and ex-factory date." % clash)
    if not doc.template:
        doc.template = frappe.db.get_single_value("Apparel Settings", "default_tna_template")


run(doc)
