# Factory Allocation, After Save: re-plan every plan of the order (the PCD and the sewing window may have moved).
def run(doc):
    # include: lib_samples.py
    # include: lib_tna.py
    # include: lib_tna_plan.py
    try:
        for name in frappe.get_all("Order TNA", filters={"sales_order": doc.sales_order, "status": ["!=", "Cancelled"]}, pluck="name"):
            replan(name)
    except Exception:
        frappe.log_error(title="T&A hook factory allocation failed", message=frappe.get_traceback())


run(doc)
