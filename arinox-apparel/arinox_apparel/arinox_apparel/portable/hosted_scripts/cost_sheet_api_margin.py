# API arinox_cost_sheet_get_margin_at_price: the margin if the garment sells at a given price (price-based charges other than profit scale with it).
def main():
    flt = frappe.utils.flt
    doc = frappe.get_doc("Cost Sheet", frappe.form_dict.get("cost_sheet"))
    doc.check_permission("read")
    price = flt(frappe.form_dict.get("price"))
    cost = flt(doc.subtotal) + price * flt(doc.price_cost_pct) / 100
    margin = price - cost
    margin_pct = flt(margin / price * 100, 2) if price else 0
    frappe.flags.arinox_result = {"cost": flt(cost, 6), "margin": flt(margin, 6), "margin_pct": margin_pct, "markup_pct": flt(margin / cost * 100, 2) if cost else 0,
                                  "floor": doc.margin_floor_pct, "below_floor": margin_pct < flt(doc.margin_floor_pct)}


main()
