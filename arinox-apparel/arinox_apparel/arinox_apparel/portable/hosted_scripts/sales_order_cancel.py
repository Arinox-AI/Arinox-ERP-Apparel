# Sales Order, After Cancel: the contract is Signed again and free for a new order.
if doc.get("apparel_sales_contract"):
    frappe.db.set_value("Sales Contract", doc.apparel_sales_contract, {"sales_order": None, "status": "Signed"})
