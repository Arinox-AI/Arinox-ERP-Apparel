# Sales Order, After Submit: make the T&A plans when a default template is set and the order has a contract.
def run(doc):
    # include: lib_samples.py
    # include: lib_tna.py
    # include: lib_tna_plan.py
    if not (frappe.db.get_single_value("Apparel Settings", "default_tna_template") and doc.get("apparel_sales_contract")):
        return
    try:
        run_script("arinox_planner_api_make_order_tnas", sales_order=doc.name)
    except Exception:
        frappe.log_error(title="T&A hook sales order failed", message=frappe.get_traceback())


run(doc)
