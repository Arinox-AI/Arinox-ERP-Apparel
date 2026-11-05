# Delivery Note, After Submit: write SHIPPED to the ledger, mark the packing lists shipped, refresh the shipment status.
def run(doc):
    lists = []
    for it in doc.items:
        if it.get("apparel_packing_list") and it.apparel_packing_list not in lists:
            lists.append(it.apparel_packing_list)
    if not lists:
        return
    by_card = {}
    for it in doc.items:
        card = it.get("apparel_production_card")
        if not card or not it.get("so_detail"):
            continue
        cs = frappe.db.get_value("Sales Order Item", it.so_detail, ["apparel_colour", "apparel_size"])
        if card not in by_card:
            by_card[card] = {}
        key = cs[0] + "\t" + cs[1]
        by_card[card][key] = by_card[card].get(key, 0) + int(it.stock_qty or it.qty or 0)
    for card in by_card:
        rows = []
        for key in by_card[card]:
            parts = key.split("\t")
            rows.append({"stage": "SHIPPED", "colour": parts[0], "size": parts[1], "qty": by_card[card][key]})
        run_script("arinox_engine", action="post", card=card, rows=json.dumps(rows), source_doctype="Delivery Note", source_name=doc.name,
                   posting_date=str(doc.posting_date), check="1")
    for pl in lists:
        frappe.db.set_value("Packing List", pl, "status", "Shipped", update_modified=False)


run(doc)
