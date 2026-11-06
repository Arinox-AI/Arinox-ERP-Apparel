# Packing List, After Cancel: take PACKED out of the ledger and cancel the finished-goods receipt. SSCC numbers already drawn stay retired.
run_script("arinox_engine", action="unpost", source_doctype="Packing List", source_name=doc.name)
if doc.fg_stock_entry:
    se = frappe.get_doc("Stock Entry", doc.fg_stock_entry)
    if se.docstatus == 1:
        se.cancel()
    elif se.docstatus == 0:
        frappe.delete_doc("Stock Entry", se.name, force=1, ignore_permissions=True)
    doc.db_set("fg_stock_entry", None)
