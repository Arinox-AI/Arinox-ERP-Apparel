def main(filters):
    # include: lib_mat.py
    # include: lib_cutting.py
    flt = frappe.utils.flt

    def col(f, l, t, w, o=None, precision=None):
        d = {"fieldname": f, "label": l, "fieldtype": t, "width": w}
        if o:
            d["options"] = o
        if precision:
            d["precision"] = precision
        return d

    columns = [col("production_card", "Production Card", "Link", 130, "Production Card"), col("colour", "Colour", "Data", 90), col("fabric_item", "Fabric", "Link", 150, "Item"),
               col("required_m", "Required (m)", "Float", 100), col("issued_m", "Issued (m)", "Float", 100), col("returned_m", "Remnants Returned (m)", "Float", 130),
               col("laid_m", "Laid (m)", "Float", 90), col("end_bit_m", "End Bits (m)", "Float", 90), col("damage_m", "Damage (m)", "Float", 90), col("pieces_cut", "Pieces Cut", "Int", 90),
               col("good_cut", "Good Garments", "Int", 100), col("card_consumption", "Card (m / pc)", "Float", 100, None, 4), col("lay_consumption", "Lay (m / pc)", "Float", 100, None, 4),
               col("actual_consumption", "Actual (m / pc)", "Float", 110, None, 4), col("variance_pct", "Actual vs Card %", "Percent", 110),
               col("marker_efficiency", "Marker Efficiency %", "Percent", 120), col("shortage_m", "Fabric Short (m)", "Float", 110)]
    cond = ["c.docstatus = 1", "c.status not in ('Superseded', 'Cancelled')"]
    args = {}
    for key, c in (("production_card", "c.name"), ("sales_order", "c.sales_order"), ("customer", "c.customer")):
        if filters.get(key):
            cond.append("%s = %%(%s)s" % (c, key))
            args[key] = filters.get(key)
    cards = frappe.db.sql("select c.name from `tabProduction Card` c where " + " and ".join(cond) + " order by c.creation desc limit 200", args, pluck="name")
    rows = []
    for card in cards:
        for f in frappe.get_all("Production Card Fabric", filters={"parent": card}, fields=["colour", "fabric_item", "required_m", "consumption", "consumption_uom"], order_by="idx"):
            lays = frappe.get_all("Lay Report", filters={"production_card": card, "colour": f.colour, "fabric_item": f.fabric_item, "docstatus": 1, "purpose": ["!=", "Sample"]},
                                  fields=["name", "laid_m", "pieces_cut", "marker_efficiency_pct", "total_plies"])
            laid = sum([flt(l.laid_m) for l in lays])
            pieces = sum([flt(l.pieces_cut) for l in lays])
            ends = frappe.db.sql("select ifnull(sum(r.end_bit_m), 0), ifnull(sum(r.damage_m), 0) from `tabLay Roll` r where r.parent in %s", (tuple([l.name for l in lays] or [""]),))[0]
            issued = moved_qty(card, "Fabric Issue", f.fabric_item)
            returned = moved_qty(card, "Remnant Return", f.fabric_item)
            good = flt(frappe.db.sql("select ifnull(sum(case when stage = 'CUT' then qty else -qty end), 0) from `tabProduction Movement` where production_card = %s and colour = %s "
                                     "and stage in ('CUT', 'CUT_REJECT')", (card, f.colour))[0][0])
            actual = (issued - returned) / good if issued and good else None
            card_cons = to_metres(flt(f.consumption), f.consumption_uom or "Meter", None, None)
            weighted = [[flt(l.marker_efficiency_pct), flt(l.total_plies)] for l in lays if flt(l.marker_efficiency_pct)]
            plies = sum([w[1] for w in weighted])
            eff = sum([w[0] * w[1] for w in weighted]) / plies if plies else None
            rows.append({"production_card": card, "colour": f.colour, "fabric_item": f.fabric_item, "required_m": f.required_m, "issued_m": issued, "returned_m": returned, "laid_m": laid,
                         "end_bit_m": ends[0], "damage_m": ends[1], "pieces_cut": pieces, "good_cut": good, "card_consumption": card_cons, "lay_consumption": (laid / pieces) if pieces else None,
                         "actual_consumption": actual, "variance_pct": (actual - card_cons) / card_cons * 100 if actual and card_cons else None, "marker_efficiency": eff,
                         "shortage_m": max(flt(f.required_m) - (issued - returned), 0) if f.required_m else None})
    return (columns, rows)


data = list(main(filters))
