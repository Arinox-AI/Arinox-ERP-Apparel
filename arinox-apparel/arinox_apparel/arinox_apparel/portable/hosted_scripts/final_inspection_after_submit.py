# Final Inspection, After Submit: each packing list points at the inspection that covers it; a rejection is announced.
for l in doc.lots:
    frappe.db.set_value("Packing List", l.packing_list, "final_inspection", doc.name, update_modified=False)
if doc.result == "Rejected":
    frappe.msgprint("Rejected: %s critical, %s major, %s minor. Repack or rework, then inspect again." % (doc.critical_found, doc.major_found, doc.minor_found), indicator="red")
