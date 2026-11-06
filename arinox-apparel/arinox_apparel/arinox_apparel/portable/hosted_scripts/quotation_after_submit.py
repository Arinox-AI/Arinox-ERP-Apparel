# Quotation, After Submit: the quote is our offer, so it becomes a round of its Price Negotiation.
def run(doc):
    if not doc.get("apparel_price_negotiation"):
        return
    pn = frappe.get_doc("Price Negotiation", doc.apparel_price_negotiation)
    for it in doc.items:
        if not it.get("apparel_cost_sheet"):
            continue
        pn.append("rounds", {"round_date": doc.transaction_date, "cost_sheet": it.apparel_cost_sheet, "direction": "Our Offer", "price": it.rate, "qty": it.qty,
                             "channel": "Email", "quotation": doc.name, "remarks": "Quotation %s submitted" % doc.name})
    pn.quotation = doc.name
    pn.flags.ignore_permissions = True
    pn.save()


run(doc)
