# API arinox_production_card_get_production_status: the stage totals of every live card of an order.
def main():
    sales_order = frappe.form_dict.get("sales_order")
    frappe.get_doc("Sales Order", sales_order).check_permission("read")
    cards = frappe.get_all("Production Card", filters={"sales_order": sales_order, "docstatus": 1, "status": ["not in", ("Superseded", "Cancelled")]}, pluck="name")
    out = []
    for c in cards:
        out.append(run_script("arinox_production_card_api_summary", name=c).get("arinox_result"))
    frappe.flags.arinox_result = out


main()
