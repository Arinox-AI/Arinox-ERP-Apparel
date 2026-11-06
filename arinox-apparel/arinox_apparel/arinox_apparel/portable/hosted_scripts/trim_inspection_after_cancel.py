# Trim Inspection, After Cancel: stock entry and quality inspection cancelled, the requisition refreshed, the stamp cleared.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_matinsp.py
    cancel_linked("Stock Entry", doc.stock_entry)
    cancel_linked("Quality Inspection", doc.quality_inspection)
    doc.db_set({"stock_entry": None, "quality_inspection": None})
    if doc.trim_requisition:
        refresh_requisition("TR", doc.trim_requisition)
    unstamp_safe("Trim Inspection", doc.name)


run(doc)
