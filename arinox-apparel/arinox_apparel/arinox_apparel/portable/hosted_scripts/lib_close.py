# shared helper from shipping/close.py: the commercial-close checklist of an order, as [label, ok, detail] rows. Pure reading; nothing is changed.
def checklist(sales_order):
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    out = []
    cards = frappe.get_all("Production Card", filters={"sales_order": sales_order, "docstatus": 1, "status": ["not in", ["Superseded", "Cancelled"]]}, fields=["name", "status"])
    open_cards = [c.name for c in cards if c.status not in ("Shipped", "Closed")]
    out.append(["Production finished", bool(cards) and not open_cards, ", ".join(open_cards) or ("no production card" if not cards else "")])
    dn_names = [r[0] for r in frappe.db.sql("select distinct parent from `tabDelivery Note Item` where against_sales_order = %s and docstatus = 1", (sales_order,))] or [""]
    dns = frappe.get_all("Delivery Note", filters={"docstatus": 1, "name": ["in", dn_names]}, fields=["name", "status"])
    unbilled = []
    for dn in dns:
        shipment = frappe.db.get_value("Delivery Note", dn.name, "apparel_shipment")
        billed = frappe.db.exists("Sales Invoice Item", {"delivery_note": dn.name, "docstatus": 1}) or (shipment and frappe.db.exists("Sales Invoice", {"apparel_shipment": shipment, "docstatus": 1}))
        if not billed:
            unbilled.append(dn.name)
    out.append(["Everything shipped is invoiced", bool(dns) and not unbilled, ", ".join(unbilled) or ("nothing shipped" if not dns else "")])
    contract = frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract")
    filters = {"docstatus": 1, "is_internal_customer": 0, "is_return": 0}
    if contract:
        filters["apparel_sales_contract"] = contract
    else:
        filters["name"] = ["in", [r[0] for r in frappe.db.sql("select distinct parent from `tabSales Invoice Item` where sales_order = %s", (sales_order,))] or [""]]
    unpaid = [i.name for i in frappe.get_all("Sales Invoice", filters=filters, fields=["name", "outstanding_amount"]) if flt(i.outstanding_amount) > 0.005]
    out.append(["Customer invoices paid", not unpaid, ", ".join(unpaid)])
    claims = frappe.get_all("Buyer Claim", filters={"sales_contract": contract, "docstatus": ["<", 2], "status": ["in", ["Open", "Under Review"]]}, pluck="name") if contract else []
    out.append(["No claim open", not claims, ", ".join(claims)])
    waiting = []
    if contract and frappe.db.exists("Sales Contract", contract):
        v = frappe.db.get_value("Sales Contract", contract, ["quality_claim_days", "quantity_claim_days"])
        longest = max(cint(v[0]), cint(v[1]))
        for s in frappe.get_all("Shipment", filters={"apparel_contracts": ["like", "%" + contract + "%"], "docstatus": ["<", 2]}, fields=["name", "apparel_contracts", "apparel_arrival_date", "apparel_delivery_date"]):
            if contract not in (s.apparel_contracts or "").splitlines():
                continue      # a longer contract number that merely contains this one
            arrival = s.apparel_arrival_date or s.apparel_delivery_date
            if not arrival or frappe.utils.date_diff(frappe.utils.nowdate(), arrival) <= longest:
                waiting.append(s.name)
    out.append(["Claim windows over", not waiting, ", ".join(waiting)])
    return out
