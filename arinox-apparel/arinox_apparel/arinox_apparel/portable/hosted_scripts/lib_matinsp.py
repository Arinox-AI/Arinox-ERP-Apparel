# shared helpers from materials/inspection.py: the 4-point fabric system, sampling, lot decision, trim AQL, and the steps both inspections share (receipt context,
# Quality Inspection, Stock Entry). Needs lib_mat.py and lib_purchasing.py.
def defect_points(length_in, always_four):
    """Points for one defect by its length in inches: up to 3 = 1, over 3 to 6 = 2, over 6 to 9 = 3, over 9 = 4. Holes (and any code marked 'always 4') take 4 points."""
    if always_four:
        return 4
    n = frappe.utils.flt(length_in)
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def roll_points(defects):
    """Total points of one roll. `defects` = list of [yard_position, points]. No more than 4 points count in one yard; a defect with no yard number counts on its own."""
    by_yard = {}
    loose = 0
    for d in defects:
        if d[0] in (None, "", 0):
            loose = loose + d[1]
        else:
            by_yard[d[0]] = by_yard.get(d[0], 0) + d[1]
    return loose + sum([min(by_yard[y], 4) for y in by_yard])


def points_per_100_linear(total_points, inspected_m):
    yards = frappe.utils.flt(inspected_m) / YARD_M
    return frappe.utils.flt(total_points) * 100 / yards if yards else 0.0


def points_per_100_square(total_points, inspected_m, width_cm):
    """points x 3600 / (inspected yards x width in inches)."""
    yards = frappe.utils.flt(inspected_m) / YARD_M
    width_in = frappe.utils.flt(width_cm) / 2.54
    return frappe.utils.flt(total_points) * 3600 / (yards * width_in) if yards and width_in else 0.0


def sampling_pct(bands, total_m):
    """Inspect % for a lot of `total_m` metres. Band to_length 0 = no upper limit. 100 when no band matches."""
    flt = frappe.utils.flt
    for b in sorted(bands, key=lambda b: flt(b.from_length_m)):
        if flt(b.from_length_m) <= flt(total_m) and (not flt(b.to_length_m) or flt(total_m) <= flt(b.to_length_m)):
            return flt(b.inspect_pct)
    return 100.0


def lot_decision(avg_points, threshold, rejected_rolls, inspected_rolls, total_rolls, max_rejected_pct, on_hold):
    """Pass / Fail / Re-inspect 100% / Hold. A sample that fails sends the lot to 100% inspection; once every roll has been inspected a failing lot is Fail."""
    flt = frappe.utils.flt
    if on_hold:
        return "Hold"
    rejected_pct = rejected_rolls * 100 / inspected_rolls if inspected_rolls else 0
    failing = flt(avg_points) > flt(threshold) or rejected_pct > flt(max_rejected_pct)
    if not failing:
        return "Pass"
    return "Re-inspect 100%" if inspected_rolls < total_rolls else "Fail"


def roll_disposition(inspected, roll_result, lot_result):
    """What happens to a roll's stock: Accepted, Accepted by Lot, Rejected or Hold."""
    if inspected:
        return {"Accept": "Accepted", "Reject": "Rejected"}.get(roll_result, "Hold")
    return "Accepted by Lot" if lot_result == "Pass" else "Hold"


def width_impact(avg_actual_cm, required_cm, net_qty_m):
    """Extra metres needed when the fabric is narrower than the cuttable width the consumption was based on."""
    flt = frappe.utils.flt
    if not flt(avg_actual_cm) or not flt(required_cm) or flt(avg_actual_cm) >= flt(required_cm):
        return 0.0
    return flt(net_qty_m) * (flt(required_cm) / flt(avg_actual_cm) - 1)


