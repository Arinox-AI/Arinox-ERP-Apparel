# Lay Report, Before Save: card and colour, the cut plan's marker and ratios, the manager override, the rolls (accepted, in Cutting WIP, one shade band, width and shrinkage spread),
# sizes, rejected panels, purpose (re-cut), pairing of lining with shell, totals and consumption.
def run(doc):
    # include: lib_cutting.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    MANAGER_ROLES = ("Apparel Production Manager", "Apparel Merchandising Manager", "System Manager")

    # ---- card
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status", "style_item", "sales_order", "company"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    card_sizes = frappe.get_all("Production Card Line", filters={"parent": doc.production_card, "colour": doc.colour}, pluck="size")
    if not card_sizes:
        frappe.throw("Colour %s is not on production card %s." % (doc.colour, doc.production_card))
    if not frappe.db.exists("Production Card Fabric", {"parent": doc.production_card, "colour": doc.colour, "fabric_item": doc.fabric_item}):
        frappe.throw("%s is not a fabric of colour %s on production card %s." % (doc.fabric_item, doc.colour, doc.production_card))

    # ---- the cut plan
    plan_lay = None
    if not doc.cut_plan:
        if doc.purpose == "Bulk" and doc.component == "Shell":
            frappe.msgprint("No cut plan chosen. Ratios and the marker are taken from what you enter here.", indicator="orange")
    else:
        plan = frappe.get_doc("Cut Plan", doc.cut_plan)
        if plan.production_card != doc.production_card or (plan.colour or "").strip().upper() != (doc.colour or "").strip().upper():
            frappe.throw("Cut plan %s is for another production card or colour." % plan.name)
        if doc.purpose == "Bulk" and plan.status != "Released":
            frappe.throw("Cut plan %s is %s. Release it before bulk cutting." % (plan.name, plan.status))
        for l in plan.lays:
            if l.lay_no == doc.lay_no:
                plan_lay = l
        if not plan_lay:
            frappe.throw("Lay %s is not in cut plan %s." % (doc.lay_no, plan.name))
        ratios = {}
        for r in plan.ratios:
            if r.lay_no == doc.lay_no:
                ratios[r.size] = cint(r.ratio)
        if not doc.marker_length_m:
            doc.marker_length_m = plan_lay.marker_length_m
        if not doc.marker_width_cm:
            doc.marker_width_cm = plan_lay.marker_width_cm
        doc.marker_ref = doc.marker_ref or plan_lay.marker_ref
        doc.marker_efficiency_pct = doc.marker_efficiency_pct or plan_lay.marker_efficiency_pct
        if not doc.sizes:
            for s in ratios:
                doc.append("sizes", {"size": s, "ratio": ratios[s]})
        for s in doc.sizes:
            if s.size not in ratios:
                frappe.throw("Size %s is not in the ratios of lay %s of the cut plan." % (s.size, doc.lay_no))
            if cint(s.ratio) != ratios[s.size]:
                frappe.throw("Size %s: the ratio is %s in the cut plan, not %s." % (s.size, ratios[s.size], s.ratio))

    # ---- the gate override
    if cint(doc.gate_override) and (doc.is_new() or doc.has_value_changed("gate_override")):
        if not [r for r in roles if r in MANAGER_ROLES]:
            frappe.throw("Only a production manager can override the bulk gate.")
        if not (doc.gate_override_reason or "").strip():
            frappe.throw("Enter the reason for the override.")

    # ---- rolls
    if not doc.rolls:
        frappe.throw("Add the rolls laid.")
    wh = setting("cutting_wip_warehouse")
    spread_w = flt(setting("max_width_spread_cm") or 1)
    spread_s = flt(setting("max_shrinkage_spread_pct") or 3)
    washed = cint(frappe.db.get_value("Production Card", doc.production_card, "is_washed"))
    remnant_min = flt(setting("remnant_min_m") or 5)
    seen = []
    shades = []
    widths = []
    warp = []
    weft = []
    for r in doc.rolls:
        if r.batch in seen:
            frappe.throw("Roll %s appears twice in this lay." % r.batch)
        seen.append(r.batch)
        info = roll_info(r.batch)
        if info.item != doc.fabric_item:
            frappe.throw("Row %s: roll %s is %s, not %s." % (r.idx, info.apparel_roll_no or r.batch, info.item, doc.fabric_item))
        if info.apparel_inspection_status not in OK_STATUS:
            frappe.throw("Row %s: roll %s is %s. Only accepted rolls can be cut." % (r.idx, info.apparel_roll_no or r.batch, info.apparel_inspection_status or "not inspected"))
        r.roll_no = info.apparel_roll_no
        r.dye_lot = info.apparel_dye_lot
        r.shade_band = info.apparel_shade_band or ""
        r.width_cm = flt(info.apparel_width_cm)
        if (r.shade_band or "") not in shades:
            shades.append(r.shade_band or "")
        if r.width_cm:
            widths.append(r.width_cm)
        warp.append(flt(info.apparel_shrinkage_warp_pct))
        weft.append(flt(info.apparel_shrinkage_weft_pct))
        if cint(r.plies) <= 0:
            frappe.throw("Row %s: enter the number of plies." % r.idx)
        r.length_laid_m = round(cint(r.plies) * flt(doc.marker_length_m), 3)
        # metres of the roll still free: what is in Cutting WIP less what submitted lays already used
        stock = roll_available(r.batch, wh, doc.fabric_item)
        used_before = frappe.db.sql("select ifnull(sum(r.length_laid_m + ifnull(r.end_bit_m, 0) + ifnull(r.damage_m, 0)), 0) from `tabLay Roll` r join `tabLay Report` l on l.name = r.parent "
                                    "where r.batch = %s and l.docstatus = 1 and l.name != %s", (r.batch, doc.name or ""))[0][0]
        avail = round(max(stock - flt(used_before), 0), 3) if wh else 0
        r.roll_length_m = avail
        used = r.length_laid_m + flt(r.end_bit_m) + flt(r.damage_m)
        if wh and used > avail + 1e-6:
            frappe.throw("Row %s: roll %s has %s m left in %s, but this lay uses %s m. Issue the roll to cutting first." % (r.idx, info.apparel_roll_no or r.batch, round(avail, 3), wh, round(used, 3)))
        balance = round(max(avail - used, 0), 3) if wh else 0
        if 0 < balance < remnant_min:      # too short to keep: it becomes end bit
            r.end_bit_m = round(flt(r.end_bit_m) + balance, 3)
            balance = 0
        r.balance_returned_m = balance
        if flt(doc.marker_width_cm) and r.width_cm and r.width_cm < flt(doc.marker_width_cm):
            frappe.throw("Row %s: roll %s is %s cm wide, narrower than the %s cm marker." % (r.idx, info.apparel_roll_no or r.batch, r.width_cm, doc.marker_width_cm))
    if len(shades) > 1:
        frappe.throw("One lay holds one shade band. This lay mixes: %s. Cut each shade band in its own lay." % ", ".join(sorted([s or "(none)" for s in shades])))
    doc.shade_band = shades[0] if shades else ""
    if plan_lay and (plan_lay.shade_band or "").strip() and doc.shade_band != plan_lay.shade_band:
        frappe.throw("The cut plan wants shade %s in this lay; the rolls are shade %s." % (plan_lay.shade_band, doc.shade_band or "(none)"))
    if widths and max(widths) - min(widths) > spread_w:
        frappe.throw("The rolls in one lay must be within %s cm of each other in width (now %s to %s cm)." % (spread_w, min(widths), max(widths)))
    if warp and (max(warp) - min(warp) > spread_s or max(weft) - min(weft) > spread_s):
        msg = "Shrinkage of the rolls differs by more than %s%%. Cut rolls of similar shrinkage together." % spread_s
        if washed:
            frappe.throw(msg)
        frappe.msgprint(msg, indicator="orange")

    # ---- sizes
    if not doc.sizes:
        frappe.throw("Add the sizes and ratios cut.")
    total_plies = sum([cint(r.plies) for r in doc.rolls])
    seen_sizes = []
    for s in doc.sizes:
        if s.size not in card_sizes:
            frappe.throw("Size %s is not on production card %s for %s." % (s.size, doc.production_card, doc.colour))
        if s.size in seen_sizes:
            frappe.throw("Size %s appears twice." % s.size)
        seen_sizes.append(s.size)
        if cint(s.ratio) <= 0:
            frappe.throw("Size %s: pieces per ply must be above zero." % s.size)
        s.pieces_cut = total_plies * cint(s.ratio)

    # ---- panel rejects
    rejected = {}
    for r in doc.panel_rejects:
        if r.size not in seen_sizes:
            frappe.throw("Rejected panels: size %s is not cut in this lay." % r.size)
        if cint(r.qty) <= 0:
            frappe.throw("Rejected panels: enter the quantity.")
        rejected["s|" + r.size] = rejected.get("s|" + r.size, 0) + cint(r.qty)
    min_pct = flt(setting("panel_inspection_pct") or 100)
    for s in doc.sizes:
        s.panels_rejected = rejected.get("s|" + s.size, 0)
        if cint(s.panels_rejected) > cint(s.pieces_cut):
            frappe.throw("Size %s: more panels rejected than cut." % s.size)
        if cint(s.panels_checked) and cint(s.panels_checked) < cint(s.panels_rejected):
            frappe.throw("Size %s: panels checked cannot be fewer than panels rejected." % s.size)
        need = frappe.utils.ceil(cint(s.pieces_cut) * min_pct / 100.0)
        if doc.docstatus == 0 and cint(s.panels_checked) and cint(s.panels_checked) < need:
            frappe.msgprint("Size %s: %s panels checked, the setting asks for %s." % (s.size, s.panels_checked, need), indicator="orange")

    # ---- purpose
    if doc.purpose == "Re-cut":
        if not doc.recut_request:
            frappe.throw("A re-cut lay needs its Re-cut Request.")
        req = frappe.db.get_value("Recut Request", doc.recut_request, ["docstatus", "production_card", "colour", "size", "qty", "status", "source_roll", "different_roll_approved", "name"], as_dict=True)
        if not req or req.docstatus != 1 or req.status != "Open":
            frappe.throw("Re-cut Request %s must be submitted and open." % doc.recut_request)
        if req.production_card != doc.production_card or req.colour != doc.colour:
            frappe.throw("Re-cut Request %s is for another card or colour." % doc.recut_request)
        if [s.size for s in doc.sizes] != [req.size] or sum([cint(s.pieces_cut) for s in doc.sizes]) > cint(req.qty):
            frappe.throw("The re-cut lay must cut only size %s, at most %s pieces." % (req.size, req.qty))
        if req.source_roll and [r for r in doc.rolls if r.batch != req.source_roll] and not req.different_roll_approved:
            frappe.throw("The request names roll %s; cutting from another roll needs the approval box ticked on the request." % req.source_roll)
    elif doc.recut_request:
        frappe.throw("Only a re-cut lay can name a Re-cut Request.")

    # ---- pairing
    if doc.component == "Shell":
        if doc.paired_with:
            frappe.throw("A shell lay is not paired with another lay.")
    else:
        if not doc.paired_with:
            frappe.throw("A %s lay must be paired with its shell lay (so the ply numbers match)." % doc.component)
        shell = frappe.get_doc("Lay Report", doc.paired_with)
        if shell.docstatus != 1 or shell.component != "Shell" or shell.production_card != doc.production_card or shell.colour != doc.colour:
            frappe.throw("Paired lay %s must be a submitted shell lay of the same card and colour." % doc.paired_with)
        if cint(shell.total_plies) != total_plies:
            frappe.throw("Paired lay %s has %s plies; this lay has %s. They must match." % (shell.name, shell.total_plies, total_plies))
        mine = {}
        for s in doc.sizes:
            mine[s.size] = cint(s.ratio)
        theirs = {}
        for s in shell.sizes:
            theirs[s.size] = cint(s.ratio)
        if mine != theirs:
            frappe.throw("Size ratios must match the shell lay %s." % shell.name)

    # ---- totals
    doc.total_plies = total_plies
    doc.laid_m = round(sum([flt(r.length_laid_m) for r in doc.rolls]), 3)
    doc.pieces_cut = sum([cint(s.pieces_cut) for s in doc.sizes])
    doc.rejected_pieces = sum([cint(r.qty) for r in doc.panel_rejects])
    per_ply = sum([cint(s.ratio) for s in doc.sizes])
    doc.lay_consumption = round(doc.laid_m / doc.pieces_cut, 4) if doc.pieces_cut else 0
    doc.cad_consumption = round(flt(doc.marker_length_m) / per_ply, 4) if per_ply else 0
    doc.consumption_difference = round(doc.lay_consumption - doc.cad_consumption, 4)


run(doc)
