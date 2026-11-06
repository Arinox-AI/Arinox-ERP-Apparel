# Sales Order, After Submit: the contract is now Ordered and points at this order.
if doc.get("apparel_sales_contract"):
    frappe.db.set_value("Sales Contract", doc.apparel_sales_contract, {"sales_order": doc.name, "status": "Ordered"})
