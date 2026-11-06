# Buyer Claim, Before Save: against a submitted buyer invoice (not the group invoice); the amount, the pieces, the cap at the CIF value of the pieces, and the contract's claim window.
def run(doc):
    # include: lib_shipping.py
    # include: lib_claim.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    si = frappe.db.get_value("Sales Invoice", doc.sales_invoice, ["docstatus", "apparel_sales_contract", "apparel_shipment", "net_total", "total_qty", "is_internal_customer", "company"], as_dict=True)
    if not si or si.docstatus != 1:
        frappe.throw("Invoice %s must be submitted." % doc.sales_invoice)
    if cint(si.is_internal_customer):
        frappe.throw("Claims are raised against the buyer's invoice, not the group invoice.")
    doc.sales_contract = si.apparel_sales_contract
    doc.shipment = si.apparel_shipment
    if flt(doc.claimed_amount) <= 0:
        frappe.throw("Enter the amount claimed.")
    for r in doc.rows:
        if cint(r.pieces) <= 0:
            frappe.throw("Claim row %s: enter the pieces." % r.idx)
    pieces = sum([cint(r.pieces) for r in doc.rows])
    unit = flt(si.net_total) / flt(si.total_qty) if flt(si.total_qty) else 0
    doc.cap_amount = round(unit * pieces, 2) if pieces else flt(si.net_total)
    arrival = None
    if doc.shipment:
        arrival = frappe.db.get_value("Shipment", doc.shipment, "apparel_arrival_date") or frappe.db.get_value("Shipment", doc.shipment, "apparel_delivery_date")
    doc.arrival_date = arrival
    q = 0
    n = 0
    if doc.sales_contract and frappe.db.exists("Sales Contract", doc.sales_contract):
        v = frappe.db.get_value("Sales Contract", doc.sales_contract, ["quality_claim_days", "quantity_claim_days"])
        q = v[0]
        n = v[1]
    wc = window_check(doc.claim_type, arrival, doc.reported_on or frappe.utils.nowdate(), q, n)
    doc.window_days = wc[0]
    doc.days_since_arrival = wc[1]
    doc.window_note = "" if wc[2] else "Reported %s days after arrival; the contract allows %s." % (wc[1], wc[0])
    if doc.docstatus == 0 and doc.settlement == "Credit Note" and not doc.rows and doc.claim_type not in NO_WINDOW:
        frappe.msgprint("Add the pieces claimed so the cap can be worked out.", indicator="orange")
    if doc.evidence is None and doc.claim_type not in NO_WINDOW and cint(settings_value("claim_requires_evidence", 1)) and doc.docstatus == 0:
        frappe.msgprint("Attach the buyer's evidence (photos or report) before accepting the claim.", indicator="orange")


run(doc)
