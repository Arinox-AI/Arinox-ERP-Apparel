# API arinox_cost_sheet_get_costing_context: one call for the AI costing agent: the parameter that applies, its rates, the cost head library, and the most similar submitted costings.
def main():
    # include: lib_costing.py
    customer = frappe.form_dict.get("customer")
    product_type = frappe.form_dict.get("product_type")
    style_no = frappe.form_dict.get("style_no")
    tech_pack = frappe.form_dict.get("tech_pack")
    frappe.new_doc("Cost Sheet").check_permission("read")
    if tech_pack:
        tp = frappe.get_doc("Tech Pack", tech_pack)
        tp.check_permission("read")
        product_type = product_type or tp.product_type
        style_no = style_no or tp.style_no
    param_name = find_costing_parameter(customer, product_type, frappe.utils.nowdate(), frappe.form_dict.get("currency"))
    param = frappe.get_doc("Costing Parameter", param_name).as_dict() if param_name else None
    filters = {"docstatus": 1, "customer": customer}
    if product_type:
        filters["product_type"] = product_type
    prev = frappe.get_all("Cost Sheet", filters=filters, order_by="costing_date desc", limit=20,
                          fields=["name", "style_no", "style_name", "costing_date", "currency", "material_cost", "subtotal", "quoted_price", "margin_pct", "order_qty", "revision_no"])
    for p in prev:
        p["agreed_price"] = frappe.db.get_value("Price Negotiation Style", {"cost_sheet": p.name, "style_status": "Agreed"}, "agreed_price")
        p["same_style"] = bool(style_no and p.style_no == style_no)
    prev = sorted(prev, key=lambda p: not p["same_style"])
    frappe.flags.arinox_result = {"costing_parameter": param, "margin_floor_pct": (param or {}).get("margin_floor_pct") or frappe.db.get_single_value("Apparel Settings", "default_margin_floor_pct"),
                                  "cost_heads": get_cost_heads(), "previous_costings": prev}


main()
