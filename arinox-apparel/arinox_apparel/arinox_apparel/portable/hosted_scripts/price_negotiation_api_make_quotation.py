# API arinox_price_negotiation_make_quotation: the agreed (else our last, else the costed) price of every live style -> Quotation (unsaved).
def main():
    # include: lib_quotation.py
    flt = frappe.utils.flt
    pn = frappe.get_doc("Price Negotiation", frappe.form_dict.get("source_name"))
    pn.check_permission("read")
    lines = []
    for s in pn.styles:
        if s.style_status == "Dropped":
            continue
        lines.append({"cost_sheet": s.cost_sheet, "qty": s.qty or 1, "rate": flt(s.agreed_price) or flt(s.our_last_offer) or flt(s.cost_price)})
    if not lines:
        frappe.throw("No live styles to quote.")
    frappe.flags.arinox_result = build_quotation(pn.customer, pn.currency, pn.opportunity, lines, pn.name).as_dict()


main()
