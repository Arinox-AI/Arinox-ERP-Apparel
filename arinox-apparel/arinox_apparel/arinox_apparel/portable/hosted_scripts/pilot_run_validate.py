# Pilot Run, Before Save: the card is open; the PP meeting was held first (when required); colours are on the card; the pilot pieces (cut, sewn, washed, rejected) are read
# from the ledger; measurements; achieved efficiency and bottlenecks from the operations.
def run(doc):
    # include: lib_samples.py
    # include: lib_pp.py
    # include: lib_sewing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status", "sales_order", "style_item"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    if frappe.db.get_single_value("Apparel Settings", "require_pp_meeting") and doc.is_new():
        held = cutting_actions_open(card.sales_order, card.style_item)
        if not held[0]:
            frappe.throw("The PP Meeting for this style has not been held yet. A pilot run follows the PP meeting.")
    card_colours = [(l.colour or "").strip().upper() for l in frappe.get_all("Production Card Line", filters={"parent": doc.production_card}, fields=["colour"])]
    seen = []
    for r in doc.colours:
        key = (r.colour or "").strip().upper()
        if key not in card_colours:
            frappe.throw("Row %s: colour %s is not on production card %s." % (r.idx, r.colour, doc.production_card))
        if key in seen:
            frappe.throw("Colour %s appears twice." % r.colour)
        seen.append(key)

    def total(colour, stages, process):
        cond = " and subcontract_process = %s" if process else ""
        args = [doc.production_card, colour, "Pilot", tuple(stages)] + ([process] if process else [])
        return cint(frappe.db.sql("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and colour=%s and purpose=%s and stage in %s" + cond, tuple(args))[0][0])

    for r in doc.colours:
        r.cut_qty = total(r.colour, ["CUT"], None) - total(r.colour, ["CUT_REJECT"], None)
        r.sewn_qty = total(r.colour, ["SEW_OUT"], None)
        r.washed_qty = total(r.colour, ["SC_BACK_GOOD"], "Wash")
        r.rejected_qty = total(r.colour, ["CUT_REJECT", "SEW_REJECT", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_REJECT"], None)
    meas_compute(doc.measurements)
    actual = sum([flt(o.actual_sam) for o in doc.operations if flt(o.actual_sam)])
    timed = sum([flt(o.planned_sam) for o in doc.operations if flt(o.actual_sam)])
    doc.achieved_efficiency_pct = round(timed / actual * 100, 2) if actual else 0
    doc.bottleneck_count = len([o for o in doc.operations if cint(o.bottleneck)])


run(doc)
