# Sales Order, Before Save: (1) an order made from a Sales Contract keeps its link and a contract has at most one live order;
# (2) fill what the production card, the packing list and the delivery gate read from each row (colour, size, buyer PO, dates,
# tolerance) when the order was typed by hand instead of made with the contract button.
def run(doc):
    def norm(x):
        return (x or "").strip().upper()

    name = doc.get("apparel_sales_contract")
    lines = []
    if name:
        sc = frappe.db.get_value("Sales Contract", name, ["docstatus", "customer", "sales_order"], as_dict=True)
        if not sc or sc.docstatus != 1:
            frappe.throw("Sales Contract %s is not signed (submitted)." % name)
        if sc.customer != doc.customer:
            frappe.throw("Sales Contract %s is for %s." % (name, sc.customer))
        if sc.sales_order and sc.sales_order != doc.name and frappe.db.get_value("Sales Order", sc.sales_order, "docstatus") != 2:
            frappe.throw("Sales Contract %s already has Sales Order %s." % (name, sc.sales_order))
        lines = frappe.get_all("Sales Contract Item", {"parent": name},
                               ["style_item", "colour", "buyer_po_code", "etd", "in_warehouse_date", "tolerance_pct", "cost_sheet"])

    colour_attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
    size_attr = frappe.db.get_single_value("Apparel Settings", "size_attribute") or "Size"
    for it in doc.items:
        style = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
        if not it.apparel_colour or not it.apparel_size:
            for a in frappe.get_all("Item Variant Attribute", {"parent": it.item_code}, ["attribute", "attribute_value"]):
                if a.attribute == colour_attr and not it.apparel_colour:
                    it.apparel_colour = a.attribute_value
                if a.attribute == size_attr and not it.apparel_size:
                    it.apparel_size = a.attribute_value
        if lines:
            cands = []
            for l in lines:
                if l.style_item == style and norm(l.colour) == norm(it.apparel_colour):
                    if not it.apparel_buyer_po or norm(l.buyer_po_code) == norm(it.apparel_buyer_po):
                        cands.append(l)
            if len(cands) == 1:          # only when it is unambiguous which contract line the row belongs to
                l = cands[0]
                it.apparel_buyer_po = it.apparel_buyer_po or l.buyer_po_code
                it.apparel_etd = it.apparel_etd or l.etd
                it.apparel_in_warehouse_date = it.apparel_in_warehouse_date or l.in_warehouse_date
                if it.apparel_qty_tolerance_pct is None or it.apparel_qty_tolerance_pct == 0:
                    it.apparel_qty_tolerance_pct = l.tolerance_pct
                it.apparel_cost_sheet = it.apparel_cost_sheet or l.cost_sheet


run(doc)
