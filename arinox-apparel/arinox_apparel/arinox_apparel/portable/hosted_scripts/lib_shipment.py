# shared helpers from shipping/shipment.py and freight.py: the shipment status from its dates and documents, the freight estimate / actual, and the allocation of freight over
# the orders on board. Needs lib_shipping.py (settings_value).
def over_short_pct(shipped, ordered):
    if not float(ordered or 0):
        return None
    return (float(shipped) - float(ordered)) / float(ordered) * 100.0


def refresh_status(shipment):
    if not frappe.db.exists("Shipment", shipment):
        return
    d = frappe.db.get_value("Shipment", shipment, ["apparel_ship_status", "apparel_booking_no", "apparel_on_board_date", "apparel_arrival_date", "apparel_delivery_date"], as_dict=True)
    if d.apparel_ship_status in ("On Hold", "Closed"):
        return        # set by a person; the dates and documents do not reopen it
    cleared = frappe.db.exists("Shipment Declaration", {"parent": shipment, "status": "Cleared"})
    handed = frappe.db.exists("Delivery Note", {"apparel_shipment": shipment, "docstatus": 1})
    prepared = frappe.db.exists("Sales Invoice", {"apparel_shipment": shipment, "docstatus": ["<", 2]})
    if d.apparel_delivery_date:
        status = "Delivered"
    elif d.apparel_arrival_date:
        status = "Arrived"
    elif d.apparel_on_board_date:
        status = "On Board"
    elif cleared:
        status = "Customs Cleared"
    elif handed:
        status = "Cargo Handed Over"
    elif prepared:
        status = "Documents Prepared"
    elif d.apparel_booking_no:
        status = "Booked"
    else:
        status = "Planned"
    if status != d.apparel_ship_status:
        frappe.db.set_value("Shipment", shipment, "apparel_ship_status", status, update_modified=False)


def refresh_costs(shipment):
    """Estimate (the chosen quote), actual (the forwarder's invoices not cancelled) and the gap, written onto the shipment."""
    flt = frappe.utils.flt
    if not frappe.db.exists("Shipment", shipment):
        return
    quote = frappe.db.get_value("Shipment", shipment, "apparel_freight_quote")
    estimate = flt(frappe.db.get_value("Supplier Quotation", quote, "base_grand_total")) if quote else 0
    actual = flt(frappe.db.sql("select ifnull(sum(base_grand_total), 0) from `tabPurchase Invoice` where apparel_shipment = %s and docstatus < 2 and ifnull(is_return, 0) = 0", (shipment,))[0][0])
    pct = over_short_pct(actual, estimate) if estimate and actual else 0
    frappe.db.set_value("Shipment", shipment, {"apparel_estimate_total": estimate, "apparel_actual_total": actual, "apparel_cost_variance_pct": round(pct or 0, 2)}, update_modified=False)
    limit = flt(settings_value("freight_estimate_variance_pct", 10))
    if estimate and actual and abs(pct or 0) > limit:
        frappe.msgprint("Forwarder bills are %s %s %% against the quote (%s vs %s)." % ("over" if pct > 0 else "under", round(abs(pct), 1), actual, estimate), indicator="orange", title="Freight cost")


def allocation_basis(shipment):
    """Share of a shipment's cost per order: by CBM at sea, by chargeable weight by air. Returns [{contract: share}, basis field]."""
    flt = frappe.utils.flt
    mode = frappe.db.get_value("Shipment", shipment, "apparel_mode")
    rows = frappe.get_all("Shipment Packing List", filters={"parent": shipment}, fields=["packing_list", "sales_contract", "cbm", "gross_kg"])
    use = "gross_kg" if mode == "Air" else "cbm"
    total = sum([flt(r.get(use)) for r in rows])
    out = {}
    for r in rows:
        key = r.sales_contract or frappe.db.get_value("Packing List", r.packing_list, "sales_order")
        out[key] = out.get(key, 0) + (flt(r.get(use)) / total if total else 1.0 / len(rows))
    return [out, use]


def allocated_costs(shipment):
    """[[contract, share, cost], ...], basis field, cost: the shipment's actual cost (estimate while no bill has arrived) shared by the basis."""
    flt = frappe.utils.flt
    d = frappe.db.get_value("Shipment", shipment, ["apparel_estimate_total", "apparel_actual_total"], as_dict=True)
    cost = flt(d.apparel_actual_total) or flt(d.apparel_estimate_total)
    ab = allocation_basis(shipment)
    return [[k, round(ab[0][k], 6), round(cost * ab[0][k], 2)] for k in sorted(ab[0])], ab[1], cost
