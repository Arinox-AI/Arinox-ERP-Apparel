# Sales Order, After Cancel: the plans of the order are cancelled.
def run(doc):
    try:
        for name in frappe.get_all("Order TNA", filters={"sales_order": doc.name, "status": ["!=", "Cancelled"]}, pluck="name"):
            frappe.db.set_value("Order TNA", name, "status", "Cancelled", update_modified=False)
            for m in frappe.get_all("TNA Milestone", filters={"order_tna": name}, pluck="name"):
                frappe.db.set_value("TNA Milestone", m, {"status": "Not Applicable", "color": "#cbd5e0"}, update_modified=False)
    except Exception:
        frappe.log_error(title="T&A hook sales order cancel failed", message=frappe.get_traceback())


run(doc)
