# shared helpers from shipping/common.py: the fields every stage document copies from its production card, the open-card rule, and T&A stamping. Needs lib_mat.py (stamp_safe).
def card_context(production_card):
    c = frappe.db.get_value("Production Card", production_card, ["sales_order", "sales_contract", "customer", "style_item", "company", "status", "docstatus", "line"], as_dict=True)
    return c or {}


def require_open_card(production_card):
    card = card_context(production_card)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % production_card)
    return card


def settings_value(field, default):
    v = frappe.db.get_single_value("Apparel Settings", field)
    return default if v in (None, "") else v


def stamp_card(card, code, date, source_doctype, source_name, colours, partial):
    """Stamp a T&A milestone for every colour of the card's order. Never raises: a T&A fault must not stop shipping."""
    c = card_context(card)
    if not colours:
        colours = []
        for r in frappe.get_all("Production Card Line", filters={"parent": card}, fields=["colour"]):
            if r.colour not in colours:
                colours.append(r.colour)
        colours = sorted(colours)
    for colour in colours:
        stamp_safe(c.sales_order, c.style_item, colour, code, date, source_doctype, source_name, partial, False)
