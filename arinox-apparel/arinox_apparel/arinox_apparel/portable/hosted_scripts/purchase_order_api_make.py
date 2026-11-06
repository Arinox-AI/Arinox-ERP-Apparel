# API arinox_purchase_order_make_purchase_orders: draft Purchase Orders from an approved FR / TR, one per supplier, for the Material Request rows not yet ordered.
# Buyer-supplied trims are skipped. Answers the PO names.
def main():
    requisition_type = frappe.form_dict.get("requisition_type")
    name = frappe.form_dict.get("name")
    dt = "Fabric Requisition" if requisition_type == "FR" else "Trim Requisition"
    req = frappe.get_doc(dt, name)
    req.check_permission("read")
    frappe.new_doc("Purchase Order").check_permission("create")
    if req.docstatus != 1:
        frappe.throw("Approve (submit) the requisition first.")
    groups = {}
    order = []
    for r in req.items:
        if not r.material_request_item or frappe.utils.cint(r.get("customer_provided")) or not r.supplier:
            continue
        if frappe.db.exists("Purchase Order Item", {"material_request_item": r.material_request_item, "docstatus": ["<", 2]}):
            continue
        if r.supplier not in groups:
            groups[r.supplier] = []
            order.append(r.supplier)
        groups[r.supplier].append(r)
    made = []
    for supplier in order:
        rows = groups[supplier]
        po = frappe.new_doc("Purchase Order")
        po.company = req.company
        po.supplier = supplier
        po.transaction_date = frappe.utils.nowdate()
        dated = [frappe.utils.getdate(r.required_by) for r in rows if r.required_by]
        po.schedule_date = min(dated) if dated else frappe.utils.getdate(frappe.utils.nowdate())
        po.apparel_purchase_terms = frappe.db.get_value("Supplier", supplier, "apparel_purchase_terms") or frappe.db.get_single_value("Apparel Settings", "default_purchase_terms")
        for r in rows:
            mri = frappe.db.get_value("Material Request Item", r.material_request_item,
                                      ["name", "parent", "item_code", "qty", "uom", "conversion_factor", "warehouse", "schedule_date", "sales_order"], as_dict=True)
            po.append("items", {"item_code": mri.item_code, "qty": mri.qty, "uom": mri.uom, "conversion_factor": mri.conversion_factor, "warehouse": mri.warehouse,
                                "schedule_date": mri.schedule_date, "sales_order": mri.sales_order, "material_request": mri.parent, "material_request_item": mri.name})
        po.run_method("set_missing_values")
        po.insert()
        made.append(po.name)
    frappe.flags.arinox_result = made


main()
