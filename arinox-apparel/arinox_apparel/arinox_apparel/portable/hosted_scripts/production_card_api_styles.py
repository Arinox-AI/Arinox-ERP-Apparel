# API arinox_production_card_get_order_styles: the style templates on a Sales Order, for the style picker.
def main():
    so = frappe.form_dict.get("sales_order")
    frappe.get_doc("Sales Order", so).check_permission("read")
    styles = []
    for it in frappe.get_all("Sales Order Item", {"parent": so}, ["item_code"]):
        s = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
        if s not in styles:
            styles.append(s)
    frappe.flags.arinox_result = styles


main()
