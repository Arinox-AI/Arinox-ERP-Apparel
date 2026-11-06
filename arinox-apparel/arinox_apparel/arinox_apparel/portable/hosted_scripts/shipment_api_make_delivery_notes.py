# API arinox_shipment_make_delivery_notes: one draft Delivery Note per Sales Order on the shipment, quantities exactly as packed, each row tied to its packing list. Answers the names.
def main():
    # include: lib_shipping.py
    cint = frappe.utils.cint
    shipment = frappe.form_dict.get("shipment") or frappe.form_dict.get("name")
    doc = frappe.get_doc("Shipment", shipment)
    doc.check_permission("write")
    frappe.new_doc("Delivery Note").check_permission("create")
    if doc.docstatus == 2:
        frappe.throw("This shipment is cancelled.")
    made = []
    existing = [r.delivery_note for r in doc.shipment_delivery_note]
    by_order = {}
    order = []
    for r in doc.apparel_packing_lists:
        if not r.packing_list:
            continue
        so = frappe.db.get_value("Packing List", r.packing_list, "sales_order")
        if "o|" + so not in by_order:
            by_order["o|" + so] = []
            order.append(so)
        by_order["o|" + so].append(r.packing_list)
    for so in order:
        pls = by_order["o|" + so]
        if frappe.db.exists("Delivery Note Item", {"apparel_packing_list": ["in", pls], "docstatus": ["<", 2]}):
            frappe.throw("Sales order %s already has a delivery note for these packing lists." % so)
        dn = frappe.call("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note", source_name=so)
        templates = {}
        for i in dn.items:
            templates["t|" + i.so_detail] = i.as_dict()
        fg = settings_value("fg_warehouse", None)
        items = []
        for pl in pls:
            card = frappe.db.get_value("Packing List", pl, "production_card")
            qty = {}
            keys = []
            for ct in frappe.get_all("Packing List Content", filters={"parent": pl}, fields=["sales_order_item", "pieces_total"]):
                if not ct.sales_order_item or not frappe.db.exists("Sales Order Item", ct.sales_order_item):
                    frappe.throw("Packing list %s has a carton row that is not tied to a Sales Order line. Open it and save the packing list again." % pl)
                if ct.sales_order_item not in keys:
                    keys.append(ct.sales_order_item)
                    qty[ct.sales_order_item] = 0
                qty[ct.sales_order_item] = qty[ct.sales_order_item] + cint(ct.pieces_total)
            for so_detail in keys:
                row = templates.get("t|" + so_detail)
                if row:
                    row = dict(row)
                else:
                    line = frappe.db.get_value("Sales Order Item", so_detail, ["item_code", "item_name", "description", "uom", "stock_uom", "conversion_factor", "rate", "warehouse"], as_dict=True)
                    row = dict(line)
                    row["doctype"] = "Delivery Note Item"
                for k in ("name", "parent", "parenttype", "parentfield", "idx", "creation", "modified", "owner", "modified_by", "docstatus"):
                    row.pop(k, None)
                row.update({"qty": qty[so_detail], "so_detail": so_detail, "against_sales_order": so, "apparel_packing_list": pl, "apparel_production_card": card})
                if fg:
                    row["warehouse"] = fg
                items.append(row)
        dn.set("items", items)
        dn.apparel_shipment = shipment
        c = frappe.db.get_value("Sales Order", so, "apparel_sales_contract")
        dn.apparel_sales_contract = c or None
        if doc.incoterm:
            dn.incoterm = doc.incoterm
        if doc.apparel_forwarder:
            dn.transporter = doc.apparel_forwarder
        dn.lr_no = doc.apparel_booking_no
        dn.run_method("set_missing_values")
        dn.run_method("calculate_taxes_and_totals")
        dn.insert()
        made.append(dn.name)
        if dn.name not in existing:
            doc.append("shipment_delivery_note", {"delivery_note": dn.name, "grand_total": dn.grand_total})
    doc.flags.ignore_validate_update_after_submit = True
    doc.save()
    frappe.flags.arinox_result = made


main()
