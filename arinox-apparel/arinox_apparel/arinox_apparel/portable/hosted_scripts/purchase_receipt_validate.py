# Purchase Receipt, Before Save: goods from a requisition are received into the inspection warehouse; the received quantity is checked against the order's quantity band.
def run(doc):
    # include: lib_mat.py
    # include: lib_purchasing.py
    flt = frappe.utils.flt
    notes = []
    for pri in doc.items:
        if not pri.get("purchase_order_item"):
            continue
        poi = frappe.db.get_value("Purchase Order Item", pri.purchase_order_item,
                                  ["name", "parent", "stock_qty", "schedule_date", "conversion_factor", "apparel_requisition", "apparel_requisition_type", "qty"], as_dict=True)
        if not poi or not poi.apparel_requisition:
            continue
        kind = "Fabric" if poi.apparel_requisition_type == "FR" else "Trim"
        if not pri.warehouse:
            pri.warehouse = company_warehouse("inspection_warehouse_fabric" if kind == "Fabric" else "inspection_warehouse_trim", doc.company)
        po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier", "status"], as_dict=True)
        terms = terms_for(po.apparel_purchase_terms, po.supplier)
        if not terms:
            continue
        ordered = flt(poi.stock_qty)
        already = flt(frappe.db.get_value("Purchase Order Item", poi.name, "received_qty")) * flt(poi.conversion_factor)
        this = flt(pri.stock_qty) if pri.get("stock_qty") else flt(pri.qty) * (flt(pri.conversion_factor) or 1)
        cumulative = already + this
        tol = qty_tolerance(terms, ordered)
        upper = ordered * (1 + tol / 100)
        lower = ordered * (1 - tol / 100)
        if cumulative > upper + 0.0005:
            excess = flt(cumulative - upper, 2)
            if terms.extra_qty_policy == "Reject":
                frappe.throw("Row %s: %s received against %s ordered is over the +%s%% band by %s." % (pri.idx, flt(cumulative, 2), flt(ordered, 2), tol, excess))
            note = "Row %s: %s over the +%s%% band." % (pri.idx, excess, tol)
            if terms.extra_qty_policy == "Accept Unpaid":
                note = note + " The excess must not be invoiced."
            notes.append(note)
        if po.status == "Closed" and cumulative < lower - 0.0005:
            notes.append("Row %s: short by %s against the order (below the -%s%% band)." % (pri.idx, flt(lower - cumulative, 2), tol))
    doc.apparel_qty_band_note = "\n".join(notes) if notes else None


run(doc)
