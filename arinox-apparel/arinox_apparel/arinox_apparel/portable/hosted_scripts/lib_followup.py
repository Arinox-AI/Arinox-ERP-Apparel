# shared helpers: the expected due date of a customer invoice and its follow-up status (shipping/followup.py)
def expected_due(basis, days, invoice_date, on_board, eta, delivery, buffer_days, transit_days):
    """[basis date, where it came from, expected due date]. ROG counts from the recorded delivery; until then from the arrival plus a
    buffer; until there is an arrival, from the sailing date plus the transit time."""
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    add_days = frappe.utils.add_days
    days = cint(days)
    inv = getdate(invoice_date)
    d = inv
    src = "Invoice"
    if basis == "Days after B/L Date":
        if on_board:
            d = getdate(on_board)
            src = "B/L"
        else:
            src = "Invoice (no B/L yet)"
    elif basis == "Days after ETA":
        if eta:
            d = getdate(eta)
            src = "ETA"
        else:
            src = "Invoice (no ETA yet)"
    elif basis == "Days after Receipt of Goods (ROG)":
        if delivery:
            d = getdate(delivery)
            src = "Delivery"
        elif eta:
            d = add_days(getdate(eta), cint(buffer_days))
            src = "ETA + buffer"
        elif on_board:
            d = add_days(getdate(on_board), cint(transit_days) + cint(buffer_days))
            src = "B/L + transit + buffer"
        else:
            src = "Invoice (no dates yet)"
    return [d, src, add_days(d, days)]


def contract_terms(contract):
    """[payment basis, payment days, transit days] of a contract, or [None, 0, 0]."""
    if not contract or not frappe.db.exists("Sales Contract", contract):
        return [None, 0, 0]
    v = frappe.db.get_value("Sales Contract", contract, ["payment_basis", "payment_days", "transit_days"])
    return [v[0], v[1], v[2]] if v else [None, 0, 0]


def refresh_invoice(name):
    """Recompute the expected due date of one invoice from its contract terms and its shipment's dates."""
    si = frappe.db.get_value("Sales Invoice", name, ["apparel_sales_contract", "apparel_shipment", "posting_date", "docstatus", "apparel_route_leg", "is_internal_customer"], as_dict=True)
    if not si or si.docstatus == 2 or frappe.utils.cint(si.is_internal_customer):
        return None
    terms = contract_terms(si.apparel_sales_contract)
    ship = None
    if si.apparel_shipment:
        ship = frappe.db.get_value("Shipment", si.apparel_shipment, ["apparel_on_board_date", "apparel_eta", "apparel_delivery_date", "apparel_arrival_date"], as_dict=True)
    arrival = (ship.apparel_arrival_date or ship.apparel_eta) if ship else None
    buffer_days = frappe.db.get_single_value("Apparel Settings", "rog_buffer_days")
    if buffer_days is None or buffer_days == "":
        buffer_days = 5
    got = expected_due(terms[0], terms[1], si.posting_date, ship.apparel_on_board_date if ship else None, arrival, ship.apparel_delivery_date if ship else None, buffer_days, terms[2])
    frappe.db.set_value("Sales Invoice", name, {"apparel_due_basis": terms[0] or "", "apparel_basis_date": got[0], "apparel_expected_due_date": got[2], "apparel_basis_source": got[1]}, update_modified=False)
    return got[2]


def status_for(outstanding, grand_total, due, today, promise, disputed, soon_days):
    """[status, days overdue] for one invoice."""
    flt = frappe.utils.flt
    getdate = frappe.utils.getdate
    today = getdate(today)
    if flt(outstanding) <= 0.005:
        return ["Paid", 0]
    overdue = (today - getdate(due)).days if due else 0
    if disputed:
        return ["Disputed", max(overdue, 0)]
    if overdue > 0:
        if promise and getdate(promise) >= today:
            return ["Promised", overdue]
        return ["Overdue", overdue]
    if flt(outstanding) < flt(grand_total) - 0.005:
        return ["Partly Paid", 0]
    if due and (getdate(due) - today).days <= soon_days:
        return ["Due Soon", 0]
    return ["Not Due", 0]
