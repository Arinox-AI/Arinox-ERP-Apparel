# shared helper: split a contract line's quantity across the Tech Pack's sizes
def size_split(qty, sizes, ratios, customer, style_item, colour):
    """{size: pieces}, adding up to exactly `qty`. `sizes` are the Tech Pack's size names and `ratios` {size: ratio} its size ratios.
    The proportions come from the buyer's own most recent earlier contract for the same style (same colour when it has one); with no earlier
    contract they come from the Tech Pack ratios. A size the earlier contract never ordered gets nothing. Returns (split, where the proportions came from)."""
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    qty = cint(qty)
    weights = {}
    where = "Tech Pack ratios"
    for name in frappe.get_all("Sales Contract", filters={"customer": customer, "docstatus": ["<", 2]}, order_by="contract_date desc, creation desc", pluck="name"):
        rows = frappe.get_all("Sales Contract Size Qty", filters={"parent": name, "parenttype": "Sales Contract", "style_item": style_item}, fields=["size", "colour", "qty"])
        same = [r for r in rows if (r.colour or "").strip().upper() == (colour or "").strip().upper()]
        use = same or rows
        if use and sum([cint(r.qty) for r in use]) > 0:
            for r in use:
                key = (r.size or "").strip().upper()
                weights[key] = weights.get(key, 0) + cint(r.qty)
            where = "contract " + name
            break
    if not weights:
        for s in sizes:
            weights[(s or "").strip().upper()] = flt(ratios.get(s))
    listed = [s for s in sizes if flt(weights.get((s or "").strip().upper())) > 0]
    total = sum([flt(weights.get((s or "").strip().upper())) for s in listed])
    split = {}
    for s in sizes:
        split[s] = 0
    if not qty or not total:
        return split, where
    exact = {}
    for s in listed:
        exact[s] = qty * flt(weights.get((s or "").strip().upper())) / total
        split[s] = int(frappe.utils.floor(exact[s]))
    left = qty - sum([split[s] for s in listed])
    for s in sorted(listed, key=lambda x: exact[x] - split[x], reverse=True)[:left]:
        split[s] = split[s] + 1
    return split, where
