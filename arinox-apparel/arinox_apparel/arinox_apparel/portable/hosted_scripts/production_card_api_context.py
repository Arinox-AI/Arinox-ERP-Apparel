# API arinox_production_card_get_production_context: everything an agent needs to draft production cards for an order.
def main():
    # include: lib_orders.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    sales_order = frappe.form_dict.get("sales_order")
    frappe.get_doc("Sales Order", sales_order).check_permission("read")
    styles = []
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, fields=["item_code"]):
        s = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
        if s not in styles:
            styles.append(s)
    fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name") or ""
    out = []
    for style in styles:
        m = order_matrix(sales_order, style)
        cells = m[0]
        cards = frappe.get_all("Production Card", filters={"sales_order": sales_order, "style_item": style, "docstatus": 1, "status": ["not in", ("Superseded", "Cancelled")]}, order_by="creation desc", limit=1)
        out.append({"style_item": style, "ex_factory_date": str(m[1]) if m[1] else None, "buyer_pos": m[2],
                    "lines": [{"colour": k[0], "size": k[1], "order_qty": cells[k]["order_qty"], "tolerance_pct": cells[k]["tolerance_pct"]} for k in sorted(cells)],
                    "card": cards[0].name if cards else None,
                    "fabric_requisitions": frappe.get_all("Fabric Requisition Item", filters={"sales_order": sales_order, "style_item": style, "docstatus": 1}, fields=["parent", "colour", "net_qty", "accepted_qty"]),
                    "trim_requisitions": frappe.get_all("Trim Requisition Item", filters={"sales_order": sales_order, "style_item": style, "docstatus": 1}, fields=["parent", "trim_category", "colour", "net_qty"]),
                    "allocation": frappe.get_all("Factory Allocation Line", filters={"parent": fa, "style_item": style}, fields=["colour", "factory", "line", "pcd", "sewing_start", "sewing_end"])})
    frappe.flags.arinox_result = {"sales_order": sales_order, "styles": out, "defaults": {"extra_cut_pct": flt(setting("default_extra_cut_pct", 5)), "bundle_size": cint(setting("bundle_size", 20))}}


main()
