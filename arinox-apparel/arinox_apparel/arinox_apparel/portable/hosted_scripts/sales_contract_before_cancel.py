# Sales Contract, Before Cancel: the order must be cancelled first.
if doc.sales_order and frappe.db.get_value("Sales Order", doc.sales_order, "docstatus") == 1:
    frappe.throw("Cancel Sales Order %s before cancelling this contract." % doc.sales_order)
