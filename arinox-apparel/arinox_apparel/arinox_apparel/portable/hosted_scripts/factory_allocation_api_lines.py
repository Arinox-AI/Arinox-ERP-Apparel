# API arinox_factory_allocation_get_lines_from_order: one allocation row per style x colour (x ship-to x PO) of the order, for the Get Order Lines button.
def main():
    # include: lib_allocation.py
    order = get_order_lines(frappe.form_dict.get("sales_order"))
    frappe.flags.arinox_result = [{"style_item": order[k]["style_item"], "colour": order[k]["colour"], "ship_to": order[k]["ship_to"], "buyer_po": order[k]["buyer_po"],
                                   "qty": order[k]["qty"], "order_qty": order[k]["qty"], "ex_factory_date": order[k]["ex_factory_date"]} for k in order]


main()
