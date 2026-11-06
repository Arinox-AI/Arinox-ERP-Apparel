# PP Meeting, Before Save: the order is submitted and carries the style, the PP sample is a PP of that style, factory / line / PCD default from the
# Factory Allocation, closed actions are stamped with the day, and the status follows the actions.
def run(doc):
    # include: lib_allocation.py
    so = frappe.db.get_value("Sales Order", doc.sales_order, ["docstatus", "customer", "apparel_sales_contract"], as_dict=True)
    if not so or so.docstatus != 1:
        frappe.throw("Sales Order %s must be submitted." % doc.sales_order)
    doc.customer = so.customer
    doc.sales_contract = so.apparel_sales_contract
    doc.meeting_type = doc.meeting_type or "PP Meeting"
    if frappe.db.get_value("Item", doc.style_item, "variant_of"):
        frappe.throw("Pick the style (template item), not a variant.")
    order = get_order_lines(doc.sales_order)
    mine = [order[k] for k in order if order[k]["style_item"] == doc.style_item]
    if not mine:
        frappe.throw("Style %s is not on Sales Order %s." % (doc.style_item, doc.sales_order))
    doc.order_qty = sum([o["qty"] for o in mine])
    if not doc.style_no:
        doc.style_no = (frappe.db.get_value("Tech Pack", doc.tech_pack, "style_no") if doc.tech_pack else None) or doc.style_item
    if doc.pp_sample:
        pp = frappe.db.get_value("Sample Approval", doc.pp_sample, ["sample_type", "style_item"], as_dict=True)
        if pp.sample_type != "PP" or pp.style_item != doc.style_item:
            frappe.throw("%s is not a PP sample of style %s." % (doc.pp_sample, doc.style_item))

    if not (doc.factory and doc.line and doc.pcd):
        fa = frappe.db.get_value("Factory Allocation", {"sales_order": doc.sales_order}, "name")
        if fa:
            row = frappe.db.get_value("Factory Allocation Line", {"parent": fa, "style_item": doc.style_item}, ["factory", "line", "pcd"], as_dict=True, order_by="pcd")
            if row:
                doc.factory = doc.factory or row.factory
                doc.line = doc.line or row.line
                doc.pcd = doc.pcd or row.pcd

    for a in doc.actions:
        if a.status == "Closed" and not a.closed_on:
            a.closed_on = frappe.utils.nowdate()
        elif a.status == "Open":
            a.closed_on = None
    if doc.docstatus == 0:
        doc.status = "Draft"
    else:
        doc.status = "Open Actions" if [a for a in doc.actions if a.status == "Open"] else "Closed"


run(doc)
