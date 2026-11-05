# Shipment (After Save and After Save of a submitted document): stamp ON_BOARD and IN_WAREHOUSE on the order's T&A.
def stamp(doc, code, day):
    # a milestone cannot be stamped with a date in the future; a planned date stays on the shipment until it has happened
    if not day or frappe.utils.getdate(day) > frappe.utils.getdate(frappe.utils.nowdate()):
        return
    for row in doc.get("apparel_packing_lists") or []:
        card = frappe.db.get_value("Packing List", row.packing_list, "production_card")
        c = frappe.db.get_value("Production Card", card, ["sales_order", "style_item"], as_dict=True) if card else None
        if not c:
            continue
        for t in frappe.get_all("Order TNA", {"sales_order": c.sales_order, "style_item": c.style_item, "status": ["!=", "Cancelled"]}, ["name"]):
            for m in frappe.get_all("TNA Milestone", {"order_tna": t.name, "milestone_type": code}, ["name", "actual_date", "source_doctype", "source_name"]):
                if not m.actual_date or (m.source_doctype == "Shipment" and m.source_name == doc.name):
                    ms = frappe.get_doc("TNA Milestone", m.name)
                    ms.actual_date = day
                    ms.source_doctype = "Shipment"
                    ms.source_name = doc.name
                    ms.save(ignore_permissions=True)


stamp(doc, "ON_BOARD", doc.get("apparel_on_board_date"))
stamp(doc, "IN_WAREHOUSE", doc.get("apparel_delivery_date"))
