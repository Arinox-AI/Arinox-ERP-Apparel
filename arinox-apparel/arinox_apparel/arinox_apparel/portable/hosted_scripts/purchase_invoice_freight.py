# Purchase Invoice, After Save / After Submit / After Cancel: the forwarder's bills are added up against the quote on the shipment (and on the one it was moved from).
def run(doc):
    # include: lib_shipping.py
    # include: lib_shipment.py
    before = doc.get_doc_before_save()
    names = []
    for n in (doc.get("apparel_shipment"), before.get("apparel_shipment") if before else None):
        if n and n not in names:
            names.append(n)
    for n in names:
        refresh_costs(n)


run(doc)
