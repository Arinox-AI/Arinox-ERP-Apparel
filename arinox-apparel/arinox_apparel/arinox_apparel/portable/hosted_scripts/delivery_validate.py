# Delivery Note, Before Save: copy the production card and contract down from the packing list on each row.
def run(doc):
    first = None
    has_lists = False
    for it in doc.items:
        if it.get("apparel_packing_list"):
            has_lists = True
            it.apparel_production_card = frappe.db.get_value("Packing List", it.apparel_packing_list, "production_card")
        if not first and it.get("against_sales_order"):
            first = it.against_sales_order
    if first and has_lists:
        doc.apparel_sales_contract = frappe.db.get_value("Sales Order", first, "apparel_sales_contract") or None


run(doc)
