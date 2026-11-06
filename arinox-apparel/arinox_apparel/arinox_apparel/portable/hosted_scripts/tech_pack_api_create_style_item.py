# API arinox_tech_pack_create_style_item: the style as an Item template with Colour and Size attributes, adding any of this Tech Pack's
# sizes and colours that the attribute lists do not have yet. Answers the Item name.
def main():
    tp = frappe.get_doc("Tech Pack", frappe.form_dict.get("tech_pack"))
    tp.check_permission("write")
    frappe.new_doc("Item").check_permission("create")
    if tp.style_item:
        frappe.flags.arinox_result = tp.style_item
        return

    colour_attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
    size_attr = frappe.db.get_single_value("Apparel Settings", "size_attribute") or "Size"

    def ensure_attribute_values(attribute, values):
        if not frappe.db.exists("Item Attribute", attribute):
            frappe.get_doc({"doctype": "Item Attribute", "attribute_name": attribute, "item_attribute_values": []}).insert(ignore_permissions=True)
        adoc = frappe.get_doc("Item Attribute", attribute)
        existing = [v.attribute_value.strip().upper() for v in adoc.item_attribute_values]
        abbrs = [v.abbr.upper() for v in adoc.item_attribute_values]
        added = False
        for value in values:
            value = (value or "").strip()
            if not value or value.upper() in existing:
                continue
            abbr = "".join([ch for ch in value.upper() if ch.isalnum()])[:10] or value[:10]
            base = abbr
            n = 1
            while abbr in abbrs:
                n = n + 1
                abbr = "%s%s" % (base[:8], n)
            adoc.append("item_attribute_values", {"attribute_value": value, "abbr": abbr})
            existing.append(value.upper())
            abbrs.append(abbr)
            added = True
        if added:
            adoc.flags.ignore_permissions = True
            adoc.save()

    ensure_attribute_values(size_attr, [s.size for s in tp.sizes])
    ensure_attribute_values(colour_attr, [c.colour for c in tp.colours])

    item_code = tp.style_no.strip()
    if frappe.db.exists("Item", item_code):
        frappe.throw("Item %s already exists. Link it in Style Item instead." % item_code)
    group = (frappe.db.get_value("Product Type", tp.product_type, "item_group") if tp.product_type else None) or frappe.db.get_single_value("Apparel Settings", "style_item_group")
    if not group:
        frappe.throw("Set an Item Group on Product Type %s or a Style Item Group in Apparel Settings." % tp.product_type)
    item = frappe.get_doc({"doctype": "Item", "item_code": item_code, "item_name": tp.style_name or item_code, "item_group": group, "stock_uom": "Nos",
                           "is_stock_item": 1, "is_sales_item": 1, "has_variants": 1, "variant_based_on": "Item Attribute",
                           "attributes": [{"attribute": colour_attr}, {"attribute": size_attr}], "image": tp.front_image,
                           "description": "%s %s (%s)" % (tp.style_no, tp.style_name or "", tp.customer_name or tp.customer)}).insert()
    tp.db_set("style_item", item.name)
    frappe.flags.arinox_result = item.name


main()
