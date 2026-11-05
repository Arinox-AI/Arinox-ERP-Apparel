# Production Card, Before Save (validate): check the order, fill the header, compute the lines, fabrics and route, set pilot rules.
def run(doc):
    # include: lib_maths.py
    # include: lib_orders.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint

    so = frappe.db.get_value("Sales Order", doc.sales_order, ["docstatus", "customer", "company"], as_dict=True)
    if not so or so.docstatus != 1:
        frappe.throw("Sales Order %s must be submitted." % doc.sales_order)
    if so.customer != doc.customer:
        frappe.throw("Sales Order %s belongs to %s, not %s." % (doc.sales_order, so.customer, doc.customer))
    if so.company != doc.company:
        frappe.throw("Sales Order %s belongs to company %s." % (doc.sales_order, so.company))

    # ---- header
    item = frappe.db.get_value("Item", doc.style_item, ["item_name"], as_dict=True)
    if not item:
        frappe.throw("Style item %s not found." % doc.style_item)
    tp = frappe.db.get_value("Tech Pack", {"style_item": doc.style_item}, ["style_no", "style_name", "season"], as_dict=True)
    doc.style_name = doc.style_name or (tp.style_name if tp else None) or item.item_name
    doc.style_no = doc.style_no or (tp.style_no if tp else None) or doc.style_item
    contract = frappe.db.get_value("Sales Order", doc.sales_order, "apparel_sales_contract")
    doc.sales_contract = contract
    doc.season = doc.season or (frappe.db.get_value("Sales Contract", contract, "season") if contract else None) or (tp.season if tp else None)
    matrix = order_matrix(doc.sales_order, doc.style_item)
    cells = matrix[0]
    doc.buyer_pos = "\n".join(matrix[2])
    doc.ex_factory_date = doc.ex_factory_date or matrix[1]
    doc.pcd = doc.pcd or get_pcd(doc.sales_order, doc.style_item)
    if doc.default_extra_cut_pct is None or doc.default_extra_cut_pct == "":
        doc.default_extra_cut_pct = flt(setting("default_extra_cut_pct", 5))
    if doc.trim_allowance_pct is None or doc.trim_allowance_pct == "":
        doc.trim_allowance_pct = flt(setting("trim_allowance_pct", 2))
    doc.bundle_size = cint(doc.bundle_size) or cint(setting("bundle_size", 20))
    if not doc.factory or not doc.line:
        fa = frappe.db.get_value("Factory Allocation", {"sales_order": doc.sales_order}, "name")
        if fa:
            rows = frappe.get_all("Factory Allocation Line", {"parent": fa, "style_item": doc.style_item}, ["factory", "line"], limit=1)
            if rows:
                doc.factory = doc.factory or rows[0].factory
                doc.line = doc.line or rows[0].line
    doc.made_by = doc.made_by or frappe.session.user
    if cint(doc.revision_no) > 0 and not (doc.revision_reason or "").strip():
        frappe.throw("Enter the reason for this revision.")

    # ---- one live card per order x style x ex-factory date (a revision chain shares the key)
    others = frappe.get_all("Production Card", {"sales_order": doc.sales_order, "style_item": doc.style_item, "ex_factory_date": doc.ex_factory_date,
                                                 "docstatus": 1, "status": ["not in", ["Superseded", "Cancelled"]], "name": ["!=", doc.name or ""]}, pluck="name")
    others = [n for n in others if n != doc.previous_card]
    if others:
        frappe.throw("Production card %s already covers this order, style and ex-factory date. Use Revise on it." % others[0])

    # ---- lines
    flags = []
    if not cells:
        frappe.throw("Style %s has no lines on Sales Order %s." % (doc.style_item, doc.sales_order))
    seen = []
    max_extra = flt(setting("max_extra_cut_pct", 8))
    is_manager = has_any_role(["Apparel Production Manager", "Apparel Merchandising Manager", "System Manager"])
    for r in doc.lines:
        key = ((r.colour or "").strip(), (r.size or "").strip())
        if key in seen:
            frappe.throw("Row %s: %s %s appears twice." % (r.idx, key[0], key[1]))
        seen.append(key)
        cell = cells.get(key)
        if not cell:
            frappe.throw("Row %s: %s %s is not on Sales Order %s. Check the colour and size spelling." % (r.idx, key[0], key[1], doc.sales_order))
        r.colour = key[0]
        r.size = key[1]
        r.order_qty = cell["order_qty"]
        r.max_qty = max_ship_qty(cell["order_qty"], cell["tolerance_pct"])
        if r.extra_cut_pct is None or r.extra_cut_pct == "":
            r.extra_cut_pct = doc.default_extra_cut_pct
        if flt(r.extra_cut_pct) < 0:
            frappe.throw("Row %s: extra cut cannot be negative." % r.idx)
        if flt(r.extra_cut_pct) > max_extra:
            if not is_manager:
                frappe.throw("Row %s: extra cut %s%% is above the limit of %s%%. A production manager can allow it." % (r.idx, r.extra_cut_pct, max_extra))
            flags.append("Extra cut above %s%% on %s %s." % (max_extra, r.colour, r.size))
        r.planned_cut_qty = planned_cut(r.order_qty, r.extra_cut_pct)
    for key in cells:
        if key not in seen:
            flags.append("%s %s is on the Sales Order but not on this card." % (key[0], key[1]))
    source = doc.name if (doc.name and not doc.is_new()) else doc.previous_card
    if source:
        cut_over = []
        for r in doc.lines:
            done = frappe.db.sql("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and colour=%s and size=%s and stage='CUT' and purpose != 'Re-cut'",
                                 (source, r.colour, r.size))[0][0]
            if done > r.planned_cut_qty:
                cut_over.append("%s %s: cut %s > plan %s" % (r.colour, r.size, int(done), r.planned_cut_qty))
        if cut_over:
            flags.append("Cut exceeds the revised plan: " + "; ".join(cut_over))

    # ---- fabrics
    def colour_cut(colour):
        total = 0
        for l in doc.lines:
            if norm(l.colour) == norm(colour):
                total = total + cint(l.planned_cut_qty)
        return total

    for r in doc.fabrics:
        if flt(r.consumption) <= 0:
            frappe.throw("Fabric row %s: consumption must be above zero." % r.idx)
        on_card = False
        for l in doc.lines:
            if norm(l.colour) == norm(r.colour):
                on_card = True
        if not on_card:
            frappe.throw("Fabric row %s: colour %s is not on the size breakup." % (r.idx, r.colour))
        gsm = None
        width = None
        if r.fabric_item:
            vals = frappe.db.get_value("Item", r.fabric_item, ["apparel_fabric_gsm", "apparel_fabric_width_cm"])
            if vals:
                gsm = vals[0]
                width = vals[1]
        per_garment_m = to_metres(flt(r.consumption), r.consumption_uom or "Meter", gsm, width)
        r.required_m = round(colour_cut(r.colour) * per_garment_m, 3)
        if r.fabric_requisition_item:
            fr = frappe.db.get_value("Fabric Requisition Item", r.fabric_requisition_item, ["net_qty", "accepted_qty"], as_dict=True)
            if fr:
                r.fr_net_m = flt(fr.net_qty)
                r.accepted_m = flt(fr.accepted_qty)
                if r.fr_net_m and r.required_m > r.fr_net_m * 1.01:
                    flags.append("%s %s: card needs %s m but the requisition covers %s m." % (r.colour, r.fabric_item or "", round(r.required_m, 1), round(r.fr_net_m, 1)))
        if r.fabric_item and doc.name and not doc.is_new():
            moved = frappe.db.sql("select ifnull(sum(d.qty), 0) from `tabStock Entry Detail` d join `tabStock Entry` s on s.name = d.parent "
                                  "where s.docstatus = 1 and s.apparel_production_card = %s and s.apparel_issue_kind = 'Fabric Issue' and d.item_code = %s",
                                  (doc.name, r.fabric_item))
            r.issued_m = flt(moved[0][0])
        r.shortage_m = round(max(flt(r.required_m) - flt(r.accepted_m), 0), 3) if r.accepted_m else flt(r.required_m)
        if r.shortage_m > 0 and doc.docstatus == 1:
            flags.append("%s: %s m of fabric still to be accepted." % (r.colour, round(r.shortage_m, 1)))

    # ---- route
    route_seen = []
    for p in doc.processes:
        key = (p.subcontract_process, (p.colour or "").strip().upper())
        if key in route_seen:
            frappe.throw("Process %s appears twice on the route." % p.subcontract_process)
        route_seen.append(key)
        info = frappe.db.get_value("Subcontract Process", p.subcontract_process, ["default_position", "item_state"], as_dict=True)
        if not p.item_state and info:
            p.item_state = info.item_state
        if p.position == "Before Sewing" and p.item_state == "Garments":
            frappe.throw("%s: garments cannot go out before sewing; choose Cut Panels or After Sewing." % p.subcontract_process)
        if p.position == "After Sewing" and p.item_state == "Cut Panels":
            frappe.throw("%s: cut panels cannot be sent after sewing; choose Garments or Before Sewing." % p.subcontract_process)

    # ---- pilot run
    total = 0
    for r in doc.lines:
        total = total + cint(r.order_qty)
    by_qty = total >= cint(setting("pilot_min_order_qty", 1000))
    rule = frappe.db.get_value("Apparel Sample Rule", {"parent": "Apparel Settings", "sample_type": "Pilot Run"}, "gate")
    doc.pilot_required = 1 if (by_qty or rule == "Required") else 0
    if cint(doc.pilot_waiver):
        if not has_any_role(["Apparel Production Manager", "System Manager"]) and doc.has_value_changed("pilot_waiver"):
            frappe.throw("Only a production manager can waive the pilot run.")
        if not (doc.pilot_waiver_reason or "").strip():
            frappe.throw("Enter the reason for waiving the pilot run.")
    unique = []
    for f in flags:
        if f not in unique:
            unique.append(f)
    doc.red_flags = "\n".join(unique)


run(doc)
