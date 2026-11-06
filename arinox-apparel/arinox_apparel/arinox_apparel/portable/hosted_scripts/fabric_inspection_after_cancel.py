# Fabric Inspection, After Cancel: the stock entry and quality inspection are cancelled, the rolls are uninspected again, the requisition refreshed, the stamp cleared.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_matinsp.py
    cancel_linked("Stock Entry", doc.stock_entry)
    cancel_linked("Quality Inspection", doc.quality_inspection)
    for r in doc.rolls:
        frappe.db.set_value("Batch", r.batch, {"apparel_inspection_status": "Uninspected", "apparel_fabric_inspection": None, "apparel_points_per_100": 0}, update_modified=False)
    doc.db_set({"stock_entry": None, "quality_inspection": None})
    if doc.fabric_requisition:
        refresh_requisition("FR", doc.fabric_requisition)
    unstamp_safe("Fabric Inspection", doc.name)


run(doc)
