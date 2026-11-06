# Purchase Receipt, After Submit: late delivery under the PO terms is stored (days, penalty %, amount; no accounting entry), then the requisitions are refreshed and
# FABRIC_IN_HOUSE / TRIMS_IN_HOUSE stamped (in progress until everything is received).
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    flt = frappe.utils.flt
    getdate = frappe.utils.getdate
    worst = 0
    terms_doc = None
    value = 0.0
    rows = []
    for pri in doc.items:
        if not pri.get("purchase_order_item"):
            continue
        poi = frappe.db.get_value("Purchase Order Item", pri.purchase_order_item, ["name", "parent", "schedule_date", "apparel_requisition", "apparel_requisition_type"], as_dict=True)
        if poi and poi.apparel_requisition:
            rows.append([pri, poi])
    for pr in rows:
        pri = pr[0]
        poi = pr[1]
        po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier", "apparel_etd_actual"], as_dict=True)
        terms = terms_for(po.apparel_purchase_terms, po.supplier)
        arrival = po.apparel_etd_actual or doc.posting_date
        days = frappe.utils.date_diff(getdate(arrival), getdate(poi.schedule_date)) if poi.schedule_date else 0
        if days > worst:
            worst = days
            terms_doc = terms
        if days > 0:
            value = value + flt(pri.net_amount)
    if rows:
        pen = delay_penalty(terms_doc, worst)
        doc.db_set({"apparel_delay_days": max(worst, 0), "apparel_penalty_pct": pen[0], "apparel_penalty_amount": flt(value * pen[0] / 100, 2)}, update_modified=False)
        if pen[1] == "Cancel or Discount" and pen[0]:
            doc.db_set("apparel_qty_band_note", ((doc.apparel_qty_band_note or "") + "\n" + "Delay of %s days: the order may be cancelled or discounted %s%%." % (worst, pen[0])).strip(), update_modified=False)
    seen = []
    for pr in rows:
        t = pr[1].apparel_requisition_type
        n = pr[1].apparel_requisition
        if [t, n] in seen:
            continue
        seen.append([t, n])
        req = refresh_requisition(t, n)
        if not req:
            continue
        code = "FABRIC_IN_HOUSE" if t == "FR" else "TRIMS_IN_HOUSE"
        done = req.status == "Received"
        keys = []
        for r in req.items:
            k = [r.sales_order, r.style_item, (r.colour or "").strip()]
            if k in keys or flt(r.received_qty) <= 0:
                continue
            keys.append(k)
            stamp_safe(r.sales_order, r.style_item, r.colour or None, code, frappe.utils.nowdate(), "Purchase Receipt", req.name, not done, False)


run(doc)
