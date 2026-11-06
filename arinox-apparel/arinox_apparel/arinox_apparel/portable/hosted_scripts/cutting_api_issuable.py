# API arinox_cutting_get_issuable_rolls: accepted rolls in the fabric store for the fabrics of a production card, with their free length.
def main():
    # include: lib_cutting.py
    card = frappe.form_dict.get("card")
    frappe.get_doc("Production Card", card).check_permission("read")
    src = setting("store_warehouse_fabric")
    items = {}
    order = []
    for f in frappe.get_all("Production Card Fabric", filters={"parent": card}, fields=["fabric_item", "colour"]):
        if f.fabric_item and "i|" + f.fabric_item not in items:
            items["i|" + f.fabric_item] = f.colour
            order.append(f.fabric_item)
    out = []
    for item in order:
        for b in frappe.get_all("Batch", filters={"item": item, "disabled": 0}, fields=["name", "apparel_roll_no", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status"]):
            if b.apparel_inspection_status not in OK_STATUS:
                continue
            qty = roll_available(b.name, src, item)
            if qty > 0:
                out.append({"batch": b.name, "roll_no": b.apparel_roll_no, "item": item, "colour": items["i|" + item], "shade": b.apparel_shade_band, "width": b.apparel_width_cm, "available_m": qty})
    frappe.flags.arinox_result = out


main()
