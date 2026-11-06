# API arinox_factory_allocation_get_planning_context: everything the planning agent needs in one call: the order lines, the factories and
# their lines, and what other orders already load into the same window.
def main():
    # include: lib_allocation.py
    sales_order = frappe.form_dict.get("sales_order")
    frappe.new_doc("Factory Allocation").check_permission("read")
    order = get_order_lines(sales_order)
    dates = [frappe.utils.getdate(order[k]["ex_factory_date"]) for k in order if order[k]["ex_factory_date"]]
    lo = None
    hi = None
    if dates:
        lo = frappe.utils.add_days(min(dates), -45)
        hi = max(dates)
    factories = []
    for f in frappe.get_all("Plant Floor", fields=["name", "company", "warehouse"]):
        f["lines"] = frappe.get_all("Workstation", filters={"plant_floor": f.name, "disabled": 0}, fields=["name", "production_capacity", "status"])
        factories.append(f)
    busy = []
    if lo:
        busy = frappe.db.sql("""select l.parent as allocation, l.style_item, l.colour, l.qty, l.factory, l.line, l.pcd, l.sewing_start, l.sewing_end
            from `tabFactory Allocation Line` l where l.parent != %s and l.sewing_end between %s and %s""", ("FA-" + sales_order, lo, frappe.utils.add_days(hi, 30)), as_dict=True)
    existing = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
    frappe.flags.arinox_result = {"sales_order": sales_order, "order_lines": [order[k] for k in order], "factories": factories, "other_allocations_in_window": busy,
                                  "current_allocation": frappe.get_doc("Factory Allocation", existing).as_dict() if existing else None}


main()
