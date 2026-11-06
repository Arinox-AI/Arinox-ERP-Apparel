# Cut Plan, Before Save: the card is issued and open, the fabric and colour are on it, lays and ratios are consistent, marker consumption against the card's, red flags.
def run(doc):
    # include: lib_mat.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    fabric = frappe.db.get_value("Production Card Fabric", {"parent": doc.production_card, "colour": doc.colour, "fabric_item": doc.fabric_item}, ["consumption", "consumption_uom"], as_dict=True)
    if not fabric:
        frappe.throw("%s is not a fabric of colour %s on production card %s." % (doc.fabric_item, doc.colour, doc.production_card))
    doc.fr_consumption = to_metres(flt(fabric.consumption), fabric.consumption_uom or "Meter", None, None)
    sizes = {}
    for l in frappe.get_all("Production Card Line", filters={"parent": doc.production_card, "colour": doc.colour}, fields=["size", "planned_cut_qty"]):
        sizes[l.size] = l
    if not sizes:
        frappe.throw("Colour %s is not on production card %s." % (doc.colour, doc.production_card))
    lay_nos = [l.lay_no for l in doc.lays]
    for n in lay_nos:
        if lay_nos.count(n) > 1:
            frappe.throw("A lay number appears twice.")
    by_lay = {}
    for r in doc.ratios:
        if r.size not in sizes:
            frappe.throw("Ratio row %s: size %s is not on the production card for %s." % (r.idx, r.size, doc.colour))
        if cint(r.ratio) <= 0:
            frappe.throw("Ratio row %s: pieces per ply must be above zero." % r.idx)
        if r.lay_no not in lay_nos:
            frappe.throw("Ratio row %s: lay %s is not in the lay list." % (r.idx, r.lay_no))
        k = "lay|%s" % r.lay_no
        if k not in by_lay:
            by_lay[k] = {}
        if r.size in by_lay[k]:
            frappe.throw("Lay %s lists size %s twice." % (r.lay_no, r.size))
        by_lay[k][r.size] = cint(r.ratio)
    flags = []
    output = {}
    for s in sizes:
        output[s] = 0
    laid = 0.0
    pieces = 0.0
    for l in doc.lays:
        if flt(l.marker_length_m) <= 0 or cint(l.planned_plies) <= 0:
            frappe.throw("Lay %s: marker length and plies must be above zero." % l.lay_no)
        ratios = by_lay.get("lay|%s" % l.lay_no)
        if not ratios:
            frappe.throw("Lay %s has no size ratios." % l.lay_no)
        l.pieces_per_ply = sum([ratios[s] for s in ratios])
        l.planned_pieces = l.pieces_per_ply * cint(l.planned_plies)
        laid = laid + flt(l.marker_length_m) * cint(l.planned_plies)
        pieces = pieces + l.planned_pieces
        for s in ratios:
            output[s] = output[s] + ratios[s] * cint(l.planned_plies)
    doc.marker_consumption = round(laid / pieces, 4) if pieces else 0
    doc.variance_pct = round((doc.marker_consumption - doc.fr_consumption) / doc.fr_consumption * 100, 2) if doc.fr_consumption and pieces else 0
    extra = cint(frappe.db.get_single_value("Apparel Settings", "cut_cap_extra_pcs") or 3)
    text = []
    for s in sorted(sizes):
        plan_q = cint(sizes[s].planned_cut_qty)
        got = output[s]
        text.append("%s: plan %s, lays %s (%+d)" % (s, plan_q, got, got - plan_q))
        if doc.lays and got == 0:
            flags.append("Size %s is on the card but in no lay." % s)
        elif got > plan_q + extra:
            flags.append("Size %s: lays cut %s more than planned (%s)." % (s, got - plan_q, got))
        elif doc.lays and got < plan_q:
            flags.append("Size %s: lays cut %s fewer than planned." % (s, plan_q - got))
    doc.size_summary = "\n".join(text)
    limit = flt(frappe.db.get_single_value("Apparel Settings", "marker_variance_pct") or 5)
    if abs(flt(doc.variance_pct)) > limit:
        flags.append("Marker consumption %s differs from the card's %s by %s%% (limit %s%%)." % (doc.marker_consumption, round(doc.fr_consumption, 4), doc.variance_pct, limit))
    doc.red_flags = "\n".join(flags)


run(doc)
