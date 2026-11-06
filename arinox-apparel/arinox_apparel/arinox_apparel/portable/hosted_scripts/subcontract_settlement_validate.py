# Subcontract Settlement, Before Save: what the vendor is owed for one challan. Vendor-damaged and missing pieces are not paid; vendor damage above the process's limit attracts
# a penalty; invoice variance against what was sent is noted.
def run(doc):
    # include: lib_shipping.py
    # include: lib_subcontract.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    ch = frappe.db.get_value("Subcontract Challan", doc.challan, ["docstatus", "production_card", "total_qty", "subcontract_process", "supplier", "purchase_order"], as_dict=True)
    if not ch or ch.docstatus != 1:
        frappe.throw("Challan %s must be submitted." % doc.challan)
    if frappe.db.exists("Subcontract Settlement", {"challan": doc.challan, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]}):
        frappe.throw("Challan %s already has a settlement." % doc.challan)
    proc = frappe.db.get_value("Subcontract Process", ch.subcontract_process, ["damage_threshold_pct", "qty_tolerance_pct"], as_dict=True)
    tot = frappe.db.sql("select ifnull(sum(r.good_qty), 0), ifnull(sum(r.reject_vendor_qty), 0), ifnull(sum(r.reject_factory_qty), 0) from `tabSubcontract Return Row` r "
                        "join `tabSubcontract Return` p on p.name = r.parent where p.docstatus = 1 and p.challan = %s", (doc.challan,))[0]
    doc.sent_qty = ch.total_qty
    doc.good_qty = cint(tot[0])
    doc.reject_vendor_qty = cint(tot[1])
    doc.reject_factory_qty = cint(tot[2])
    doc.short_qty = max(0, doc.sent_qty - doc.good_qty - doc.reject_vendor_qty - doc.reject_factory_qty)
    doc.threshold_pct = flt(proc.damage_threshold_pct)
    doc.qty_tolerance_pct = flt(proc.qty_tolerance_pct)
    basis = settings_value("subcontract_penalty_basis", "Cost Sheet FOB")
    scope = settings_value("subcontract_penalty_scope", "All Damaged")
    rows = [r for r in frappe.get_all("Subcontract Challan Row", filters={"parent": doc.challan}, fields=["qty", "unit_value"]) if flt(r.unit_value)]
    if rows:
        doc.unit_value = sum([r.qty * flt(r.unit_value) for r in rows]) / sum([r.qty for r in rows])
    else:
        doc.unit_value = unit_value_for_card(ch.production_card, basis)
    pen = penalty(doc.sent_qty, doc.reject_vendor_qty, doc.threshold_pct, doc.unit_value, scope)
    doc.vendor_reject_pct = round(pen[0] or 0, 4)
    doc.penalty_qty = pen[1]
    doc.penalty_amount = round(pen[2], 2)
    doc.payable_qty = doc.good_qty + doc.reject_factory_qty
    doc.gross_amount = round(doc.payable_qty * flt(doc.rate), 2)
    doc.net_amount = round(doc.gross_amount - doc.penalty_amount, 2)
    doc.variance_note = ""
    if cint(doc.invoiced_qty):
        over = (flt(doc.invoiced_qty) - flt(doc.sent_qty)) / flt(doc.sent_qty) * 100.0 if flt(doc.sent_qty) else 0
        doc.invoice_variance_pct = round(over, 2)
        notes = []
        if abs(doc.invoice_variance_pct) > doc.qty_tolerance_pct:
            notes.append("The vendor invoices %s pieces against %s sent (%s %%), outside the +-%s %% allowed." % (doc.invoiced_qty, doc.sent_qty, doc.invoice_variance_pct, doc.qty_tolerance_pct))
        if doc.invoiced_qty > doc.payable_qty:
            notes.append("The invoice charges %s pieces more than the %s we owe for." % (doc.invoiced_qty - doc.payable_qty, doc.payable_qty))
        doc.variance_note = "\n".join(notes)
        if notes and doc.docstatus == 0:
            frappe.msgprint("<br>".join(notes), indicator="orange")


run(doc)
