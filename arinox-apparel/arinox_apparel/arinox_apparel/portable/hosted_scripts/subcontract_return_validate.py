# Subcontract Return, Before Save: the challan is submitted and not short-closed; pieces split into good / vendor fault / factory fault; a vendor cannot return more than was sent.
def run(doc):
    cint = frappe.utils.cint
    ch = frappe.db.get_value("Subcontract Challan", doc.challan, ["docstatus", "status", "production_card", "supplier", "subcontract_process", "expected_return_date", "sales_contract"], as_dict=True)
    if not ch or ch.docstatus != 1:
        frappe.throw("Challan %s must be submitted." % doc.challan)
    if ch.status == "Short Closed":
        frappe.throw("Challan %s was short-closed; nothing more can be received on it." % doc.challan)
    doc.production_card = ch.production_card
    doc.supplier = ch.supplier
    doc.subcontract_process = ch.subcontract_process
    doc.sales_contract = ch.sales_contract
    if not doc.rows:
        frappe.throw("Add the pieces received.")
    sent = {}
    back = {}
    for r in frappe.get_all("Subcontract Challan Row", filters={"parent": doc.challan}, fields=["colour", "size", "qty"]):
        k = "%s|%s" % (r.colour, r.size)
        sent[k] = sent.get(k, 0) + r.qty
    for r in frappe.db.sql("select r.colour, r.size, sum(r.good_qty + r.reject_vendor_qty + r.reject_factory_qty) from `tabSubcontract Return Row` r join `tabSubcontract Return` p on p.name = r.parent "
                           "where p.docstatus = 1 and p.challan = %s and p.name != %s group by r.colour, r.size", (doc.challan, doc.name or "")):
        back["%s|%s" % (r[0], r[1])] = r[2] or 0
    good = 0
    rv = 0
    rf = 0
    now = {}
    for r in doc.rows:
        r.production_card = doc.production_card
        for fld in ("good_qty", "reject_vendor_qty", "reject_factory_qty", "accepted_for_repair"):
            r.set(fld, cint(r.get(fld)))
            if r.get(fld) < 0:
                frappe.throw("Row %s: quantities cannot be negative." % r.idx)
        key = "%s|%s" % (r.colour, r.size)
        if key not in sent:
            frappe.throw("Row %s: %s %s was not sent on challan %s." % (r.idx, r.colour, r.size, doc.challan))
        r.sent_qty = sent[key]
        got = r.good_qty + r.reject_vendor_qty + r.reject_factory_qty
        if got <= 0:
            frappe.throw("Row %s: enter the pieces received." % r.idx)
        if r.accepted_for_repair > r.reject_factory_qty:
            frappe.throw("Row %s: only factory-fault pieces can be taken back to repair." % r.idx)
        now[key] = now.get(key, 0) + got
        if now[key] + back.get(key, 0) > sent[key]:
            frappe.throw("Row %s: %s %s - %s received in all, only %s were sent." % (r.idx, r.colour, r.size, now[key] + back.get(key, 0), sent[key]))
        good = good + r.good_qty
        rv = rv + r.reject_vendor_qty
        rf = rf + r.reject_factory_qty
    doc.total_good = good
    doc.total_reject_vendor = rv
    doc.total_reject_factory = rf
    if ch.expected_return_date and frappe.utils.getdate(doc.return_date) > frappe.utils.getdate(ch.expected_return_date) and doc.docstatus == 0:
        frappe.msgprint("This return is %s day(s) after the date agreed (%s)." % ((frappe.utils.getdate(doc.return_date) - frappe.utils.getdate(ch.expected_return_date)).days, ch.expected_return_date), indicator="orange")


run(doc)
