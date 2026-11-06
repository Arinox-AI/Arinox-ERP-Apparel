# Shipment, After Cancel: its packing lists are free again and the stamps cleared.
def run(doc):
    # include: lib_mat.py
    for pl in frappe.get_all("Packing List", filters={"shipment": doc.name}, pluck="name"):
        frappe.db.set_value("Packing List", pl, {"shipment": None, "status": "Open"}, update_modified=False)
    unstamp_safe("Shipment", doc.name)


run(doc)
