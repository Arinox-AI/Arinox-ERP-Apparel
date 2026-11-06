# shared helpers: the Sales Order at the order grain, rolled up to style x colour, and the tolerance cap (factory_allocation.py)
def norm(colour):
    return (colour or "").strip().upper()


def get_order_lines(sales_order):
    """Sales Order grouped to (style, colour, ship-to, buyer PO) -> qty, tolerance %, earliest ex-factory date. A dict of dicts, in order of appearance."""
    lines = {}
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order},
                             fields=["item_code", "qty", "apparel_colour", "apparel_ship_to", "apparel_buyer_po", "apparel_qty_tolerance_pct", "delivery_date"]):
        style = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
        key = (style, norm(it.apparel_colour), norm(it.apparel_ship_to), norm(it.apparel_buyer_po))
        row = lines.get(key)
        if not row:
            row = {"style_item": style, "colour": (it.apparel_colour or "").strip(), "ship_to": (it.apparel_ship_to or "").strip(),
                   "buyer_po": (it.apparel_buyer_po or "").strip(), "qty": 0, "tolerance_pct": 0, "ex_factory_date": None}
            lines[key] = row
        row["qty"] = row["qty"] + frappe.utils.cint(it.qty)
        row["tolerance_pct"] = max(frappe.utils.flt(row["tolerance_pct"]), frappe.utils.flt(it.apparel_qty_tolerance_pct))
        if it.delivery_date and (not row["ex_factory_date"] or frappe.utils.getdate(it.delivery_date) < frappe.utils.getdate(row["ex_factory_date"])):
            row["ex_factory_date"] = it.delivery_date
    return lines


def colour_level(order):
    """The order lines rolled up to (style, colour)."""
    out = {}
    for key in order:
        o = order[key]
        ckey = (key[0], key[1])
        row = out.get(ckey)
        if not row:
            row = {"style_item": key[0], "colour": o["colour"], "qty": 0, "tolerance_pct": 0, "ex_factory_date": None}
            out[ckey] = row
        row["qty"] = row["qty"] + o["qty"]
        row["tolerance_pct"] = max(frappe.utils.flt(row["tolerance_pct"]), frappe.utils.flt(o["tolerance_pct"]))
        if o["ex_factory_date"] and (not row["ex_factory_date"] or frappe.utils.getdate(o["ex_factory_date"]) < frappe.utils.getdate(row["ex_factory_date"])):
            row["ex_factory_date"] = o["ex_factory_date"]
    return out


def cap_of(qty, tolerance_pct):
    return int(qty * (1 + frappe.utils.flt(tolerance_pct) / 100))
