# Delivery Note, Before Submit: the final-inspection ship gate and the over-ship check (per size, in total, or both).
def run(doc):
    flt = frappe.utils.flt
    lists = []
    for it in doc.items:
        if it.get("apparel_packing_list") and it.apparel_packing_list not in lists:
            lists.append(it.apparel_packing_list)
    if not lists:
        return
    managers = frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    is_manager = "Apparel Production Manager" in managers or "Apparel Merchandising Manager" in managers or "System Manager" in managers

    def setting(field, default):
        v = frappe.db.get_single_value("Apparel Settings", field)
        if v is None or v == "":
            return default
        return v

    lists = sorted(lists)
    for pl in lists:
        row = frappe.db.get_value("Packing List", pl, ["docstatus", "status"], as_dict=True)
        if not row or row.docstatus != 1:
            frappe.throw("Packing list %s must be submitted before it ships." % pl)
        if row.status == "Shipped":
            frappe.throw("Packing list %s has already shipped." % pl)

    # ---- the final-inspection gate
    mode = setting("ship_gate_final_inspection", "Block")
    if mode != "Off":
        problems = []
        for pl in lists:
            rows = frappe.db.sql(
                "select i.name, i.result from `tabFinal Inspection` i join `tabFinal Inspection Lot` l on l.parent = i.name "
                "where l.packing_list = %s and i.docstatus = 1 and i.inspection_type in ('Final', 'Re-inspection', '2nd Re-inspection') "
                "order by i.inspection_date desc, i.creation desc limit 1", pl, as_dict=True)
            if not rows:
                problems.append("%s has no final inspection." % pl)
            elif rows[0].result not in ("Accepted", "Accepted with Concession"):
                problems.append("%s: the latest inspection %s is %s." % (pl, rows[0].name, rows[0].result or "undecided"))
        if problems:
            if doc.get("apparel_gate_override"):
                if not is_manager:
                    frappe.throw("Only a manager can override the inspection gate.")
                if not (doc.get("apparel_gate_override_reason") or "").strip():
                    frappe.throw("Write the reason for overriding the inspection gate.")
            elif mode == "Block":
                frappe.throw("<br>".join(problems), title="Final inspection")
            else:
                frappe.msgprint("<br>".join(problems), indicator="orange", title="Final inspection")

    # ---- the over-ship check
    basis = setting("ship_tolerance_basis", "Both")
    by_row = {}
    for it in doc.items:
        if not it.get("so_detail") or not it.get("apparel_packing_list"):
            continue
        by_row[it.so_detail] = by_row.get(it.so_detail, 0) + flt(it.stock_qty or it.qty)
    problems = []
    ordered_total = {}
    shipped_total = {}
    tol_by_order = {}
    orders = []
    for d in by_row:
        parent = frappe.db.get_value("Sales Order Item", d, "parent")
        if parent not in orders:
            orders.append(parent)
    for so in orders:    # the whole order, not only the lines on this note
        ordered_total[so] = flt(frappe.db.sql("select ifnull(sum(qty), 0) from `tabSales Order Item` where parent = %s", so)[0][0])
        shipped_total[so] = flt(frappe.db.sql("select ifnull(sum(i.stock_qty), 0) from `tabDelivery Note Item` i where i.against_sales_order = %s and i.docstatus = 1 and i.parent != %s",
                                              (so, doc.name or ""))[0][0])
    for so_detail in by_row:
        qty = by_row[so_detail]
        line = frappe.db.get_value("Sales Order Item", so_detail, ["parent", "qty", "apparel_qty_tolerance_pct", "apparel_colour", "apparel_size"], as_dict=True)
        if not line:
            continue
        before = frappe.db.sql("select ifnull(sum(stock_qty), 0) from `tabDelivery Note Item` where so_detail = %s and docstatus = 1 and parent != %s",
                               (so_detail, doc.name or ""))[0][0]
        shipped = flt(before) + qty
        limit = int(frappe.utils.floor(round(float(line.qty or 0) * (1 + float(line.apparel_qty_tolerance_pct or 0) / 100.0), 6)))
        if (basis == "Each Size" or basis == "Both") and shipped > limit + 0.000000001:
            problems.append("%s %s: %s shipped against %s ordered (allowed up to %s)." % (line.apparel_colour, line.apparel_size, int(shipped), int(line.qty), limit))
        shipped_total[line.parent] = shipped_total[line.parent] + qty
        tol_by_order[line.parent] = flt(line.apparel_qty_tolerance_pct)
    if basis == "Total" or basis == "Both":
        for so in shipped_total:
            limit = int(frappe.utils.floor(round(float(ordered_total[so] or 0) * (1 + float(tol_by_order.get(so, 0) or 0) / 100.0), 6)))
            if shipped_total[so] > limit + 0.000000001:
                problems.append("%s: %s shipped in all against %s ordered (allowed up to %s)." % (so, int(shipped_total[so]), int(ordered_total[so]), limit))
    if problems:
        if doc.get("apparel_over_ship_override"):
            if not is_manager:
                frappe.throw("Only a manager can approve shipping outside the allowance.")
            if not (doc.get("apparel_over_ship_override_reason") or "").strip():
                frappe.throw("Write the reason for shipping outside the allowance.")
        else:
            frappe.throw("<br>".join(problems), title="Over-shipment")


run(doc)
