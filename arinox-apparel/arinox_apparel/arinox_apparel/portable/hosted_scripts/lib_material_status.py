# shared helpers from materials/status.py: the status of every approved requisition line (material_rows, line_status). The gate parts are in lib_materials.py.
def line_status(r, min_pct):
    """Status of one requisition line. `r` carries net, ordered, received, accepted, rejected, hold, eta / etd flags."""
    flt = frappe.utils.flt
    need = flt(r["net"]) * flt(min_pct) / 100
    if flt(r["net"]) <= 0 or flt(r["accepted"]) + 0.0005 >= need:
        return "Accepted"
    if flt(r["received"]) - flt(r["accepted"]) - flt(r["rejected"]) > 0.0005:
        return "In House - QC Pending"
    if flt(r["rejected"]) > 0 and flt(r["received"]) + 0.0005 >= flt(r["net"]):
        return "Rejected"
    if flt(r["received"]) > 0:
        return "Short"
    if flt(r["ordered"]) > 0:
        return "In Transit" if (r.get("etd_actual") or r.get("eta")) else "Ordered"
    if frappe.utils.cint(r.get("hold")):
        return "On Hold"
    return "Requested"


def material_rows(filters):
    """One dict per approved, current FR / TR line, with purchase order, receipt and inspection facts."""
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    min_pct = flt(frappe.db.get_single_value("Apparel Settings", "material_gate_min_pct") or 100)
    out = []
    for kind in (["FR", "Fabric Requisition", "Fabric Requisition Item", "fabric_item"], ["TR", "Trim Requisition", "Trim Requisition Item", "trim_item"]):
        typ = kind[0]
        dt = kind[1]
        child = kind[2]
        item_f = kind[3]
        if filters.get("material_type") and filters.get("material_type") != ("Fabric" if typ == "FR" else "Trim"):
            continue
        cond = ["p.docstatus = 1", "p.status not in ('Superseded', 'Cancelled')"]
        args = {}
        for f, col in (("customer", "p.customer"), ("company", "p.company")):
            if filters.get(f):
                cond.append("%s = %%(%s)s" % (col, f))
                args[f] = filters.get(f)
        if filters.get("sales_order"):
            cond.append("c.sales_order = %(sales_order)s")
            args["sales_order"] = filters.get("sales_order")
        if filters.get("supplier"):
            cond.append("c.supplier = %(supplier)s")
            args["supplier"] = filters.get("supplier")
        rows = frappe.db.sql("select c.name, c.parent, c.sales_order, c.style_no, c.colour, c.%s as item, c.supplier, c.required_by, c.net_qty, c.ordered_qty, c.received_qty, c.accepted_qty, "
                             "c.rejected_qty, c.hold, c.material_request_item, p.customer, p.company from `tab%s` c join `tab%s` p on p.name = c.parent where %s order by c.sales_order, c.style_no, c.colour"
                             % (item_f, child, dt, " and ".join(cond)), args, as_dict=True)
        for r in rows:
            po = []
            if r.material_request_item:
                po = frappe.db.sql("select o.name, o.transaction_date, o.apparel_etd_planned, o.apparel_etd_revised, o.apparel_etd_actual, o.apparel_eta, o.apparel_supplier_contract_no "
                                   "from `tabPurchase Order Item` i join `tabPurchase Order` o on o.name = i.parent where i.material_request_item = %s and o.docstatus = 1 order by o.creation",
                                   (r.material_request_item,), as_dict=True)
            last = po[-1] if po else {}
            claim = None
            if typ == "FR" and r.material_request_item:
                claim = frappe.db.sql("select min(claim_deadline) from `tabFabric Inspection` where docstatus = 1 and purchase_receipt_item in ("
                                      "select name from `tabPurchase Receipt Item` where purchase_order_item in (select name from `tabPurchase Order Item` where material_request_item = %s))",
                                      (r.material_request_item,))[0][0]
            d = {"type": typ, "requisition": r.parent, "sales_order": r.sales_order, "customer": r.customer, "style_no": r.style_no, "colour": r.colour, "item": r.item, "supplier": r.supplier,
                 "required_by": r.required_by, "net": flt(r.net_qty), "ordered": flt(r.ordered_qty), "received": flt(r.received_qty), "accepted": flt(r.accepted_qty),
                 "rejected": flt(r.rejected_qty), "hold": cint(r.hold), "po": ", ".join([p.name for p in po]), "po_date": last.get("transaction_date"),
                 "etd_planned": last.get("apparel_etd_planned"), "etd_revised": last.get("apparel_etd_revised"), "etd_actual": last.get("apparel_etd_actual"), "eta": last.get("apparel_eta"),
                 "claim_deadline": claim}
            d["in_inspection"] = max(d["received"] - d["accepted"] - d["rejected"], 0)
            d["balance"] = max(d["net"] - d["received"], 0)
            d["status"] = line_status(d, min_pct)
            d["days_late"] = max(frappe.utils.date_diff(frappe.utils.nowdate(), r.required_by), 0) if r.required_by and d["status"] != "Accepted" else 0
            if filters.get("status") and filters.get("status") != d["status"]:
                continue
            if cint(filters.get("only_late")) and not d["days_late"]:
                continue
            out.append(d)
    return out
