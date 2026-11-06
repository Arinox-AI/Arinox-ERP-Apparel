# Packing List, Before Cancel: not while it is on a shipment or used by a submitted Delivery Note.
if doc.shipment:
    frappe.throw("%s is on shipment %s. Remove it from the shipment first." % (doc.name, doc.shipment))
if frappe.db.exists("Delivery Note Item", {"apparel_packing_list": doc.name, "docstatus": 1}):
    frappe.throw("A submitted Delivery Note uses this packing list.")
lots = frappe.get_all("Final Inspection Lot", {"packing_list": doc.name}, pluck="parent")
if lots and frappe.db.exists("Final Inspection", {"name": ["in", lots], "docstatus": 1, "result": ["in", ["Accepted", "Accepted with Concession"]]}):
    frappe.msgprint("An accepted final inspection covers this list; a new inspection is needed after repacking.", indicator="orange")
