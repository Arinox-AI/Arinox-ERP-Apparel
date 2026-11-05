# Production Card, Before Submit: the breakup is required; list what is still open (it never blocks issuing).
def run(doc):
    if not doc.lines:
        frappe.throw("Add the colour x size breakup before issuing.")
    missing = []
    if not frappe.db.exists("Factory Allocation", {"sales_order": doc.sales_order}):
        missing.append("No Factory Allocation for this order.")
    if not frappe.db.exists("Tech Pack", {"style_item": doc.style_item, "docstatus": ["<", 2]}):
        missing.append("No Tech Pack for this style.")
    if not frappe.db.exists("Fabric Requisition Item", {"sales_order": doc.sales_order, "style_item": doc.style_item, "docstatus": 1}):
        missing.append("No approved Fabric Requisition.")
    if not frappe.db.exists("Trim Requisition Item", {"sales_order": doc.sales_order, "style_item": doc.style_item, "docstatus": 1}):
        missing.append("No approved Trim Requisition.")
    if not doc.packing_instruction:
        missing.append("No Packing Instruction.")
    if missing:
        frappe.msgprint("<br>• ".join(["Issued with these still open:"] + missing), indicator="orange", title="Production Card")


run(doc)
