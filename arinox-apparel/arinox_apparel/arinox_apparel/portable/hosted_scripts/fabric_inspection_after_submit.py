# Fabric Inspection, After Submit: the result is written to every roll (Batch), the Quality Inspection and the Stock Entry that releases accepted rolls and moves rejected
# ones are made, the requisition gets its red flags and quantities, and FABRIC_QC_PASSED is stamped.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_matinsp.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    ctx = receipt_context(doc.purchase_receipt, doc.purchase_receipt_item, "Fabric")
    for r in doc.rolls:
        disp = roll_disposition(cint(r.inspected), r.roll_result, doc.lot_result)
        frappe.db.set_value("Batch", r.batch, {"apparel_inspection_status": disp, "apparel_fabric_inspection": doc.name, "apparel_shade_band": r.shade_band or "",
                                               "apparel_actual_length": r.actual_length, "apparel_points_per_100": r.points_per_100,
                                               "apparel_width_cm": flt(r.width_middle_cm) or flt(r.width_start_cm)}, update_modified=False)
    by_roll = {}
    for r in doc.rolls:
        by_roll[r.roll_no] = r.batch
    for s in doc.shrinkage:
        b = by_roll.get(s.roll_no)
        if b:
            frappe.db.set_value("Batch", b, {"apparel_shrinkage_warp_pct": s.shrink_warp_pct, "apparel_shrinkage_weft_pct": s.shrink_weft_pct}, update_modified=False)

    accepted = doc.lot_result == "Pass"
    inspected = [flt(r.points_per_100) for r in doc.rolls if cint(r.inspected)]
    worst = max(inspected) if inspected else 0
    warp = max([abs(flt(s.shrink_warp_pct)) for s in doc.shrinkage]) if doc.shrinkage else 0
    weft = max([abs(flt(s.shrink_weft_pct)) for s in doc.shrinkage]) if doc.shrinkage else 0
    limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
    readings = [["Average Points per 100 Linear Yards", flt(doc.avg_points, 2), "Accepted" if flt(doc.avg_points) <= flt(doc.points_threshold) else "Rejected"],
                ["Worst Roll Points per 100", flt(worst, 2), "Accepted" if worst <= flt(doc.points_threshold) else "Rejected"]]
    if doc.avg_actual_width_cm:
        readings.append(["Average Width (cm)", doc.avg_actual_width_cm, "Accepted" if flt(doc.avg_actual_width_cm) >= flt(doc.required_width_cm) - 0.5 else "Rejected"])
    if doc.shrinkage:
        readings.append(["Shrinkage Warp %", warp, "Rejected" if limit and warp > limit else "Accepted"])
        readings.append(["Shrinkage Weft %", weft, "Rejected" if limit and weft > limit else "Accepted"])
    qi = make_quality_inspection(ctx, doc.fabric_item, accepted, readings, doc.inspected_rolls, doc.remarks)
    store = company_warehouse("store_warehouse_fabric", doc.company)
    reject = company_warehouse("rejected_warehouse", doc.company)
    rows = []
    for r in doc.rolls:
        disp = roll_disposition(cint(r.inspected), r.roll_result, doc.lot_result)
        if disp in ("Accepted", "Accepted by Lot"):
            rows.append({"item_code": doc.fabric_item, "qty": r.ticket_length, "target": store, "batch_no": r.batch})
        elif disp == "Rejected":
            rows.append({"item_code": doc.fabric_item, "qty": r.ticket_length, "target": reject, "batch_no": r.batch})
    se = make_stock_entry(ctx, rows, cint(frappe.db.get_single_value("Apparel Settings", "submit_inspection_stock_entry")))
    doc.db_set({"quality_inspection": qi, "stock_entry": se})

    if doc.fabric_requisition:
        short = width_impact(doc.avg_actual_width_cm, doc.required_width_cm, doc.accepted_m + doc.rejected_m + doc.hold_m)
        doc.db_set("width_shortfall_m", flt(short, 2))
        if short > 0:
            append_red_flag("FR", doc.fabric_requisition, "%s: fabric is narrower (%s cm vs %s cm cuttable width). About %s m more will be needed." %
                            (doc.name, doc.avg_actual_width_cm, doc.required_width_cm, flt(short, 0)))
        if len((doc.shade_bands_found or "").split(", ")) > 1:
            append_red_flag("FR", doc.fabric_requisition, "%s: more than one shade band (%s). Cut by shade band." % (doc.name, doc.shade_bands_found))
        req = refresh_requisition("FR", doc.fabric_requisition)
        if req:
            need = frappe.db.get_single_value("Apparel Settings", "material_gate_min_pct") or 100
            full = {}
            anyq = {}
            keys = []
            for r in req.items:
                k = "%s|%s|%s" % (r.sales_order, r.style_item, r.colour or "")
                if k not in keys:
                    keys.append(k)
                    full[k] = True
                    anyq[k] = False
                    full[k + "#"] = [r.sales_order, r.style_item, r.colour]
                full[k] = full[k] and (flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * flt(need) / 100)
                if flt(r.accepted_qty) > 0:
                    anyq[k] = True
            for k in keys:
                if full[k] or anyq[k]:
                    v = full[k + "#"]
                    stamp_safe(v[0], v[1], v[2], "FABRIC_QC_PASSED", doc.inspection_date, "Fabric Inspection", doc.name, not full[k], False)


run(doc)
