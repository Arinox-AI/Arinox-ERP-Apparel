# Sample Approval, After Save: the approval milestones of every plan of this style x colour follow the approvals.
def run(doc):
    try:
        filters = {"style_item": doc.style_item, "status": ["!=", "Cancelled"]}
        if doc.sales_order:
            filters["sales_order"] = doc.sales_order
        for t in frappe.get_all("Order TNA", filters=filters, fields=["name", "colour"]):
            if doc.colour and (t.colour or "").strip() and (t.colour or "").strip().upper() != doc.colour.strip().upper():
                continue
            run_script("arinox_tna", action="samples", order_tna=t.name)
    except Exception:
        frappe.log_error(title="T&A hook sample approval failed", message=frappe.get_traceback())


run(doc)
