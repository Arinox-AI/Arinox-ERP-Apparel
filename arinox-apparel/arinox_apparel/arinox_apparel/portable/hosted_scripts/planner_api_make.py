# API arinox_planner_make_order_tnas: one Order TNA per style x colour x ex-factory date of a submitted Sales Order. Existing ones are left alone. Answers the names made.
def main():
    # include: lib_samples.py
    # include: lib_tna.py
    # include: lib_tna_plan.py
    sales_order = frappe.form_dict.get("sales_order")
    template = frappe.form_dict.get("template")
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("read")
    frappe.new_doc("Order TNA").check_permission("create")
    if so.docstatus != 1:
        frappe.throw("Submit the Sales Order first.")
    made = []
    for g in order_groups(sales_order):
        if not g["ex_factory"]:
            frappe.msgprint("Style %s %s has no delivery date on the Sales Order; no T&A was made for it." % (g["style_item"], g["colour"]))
            continue
        if frappe.db.exists("Order TNA", {"sales_order": sales_order, "style_item": g["style_item"], "colour": g["colour"], "ex_factory_date": frappe.utils.getdate(g["ex_factory"]),
                                          "status": ["!=", "Cancelled"]}):
            continue
        tp = tech_pack_for(g["style_item"])
        tpl = template or pick_template(so.customer, tp.product_type if tp else None, None)
        if not tpl:
            frappe.throw("No T&A template. Set a default in Apparel Settings.")
        al = allocation_for(sales_order, g["style_item"], g["colour"])
        doc = frappe.get_doc({"doctype": "Order TNA", "sales_order": sales_order, "style_item": g["style_item"], "style_no": tp.style_no if tp else g["style_item"],
                              "colour": g["colour"], "order_qty": g["qty"], "ship_tos": ", ".join(sorted(g["ship_tos"])), "merchant": frappe.session.user, "factory": al[0],
                              "order_received_date": so.po_date or so.transaction_date, "order_date_missing": 0 if so.po_date else 1, "pcd": al[1],
                              "ex_factory_date": frappe.utils.getdate(g["ex_factory"]), "template": tpl})
        doc.flags.ignore_permissions = True
        doc.insert()
        build_milestones(doc)
        backfill(doc.name)
        made.append(doc.name)
    frappe.flags.arinox_result = made


main()