def trim_sample(plan, received_qty):
    """[sample size, accept max, reject min] of a Trim Sampling Plan for a lot. Percent plans have no accept numbers."""
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    received_qty = flt(received_qty)
    if plan.method == "Percent":
        return [max(1, frappe.utils.ceil(received_qty * flt(plan.inspect_pct) / 100)) if received_qty else 0, None, None]
    if received_qty <= cint(plan.full_inspect_up_to):
        return [received_qty, None, None]
    rows = sorted(plan.rows, key=lambda r: cint(r.lot_from))
    pick = None
    for r in rows:
        if cint(r.lot_from) <= received_qty <= cint(r.lot_to):
            pick = r
            break
    if not pick and rows:
        pick = rows[-1]
    if not pick:
        return [received_qty, None, None]
    return [min(flt(pick.sample_size), received_qty), cint(pick.accept_max), cint(pick.reject_min)]


def trim_result(plan, defective, inspected, reject_min, size_mixup):
    """Pass or Fail. A size mix-up always fails. AQL: fail at the reject number. Percent: fail above the plan's limit."""
    flt = frappe.utils.flt
    if size_mixup:
        return "Fail"
    if plan.method == "AQL Table" and reject_min is not None:
        return "Fail" if frappe.utils.cint(defective) >= frappe.utils.cint(reject_min) else "Pass"
    pct = flt(defective) * 100 / flt(inspected) if flt(inspected) else 0
    limit = plan.get("max_defective_pct")
    return "Fail" if pct > flt(5 if limit is None else limit) else "Pass"


def receipt_context(pr_name, row_name, kind):
    """Everything an inspection needs about one Purchase Receipt row of an FR (fabric) or TR (trim)."""
    pr = frappe.db.get_value("Purchase Receipt", pr_name, ["name", "docstatus", "company", "supplier", "posting_date", "currency"], as_dict=True)
    if not pr:
        frappe.throw("Purchase Receipt %s does not exist." % pr_name)
    if pr.docstatus != 1:
        frappe.throw("Purchase Receipt %s is not submitted. Inspect goods that have been received." % pr_name)
    row = frappe.db.get_value("Purchase Receipt Item", {"name": row_name, "parent": pr_name},
                              ["name", "item_code", "warehouse", "stock_qty", "qty", "uom", "conversion_factor", "purchase_order", "purchase_order_item", "serial_and_batch_bundle", "net_amount"], as_dict=True)
    if not row:
        frappe.throw("Row %s is not on %s." % (row_name, pr_name))
    ctx = {"pr": pr, "row": row, "requisition": None, "requisition_type": None, "mri": None, "so_list": [], "styles": [], "customer": None, "terms": None,
           "purchase_order": None, "colour": None, "required_width": None}
    if row.purchase_order_item:
        poi = frappe.db.get_value("Purchase Order Item", row.purchase_order_item, ["parent", "material_request_item", "apparel_requisition_type", "apparel_requisition"], as_dict=True)
        ctx["mri"] = poi.material_request_item
        ctx["requisition_type"] = poi.apparel_requisition_type
        ctx["requisition"] = poi.apparel_requisition
        ctx["purchase_order"] = poi.parent
        po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier"], as_dict=True)
        ctx["terms"] = terms_for(po.apparel_purchase_terms, po.supplier)
    want = "FR" if kind == "Fabric" else "TR"
    if ctx["requisition_type"] and ctx["requisition_type"] != want:
        frappe.throw("This receipt row came from a %s; use the %s inspection." % (ctx["requisition_type"], "trim" if want == "FR" else "fabric"))
    if ctx["requisition"]:
        dt = "Fabric Requisition" if want == "FR" else "Trim Requisition"
        fields = ["sales_order", "style_no", "colour", "style_item"] + (["cuttable_width_cm"] if want == "FR" else [])
        req_rows = frappe.get_all(dt + " Item", filters={"parent": ctx["requisition"], "material_request_item": ctx["mri"]}, fields=fields)
        sos = []
        styles = []
        for r in req_rows:
            if r.sales_order not in sos:
                sos.append(r.sales_order)
            if r.style_no and r.style_no not in styles:
                styles.append(r.style_no)
        ctx["so_list"] = sorted(sos)
        ctx["styles"] = sorted(styles)
        ctx["colour"] = req_rows[0].colour if req_rows else None
        ctx["required_width"] = req_rows[0].get("cuttable_width_cm") if req_rows else None
        ctx["customer"] = frappe.db.get_value(dt, ctx["requisition"], "customer")
    return ctx


