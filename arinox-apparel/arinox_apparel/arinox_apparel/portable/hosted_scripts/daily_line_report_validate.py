# Daily Line Report, Before Save: manpower and time, every output row on an open card, the bundle (when asked), and efficiency from the operation bulletin:
# produced minutes = output x SAM, available minutes = workers x (shift + overtime - downtime); the target follows the learning curve.
def run(doc):
    # include: lib_shipping.py
    # include: lib_sewing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    if cint(doc.operators_present) <= 0:
        frappe.throw("Enter the operators present.")
    if min(cint(doc.overtime_minutes), cint(doc.downtime_minutes), cint(doc.helpers_present)) < 0:
        frappe.throw("Overtime, downtime and helpers cannot be negative.")
    if cint(doc.downtime_minutes) and not doc.downtime_reason:
        frappe.throw("Choose the downtime reason.")
    if not doc.outputs:
        frappe.throw("Enter the output.")
    styles = {}
    order = []
    require_bundle = cint(frappe.db.get_single_value("Apparel Settings", "require_bundle_on_output"))
    for r in doc.outputs:
        if cint(r.qty) <= 0:
            frappe.throw("Row %s: enter a quantity above zero." % r.idx)
        card = frappe.db.get_value("Production Card", r.production_card, ["docstatus", "status", "style_item"], as_dict=True)
        if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
            frappe.throw("Row %s: production card %s must be issued and open." % (r.idx, r.production_card))
        if not frappe.db.exists("Production Card Line", {"parent": r.production_card, "colour": r.colour, "size": r.size}):
            frappe.throw("Row %s: %s %s is not on production card %s." % (r.idx, r.colour, r.size, r.production_card))
        sk = "s|" + card.style_item
        if sk not in styles:
            styles[sk] = 0
            order.append(card.style_item)
        styles[sk] = styles[sk] + cint(r.qty)
        if not r.bundle:
            if require_bundle:
                frappe.throw("Row %s: choose the bundle (Apparel Settings asks for bundles on output)." % r.idx)
            continue
        b = frappe.db.get_value("Cut Bundle", r.bundle, ["production_card", "colour", "size", "qty", "sewn_qty", "rejected_qty", "status", "line", "component"], as_dict=True)
        if not b or b.production_card != r.production_card or b.colour != r.colour or b.size != r.size:
            frappe.throw("Row %s: bundle %s is not %s %s of card %s." % (r.idx, r.bundle, r.colour, r.size, r.production_card))
        if b.status != "Issued" and doc.docstatus == 0:
            frappe.throw("Row %s: bundle %s is %s; only a bundle loaded on a line can be reported." % (r.idx, r.bundle, b.status))
        if b.line and b.line != doc.line:
            frappe.throw("Row %s: bundle %s is on line %s, not %s." % (r.idx, r.bundle, b.line, doc.line))
        if cint(b.sewn_qty) + cint(b.rejected_qty) + cint(r.qty) > cint(b.qty) and doc.docstatus == 0:
            frappe.throw("Row %s: bundle %s has %s pieces; %s already reported." % (r.idx, r.bundle, b.qty, cint(b.sewn_qty) + cint(b.rejected_qty)))

    first_style = order[0]
    ob = active_ob(first_style)
    settings_minutes = cint(frappe.db.get_single_value("Apparel Settings", "work_minutes_per_day") or 480)
    doc.shift_minutes = cint(doc.shift_minutes) or (cint(ob.working_minutes) if ob else 0) or settings_minutes
    worked = max(doc.shift_minutes + cint(doc.overtime_minutes) - cint(doc.downtime_minutes), 0)
    doc.total_output = sum([cint(r.qty) for r in doc.outputs])
    produced = 0.0
    missing = []
    for style in order:
        o = active_ob(style)
        if not o or not flt(o.total_sam):
            missing.append(style)
            continue
        produced = produced + styles["s|" + style] * flt(o.total_sam)
    doc.produced_minutes = round(produced, 2)
    workers = cint(doc.operators_present) + cint(doc.helpers_present)      # the OB total SAM includes helper time
    doc.available_minutes = round(workers * worked, 2)
    doc.efficiency_pct = round(pct_of(produced, doc.available_minutes) or 0, 2)
    if missing and doc.docstatus == 0:
        frappe.msgprint("No active Operation Bulletin for %s: efficiency cannot include its output." % ", ".join(missing), indicator="orange")
    eff_plan = flt(ob.expected_efficiency_pct) if ob and flt(ob.expected_efficiency_pct) else flt(frappe.db.get_single_value("Apparel Settings", "planned_efficiency_pct") or 65)
    doc.learning_day = learning_day(doc.line, first_style, doc.report_date)
    factor = learning_factor(doc.learning_day, curve())
    doc.learning_factor_pct = round(factor * 100, 2)
    doc.target_qty = round(day_target(workers, worked, eff_plan, flt(ob.total_sam)) * factor, 1) if ob and flt(ob.total_sam) else 0
    doc.variance_to_target = round(doc.total_output - flt(doc.target_qty), 1)
    hourly = sum([cint(h.output_qty) for h in doc.hours])
    if doc.hours and hourly != doc.total_output and doc.docstatus == 0:
        frappe.msgprint("The hourly output (%s) does not add up to the day's output (%s)." % (hourly, doc.total_output), indicator="orange")


run(doc)
