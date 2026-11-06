# Line Input, Before Save: the card is open; each bundle belongs to it, is loadable (cut, or back from a panel process), has the right purpose and returned from any "before sewing" process;
# the line is the allocated one (warning); the kit of lining / pocketing bundles is complete (warn or block by setting).
def run(doc):
    # include: lib_mat.py
    # include: lib_shipping.py
    # include: lib_cutting.py
    cint = frappe.utils.cint
    card = require_open_card(doc.production_card)
    require = cint(frappe.db.get_single_value("Apparel Settings", "require_bundle_on_input"))
    seen = []
    for r in doc.bundles:
        if r.bundle:
            if r.bundle in seen:
                frappe.throw("Bundle %s appears twice." % r.bundle)
            seen.append(r.bundle)
            b = frappe.db.get_value("Cut Bundle", r.bundle, ["production_card", "colour", "size", "qty", "component", "shade_band", "status", "purpose", "sewn_qty"], as_dict=True)
            if not b or b.production_card != doc.production_card:
                frappe.throw("Row %s: bundle %s belongs to another production card." % (r.idx, r.bundle))
            if b.status not in ("Cut", "Back") and not (doc.docstatus == 1):
                frappe.throw("Row %s: bundle %s is %s; only cut bundles (or bundles back from a panel process) can be loaded." % (r.idx, r.bundle, b.status))
            if b.purpose != doc.purpose:
                frappe.throw("Row %s: bundle %s is a %s bundle; this input is %s." % (r.idx, r.bundle, b.purpose, doc.purpose))
            before = [p for p in frappe.get_all("Production Card Process", filters={"parent": doc.production_card, "position": "Before Sewing"}, fields=["subcontract_process", "colour"])
                      if not (p.colour or "").strip() or (p.colour or "").strip().upper() == (b.colour or "").strip().upper()]
            if before and b.status != "Back":
                frappe.throw("Row %s: bundle %s must go to %s and come back before it is loaded." % (r.idx, r.bundle, ", ".join([p.subcontract_process for p in before])))
            r.colour = b.colour
            r.size = b.size
            r.qty = b.qty
            r.component = b.component
            r.shade_band = b.shade_band
        elif require:
            frappe.throw("Row %s: choose the bundle (Apparel Settings asks for bundles on every line input)." % r.idx)
        else:
            if not (r.colour and r.size and cint(r.qty) > 0):
                frappe.throw("Row %s: enter colour, size and quantity." % r.idx)
            if not frappe.db.exists("Production Card Line", {"parent": doc.production_card, "colour": r.colour, "size": r.size}):
                frappe.throw("Row %s: %s %s is not on production card %s." % (r.idx, r.colour, r.size, doc.production_card))
    doc.total_qty = sum([cint(r.qty) for r in doc.bundles if (r.component or "Shell") == "Shell"])
    fa = frappe.db.get_value("Factory Allocation", {"sales_order": card.sales_order}, "name")
    if fa:
        lines = []
        for r in frappe.get_all("Factory Allocation Line", filters={"parent": fa, "style_item": card.style_item}, fields=["line"]):
            if r.line and r.line not in lines:
                lines.append(r.line)
        if lines and doc.line not in lines and doc.docstatus == 0:
            frappe.msgprint("Line %s is not the line allocated to this style (%s)." % (doc.line, ", ".join(sorted(lines))), indicator="orange")
    mode = frappe.db.get_single_value("Apparel Settings", "kit_check") or "Warn"
    if mode != "Off":
        missing = kit_missing([r.bundle for r in doc.bundles if r.bundle])
        if missing:
            msg = "Matching lining / pocketing bundles are missing for: %s" % ", ".join(missing[:6])
            if mode == "Block":
                frappe.throw(msg)
            frappe.msgprint(msg, indicator="orange")


run(doc)
