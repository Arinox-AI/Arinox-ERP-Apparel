# API arinox_production_card_get_card_lines: colour x size rows for a new card, straight from the Sales Order.
def main():
    # include: lib_orders.py
    so = frappe.form_dict.get("sales_order")
    frappe.get_doc("Sales Order", so).check_permission("read")
    m = order_matrix(so, frappe.form_dict.get("style_item"))
    cells = m[0]
    keys = sorted(cells.keys())
    frappe.flags.arinox_result = {"lines": [{"colour": k[0], "size": k[1], "order_qty": cells[k]["order_qty"]} for k in keys],
                                  "ex_factory_date": str(m[1]) if m[1] else None, "buyer_pos": m[2]}


main()
