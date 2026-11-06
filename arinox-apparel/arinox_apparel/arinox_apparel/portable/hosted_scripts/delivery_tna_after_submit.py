# Delivery Note, After Submit: the day it leaves the factory stamps EX_FACTORY for each card on it, and the shipment status moves on.
def run(doc):
    # include: lib_mat.py
    # include: lib_shipping.py
    # include: lib_shipment.py
    if not [it for it in doc.items if it.get("apparel_packing_list")]:
        return
    cards = []
    for it in doc.items:
        c = it.get("apparel_production_card")
        if c and c not in cards:
            cards.append(c)
    for card in cards:
        stamp_card(card, "EX_FACTORY", doc.posting_date, "Delivery Note", doc.name, None, False)
    if doc.get("apparel_shipment"):
        refresh_status(doc.apparel_shipment)


run(doc)
