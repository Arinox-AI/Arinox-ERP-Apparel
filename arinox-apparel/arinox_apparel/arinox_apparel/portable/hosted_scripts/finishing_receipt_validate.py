# Finishing Receipt, Before Save: the pieces received into finishing are on the card; a vendor return names the vendor.
def run(doc):
    # include: lib_shipping.py
    cint = frappe.utils.cint
    card = require_open_card(doc.production_card)
    doc.sales_contract = card.sales_contract
    doc.sales_order = card.sales_order
    if not doc.rows:
        frappe.throw("Add the pieces received.")
    on_card = ["%s|%s" % (l.colour, l.size) for l in frappe.get_all("Production Card Line", filters={"parent": doc.production_card}, fields=["colour", "size"])]
    total = 0
    for r in doc.rows:
        r.qty = cint(r.qty)
        if r.qty <= 0:
            frappe.throw("Row %s: enter a quantity above zero." % r.idx)
        if "%s|%s" % (r.colour, r.size) not in on_card:
            frappe.throw("Row %s: %s %s is not on production card %s." % (r.idx, r.colour, r.size, doc.production_card))
        total = total + r.qty
    doc.total_qty = total
    if doc.source == "Subcontract Return" and not doc.supplier:
        frappe.throw("Name the vendor the pieces came from.")


run(doc)
