# shared helpers for the subcontract documents: working-day arithmetic, the vendor-damage penalty, over/short %, the roll-up of returns onto a challan, the value of a piece.
# Needs lib_shipping.py; the working-day due date also needs lib_tna_plan.py (holiday_dates).
def add_working_days(start, days, holidays):
    """Date `days` working days after `start` (the day of receipt is day 0). Sundays and `holidays` are skipped."""
    d = frappe.utils.getdate(start)
    left = int(days)
    hol = holidays or []
    while left > 0:
        d = frappe.utils.getdate(frappe.utils.add_days(d, 1))
        if d.weekday() == 6 or d in hol:
            continue
        left = left - 1
    return d


def penalty(sent, reject_vendor, threshold_pct, unit_value, scope):
    """[reject %, penalised qty, amount] for vendor-damaged pieces. Applies only when the vendor-fault rate is ABOVE the threshold."""
    if not float(sent or 0):
        return [None, 0, 0.0]
    rate = float(reject_vendor or 0) / float(sent) * 100.0
    if rate <= float(threshold_pct):
        return [rate, 0, 0.0]
    if scope == "Excess Only":
        qty = max(0, int(reject_vendor) - int(frappe.utils.floor(float(sent) * float(threshold_pct) / 100.0 + 1e-9)))
    else:
        qty = int(reject_vendor)
    return [rate, qty, qty * float(unit_value or 0)]


def refresh_returns(challan):
    """Recompute what came back against each challan row and the challan status from the submitted returns."""
    doc = frappe.get_doc("Subcontract Challan", challan)
    back = {}
    for r in frappe.db.sql("select r.colour, r.size, sum(r.good_qty + r.reject_vendor_qty + r.reject_factory_qty) from `tabSubcontract Return Row` r "
                           "join `tabSubcontract Return` p on p.name = r.parent where p.docstatus = 1 and p.challan = %s group by r.colour, r.size", (challan,)):
        back["%s|%s" % (r[0], r[1])] = r[2] or 0
    total = 0
    for r in doc.rows:
        k = "%s|%s" % (r.colour, r.size)
        take = min(r.qty, back.get(k, 0))
        back[k] = back.get(k, 0) - take
        total = total + take
        frappe.db.set_value("Subcontract Challan Row", r.name, "returned_qty", take, update_modified=False)
    status = doc.status
    if status != "Short Closed":
        status = "Returned" if total >= doc.total_qty else ("Partly Returned" if total else "Open")
    frappe.db.set_value("Subcontract Challan", challan, {"returned_qty": total, "status": status}, update_modified=False)


def unit_value_for_card(card, basis):
    """Value of one piece for the penalty: the Cost Sheet FOB price, the Sales Order rate, or nothing for a fixed basis."""
    if basis == "Fixed Per Piece":
        return 0.0
    c = card_context(card)
    rows = frappe.db.sql("select i.rate, i.apparel_cost_sheet from `tabSales Order Item` i where i.parent = %s and i.item_code in "
                         "(select name from `tabItem` where variant_of = %s or name = %s) order by i.idx limit 1", (c.sales_order, c.style_item, c.style_item), as_dict=True)
    if not rows:
        return 0.0
    if basis == "Cost Sheet FOB" and rows[0].apparel_cost_sheet:
        price = frappe.db.get_value("Cost Sheet", rows[0].apparel_cost_sheet, "approved_price")
        if price:
            return frappe.utils.flt(price)
    return frappe.utils.flt(rows[0].rate)
