# shared helper: an unsaved Quotation with one line per style (price_negotiation.py build_quotation, get_quote_item, get_default_company)
def build_quotation(customer, currency, opportunity, lines, price_negotiation):
    """Lines use the generic style item because ERPNext refuses a template item on a Quotation."""
    quote_item = frappe.db.get_single_value("Apparel Settings", "quote_item")
    if not quote_item:
        if not frappe.db.exists("Item", "APPAREL-STYLE"):
            group = frappe.db.get_single_value("Apparel Settings", "style_item_group") or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            frappe.get_doc({"doctype": "Item", "item_code": "APPAREL-STYLE", "item_name": "Apparel Style (quotation line)", "item_group": group, "stock_uom": "Nos",
                            "is_stock_item": 0, "is_sales_item": 1, "is_purchase_item": 0, "include_item_in_manufacturing": 0,
                            "description": "Generic line item for quoting a garment style. The style is on the line."}).insert(ignore_permissions=True)
        frappe.db.set_value("Apparel Settings", "Apparel Settings", "quote_item", "APPAREL-STYLE")
        quote_item = "APPAREL-STYLE"
    q = frappe.new_doc("Quotation")
    q.company = (frappe.db.get_value("DefaultValue", {"parent": frappe.session.user, "defkey": "Company"}, "defvalue") or frappe.db.get_single_value("Global Defaults", "default_company")
                 or frappe.db.get_value("Company", {}, "name", order_by="creation asc"))
    q.quotation_to = "Customer"
    q.party_name = customer
    q.currency = currency
    q.opportunity = opportunity
    q.apparel_price_negotiation = price_negotiation
    for line in lines:
        cs = frappe.get_doc("Cost Sheet", line["cost_sheet"])
        label = " - ".join([x for x in (cs.style_no, cs.style_name) if x])
        q.append("items", {"item_code": quote_item, "item_name": label[:140], "description": label, "qty": line.get("qty") or 1, "rate": line["rate"],
                           "apparel_cost_sheet": cs.name, "apparel_style_item": cs.style_item, "apparel_style_no": cs.style_no})
    q.run_method("set_missing_values")
    n = 0
    for row in q.items:
        row.rate = lines[n]["rate"]
        row.price_list_rate = 0
        n = n + 1
    q.run_method("calculate_taxes_and_totals")
    return q
