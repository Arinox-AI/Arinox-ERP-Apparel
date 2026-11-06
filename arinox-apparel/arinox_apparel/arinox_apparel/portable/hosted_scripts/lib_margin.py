# shared helper: the margin if a costed garment sells at a price (Cost Sheet.margin_at_price in the app)
def margin_at_price(cs, price):
    """Price-based charges other than profit scale with the price. `cs` is a Cost Sheet document."""
    flt = frappe.utils.flt
    price = flt(price)
    cost = flt(cs.subtotal) + price * flt(cs.price_cost_pct) / 100
    margin = price - cost
    return {"cost": flt(cost, 6), "margin": flt(margin, 6), "margin_pct": flt(margin / price * 100, 2) if price else 0,
            "markup_pct": flt(margin / cost * 100, 2) if cost else 0}
