# Tech Pack, Before Save (tech_pack.py validate): status reset on edit, sizes, measurements, fit rounds, duplicate-style notice.
def run(doc):
    flt = frappe.utils.flt

    if doc.status in ("Accepted", "Cancelled"):
        doc.status = "Draft"

    # ---- sizes: no duplicates, one base size, ratios usually total 1 or 100
    seen = []
    for s in doc.sizes:
        key = (s.size or "").strip().upper()
        if key in seen:
            frappe.throw("Size %s is listed twice." % s.size)
        seen.append(key)
    bases = [s.size for s in doc.sizes if s.is_base_size]
    if len(bases) > 1:
        frappe.throw("Only one base size is allowed.")
    doc.base_size = bases[0] if bases else None
    total = sum([flt(s.ratio) for s in doc.sizes])
    if total and abs(total - 1) > 0.001 and abs(total - 100) > 0.1:
        frappe.msgprint("Size ratios add up to %s. They usually total 1 or 100." % flt(total, 3), indicator="orange")

    # ---- measurements: one row per point of measure; a value under a size column needs that size in the size list
    listed = [(x.size or "").strip().upper() for x in doc.sizes]
    seen = []
    for m in doc.measurements:
        key = "%s|%s|%s" % ((m.pom_code or "").strip().upper(), (m.point_of_measure or "").strip().upper(), (m.section or "").strip().upper())
        if key in seen:
            frappe.throw("Measurement row %s: %s %s is entered twice (an earlier row has the same POM code, point of measure and section). Keep one row per point, with the size values in the size columns, or give them different sections. If the sizes show 0 on every row, run the API arinox_tech_pack_merge_measurements." % (m.idx, (m.pom_code or "").strip().upper(), m.point_of_measure))
        seen.append(key)
        for size in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]:
            if flt(m.get(size.lower())) and listed and size not in listed:
                frappe.throw("Measurement row %s: %s has a value for size %s, which is not in the size list." % (m.idx, m.point_of_measure, size))

    # ---- fit rounds: the header shows the result of the latest round
    dated = sorted([r for r in doc.fit_rounds if r.round_date], key=lambda r: str(r.round_date))
    last = None
    if dated:
        last = dated[-1]
    elif doc.fit_rounds:
        last = doc.fit_rounds[-1]
    doc.fit_status = last.round_status if last else None

    # ---- the same style already accepted for this season: tell the user (not a block)
    filters = {"customer": doc.customer, "style_no": doc.style_no, "docstatus": 1, "name": ("!=", doc.name), "season": doc.season or ("is", "not set")}
    dup = frappe.db.get_value("Tech Pack", filters, "name")
    if dup and dup != doc.amended_from:
        frappe.msgprint("Tech Pack %s is already accepted for this style and season. Amend it to record a new buyer revision." % dup, indicator="orange")


run(doc)
