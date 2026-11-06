# Shipment, After Save (also after save of a submitted one): the packing lists are tied to this shipment (and released when taken off), the booking stamps FREIGHT_BOOKING,
# the status and the freight costs are refreshed.
def run(doc):
    # include: lib_mat.py
    # include: lib_shipping.py
    # include: lib_shipment.py
    lists = [r.packing_list for r in (doc.get("apparel_packing_lists") or []) if r.packing_list]
    if not lists and not frappe.db.exists("Packing List", {"shipment": doc.name}):
        return
    for pl in frappe.get_all("Packing List", filters={"shipment": doc.name, "status": ["!=", "Shipped"]}, pluck="name"):
        if pl not in lists:
            frappe.db.set_value("Packing List", pl, {"shipment": None, "status": "Open"}, update_modified=False)
    for pl in lists:
        if frappe.db.get_value("Packing List", pl, "status") != "Shipped":
            frappe.db.set_value("Packing List", pl, {"shipment": doc.name, "status": "On Shipment"}, update_modified=False)
    if doc.apparel_booking_no:
        cards = []
        for pl in lists:
            c = frappe.db.get_value("Packing List", pl, "production_card")
            if c not in cards:
                cards.append(c)
        for card in cards:
            stamp_card(card, "FREIGHT_BOOKING", doc.apparel_booking_date or frappe.utils.nowdate(), "Shipment", doc.name, None, False)
    refresh_status(doc.name)
    refresh_costs(doc.name)


run(doc)
