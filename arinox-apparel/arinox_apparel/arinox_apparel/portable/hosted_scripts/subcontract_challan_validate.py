# Subcontract Challan, Before Save: the pieces are on the open card, the process is enabled, the expected return date counts the process's turnaround in working days, and a warning
# when the pieces sent on all challans of one order would exceed what the order allows.
def run(doc):
    # include: lib_shipping.py
    # include: lib_tna_plan.py
    # include: lib_subcontract.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    card = require_open_card(doc.production_card)
    doc.sales_contract = card.sales_contract
    doc.sales_order = card.sales_order
    if not doc.rows:
        frappe.throw("Add the pieces being sent.")
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
    proc = frappe.db.get_value("Subcontract Process", doc.subcontract_process, ["enabled", "turnaround_days"], as_dict=True)
    if not proc or not proc.enabled:
        frappe.throw("Process %s is not enabled." % doc.subcontract_process)
    if cint(proc.turnaround_days) and doc.challan_date:
        company = frappe.db.get_value("Production Card", doc.production_card, "company")
        doc.expected_return_date = add_working_days(frappe.utils.getdate(doc.challan_date), cint(proc.turnaround_days), holiday_dates(company))
    if doc.purchase_order:
        po_qty = frappe.db.sql("select ifnull(sum(qty), 0) from `tabPurchase Order Item` where parent = %s", (doc.purchase_order,))[0][0]
        tol = flt(frappe.db.get_value("Subcontract Process", doc.subcontract_process, "qty_tolerance_pct"))
        sent = frappe.db.sql("select ifnull(sum(total_qty), 0) from `tabSubcontract Challan` where purchase_order = %s and docstatus = 1 and name != %s", (doc.purchase_order, doc.name or ""))[0][0]
        if po_qty and sent + doc.total_qty > po_qty * (1 + tol / 100.0) + 1e-9:
            frappe.msgprint("Pieces sent on this order would be %s; the order is for %s (+%s %%)." % (sent + doc.total_qty, int(po_qty), tol), indicator="orange")


run(doc)
