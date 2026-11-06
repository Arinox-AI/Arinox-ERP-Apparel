# Fabric Inspection, Before Save: the receipt row, the rolls, defects -> points (4-point system), per-roll result, shrinkage, and the lot decision (sampling, average points, rejected rolls).
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_po.py
    # include: lib_matinsp.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    ctx = receipt_context(doc.purchase_receipt, doc.purchase_receipt_item, "Fabric")
    doc.company = ctx["pr"].company
    doc.supplier = ctx["pr"].supplier
    doc.purchase_order = ctx["purchase_order"]
    doc.fabric_requisition = ctx["requisition"]
    doc.fabric_item = ctx["row"].item_code
    doc.customer = ctx["customer"]
    doc.sales_orders = ", ".join(ctx["so_list"])
    doc.style_nos = ", ".join(ctx["styles"])
    doc.colour = doc.colour or ctx["colour"]
    if not flt(doc.required_width_cm):
        doc.required_width_cm = flt(ctx["required_width"]) or flt(frappe.db.get_value("Item", ctx["row"].item_code, "apparel_fabric_width_cm"))
    doc.points_basis = frappe.db.get_single_value("Apparel Settings", "fabric_points_basis") or "Per 100 Linear Yards"
    terms = ctx["terms"]
    if not flt(doc.points_threshold):
        doc.points_threshold = flt(terms.points_threshold) if terms and flt(terms.points_threshold) else flt(frappe.db.get_single_value("Apparel Settings", "fabric_points_threshold") or 20)
    window = cint(terms.claim_window_days) if terms else 0
    doc.claim_deadline = frappe.utils.add_days(ctx["pr"].posting_date, window) if window else None
    if not doc.inspected_by:
        doc.inspected_by = frappe.session.user
    if cint(doc.result_override):
        if not is_manager():
            frappe.throw("Only an Apparel Merchandising Manager can override the inspection rules.")
        if not (doc.override_reason or "").strip():
            frappe.throw("Enter the reason for overriding the inspection rules.")
    if not doc.rolls:
        frappe.throw("Load the rolls first (Tools > Load Rolls from Receipt).")

    # ---- rolls must be the ones received on this row
    bundle = ctx["row"].serial_and_batch_bundle
    allowed = []
    if bundle:
        allowed = [e.batch_no for e in frappe.get_all("Serial and Batch Entry", filters={"parent": bundle}, fields=["batch_no"]) if e.batch_no]
    seen = []
    for r in doc.rolls:
        if r.batch not in allowed:
            frappe.throw("Row %s: batch %s was not received on this receipt row." % (r.idx, r.batch))
        if r.batch in seen:
            frappe.throw("Row %s: batch %s is listed twice." % (r.idx, r.batch))
        seen.append(r.batch)
        b = frappe.db.get_value("Batch", r.batch, ["apparel_roll_no", "apparel_dye_lot", "apparel_ticket_length"], as_dict=True)
        r.roll_no = b.apparel_roll_no
        r.dye_lot = b.apparel_dye_lot
        r.ticket_length = flt(b.apparel_ticket_length)
        if not flt(r.actual_length):
            r.actual_length = r.ticket_length
        r.length_variance = flt(r.actual_length) - flt(r.ticket_length)
    doc.total_rolls = len(doc.rolls)
    doc.total_received_m = sum([flt(r.ticket_length) for r in doc.rolls])
    roll_nos = [r.roll_no for r in doc.rolls]
    for d in doc.defects:
        if d.roll_no not in roll_nos:
            frappe.throw("Defect row %s: roll %s is not in the roll list." % (d.idx, d.roll_no))

    # ---- defects -> points
    always = {}
    for c in frappe.get_all("Fabric Defect Code", fields=["name", "always_four_points"]):
        always[c.name] = cint(c.always_four_points)
    for d in doc.defects:
        if flt(d.defect_length_in) <= 0 and not always.get(d.defect_code):
            frappe.throw("Defect row %s: enter the defect length in inches." % d.idx)
        d.points = defect_points(d.defect_length_in, always.get(d.defect_code))

    # ---- rolls
    threshold = flt(doc.points_threshold)
    square = doc.points_basis == "Per 100 Square Yards"
    widths = []
    for r in doc.rolls:
        if not cint(r.inspected):
            r.total_points = 0
            r.points_per_100 = 0
            r.roll_result = r.roll_result if r.roll_result == "Hold" else None
            continue
        if not flt(r.inspected_length_m):
            r.inspected_length_m = flt(r.actual_length)
        if flt(r.inspected_length_m) > flt(r.actual_length) + 0.005:
            frappe.throw("Row %s: inspected length %s m is more than the roll (%s m)." % (r.idx, r.inspected_length_m, r.actual_length))
        mine = [[d.yard_position, d.points] for d in doc.defects if d.roll_no == r.roll_no]
        r.total_points = roll_points(mine)
        width = [flt(w) for w in (r.width_start_cm, r.width_middle_cm, r.width_end_cm) if flt(w)]
        avg_w = sum(width) / len(width) if width else 0
        if avg_w:
            widths.append(avg_w)
        r.width_required_cm = flt(r.width_required_cm) or flt(doc.required_width_cm)
        r.width_ok = 1 if (not width or min(width) + 0.5 >= flt(r.width_required_cm)) else 0
        if square:
            r.points_per_100 = flt(points_per_100_square(r.total_points, r.inspected_length_m, avg_w or r.width_required_cm), 2)
        else:
            r.points_per_100 = flt(points_per_100_linear(r.total_points, r.inspected_length_m), 2)
        auto = "Reject" if r.points_per_100 > threshold else "Accept"
        if r.roll_result == "Hold":
            pass
        elif auto == "Reject" or not r.roll_result:
            r.roll_result = auto      # a roll over the threshold cannot be accepted
    doc.avg_actual_width_cm = flt(sum(widths) / len(widths), 1) if widths else 0

    # ---- shrinkage
    limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
    over = []
    for r in doc.shrinkage:
        for d in ("warp", "weft", "bias"):
            before = flt(r.get("before_" + d))
            after = flt(r.get("after_" + d))
            r.set("shrink_" + d + "_pct", round((after - before) / before * 100, 2) if before else 0)
        if limit and (abs(flt(r.get("shrink_warp_pct"))) > limit or abs(flt(r.get("shrink_weft_pct"))) > limit):
            over.append(r.roll_no or r.idx)
    if over:
        frappe.msgprint("Shrinkage above %s%% on: %s" % (limit, ", ".join([str(x) for x in over])), indicator="orange")

    # ---- lot
    bands = frappe.get_all("Fabric Sampling Band", filters={"parent": "Apparel Settings", "parenttype": "Apparel Settings"}, fields=["from_length_m", "to_length_m", "inspect_pct"])
    doc.sampling_pct = sampling_pct(bands, doc.total_received_m)
    doc.required_inspect_m = flt(doc.total_received_m * doc.sampling_pct / 100, 2)
    done = [r for r in doc.rolls if cint(r.inspected)]
    doc.inspected_rolls = len(done)
    doc.inspected_m = flt(sum([flt(r.inspected_length_m) for r in done]), 2)
    doc.inspected_pct = flt(doc.inspected_m * 100 / doc.total_received_m, 2) if flt(doc.total_received_m) else 0
    pts = sum([cint(r.total_points) for r in done])
    doc.avg_points = flt(points_per_100_linear(pts, doc.inspected_m), 2)
    w = flt(doc.avg_actual_width_cm) or flt(doc.required_width_cm)
    doc.avg_points_sq = flt(points_per_100_square(pts, doc.inspected_m, w), 2)
    doc.rejected_rolls = len([r for r in done if r.roll_result == "Reject"])
    bands_found = []
    for r in doc.rolls:
        sb = (r.shade_band or "").strip()
        if sb and sb not in bands_found:
            bands_found.append(sb)
    doc.shade_bands_found = ", ".join(sorted(bands_found))
    basis_value = doc.avg_points_sq if doc.points_basis == "Per 100 Square Yards" else doc.avg_points
    mr = frappe.db.get_single_value("Apparel Settings", "max_rejected_rolls_pct")
    doc.lot_result = lot_decision(basis_value, doc.points_threshold, doc.rejected_rolls, doc.inspected_rolls, doc.total_rolls, flt(mr if mr is not None else 10), cint(doc.on_hold))
    accepted = 0.0
    hold = 0.0
    rejected = 0.0
    for r in doc.rolls:
        disp = roll_disposition(cint(r.inspected), r.roll_result, doc.lot_result)
        if disp in ("Accepted", "Accepted by Lot"):
            accepted = accepted + flt(r.ticket_length)
        elif disp == "Rejected":
            rejected = rejected + flt(r.ticket_length)
        else:
            hold = hold + flt(r.ticket_length)
    doc.accepted_m = flt(accepted, 2)
    doc.rejected_m = flt(rejected, 2)
    doc.hold_m = flt(hold, 2)


run(doc)