def append_red_flag(requisition_type, name, text):
    dt = "Fabric Requisition" if requisition_type == "FR" else "Trim Requisition"
    if not name or not frappe.db.exists(dt, name):
        return
    cur = frappe.db.get_value(dt, name, "red_flags") or ""
    if text not in cur:
        frappe.db.set_value(dt, name, "red_flags", (cur + "\n" + text).strip(), update_modified=False)


def make_quality_inspection(ctx, item_code, accepted, readings, sample_size, remarks):
    """Incoming Quality Inspection against the receipt: manual statuses, submitted. `readings` = [[parameter, value, status], ...]."""
    for p in ("Average Points per 100 Linear Yards", "Worst Roll Points per 100", "Average Width (cm)", "Shrinkage Warp %", "Shrinkage Weft %", "Trim Defective %", "Trim Size Mix-up"):
        if not frappe.db.exists("Quality Inspection Parameter", p):
            frappe.get_doc({"doctype": "Quality Inspection Parameter", "parameter": p}).insert(ignore_permissions=True)
    # ERPNext refuses a Quality Inspection for an item that is not flagged "Inspection Required before Purchase" (the dev suite runs in test mode, which skips that check)
    # The flag is set only while the inspection is made, so later receipts of the item are not blocked waiting for one.
    was_flagged = frappe.db.get_value("Item", item_code, "inspection_required_before_purchase")
    if not was_flagged:
        frappe.db.set_value("Item", item_code, "inspection_required_before_purchase", 1)
    qi = frappe.new_doc("Quality Inspection")
    qi.update({"inspection_type": "Incoming", "reference_type": "Purchase Receipt", "reference_name": ctx["pr"].name, "item_code": item_code, "report_date": frappe.utils.nowdate(),
               "sample_size": sample_size, "inspected_by": frappe.session.user, "manual_inspection": 1, "status": "Accepted" if accepted else "Rejected", "remarks": remarks,
               "child_row_reference": ctx["row"].name})
    for rd in readings:
        qi.append("readings", {"specification": rd[0], "value": "", "reading_value": str(rd[1]), "manual_inspection": 1, "numeric": 0, "status": rd[2]})
    qi.flags.ignore_permissions = True
    qi.insert()
    qi.submit()
    if not was_flagged:
        frappe.db.set_value("Item", item_code, "inspection_required_before_purchase", 0)
    return qi.name


def make_stock_entry(ctx, rows, submit):
    """Move stock out of the inspection warehouse. `rows` = list of dict(item_code, qty, target, batch_no). Returns the Stock Entry name, or None when nothing moves."""
    rows = [r for r in rows if frappe.utils.flt(r["qty"]) > 0 and r["target"]]
    if not rows:
        return None
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.purpose = "Material Transfer"
    se.company = ctx["pr"].company
    for r in rows:
        line = {"item_code": r["item_code"], "qty": r["qty"], "s_warehouse": ctx["row"].warehouse, "t_warehouse": r["target"]}
        if r.get("batch_no"):
            line["batch_no"] = r["batch_no"]
            line["use_serial_batch_fields"] = 1
        se.append("items", line)
    se.remarks = "Inspection release for %s" % ctx["pr"].name
    se.flags.ignore_permissions = True
    se.insert()
    if submit:
        se.submit()
    return se.name


def cancel_linked(doctype, name):
    if name and frappe.db.exists(doctype, name):
        d = frappe.get_doc(doctype, name)
        d.flags.ignore_permissions = True
        if d.docstatus == 1:
            d.cancel()
        elif d.docstatus == 0:
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
