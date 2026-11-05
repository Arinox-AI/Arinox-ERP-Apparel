# Delivery Note, After Cancel: take SHIPPED back out of the ledger and reopen the packing lists.
def run(doc):
    lists = []
    for it in doc.items:
        if it.get("apparel_packing_list") and it.apparel_packing_list not in lists:
            lists.append(it.apparel_packing_list)
    if not lists:
        return
    run_script("arinox_engine", action="unpost", source_doctype="Delivery Note", source_name=doc.name)
    for pl in lists:
        shipment = frappe.db.get_value("Packing List", pl, "shipment")
        frappe.db.set_value("Packing List", pl, "status", "On Shipment" if shipment else "Open", update_modified=False)


run(doc)
