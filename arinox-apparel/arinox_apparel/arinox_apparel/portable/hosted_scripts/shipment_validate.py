# Shipment, Before Save: the packing lists on board (submitted, free, one customer), their totals, parcels and goods value, air on a sea contract needs a reason,
# and declared / booked / carrier / customs measures are compared and noted, never overwritten.
def run(doc):
    # include: lib_shipping.py
    # include: lib_shipment.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    PL_FIELDS = ["name", "sales_contract", "buyer_po", "total_cartons", "total_pieces", "total_net_kg", "total_gross_kg", "total_cbm", "customer", "sales_order", "production_card",
                 "ship_to", "docstatus", "shipment", "status"]
    lists = [r.packing_list for r in (doc.get("apparel_packing_lists") or []) if r.packing_list]
    before = doc.get_doc_before_save()
    if before:
        for r in before.get("apparel_packing_lists") or []:
            if r.packing_list not in lists and frappe.db.get_value("Packing List", r.packing_list, "status") == "Shipped":
                frappe.throw("Packing list %s has shipped on a Delivery Note and cannot be taken off the shipment." % r.packing_list)
    if not lists:
        return
    seen = []
    rows = {}
    order = []
    for r in doc.apparel_packing_lists:
        if r.packing_list in seen:
            frappe.throw("Packing list %s is on this shipment twice." % r.packing_list)
        seen.append(r.packing_list)
        pl = frappe.db.get_value("Packing List", r.packing_list, PL_FIELDS, as_dict=True)
        if not pl or pl.docstatus != 1:
            frappe.throw("Packing list %s must be submitted." % r.packing_list)
        if pl.shipment and pl.shipment != doc.name:
            frappe.throw("Packing list %s is already on shipment %s." % (r.packing_list, pl.shipment))
        rows["p|" + r.packing_list] = pl
        order.append(r.packing_list)
        r.sales_contract = pl.sales_contract
        r.buyer_po = pl.buyer_po
        r.cartons = pl.total_cartons
        r.pieces = pl.total_pieces
        r.net_kg = pl.total_net_kg
        r.gross_kg = pl.total_gross_kg
        r.cbm = pl.total_cbm
    plist = [rows["p|" + n] for n in order]
    customers = []
    for p in plist:
        if p.customer not in customers:
            customers.append(p.customer)
    if len(customers) > 1:
        frappe.throw("All packing lists on a shipment must be for one customer (%s)." % ", ".join(sorted([c or "-" for c in customers])))
    contracts = []
    for p in plist:
        c = p.sales_contract or p.sales_order
        if c not in contracts:
            contracts.append(c)
    doc.apparel_contracts = "\n".join(sorted(contracts))
    doc.apparel_declared_cbm = round(sum([flt(p.total_cbm) for p in plist]), 6)
    doc.apparel_declared_gross_kg = round(sum([flt(p.total_gross_kg) for p in plist]), 3)
    if not doc.shipment_parcel:
        groups = {}
        keys = []
        for n in order:
            for c in frappe.get_all("Packing List Carton", filters={"parent": n}, fields=["length_cm", "width_cm", "height_cm", "gross_weight_kg", "carton_count"]):
                k = (flt(c.length_cm), flt(c.width_cm), flt(c.height_cm), flt(c.gross_weight_kg))
                if k not in groups:
                    groups[k] = 0
                    keys.append(k)
                groups[k] = groups[k] + cint(c.carton_count)
        for k in sorted(keys):
            doc.append("shipment_parcel", {"length": k[0], "width": k[1], "height": k[2], "weight": k[3], "count": groups[k]})
    doc.description_of_content = doc.description_of_content or "Garments, contract(s) %s" % ", ".join(sorted(contracts))
    if not flt(doc.value_of_goods):
        total = 0.0
        for n in order:
            for ct in frappe.get_all("Packing List Content", filters={"parent": n}, fields=["pieces_total", "sales_order_item"]):
                rate = frappe.db.get_value("Sales Order Item", ct.sales_order_item, "rate") if ct.sales_order_item else 0
                total = total + cint(ct.pieces_total) * flt(rate)
        doc.value_of_goods = round(total, 2)
    contract_mode = None
    for c in (doc.apparel_contracts or "").splitlines():
        if frappe.db.exists("Sales Contract", c):
            contract_mode = frappe.db.get_value("Sales Contract", c, "shipment_mode")
    if doc.apparel_mode == "Air" and contract_mode == "Sea":
        if not (doc.apparel_reason_for_air or "").strip() or not doc.apparel_air_cost_borne_by:
            frappe.throw("The contract is for sea freight. Say why this goes by air and who pays the difference.")
    notes = []
    cbm_tol = flt(settings_value("measure_variance_warn_pct", 5))
    kg_tol = flt(settings_value("weight_variance_warn_pct", 2))
    for t in (["Booked CBM", doc.apparel_declared_cbm, doc.apparel_booked_cbm, cbm_tol], ["Carrier CBM", doc.apparel_declared_cbm, doc.apparel_carrier_cbm, cbm_tol],
              ["Booked weight", doc.apparel_declared_gross_kg, doc.apparel_booked_gross_kg, kg_tol], ["Carrier weight", doc.apparel_declared_gross_kg, doc.apparel_carrier_gross_kg, kg_tol],
              ["Customs weight", doc.apparel_declared_gross_kg, doc.apparel_customs_gross_kg, kg_tol]):
        if flt(t[2]) and flt(t[1]):
            diff = over_short_pct(t[2], t[1])
            if abs(diff) > t[3]:
                notes.append("%s %s against %s on the packing lists (%+.2f %%)." % (t[0], t[2], t[1], diff))
    doc.apparel_measure_note = "\n".join(notes)
    if notes and doc.docstatus == 0:
        frappe.msgprint("<br>".join(notes), indicator="orange", title="Measures differ")


run(doc)
