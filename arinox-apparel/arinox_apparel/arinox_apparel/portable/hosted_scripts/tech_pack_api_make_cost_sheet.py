# API arinox_tech_pack_make_cost_sheet: Tech Pack -> new Cost Sheet (unsaved), materials copied from the buyer BOM with buying rates.
def main():
    # include: lib_costing.py
    flt = frappe.utils.flt
    tp = frappe.get_doc("Tech Pack", frappe.form_dict.get("source_name"))
    tp.check_permission("read")
    if tp.docstatus == 2:
        frappe.throw("This Tech Pack is cancelled. Use its amended revision.")
    if not tp.product_type:
        frappe.throw("Set the Product Type on the Tech Pack first; costing rates depend on it.")

    cs = frappe.new_doc("Cost Sheet")
    cs.update({"customer": tp.customer, "opportunity": tp.opportunity, "tech_pack": tp.name, "style_no": tp.style_no, "style_name": tp.style_name,
               "product_type": tp.product_type, "style_item": tp.style_item, "season": tp.season,
               "sam": frappe.db.get_value("Product Type", tp.product_type, "default_sam")})
    if tp.opportunity:
        cs.order_qty = frappe.db.get_value("Opportunity", tp.opportunity, "apparel_target_qty")
    company = frappe.db.get_value("DefaultValue", {"parent": frappe.session.user, "defkey": "Company"}, "defvalue")
    cs.currency = (frappe.db.get_value("Customer", tp.customer, "default_currency")
                   or (frappe.db.get_value("Company", company, "default_currency") if company else None)
                   or frappe.db.get_default("currency"))
    cs.costing_parameter = find_costing_parameter(cs.customer, cs.product_type, None, cs.currency)
    price_list = frappe.db.get_single_value("Apparel Settings", "buying_price_list")

    def buying_rate(item):
        if not item:
            return 0
        filters = {"item_code": item, "buying": 1}
        if price_list:
            filters["price_list"] = price_list
        rate = frappe.db.get_value("Item Price", filters, "price_list_rate", order_by="valid_from desc")
        return flt(rate) or flt(frappe.db.get_value("Item", item, "last_purchase_rate"))

    for m in tp.materials:
        cs.append("materials", {"material_type": m.material_type, "description": " ".join([x for x in (m.description, m.composition, m.gsm) if x]),
                                "item": m.item, "uom": m.uom, "consumption": flt(m.consumption), "conversion_factor": 1, "supplier": m.nominated_supplier,
                                "rate": buying_rate(m.item), "is_selected": 1})
    cs.set("charges", [])
    for row in charge_rows(cs.costing_parameter):
        cs.append("charges", row)
    frappe.flags.arinox_result = cs.as_dict()


main()
