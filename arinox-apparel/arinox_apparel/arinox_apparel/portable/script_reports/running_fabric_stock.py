def main(filters):
    # include: lib_mat.py
    # include: lib_cutting.py
    # include: lib_summary.py
    flt = frappe.utils.flt

    def C(f, l, t="Data", w=100, o=None):
        d = {"fieldname": f, "label": l, "fieldtype": t, "width": w}
        if o:
            d["options"] = o
        return d

    columns = [C("po_date", "PO Date", "Date", 90), C("customer", "Buyer", "Link", 120, "Customer"), C("merchant", "Merchant", w=110), C("style_no", "Style", w=100),
               C("supplier", "Supplier", "Link", 130, "Supplier"), C("contract_no", "Supplier Contract", w=120), C("po", "Purchase Order", "Link", 120, "Purchase Order"),
               C("fabric", "Fabric", w=240), C("colour", "Colour", w=100), C("ordered", "Ordered", "Float", 90), C("uom", "Unit", w=60), C("price", "Price", "Currency", 80),
               C("value", "Ordered Value", "Currency", 110), C("delivery_date", "Delivery Date", "Date", 95), C("delay_days", "Delay (days)", "Int", 80), C("received_date", "Received On", "Date", 95),
               C("received", "Received", "Float", 90), C("over_short", "Over / Short", "Float", 90), C("over_short_pct", "Over / Short %", "Percent", 90), C("issued", "Issued", "Float", 90),
               C("balance", "Balance", "Float", 90), C("balance_pct_order", "% of Order", "Percent", 80), C("balance_pct_received", "% of Received", "Percent", 90),
               C("stock_value", "Stock Value", "Currency", 100), C("garment_qty", "Garment Qty", "Int", 90), C("cut_qty", "Cut Qty", "Int", 120), C("used_consumption", "Actual Used / pc", "Float", 150)]
    cond = ["o.docstatus = 1", "i.apparel_requisition_type = 'FR'"]
    args = {}
    for key, col in (("customer", "r.customer"), ("supplier", "o.supplier"), ("sales_order", "i.sales_order")):
        if filters.get(key):
            cond.append("%s = %%(%s)s" % (col, key))
            args[key] = filters.get(key)
    rows = frappe.db.sql("select o.name po, o.transaction_date po_date, o.supplier, o.apparel_supplier_contract_no contract_no, i.name poi, i.item_code, i.item_name, i.description, "
                         "i.stock_qty ordered, i.stock_uom uom, i.rate price, i.amount, i.schedule_date delivery_date, i.apparel_style_no style_no, i.apparel_colour colour, "
                         "i.apparel_requisition, i.material_request_item, i.sales_order, (select variant_of from `tabItem` where name = (select item_code from `tabSales Order Item` "
                         "where parent = i.sales_order and apparel_colour = i.apparel_colour limit 1)) style_item, r.customer, r.ordered_by from `tabPurchase Order Item` i "
                         "join `tabPurchase Order` o on o.name = i.parent left join `tabFabric Requisition` r on r.name = i.apparel_requisition where " + " and ".join(cond) +
                         " order by o.transaction_date, o.name", args, as_dict=True)
    stores = []
    for c in frappe.get_all("Company", pluck="name"):
        w = company_warehouse("store_warehouse_fabric", c)
        if w and w not in stores:
            stores.append(w)
    out = []
    for r in rows:
        prs = frappe.db.sql("select pr.name, pr.posting_date, pri.stock_qty from `tabPurchase Receipt Item` pri join `tabPurchase Receipt` pr on pr.name = pri.parent "
                            "where pri.purchase_order_item = %s and pr.docstatus = 1 order by pr.posting_date", (r.poi,), as_dict=True)
        received = sum([flt(p.stock_qty) for p in prs])
        first = prs[0].posting_date if prs else None
        batches = frappe.get_all("Batch", filters={"reference_doctype": "Purchase Receipt", "reference_name": ["in", [p.name for p in prs] or [""]]}, pluck="name")
        issued = 0.0
        if batches and stores:
            issued = flt(frappe.db.sql("select coalesce(-sum(e.qty), 0) from `tabSerial and Batch Entry` e join `tabSerial and Batch Bundle` b on b.name = e.parent "
                                       "where b.docstatus = 1 and b.is_cancelled = 0 and e.qty < 0 and e.batch_no in %s and e.warehouse in %s", (tuple(batches), tuple(stores)))[0][0])
        balance = received - issued
        merchant = frappe.db.get_value("User", r.ordered_by, "full_name") if r.ordered_by else None
        garment = frappe.db.get_value("Fabric Requisition Item", {"parent": r.apparel_requisition, "material_request_item": r.material_request_item}, "garment_qty") if r.apparel_requisition else None
        cut_qty = None
        used = None
        if r.sales_order and r.style_item:
            fu = fabric_usage(r.sales_order, r.style_item, r.colour, r.item_code)
            cut_qty = fu[0] or None
            used = fu[2]
        out.append({"po_date": r.po_date, "customer": r.customer, "merchant": merchant, "style_no": r.style_no, "supplier": r.supplier, "contract_no": r.contract_no, "po": r.po,
                    "fabric": (r.description or r.item_name or r.item_code)[:120], "colour": r.colour, "ordered": r.ordered, "uom": r.uom, "price": r.price, "value": r.amount,
                    "delivery_date": r.delivery_date, "delay_days": frappe.utils.date_diff(first, r.delivery_date) if first and r.delivery_date else None, "received_date": first,
                    "received": received, "over_short": received - flt(r.ordered), "over_short_pct": (received - flt(r.ordered)) * 100 / flt(r.ordered) if flt(r.ordered) else 0,
                    "issued": issued, "balance": balance, "balance_pct_order": balance * 100 / flt(r.ordered) if flt(r.ordered) else 0,
                    "balance_pct_received": balance * 100 / received if received else 0, "stock_value": balance * flt(r.price), "garment_qty": garment, "cut_qty": cut_qty, "used_consumption": used})
    return (columns, out)


data = list(main(filters))
