# API arinox_fabric_requisition_get_requisition_context: everything an agent needs to draft the FR and TR for an order.
def main():
    # include: lib_samples.py
    # include: lib_allocation.py
    # include: lib_mat.py
    sales_order = frappe.form_dict.get("sales_order")
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("read")
    styles = {}
    cl = colour_level(get_order_lines(sales_order))
    for key in cl:
        style = key[0]
        o = cl[key]
        tp = tech_pack_for(style)
        cs = cost_sheet_for(sales_order, style)
        d = get_style_dates(sales_order, style, o["colour"])
        if "s|" + style not in styles:
            styles["s|" + style] = {"style_item": style, "tech_pack": tp.name if tp else None, "cost_sheet": cs.name if cs else None, "colours": []}
        st = styles["s|" + style]
        st["colours"].append({"colour": o["colour"], "qty": frappe.utils.cint(o["qty"]), "pcd": str(d[0]) if d[0] else None, "ex_factory": str(d[1]) if d[1] else None,
                              "lab_dip": approval_info(sales_order, style, "Lab Dip", o["colour"], so.customer)[0], "bulk_trim": approval_info(sales_order, style, "Bulk Trim", None, so.customer)[0]})
        if tp and "materials" not in st:
            st["materials"] = [m.as_dict() for m in tp.materials]
    frappe.flags.arinox_result = {"sales_order": sales_order, "customer": so.customer, "company": so.company, "styles": [styles[s] for s in styles],
                                  "allowance_rules": frappe.get_all("Material Allowance Rule", filters={"enabled": 1}, fields=["material_type", "trim_category", "customer", "allowance_pct", "pack_size"]),
                                  "fr_material_types": fr_material_types()}


main()
