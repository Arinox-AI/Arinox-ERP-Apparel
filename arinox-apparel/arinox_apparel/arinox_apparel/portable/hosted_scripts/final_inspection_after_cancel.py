# Final Inspection, After Cancel: the packing lists it covered are free of it.
for l in doc.lots:
    if frappe.db.get_value("Packing List", l.packing_list, "final_inspection") == doc.name:
        frappe.db.set_value("Packing List", l.packing_list, "final_inspection", None, update_modified=False)
