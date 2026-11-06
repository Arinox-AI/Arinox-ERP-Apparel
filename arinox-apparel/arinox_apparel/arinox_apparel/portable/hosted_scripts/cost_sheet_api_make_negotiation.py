# API arinox_cost_sheet_make_price_negotiation: add this costing to the customer's open negotiation for the inquiry, or start one. Answers its name.
def main():
    cs = frappe.get_doc("Cost Sheet", frappe.form_dict.get("source_name"))
    if cs.docstatus != 1:
        frappe.throw("Submit the Cost Sheet before negotiating on it.")
    filters = {"customer": cs.customer, "status": ("in", ["Open", "Partly Agreed", "On Hold"])}
    filters["opportunity"] = cs.opportunity or ("is", "not set")
    name = frappe.db.get_value("Price Negotiation", filters, "name", order_by="creation desc")
    pn = frappe.get_doc("Price Negotiation", name) if name else frappe.new_doc("Price Negotiation")
    if not name:
        pn.update({"customer": cs.customer, "opportunity": cs.opportunity, "currency": cs.currency})
    if pn.currency != cs.currency:
        frappe.throw("Negotiation %s is in %s; this Cost Sheet is in %s." % (pn.name, pn.currency, cs.currency))
    if not [s for s in pn.styles if s.cost_sheet == cs.name]:
        pn.append("styles", {"cost_sheet": cs.name, "qty": cs.order_qty})
        pn.append("rounds", {"cost_sheet": cs.name, "direction": "Our Offer", "price": cs.quoted_price, "qty": cs.order_qty,
                             "remarks": "Opening offer from costing rev %s" % cs.revision_no})
    pn.save()
    frappe.flags.arinox_result = pn.name


main()
