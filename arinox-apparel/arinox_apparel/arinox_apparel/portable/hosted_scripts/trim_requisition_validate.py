# Trim Requisition, Before Save: lines checked against the order, bulk-trim approval hold, dates, allowance, quantity by basis (per garment, size, colour, carton, length, fixed), stock claims.
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
    ceil = frappe.utils.ceil
    if not doc.ordered_by:
        doc.ordered_by = frappe.session.user
    if not doc.items:
        frappe.throw("Add at least one trim line.")
    if cint(doc.revision_no) > 0 and not (doc.revision_reason or "").strip():
        frappe.throw("Enter the reason for this revision.")
    seen = {}
    for r in doc.items:
        if not (r.trim_item or r.description):
            continue
        k = tr_row_key(r)
        if k in seen:
            frappe.throw("Row %s repeats row %s: same order, style, colour, size, category and trim." % (r.idx, seen[k]))
        seen[k] = r.idx

    flags = []
    hold_mode = frappe.db.get_single_value("Apparel Settings", "hold_po_until_approval") or "Warn"
    due_days = cint(frappe.db.get_single_value("Apparel Settings", "trim_due_days_before_pcd") or 7)
    for r in doc.items:
        so = frappe.db.get_value("Sales Order", r.sales_order, ["docstatus", "customer", "company"], as_dict=True)
        if not so:
            frappe.throw("Row %s: Sales Order %s does not exist." % (r.idx, r.sales_order))
        if so.docstatus != 1:
            frappe.throw("Row %s: Sales Order %s is not submitted." % (r.idx, r.sales_order))
        if so.customer != doc.customer or so.company != doc.company:
            frappe.throw("Row %s: Sales Order %s belongs to another buyer or company." % (r.idx, r.sales_order))
        if frappe.db.get_value("Item", r.style_item, "variant_of"):
            frappe.throw("Row %s: pick the style (template item), not a variant." % r.idx)
        r.style_no = r.style_no or frappe.db.get_value("Tech Pack", {"style_item": r.style_item}, "style_no") or r.style_item
        if (r.trim_colour or "").strip().upper() in ("DTM", "DTM GROUND COLOR", "DYED TO MATCH") and r.colour:
            r.trim_colour = r.colour       # DTM resolves to the garment colour
        if not cint(r.garment_qty) and r.calc_basis != "Fixed Qty":
            total = 0
            for it in frappe.get_all("Sales Order Item", filters={"parent": r.sales_order}, fields=["item_code", "qty", "apparel_colour", "apparel_size"]):
                if style_of(it.item_code) != r.style_item:
                    continue
                if r.colour and (it.apparel_colour or "").strip().upper() != r.colour.strip().upper():
                    continue
                if r.size and (it.apparel_size or "").strip().upper() != r.size.strip().upper():
                    continue
                total = total + cint(it.qty)
            r.garment_qty = total
        ap = approval_info(r.sales_order, r.style_item, "Bulk Trim", None, doc.customer)
        r.approval_status = ap[0]
        r.hold = 1 if (not ap[1] and hold_mode != "Off" and not cint(r.customer_provided)) else 0
        if r.hold:
            flags.append("Row %s: bulk trim approval is %s; the purchase order will be held." % (r.idx, ap[0]))
        pcd = get_style_dates(r.sales_order, r.style_item, r.colour or None)[0]
        if pcd and not r.required_by:
            r.required_by = add_days(pcd, -due_days)
        if pcd and r.required_by and getdate(r.required_by) > add_days(getdate(pcd), -due_days):
            flags.append("Row %s: required by %s is later than PCD %s minus %s days." % (r.idx, r.required_by, pcd, due_days))
        if not pcd:
            flags.append("Row %s: no planned cut date yet; set the Factory Allocation." % r.idx)

        # ---- quantity by basis
        basis = r.calc_basis or "Per Garment"
        rule = get_allowance(material_type_for(r.trim_category), r.trim_category, doc.customer, None)
        default_pct = flt(rule["allowance_pct"])
        if r.allowance_pct is None:
            r.allowance_pct = default_pct
        elif flt(r.allowance_pct) != default_pct and not (r.allowance_reason or "").strip():
            frappe.throw("Row %s: the allowance %s%% differs from the rule (%s%%). Enter the reason." % (r.idx, r.allowance_pct, default_pct))
        if not flt(r.pack_size):
            r.pack_size = flt(rule["pack_size"])
        a = 1 + flt(r.allowance_pct) / 100
        gq = cint(r.garment_qty)
        qpg = flt(r.qty_per_garment)
        spare = flt(r.spare_per_garment)
        if basis == "Per Garment" or basis == "Per Size" or basis == "Per Colour":
            if basis == "Per Size" and not (r.size or "").strip():
                frappe.throw("Row %s: a per-size line needs the size." % r.idx)
            if basis == "Per Colour" and not (r.colour or "").strip():
                frappe.throw("Row %s: a per-colour line needs the colour." % r.idx)
            gross = gq * (qpg + spare) * a
        elif basis == "Per Carton":
            if cint(r.pcs_per_carton) <= 0:
                frappe.throw("Row %s: enter the pieces per carton." % r.idx)
            gross = ceil(gq / cint(r.pcs_per_carton)) * qpg * a
        elif basis == "By Length":
            if flt(r.consumption) <= 0 or not r.consumption_uom:
                frappe.throw("Row %s: enter the length per garment and its unit." % r.idx)
            gross = gq * flt(r.consumption) * a
        else:
            gross = qpg
        if qpg <= 0 and basis != "By Length":
            frappe.throw("Row %s: enter the quantity per garment (or carton)." % r.idx)
        r.gross_qty = flt(gross, 4)
        if flt(r.stock_used) > 0:
            if not r.stock_warehouse or not r.trim_item:
                frappe.throw("Row %s: choose the trim item and warehouse to use leftover stock." % r.idx)
            free = free_stock(r.trim_item, r.stock_warehouse, "Trim Requisition", "Trim Requisition Item", doc.name)
            if flt(r.stock_used) > free + 0.0001:
                frappe.throw("Row %s: only %s of %s is free in %s (the rest is claimed by other requisitions)." % (r.idx, flt(free, 2), r.trim_item, r.stock_warehouse))
        r.net_qty = flt(max(flt(r.gross_qty) - flt(r.stock_used), 0), 4)
        base_uom = r.consumption_uom if basis == "By Length" else (frappe.db.get_value("Item", r.trim_item, "stock_uom") if r.trim_item else None) or "Nos"
        r.order_uom = r.order_uom or base_uom
        qty = r.net_qty
        if r.order_uom != base_uom:
            if uom_kind(r.order_uom) and uom_kind(base_uom) in ("m", "yd"):
                qty = from_metres(to_metres(qty, base_uom, None, None), r.order_uom, None, None)
            else:
                frappe.throw("Row %s: cannot convert %s to %s. Use the same unit or a length unit." % (r.idx, base_uom, r.order_uom))
        if basis == "By Length":
            r.order_qty = round_up_to_pack(flt(qty, 2), r.pack_size) if r.net_qty > 0 else 0
        else:
            r.order_qty = round_up_to_pack(ceil(round(qty, 4)), r.pack_size) if r.net_qty > 0 else 0

    if doc.previous_tr:
        chain = revision_chain("Trim Requisition", "previous_tr", doc.previous_tr)
        for r in doc.items:
            before = requested_so_far("TR", chain, tr_row_key(r))
            if before and flt(r.net_qty) + 0.0005 < before:
                flags.append("Row %s: reduced from %s to %s. Reduce the order with the supplier." % (r.idx, flt(before, 2), flt(r.net_qty, 2)))
    doc.red_flags = "\n".join(uniq(flags))
    doc.status = requisition_status(doc)


run(doc)
