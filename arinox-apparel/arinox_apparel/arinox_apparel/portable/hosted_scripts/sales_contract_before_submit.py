# Sales Contract, Before Submit: drop empty size rows, check the contract is ready to sign, and that nothing is left as a placeholder.
def run(doc):
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    doc.set("sizes", [s for s in doc.sizes if cint(s.qty)])
    n = 1
    for s in doc.sizes:
        s.idx = n
        n = n + 1

    def line_index(style_item, colour, po):
        cands = []
        n = 0
        for it in doc.items:
            if it.style_item == style_item and (it.colour or "").strip().upper() == (colour or "").strip().upper():
                if not po or (it.buyer_po_code or "").strip().upper() == po.strip().upper():
                    cands.append(n)
            n = n + 1
        if len(cands) == 1:
            return cands[0]
        return None

    problems = []
    by_line = {}
    for s in doc.sizes:
        k = line_index(s.style_item, s.colour, s.buyer_po_no)
        by_line[k] = by_line.get(k, 0) + cint(s.qty)
    position = 0
    for it in doc.items:
        position = position + 1
        label = "%s / %s" % (it.style_no or it.style_item, it.colour or "-")
        if not it.colour:
            problems.append("%s: colour is missing" % label)
        if cint(it.qty) <= 0:
            problems.append("%s: quantity is missing" % label)
        if not flt(it.rate):
            problems.append("%s: rate is missing" % label)
        for f in (("ex_factory_date", "ex-factory date"), ("etd", "ETD"), ("in_warehouse_date", "in-warehouse date")):
            if not it.get(f[0]):
                problems.append("%s: %s is missing" % (label, f[1]))
        sized = by_line.get(position - 1, 0)
        if sized != cint(it.qty):
            problems.append("%s: size breakdown totals %s, line quantity is %s" % (label, sized, cint(it.qty)))
    for f in (("incoterm", "Incoterm"), ("port_of_loading", "Port of loading")):
        if not doc.get(f[0]):
            problems.append("%s is missing" % f[1])
    if not ((doc.payment_basis and cint(doc.payment_days)) or doc.payment_basis == "Advance" or doc.payment_terms_template):
        problems.append("Payment terms are missing (basis and days, or a payment terms template)")
    if problems:
        frappe.throw("<br>".join(problems), title="Contract not ready to sign")

    # ---- nothing is left TBA on a signed contract
    raw = frappe.db.get_single_value("Apparel Settings", "placeholder_words") or ""
    words = []
    for w in raw.splitlines():
        if w.strip():
            words.append(w.strip().upper())
    if not words:
        return
    hits = []
    text_types = ("Data", "Small Text", "Text", "Long Text")
    allowed_tba = ("shipping_marks",)      # advised at booking; the real contracts print TBA here

    def scan(d, label):
        for df in d.meta.fields:
            if df.fieldtype not in text_types or df.fieldname in allowed_tba:
                continue
            val = (d.get(df.fieldname) or "").strip()
            if not val:
                continue
            bad = val.upper() in words
            if not bad:
                for tok in val.upper().replace(",", " ").split():
                    if len(tok) > 2 and tok in words:
                        bad = True
            if bad:
                hits.append("%s%s: %s" % (label, df.label, val))

    scan(doc, "")
    for it in doc.items:
        scan(it, "Row %s " % it.idx)
    if hits:
        frappe.throw("Nothing may be left as a placeholder on a signed contract:<br>" + "<br>".join(hits), title="Placeholders found")


run(doc)
