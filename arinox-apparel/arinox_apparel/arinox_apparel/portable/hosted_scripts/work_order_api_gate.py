# API arinox_work_order_get_bulk_gate: the blockers (empty = the gate is open) for bulk production of an item on an order. Not an apparel style variant: not applicable.
def main():
    production_item = frappe.form_dict.get("production_item")
    sales_order = frappe.form_dict.get("sales_order")
    style = frappe.db.get_value("Item", production_item, "variant_of")
    if style and not (frappe.db.exists("Sales Contract Item", {"style_item": style}) or frappe.db.exists("Tech Pack", {"style_item": style})):
        style = None
    if not style or not sales_order:
        frappe.flags.arinox_result = {"applies": False, "blockers": []}
        return
    attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
    colour = frappe.db.get_value("Item Variant Attribute", {"parent": production_item, "attribute": attr}, "attribute_value")
    res = run_script("arinox_engine", action="bulk_gate", sales_order=sales_order, style=style, colour=colour, stage="bulk")
    frappe.flags.arinox_result = res.get("arinox_result")


main()
