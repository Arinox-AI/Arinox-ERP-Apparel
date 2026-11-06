# Line QC Report, Before Save: hourly checked / passed, defect totals, DHU and RFT, dispositions (B-grade only at finishing; a re-cut needs a rejected piece and a defect),
# A-grade passes at finishing equal the pieces passed, the traffic-light colour per operator.
def run(doc):
    # include: lib_sewing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    FINISH = "Finishing"
    INLINE = "Inline (Traffic Light)"
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    for h in doc.hours:
        if cint(h.checked) < 0 or cint(h.passed) < 0 or cint(h.passed) > cint(h.checked):
            frappe.throw("Hour %s: passed cannot be more than checked, and neither can be negative." % h.hour_slot)
    doc.total_checked = sum([cint(h.checked) for h in doc.hours])
    doc.total_passed = sum([cint(h.passed) for h in doc.hours])
    doc.total_defects = sum([cint(d.qty) for d in doc.defects])
    for d in doc.defects:
        if cint(d.qty) <= 0:
            frappe.throw("Defect %s: enter a quantity above zero." % d.defect_code)
    doc.dhu = round(pct_of(doc.total_defects, doc.total_checked) or 0, 2)
    doc.defect_pct = round(pct_of(doc.total_checked - doc.total_passed, doc.total_checked) or 0, 2)
    doc.rft_pct = round(pct_of(doc.total_passed, doc.total_checked) or 0, 2)
    if doc.dhu > flt(frappe.db.get_single_value("Apparel Settings", "dhu_alert_threshold") or 5) and doc.docstatus == 0:
        frappe.msgprint("DHU %s is above the alert level." % doc.dhu, indicator="orange")
    for r in doc.dispositions:
        r.production_card = doc.production_card
        if cint(r.qty) <= 0:
            frappe.throw("Disposition row %s: enter a quantity above zero." % r.idx)
        if not frappe.db.exists("Production Card Line", {"parent": doc.production_card, "colour": r.colour, "size": r.size}):
            frappe.throw("Disposition row %s: %s %s is not on production card %s." % (r.idx, r.colour, r.size, doc.production_card))
        if r.disposition == "B-Grade" and doc.audit_type != FINISH:
            frappe.throw("Disposition row %s: B-grade is decided at finishing, not at %s." % (r.idx, doc.audit_type))
        if cint(r.replace) and r.disposition != "Reject":
            frappe.throw("Disposition row %s: only a rejected piece needs a re-cut." % r.idx)
        if cint(r.replace) and not r.defect_code:
            frappe.throw("Disposition row %s: choose the defect to raise the re-cut request." % r.idx)
    if doc.audit_type == FINISH:
        total = sum([cint(p.qty) for p in doc.passes])
        for p in doc.passes:
            if not frappe.db.exists("Production Card Line", {"parent": doc.production_card, "colour": p.colour, "size": p.size}):
                frappe.throw("Passed row %s: %s %s is not on production card %s." % (p.idx, p.colour, p.size, doc.production_card))
        if doc.hours and total != doc.total_passed:
            frappe.throw("The A-grade pieces by colour and size (%s) must equal the pieces passed in the hourly check (%s)." % (total, doc.total_passed))
    rules = [[r.colour, r.defects_from] for r in frappe.get_all("Traffic Light Rule", filters={"parent": "Apparel Settings", "parentfield": "traffic_light_rules"}, fields=["colour", "defects_from"])]
    reds = 0
    for t in doc.traffic:
        t.light = traffic_colour(cint(t.defects), rules)
        reds = reds + (1 if t.light == "Red" else 0)
    if reds and doc.docstatus == 0:
        frappe.msgprint("%s operator(s) are red. Retrain or re-set the operation before the next round." % reds, indicator="red")


run(doc)
