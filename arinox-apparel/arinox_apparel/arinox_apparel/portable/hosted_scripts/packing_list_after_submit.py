# Packing List, After Submit: PACKED goes to the production ledger (checked against what finishing passed as A-grade), one SSCC per carton from a
# counter that never goes back, and a draft Material Receipt of the packed pieces into Finished Goods so the Delivery Note has stock.
def run(doc):
    # include: lib_packing.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    sums = {}
    for ct in doc.contents:
        k = ct.colour + "\t" + ct.size
        sums[k] = sums.get(k, 0) + cint(ct.pieces_total)
    rows = []
    for k in sums:
        parts = k.split("\t")
        rows.append({"stage": "PACKED", "colour": parts[0], "size": parts[1], "qty": sums[k]})
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Packing List", source_name=doc.name,
               posting_date=str(doc.packing_date), check="1")

    prefix = frappe.db.get_single_value("Apparel Settings", "gs1_company_prefix")
    if prefix:
        idx = 0
        for c in doc.cartons:
            for n in range(cint(c.carton_from), cint(c.carton_to) + 1):
                series = "SSCC-" + str(prefix) + "-"
                drawn = frappe.get_doc({"doctype": "Arinox Number", "prefix": series}).insert(ignore_permissions=True)
                serial = int(drawn.name[len(series):])
                idx = idx + 1
                frappe.get_doc({"doctype": "Packing List SSCC", "parent": doc.name, "parenttype": "Packing List", "parentfield": "sscc", "idx": idx,
                                "carton_no": n, "sscc": sscc_number(prefix, serial)}).insert(ignore_permissions=True)

    receive = frappe.db.get_single_value("Apparel Settings", "post_fg_receipt")
    if receive is None or receive == "":
        receive = 1
    wh = frappe.db.get_single_value("Apparel Settings", "fg_warehouse")
    if cint(receive) and wh:
        items = frappe.get_all("Sales Order Item", {"parent": doc.sales_order}, ["name", "item_code", "rate", "apparel_cost_sheet"])
        by_name = {}
        for i in items:
            by_name[i.name] = i
        qty = {}
        rate = {}
        for ct in doc.contents:
            i = by_name.get(ct.sales_order_item)
            if not i:
                continue
            qty[i.item_code] = qty.get(i.item_code, 0) + cint(ct.pieces_total)
            cost = frappe.db.get_value("Cost Sheet", i.apparel_cost_sheet, "product_cost") if i.apparel_cost_sheet else None
            rate[i.item_code] = flt(cost) or flt(frappe.db.get_value("Item", i.item_code, "valuation_rate")) or flt(i.rate)
        if qty:
            try:
                se = frappe.new_doc("Stock Entry")
                se.stock_entry_type = "Material Receipt"
                se.purpose = "Material Receipt"
                se.company = frappe.db.get_value("Production Card", doc.production_card, "company")
                se.apparel_production_card = doc.production_card
                se.apparel_issue_kind = "Finished Goods Receipt"
                for code in qty:
                    se.append("items", {"item_code": code, "qty": qty[code], "t_warehouse": wh, "basic_rate": rate[code], "allow_zero_valuation_rate": 0 if rate[code] else 1})
                se.remarks = "Packed on %s. Rate from the Cost Sheet cost (or the order rate when none): check before submitting." % doc.name
                se.insert(ignore_permissions=True)
                if cint(frappe.db.get_single_value("Apparel Settings", "auto_submit_stock_entries")):
                    se.submit()
                doc.db_set("fg_stock_entry", se.name)
            except Exception:
                frappe.msgprint("The finished-goods receipt could not be drafted. Packing itself is saved.", indicator="orange")
    elif cint(receive):
        frappe.msgprint("Set the Finished Goods warehouse in Apparel Settings to receive packed pieces into stock.", indicator="orange")


run(doc)
