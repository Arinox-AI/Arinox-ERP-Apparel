# shared helpers from materials/items.py (+ ensure_attribute_values from tech_pack.py): a template per fabric quality with the Colour attribute, a variant per colour,
# and a plain stock item per trim code. Needs lib_mat.py (YARD_M).
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


def canonical_attribute_value(attribute, value):
    """The attribute's own spelling of `value`, adding the value when it is new. ERPNext compares the exact text when it makes a variant, so 'BLACK' is
    refused where the attribute says 'Black'."""
    ensure_attribute_values(attribute, [value])
    want = (value or "").strip().upper()
    for v in frappe.get_all("Item Attribute Value", filters={"parent": attribute, "parenttype": "Item Attribute"}, pluck="attribute_value"):
        if (v or "").strip().upper() == want:
            return v
    return (value or "").strip()


def ensure_uom(name):
    if not frappe.db.exists("UOM", name):
        frappe.get_doc({"doctype": "UOM", "uom_name": name}).insert(ignore_permissions=True)


def material_item_group():
    for g in ("Raw Material", "Raw Materials"):
        if frappe.db.exists("Item Group", g):
            return g
    return frappe.db.get_single_value("Apparel Settings", "style_item_group") or frappe.db.get_value("Item Group", {"is_group": 0}, "name")


def add_uom_rows(item_doc, gsm, width_cm):
    """Yard always (1 yd = 0.9144 m); Kg when GSM and width are known (1 kg = 1000 / (gsm x width_m) m)."""
    have = [u.uom for u in item_doc.get("uoms") or []]
    if "Yard" not in have:
        ensure_uom("Yard")
        item_doc.append("uoms", {"uom": "Yard", "conversion_factor": YARD_M})
    if frappe.utils.flt(gsm) and frappe.utils.flt(width_cm) and "Kg" not in have:
        ensure_uom("Kg")
        item_doc.append("uoms", {"uom": "Kg", "conversion_factor": round(1000 / (frappe.utils.flt(gsm) * frappe.utils.flt(width_cm) / 100), 6)})


def ensure_fabric_item(quality_code, colour, description, gsm, width_cm):
    """Template `quality_code` (stock UOM Meter, batch tracked, Colour attribute) and its colour variant; returns the variant item code. Safe to call again."""
    quality_code = (quality_code or "").strip()
    if not quality_code:
        frappe.throw("Enter the fabric quality code.")
    attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
    colour = canonical_attribute_value(attr, colour)
    ensure_uom("Meter")
    if not frappe.db.exists("Item", quality_code):
        tpl = frappe.get_doc({"doctype": "Item", "item_code": quality_code, "item_name": quality_code, "item_group": material_item_group(), "stock_uom": "Meter",
                              "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0, "has_batch_no": 1, "has_variants": 1, "variant_based_on": "Item Attribute",
                              "attributes": [{"attribute": attr}], "description": description or quality_code, "apparel_material_type": "Fabric",
                              "apparel_fabric_gsm": gsm, "apparel_fabric_width_cm": width_cm})
        add_uom_rows(tpl, gsm, width_cm)
        tpl.flags.ignore_permissions = True
        tpl.insert()
    elif not frappe.db.get_value("Item", quality_code, "has_variants"):
        return quality_code   # a plain (non-variant) fabric item is used as it is
    args = {attr: colour}
    code = frappe.call("erpnext.controllers.item_variant.get_variant", template=quality_code, args=args)
    if not code:
        variant = frappe.call("erpnext.controllers.item_variant.create_variant", item=quality_code, args=args)
        variant.update({"has_batch_no": 1, "apparel_material_type": "Fabric", "apparel_fabric_gsm": gsm, "apparel_fabric_width_cm": width_cm})
        add_uom_rows(variant, gsm, width_cm)
        variant.flags.ignore_permissions = True
        variant.insert()
        code = variant.name
    return code


def ensure_trim_item(item_code, description, trim_category, uom, customer, buyer_code, customer_provided):
    """A plain stock item per trim code. The buyer code goes on Item Customer Detail."""
    ensure_uom(uom)
    if frappe.db.exists("Item", item_code):
        return item_code
    item = frappe.get_doc({"doctype": "Item", "item_code": item_code, "item_name": description or item_code, "item_group": material_item_group(), "stock_uom": uom,
                           "is_stock_item": 1, "is_purchase_item": 0 if customer_provided else 1, "is_sales_item": 0,
                           "is_customer_provided_item": 1 if customer_provided else 0, "customer": customer if customer_provided else None,
                           "description": description or item_code, "apparel_material_type": "Trim", "apparel_trim_category": trim_category})
    if customer and buyer_code:
        item.append("customer_items", {"customer_name": customer, "ref_code": buyer_code})
    item.flags.ignore_permissions = True
    item.insert()
    return item.name
