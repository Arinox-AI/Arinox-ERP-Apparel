# Factory Allocation, Before Save: the order must be submitted; every row is a style x colour of the order (optionally narrowed to a ship-to and/or buyer PO),
# its line belongs to its factory, the dates run in order, and no colour (or narrowed group) is allocated above the order plus tolerance. Sets the status.
def run(doc):
    # include: lib_allocation.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    getdate = frappe.utils.getdate
    so = frappe.db.get_value("Sales Order", doc.sales_order, ["docstatus", "customer", "company", "apparel_sales_contract"], as_dict=True)
    if not so or so.docstatus != 1:
        frappe.throw("Sales Order %s must be submitted (order confirmed) before it is planned." % doc.sales_order)
    doc.customer = so.customer
    doc.company = so.company
    doc.sales_contract = so.apparel_sales_contract
    order = get_order_lines(doc.sales_order)
    doc.order_qty = sum([order[k]["qty"] for k in order])

    colours = colour_level(order)
    by_colour = {}
    by_group = {}
    groups = {}
    for r in doc.lines:
        ckey = (r.style_item, norm(r.colour))
        c = colours.get(ckey)
        if not c:
            frappe.throw("Row %s: %s / %s is not on Sales Order %s." % (r.idx, r.style_item, r.colour, doc.sales_order))
        if cint(r.qty) <= 0:
            frappe.throw("Row %s: allocated qty must be above zero." % r.idx)
        if r.ship_to or r.buyer_po:
            match = [order[k] for k in order if (k[0], k[1]) == ckey and (not r.ship_to or k[2] == norm(r.ship_to)) and (not r.buyer_po or k[3] == norm(r.buyer_po))]
            if not match:
                frappe.throw("Row %s: %s / %s has no order line for ship-to '%s' PO '%s'." % (r.idx, r.style_item, r.colour, r.ship_to or "-", r.buyer_po or "-"))
            gkey = (r.style_item, norm(r.colour), norm(r.ship_to), norm(r.buyer_po))
            groups[gkey] = [sum([o["qty"] for o in match]), max([flt(o["tolerance_pct"]) for o in match])]
            by_group[gkey] = by_group.get(gkey, 0) + cint(r.qty)
            r.order_qty = groups[gkey][0]
            dates = [o["ex_factory_date"] for o in match if o["ex_factory_date"]]
            r.ex_factory_date = min(dates) if dates else None
        else:
            r.order_qty = c["qty"]
            r.ex_factory_date = c["ex_factory_date"]
        r.style_no = r.style_no or r.style_item
        by_colour[ckey] = by_colour.get(ckey, 0) + cint(r.qty)
        if r.line:
            floor = frappe.db.get_value("Workstation", r.line, "plant_floor")
            if floor != r.factory:
                frappe.throw("Row %s: line %s does not belong to factory %s." % (r.idx, r.line, r.factory))
        chain = [["PCD", r.pcd], ["Sewing start", r.sewing_start], ["Sewing end", r.sewing_end], ["Ex-factory", r.ex_factory_date]]
        chain = [[x[0], getdate(x[1])] for x in chain if x[1]]
        i = 0
        while i < len(chain) - 1:
            if chain[i][1] > chain[i + 1][1]:
                frappe.throw("Row %s: %s (%s) is after %s (%s)." % (r.idx, chain[i][0], chain[i][1], chain[i + 1][0], chain[i + 1][1]))
            i = i + 1
    for ckey in by_colour:
        c = colours[ckey]
        if by_colour[ckey] > cap_of(c["qty"], c["tolerance_pct"]):
            frappe.throw("%s / %s: allocated %s is more than the order %s plus tolerance (%s)." % (ckey[0], c["colour"], by_colour[ckey], c["qty"], cap_of(c["qty"], c["tolerance_pct"])))
    for gkey in by_group:
        total = groups[gkey][0]
        if by_group[gkey] > cap_of(total, groups[gkey][1]):
            frappe.throw("%s / %s (ship-to %s, PO %s): allocated %s is more than the order %s plus tolerance (%s)." %
                         (gkey[0], gkey[1], gkey[2] or "-", gkey[3] or "-", by_group[gkey], total, cap_of(total, groups[gkey][1])))
    doc.allocated_qty = sum([by_colour[k] for k in by_colour])

    if not by_colour:
        doc.status = "Unplanned"
    elif len([k for k in colours if by_colour.get(k, 0) >= colours[k]["qty"]]) == len(colours):
        doc.status = "Planned"
    else:
        doc.status = "Partly Planned"


run(doc)
