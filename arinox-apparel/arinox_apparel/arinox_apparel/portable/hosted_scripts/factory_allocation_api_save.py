# API arinox_factory_allocation_save_allocation: create or replace the allocation of a Sales Order. `lines` is a list (or JSON) of
# {style_item, colour, qty, factory, line, pcd, sewing_start, sewing_end, reason}. Answers the allocation name.
def main():
    sales_order = frappe.form_dict.get("sales_order")
    lines = frappe.form_dict.get("lines")
    if isinstance(lines, str):
        lines = json.loads(lines)
    name = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
    d = frappe.get_doc("Factory Allocation", name) if name else frappe.new_doc("Factory Allocation")
    d.sales_order = sales_order
    d.planned_by = frappe.form_dict.get("planned_by") or "AI Agent"
    if frappe.form_dict.get("agent_notes") is not None:
        d.agent_notes = frappe.form_dict.get("agent_notes")
    d.set("lines", [])
    for ln in lines:
        d.append("lines", ln)
    d.save()
    frappe.flags.arinox_result = d.name


main()
