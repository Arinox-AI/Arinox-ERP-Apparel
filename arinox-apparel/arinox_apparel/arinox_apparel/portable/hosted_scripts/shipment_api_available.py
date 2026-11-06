# API arinox_shipment_get_available_packing_lists: submitted packing lists not on any shipment, with the state of their final inspection.
def main():
    frappe.new_doc("Packing List").check_permission("read")
    filters = {"docstatus": 1, "shipment": ["is", "not set"], "status": "Open"}
    if frappe.form_dict.get("customer"):
        filters["customer"] = frappe.form_dict.get("customer")
    rows = frappe.get_all("Packing List", filters=filters, order_by="creation", fields=["name", "sales_contract", "buyer_po", "total_cartons", "total_pieces", "total_net_kg", "total_gross_kg",
                                                                                         "total_cbm", "customer", "sales_order", "production_card", "ship_to", "docstatus", "shipment",
                                                                                         "status", "final_inspection"])
    for r in rows:
        r["inspection_result"] = frappe.db.get_value("Final Inspection", r.final_inspection, "result") if r.final_inspection else None
    frappe.flags.arinox_result = rows


main()
