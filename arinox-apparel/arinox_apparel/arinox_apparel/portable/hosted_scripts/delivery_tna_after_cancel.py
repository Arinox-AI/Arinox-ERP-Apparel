# Delivery Note, After Cancel: the EX_FACTORY stamp is cleared and the shipment status refreshed.
def run(doc):
    # include: lib_mat.py
    # include: lib_shipping.py
    # include: lib_shipment.py
    if not [it for it in doc.items if it.get("apparel_packing_list")]:
        return
    unstamp_safe("Delivery Note", doc.name)
    if doc.get("apparel_shipment"):
        refresh_status(doc.apparel_shipment)


run(doc)
