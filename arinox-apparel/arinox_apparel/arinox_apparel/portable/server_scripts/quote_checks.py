# Supplier Quotation used as a freight quote (Before Validate): quantity against the shipment, minimum and maximum charges, at-cost lines.
u = frappe.utils
sh = None
if doc.get("apparel_shipment"):
    sh = frappe.db.get_value("Shipment", doc.apparel_shipment, ["apparel_declared_cbm", "apparel_declared_gross_kg", "apparel_chargeable_kg"], as_dict=True)

for it in doc.items:
    unit = it.get("apparel_charge_unit")
    if not unit:
        continue
    qty = u.flt(it.qty)
    if unit == "At Cost":
        it.rate = 0
        if "(at cost" not in (it.description or ""):
            it.description = (it.description or "") + " (at cost: not in the total)"
        continue
    if sh:
        want = None
        if unit == "Per CBM":
            want = u.flt(sh.apparel_declared_cbm)
        elif unit == "Per kg":
            want = u.flt(sh.apparel_chargeable_kg) or u.flt(sh.apparel_declared_gross_kg)
        elif unit == "Per HBL" or unit == "Per Shipment":
            want = 1
        if want and abs(qty - want) > max(0.01, want * 0.01):
            frappe.msgprint(f"{it.item_code}: quoted on {qty} but the shipment has {want} ({unit}).", indicator="orange", title="Freight quote")
    amount = qty * u.flt(it.rate)
    minimum = u.flt(it.get("apparel_min_amount"))
    maximum = u.flt(it.get("apparel_max_amount"))
    if qty and minimum and amount < minimum:
        it.rate = minimum / qty
    elif qty and maximum and amount > maximum:
        it.rate = maximum / qty
