# API arinox_sales_contract_make_sales_order: Sales Contract -> Sales Order (unsaved, returned as a document for the form to open):
# one row per size row, with the variant of the style for that colour and size (created when missing), the price of its contract line,
# and the colour, size, PO, dates and tolerance the production card and the shipping gates read.
def main():
    # include: lib_items.py
    cint = frappe.utils.cint
    sc = frappe.get_doc("Sales Contract", frappe.form_dict.get("source_name"))
    sc.check_permission("read")
    if sc.docstatus != 1:
        frappe.throw("Submit (sign) the contract first.")
    if sc.sales_order and frappe.db.get_value("Sales Order", sc.sales_order, "docstatus") != 2:
        frappe.throw("Sales Order %s already exists for this contract." % sc.sales_order)
    colour_attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
    size_attr = frappe.db.get_single_value("Apparel Settings", "size_attribute") or "Size"

    def line_of(size_row):
        cands = []
        for it in sc.items:
            if it.style_item == size_row.style_item and (it.colour or "").strip().upper() == (size_row.colour or "").strip().upper():
                if not size_row.buyer_po_no or (it.buyer_po_code or "").strip().upper() == size_row.buyer_po_no.strip().upper():
                    cands.append(it)
        if len(cands) != 1:
            frappe.throw("Size row %s: cannot tell which contract line it belongs to. Enter the buyer PO on it." % size_row.idx)
        return cands[0]

    warehouse = None
    for wh in (frappe.db.get_single_value("Apparel Settings", "fg_warehouse"), frappe.db.get_single_value("Stock Settings", "default_warehouse")):
        if wh and frappe.db.get_value("Warehouse", wh, "company") == sc.company:
            warehouse = wh
            break
    if not warehouse:
        frappe.throw("Set the Finished Goods warehouse in Apparel Settings (or the default warehouse in Stock Settings) before making a Sales Order.")
    first_delivery = None
    for it in sc.items:
        if it.ex_factory_date and (not first_delivery or frappe.utils.getdate(it.ex_factory_date) < frappe.utils.getdate(first_delivery)):
            first_delivery = it.ex_factory_date

    so = frappe.new_doc("Sales Order")
    so.update({"customer": sc.customer, "company": sc.company, "currency": sc.currency, "po_no": sc.buyer_po_no, "po_date": sc.contract_date,
               "transaction_date": sc.contract_date, "delivery_date": first_delivery, "incoterm": sc.incoterm, "named_place": sc.named_place,
               "payment_terms_template": sc.payment_terms_template, "tc_name": sc.terms_and_conditions, "terms": sc.terms,
               "apparel_sales_contract": sc.name, "set_warehouse": warehouse})
    rates = []
    for s in sc.sizes:
        if cint(s.qty) <= 0:
            continue    # a size nobody orders is not an order line (the ERP refuses a zero quantity)
        line = line_of(s)
        item_code = s.style_item
        if frappe.db.get_value("Item", s.style_item, "has_variants"):
            args = {colour_attr: canonical_attribute_value(colour_attr, s.colour), size_attr: canonical_attribute_value(size_attr, s.size)}
            item_code = frappe.call("erpnext.controllers.item_variant.get_variant", template=s.style_item, args=args)
            if not item_code:
                variant = frappe.call("erpnext.controllers.item_variant.create_variant", item=s.style_item, args=args)
                variant.insert()
                item_code = variant.name
            s.db_set("item_code", item_code)
        so.append("items", {"item_code": item_code, "qty": s.qty, "rate": line.rate, "uom": line.uom or "Nos", "delivery_date": line.ex_factory_date, "warehouse": warehouse,
                            "apparel_colour": s.colour, "apparel_size": s.size, "apparel_ship_to": s.ship_to, "apparel_buyer_po": s.buyer_po_no or line.buyer_po_code,
                            "apparel_etd": line.etd, "apparel_in_warehouse_date": line.in_warehouse_date, "apparel_qty_tolerance_pct": line.tolerance_pct,
                            "apparel_cost_sheet": line.cost_sheet})
        rates.append(line.rate)
    if not so.items:
        frappe.throw("Every size row on this contract has a quantity of zero, so there is nothing to order. Enter the pieces first.")
    so.run_method("set_missing_values")
    n = 0
    for row in so.items:
        row.rate = rates[n]
        row.price_list_rate = 0
        n = n + 1
    so.run_method("calculate_taxes_and_totals")
    frappe.flags.arinox_result = so.as_dict()


main()
