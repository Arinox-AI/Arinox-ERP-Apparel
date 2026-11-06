# Packing List, Before Save: the card must be open; carton rows are contiguous, never overlap, start at the start number and have contents;
# totals and the packed-versus-ordered summary are computed here.
def run(doc):
    # include: lib_packing.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt

    card = frappe.db.get_value("Production Card", doc.production_card, ["sales_order", "sales_contract", "customer", "style_item", "status", "docstatus"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    doc.sales_contract = card.sales_contract
    doc.sales_order = card.sales_order
    doc.customer = card.customer
    doc.style_item = card.style_item
    if not cint(doc.pcs_per_carton) or cint(doc.pcs_per_carton) <= 0:
        frappe.throw("Enter the pieces per carton.")

    default = None
    if doc.carton_type:
        default = frappe.db.get_value("Shipment Parcel Template", doc.carton_type, ["length", "width", "height"], as_dict=True)
    for c in doc.cartons:
        if default and not (flt(c.length_cm) and flt(c.width_cm) and flt(c.height_cm)):
            c.length_cm = default.length
            c.width_cm = default.width
            c.height_cm = default.height
        if not c.carton_type:
            c.carton_type = doc.carton_type

    if doc.cartons or doc.docstatus == 1:
        if not doc.cartons:
            frappe.throw("Add the cartons, or use Generate Cartons.")
        problems = check_ranges([[c.carton_from, c.carton_to] for c in doc.cartons])
        first = min([cint(c.carton_from) for c in doc.cartons])
        if first != cint(doc.carton_start or 1):
            problems.append("Cartons must start at %s." % cint(doc.carton_start or 1))
        if problems:
            frappe.throw("<br>".join(problems), title="Carton numbers")
        for c in doc.cartons:
            c.carton_count = cint(c.carton_to) - cint(c.carton_from) + 1
            c.cbm_per_carton = round(carton_cbm(c.length_cm or 0, c.width_cm or 0, c.height_cm or 0), 6)
            c.total_cbm = round(c.cbm_per_carton * c.carton_count, 6)

        items = frappe.get_all("Sales Order Item", {"parent": doc.sales_order}, ["name", "apparel_colour", "apparel_size", "apparel_ship_to", "apparel_buyer_po"])
        on_card = []
        for l in frappe.get_all("Production Card Line", {"parent": doc.production_card}, ["colour", "size"]):
            on_card.append((l.colour, l.size))
        by_row = {}
        for ct in doc.contents:
            ct.qty_per_carton = cint(ct.qty_per_carton)
            if ct.qty_per_carton <= 0:
                frappe.throw("Carton content row %s: enter a quantity above zero." % ct.idx)
            if (ct.colour, ct.size) not in on_card:
                frappe.throw("Carton content row %s: %s %s is not on production card %s." % (ct.idx, ct.colour, ct.size, doc.production_card))
            cands = [i for i in items if i.apparel_colour == ct.colour and i.apparel_size == ct.size]
            if doc.ship_to and [i for i in cands if i.apparel_ship_to]:
                cands = [i for i in cands if (i.apparel_ship_to or "") == doc.ship_to]
            if doc.buyer_po and [i for i in cands if i.apparel_buyer_po]:
                cands = [i for i in cands if (i.apparel_buyer_po or "") == doc.buyer_po]
            if not cands:
                frappe.throw("%s %s (ship to %s) is not on Sales Order %s." % (ct.colour, ct.size, doc.ship_to or "-", doc.sales_order))
            ct.sales_order_item = cands[0].name
            by_row[cint(ct.carton_from)] = by_row.get(cint(ct.carton_from), 0) + ct.qty_per_carton
        for c in doc.cartons:
            got = by_row.get(cint(c.carton_from), 0)
            if not got:
                frappe.throw("Cartons %s~%s have no contents." % (c.carton_from, c.carton_to))
            c.pieces_per_carton = got
            c.total_pieces = got * c.carton_count
        known = [cint(c.carton_from) for c in doc.cartons]
        for k in by_row:
            if k not in known:
                frappe.throw("Contents point at carton row %s, which does not exist." % k)
        for ct in doc.contents:
            for c in doc.cartons:
                if cint(c.carton_from) == cint(ct.carton_from):
                    ct.pieces_total = ct.qty_per_carton * c.carton_count

    doc.total_cartons = sum([c.carton_count or 0 for c in doc.cartons])
    doc.total_pieces = sum([c.total_pieces or 0 for c in doc.cartons])
    doc.total_net_kg = round(sum([flt(c.net_weight_kg) * (c.carton_count or 0) for c in doc.cartons]), 3)
    doc.total_gross_kg = round(sum([flt(c.gross_weight_kg) * (c.carton_count or 0) for c in doc.cartons]), 3)
    doc.total_cbm = round(sum([c.total_cbm or 0 for c in doc.cartons]), 6)

    packed = packed_by_key(doc.production_card, doc.name, [0, 1], None)
    for ct in doc.contents:
        k = (ct.colour, ct.size)
        packed[k] = packed.get(k, 0) + cint(ct.pieces_total)
    ordered = {}
    on_lines = []
    for l in frappe.get_all("Production Card Line", {"parent": doc.production_card}, ["colour", "size"]):
        on_lines.append((l.colour, l.size))
    for i in frappe.get_all("Sales Order Item", {"parent": doc.sales_order}, ["apparel_colour", "apparel_size", "qty"]):
        k = (i.apparel_colour, i.apparel_size)
        if k in on_lines:
            ordered[k] = ordered.get(k, 0) + flt(i.qty)
    summary = size_summary(packed, ordered)
    doc.size_summary = summary[0]
    doc.total_vs_order_pct = summary[1]


run(doc)
