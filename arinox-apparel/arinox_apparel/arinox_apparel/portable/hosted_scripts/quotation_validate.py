# Quotation, Before Save: lines that carry a Cost Sheet are held to its margin floor (a submitted costing, the right customer and currency).
def run(doc):
    # include: lib_margin.py
    flt = frappe.utils.flt
    for it in doc.items:
        if not it.get("apparel_cost_sheet"):
            continue
        cs = frappe.get_doc("Cost Sheet", it.apparel_cost_sheet)
        if cs.docstatus != 1:
            frappe.throw("Row %s: Cost Sheet %s is not submitted. Only a submitted costing can be quoted." % (it.idx, cs.name))
        if doc.quotation_to == "Customer" and cs.customer != doc.party_name:
            frappe.throw("Row %s: Cost Sheet %s belongs to %s." % (it.idx, cs.name, cs.customer))
        if cs.currency != doc.currency:
            frappe.throw("Row %s: Cost Sheet %s is in %s, the Quotation in %s." % (it.idx, cs.name, cs.currency, doc.currency))
        it.apparel_style_item = it.apparel_style_item or cs.style_item
        it.apparel_style_no = it.apparel_style_no or cs.style_no
        margin = margin_at_price(cs, it.rate)["margin_pct"]
        approved_at = flt(cs.approved_price) if cs.approval_status == "Approved" else None
        if margin < flt(cs.margin_floor_pct) and not (approved_at and flt(it.rate) >= approved_at - 0.0001):
            frappe.throw("Row %s (%s): %s leaves a margin of %s%%, below the floor of %s%%. Amend the Cost Sheet at this price and get it approved first." %
                         (it.idx, cs.style_no, flt(it.rate), margin, flt(cs.margin_floor_pct)), title="Below Margin Floor")


run(doc)
