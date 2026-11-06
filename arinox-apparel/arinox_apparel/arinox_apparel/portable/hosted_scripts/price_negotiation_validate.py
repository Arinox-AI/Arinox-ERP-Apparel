# Price Negotiation, Before Save: each round is checked against its Cost Sheet and given the margin its price would leave;
# the style table summarises the last offers and the agreed price; the status follows the styles.
def run(doc):
    # include: lib_margin.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    OUR = ("Our Offer", "Our Counter")
    BUYER = ("Buyer Target", "Buyer Counter")
    MANUAL_STATUS = ("On Hold", "Lost")

    cache = {}
    for r in doc.rounds:
        cs = cache.get(r.cost_sheet) or frappe.get_doc("Cost Sheet", r.cost_sheet)
        cache[r.cost_sheet] = cs
        if cs.customer != doc.customer:
            frappe.throw("Round %s: Cost Sheet %s belongs to another customer." % (r.idx, cs.name))
        if cs.currency != doc.currency:
            frappe.throw("Round %s: Cost Sheet %s is in %s, not %s." % (r.idx, cs.name, cs.currency, doc.currency))
        if cs.docstatus == 2:
            frappe.throw("Round %s: Cost Sheet %s is cancelled. Use its amended revision." % (r.idx, cs.name))
        r.style_no = cs.style_no
        if r.direction != "Dropped" and not flt(r.price):
            frappe.throw("Round %s: enter the price." % r.idx)
        if flt(r.price):
            m = margin_at_price(cs, r.price)
            r.margin_pct = m["margin_pct"]
            r.below_floor = 1 if m["margin_pct"] < flt(cs.margin_floor_pct) else 0
        if not r.recorded_by:
            r.recorded_by = frappe.session.user
        if r.direction == "Agreed" and r.below_floor:
            frappe.msgprint("Style %s agreed at %s, margin %s%% is below the floor. The Quotation will need an approved Cost Sheet revision." % (r.style_no, r.price, r.margin_pct),
                            indicator="orange")
        if not [s for s in doc.styles if s.cost_sheet == r.cost_sheet]:
            doc.append("styles", {"cost_sheet": r.cost_sheet, "qty": r.qty or cs.order_qty})

    rounds = sorted(doc.rounds, key=lambda r: (getdate(r.round_date), r.idx))
    for s in doc.styles:
        cs = frappe.get_doc("Cost Sheet", s.cost_sheet)
        s.style_no = cs.style_no
        s.cost_price = cs.quoted_price
        s.our_last_offer = 0
        s.buyer_last_offer = 0
        s.agreed_price = 0
        s.margin_at_agreed = 0
        status = "Open"
        for r in rounds:
            if r.cost_sheet != s.cost_sheet:
                continue
            if r.direction in OUR:
                s.our_last_offer = r.price
            elif r.direction in BUYER:
                s.buyer_last_offer = r.price
            elif r.direction == "Agreed":
                s.agreed_price = r.price
                s.margin_at_agreed = r.margin_pct
                status = "Agreed"
            elif r.direction == "Dropped":
                status = "Dropped"
            if r.qty:
                s.qty = r.qty
        s.style_status = status

    doc.total_qty = sum([cint(s.qty) for s in doc.styles if s.style_status != "Dropped"])
    doc.total_value = flt(sum([cint(s.qty) * flt(s.agreed_price) for s in doc.styles if s.style_status == "Agreed"]), 2)

    if doc.status not in MANUAL_STATUS:
        live = [s for s in doc.styles if s.style_status != "Dropped"]
        agreed = [s for s in live if s.style_status == "Agreed"]
        if live and len(agreed) == len(live):
            doc.status = "Agreed"
        elif agreed:
            doc.status = "Partly Agreed"
        else:
            doc.status = "Open"


run(doc)
