# Fabric Requisition, Before Save: lines checked against the order, approvals (lab dip hold), dates, allowance, stock claims, costing; totals are always computed here.
def run(doc):
    # include: lib_samples.py
    # include: lib_allocation.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_requisition.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    add_days = frappe.utils.add_days
    if not doc.ordered_by:
        doc.ordered_by = frappe.session.user
    if not doc.terms:
        doc.terms = default_terms()
    if not doc.items:
        frappe.throw("Add at least one fabric line.")
    if cint(doc.revision_no) > 0 and not (doc.revision_reason or "").strip():
        frappe.throw("Enter the reason for this revision.")
    seen = {}
    for r in doc.items:
        if not r.fabric_item:
            continue
        k = fr_row_key(r)
        if k in seen:
            frappe.throw("Row %s repeats row %s: same order, style, colour, role and fabric." % (r.idx, seen[k]))
        seen[k] = r.idx

    flags = []
    hold_mode = frappe.db.get_single_value("Apparel Settings", "hold_po_until_approval") or "Warn"
    due_days = cint(frappe.db.get_single_value("Apparel Settings", "fabric_due_days_before_pcd") or 10)
    for r in doc.items:
        # ---- fill the row
        so = frappe.db.get_value("Sales Order", r.sales_order, ["docstatus", "customer", "company", "apparel_sales_contract"], as_dict=True)
        if not so:
            frappe.throw("Row %s: Sales Order %s does not exist." % (r.idx, r.sales_order))
        if so.docstatus != 1:
            frappe.throw("Row %s: Sales Order %s is not submitted." % (r.idx, r.sales_order))
        if so.customer != doc.customer or so.company != doc.company:
            frappe.throw("Row %s: Sales Order %s belongs to another buyer or company." % (r.idx, r.sales_order))
        r.sales_contract = so.apparel_sales_contract
        if frappe.db.get_value("Item", r.style_item, "variant_of"):
            frappe.throw("Row %s: pick the style (template item), not a variant." % r.idx)
        r.style_no = r.style_no or frappe.db.get_value("Tech Pack", {"style_item": r.style_item}, "style_no") or r.style_item
        order_qty = order_colour_qty(r.sales_order, r.style_item, r.colour)
        if not cint(r.garment_qty):
            r.garment_qty = order_qty
        elif order_qty and cint(r.garment_qty) != order_qty:
            flags.append("Row %s: garment qty %s differs from the Sales Order (%s)." % (r.idx, r.garment_qty, order_qty))
        if flt(r.consumption) <= 0:
            frappe.throw("Row %s: consumption must be more than zero." % r.idx)
        if flt(r.cuttable_width_cm) <= 0:
            frappe.throw("Row %s: enter the cuttable width." % r.idx)
        if not r.consumption_source:
            frappe.throw("Row %s: say where the consumption comes from (marker, cost sheet, tech pack or manual)." % r.idx)
        if uom_kind(r.consumption_uom) == "kg" and not flt(r.gsm):
            frappe.throw("Row %s: a kg line needs the GSM." % r.idx)
        if r.fabric_item and not flt(r.gsm):
            r.gsm = flt(frappe.db.get_value("Item", r.fabric_item, "apparel_fabric_gsm"))
        ap = approval_info(r.sales_order, r.style_item, "Lab Dip", r.colour, doc.customer)
        r.lab_dip_status = ap[0]
        r.hold = 1 if (not ap[1] and hold_mode != "Off") else 0
        if not ap[1]:
            flags.append("Row %s: lab dip is %s; the purchase order will be held." % (r.idx, ap[0]))
        cw = cw_in(r.fabric_description)
        if cw is not None and abs(flt(cw) - flt(r.cuttable_width_cm)) > 0.5:
            flags.append("Row %s: the description says CW %s but the cuttable width is %s." % (r.idx, cw, r.cuttable_width_cm))
        pcd = get_style_dates(r.sales_order, r.style_item, r.colour)[0]
        if pcd and not r.required_by:
            r.required_by = add_days(pcd, -due_days)
        if pcd and r.required_by and getdate(r.required_by) > add_days(getdate(pcd), -due_days):
            flags.append("Row %s: required by %s is later than PCD %s minus %s days." % (r.idx, r.required_by, pcd, due_days))
        if not pcd:
            flags.append("Row %s: no planned cut date yet; set the Factory Allocation." % r.idx)
        if not r.supplier:
            flags.append("Row %s: no supplier chosen." % r.idx)

        # ---- compute the row
        cons_m = to_metres(r.consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
        mtype = "Lining" if r.material_role == "Lining" else ("Contrast Fabric" if r.material_role == "Contrast" else "Fabric")
        rule = get_allowance(mtype, None, doc.customer, frappe.db.get_value("Item", r.fabric_item, "item_group") if r.fabric_item else None)
        default_pct = flt(rule["allowance_pct"])
        if r.allowance_pct is None:
            r.allowance_pct = default_pct
        elif flt(r.allowance_pct) != default_pct and not (r.allowance_reason or "").strip():
            frappe.throw("Row %s: the allowance %s%% differs from the rule (%s%%). Enter the reason." % (r.idx, r.allowance_pct, default_pct))
        r.pack_size = flt(rule["pack_size"])
        r.gross_qty = flt(cint(r.garment_qty) * cons_m * (1 + flt(r.allowance_pct) / 100), 4)
        if flt(r.stock_used) > 0:
            if not r.stock_warehouse or not r.fabric_item:
                frappe.throw("Row %s: choose the fabric item and warehouse to use leftover stock." % r.idx)
            free = free_stock(r.fabric_item, r.stock_warehouse, "Fabric Requisition", "Fabric Requisition Item", doc.name)
            if flt(r.stock_used) > free + 0.0001:
                frappe.throw("Row %s: only %s m of %s is free in %s (the rest is claimed by other requisitions)." % (r.idx, flt(free, 2), r.fabric_item, r.stock_warehouse))
        r.net_qty = flt(max(flt(r.gross_qty) - flt(r.stock_used), 0), 4)
        r.order_uom = r.order_uom or (frappe.db.get_value("Item", r.fabric_item, "stock_uom") if r.fabric_item else None) or "Meter"
        r.order_qty = round_up_to_pack(from_metres(r.net_qty, r.order_uom, r.gsm, r.cuttable_width_cm), r.pack_size) if r.net_qty > 0 else 0
        if r.net_qty > 0 and flt(rule["min_order_qty"]) and flt(r.order_qty) < flt(rule["min_order_qty"]):
            r.order_qty = flt(rule["min_order_qty"])
            flags.append("Row %s: raised to the minimum order of %s." % (r.idx, rule["min_order_qty"]))
        if r.costed_consumption and r.consumption:
            costed_m = to_metres(r.costed_consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
            now_m = to_metres(r.consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
            if costed_m and abs(now_m - costed_m) / costed_m > 0.05:
                flags.append("Row %s: consumption %s is more than 5%% %s than costed (%s)." % (r.idx, r.consumption, "less" if now_m < costed_m else "more", r.costed_consumption))

    # ---- revision: quantities cut back or lines removed against what was already requested
    if doc.previous_fr:
        chain = revision_chain("Fabric Requisition", "previous_fr", doc.previous_fr)
        mine = {}
        for r in doc.items:
            if r.fabric_item:
                mine[fr_row_key(r)] = r
        for k in mine:
            r = mine[k]
            before = requested_so_far("FR", chain, k)
            if before and flt(r.net_qty) + 0.0005 < before:
                flags.append("Row %s: reduced from %s m to %s m. Reduce the order with the supplier." % (r.idx, flt(before, 2), flt(r.net_qty, 2)))
        prev = frappe.db.sql("select i.apparel_requisition_item, sum(i.stock_qty) from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent "
                             "where i.apparel_requisition_type = 'FR' and i.apparel_requisition in %s and m.docstatus < 2 group by i.apparel_requisition_item", (tuple(chain),))
        for p in prev:
            if p[0] not in mine and flt(p[1]) > 0:
                flags.append("Line removed (%s): %s m was already requested. Cancel or reduce the order with the supplier." % (p[0].replace("|", " / "), flt(p[1], 2)))

    # ---- summary per fabric and supplier
    doc.set("summary", [])
    groups = {}
    order = []
    for r in doc.items:
        if flt(r.net_qty) <= 0:
            continue
        gk = "k|%s|%s" % (r.fabric_item or r.fabric_description, r.supplier or "")
        if gk not in groups:
            groups[gk] = {"fabric_item": r.fabric_item, "fabric_description": r.fabric_description, "supplier": r.supplier, "total": 0, "uom": r.order_uom, "date": None, "n": 0}
            order.append(gk)
        g = groups[gk]
        g["total"] = g["total"] + flt(r.order_qty)
        g["n"] = g["n"] + 1
        if r.required_by and (not g["date"] or getdate(r.required_by) < getdate(g["date"])):
            g["date"] = r.required_by
    for gk in order:
        g = groups[gk]
        doc.append("summary", {"fabric_item": g["fabric_item"], "fabric_description": g["fabric_description"], "supplier": g["supplier"], "total_order_qty": flt(g["total"], 2),
                               "uom": g["uom"], "earliest_required_by": g["date"], "line_count": g["n"]})
    doc.total_order_m = sum([flt(r.net_qty) for r in doc.items])
    doc.red_flags = "\n".join(uniq(flags))
    doc.status = requisition_status(doc)


run(doc)
