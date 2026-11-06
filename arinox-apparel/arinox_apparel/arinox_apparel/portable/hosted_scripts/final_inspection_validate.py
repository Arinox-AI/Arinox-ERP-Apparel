# Final Inspection, Before Save: the lot (packing lists), the AQL sample and accept/reject numbers, the defects found, the re-inspection chain
# and the result (Accepted needs every check passed and the defects within the plan; a concession needs the buyer's reference).
def run(doc):
    # include: lib_inspection.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    FINAL_TYPES = ("Final", "Re-inspection", "2nd Re-inspection")
    CHECKS = ("fpt", "gpt", "azo", "wash_care_ok", "fibre_ok", "sealer_style", "sealer_material", "sealer_colour", "sealer_construction",
              "metal_detection_ok", "measurement_ok", "drop_test_ok", "barcode_ok", "packing_ok")
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))

    def setting(field, default):
        v = frappe.db.get_single_value("Apparel Settings", field)
        if v is None or v == "":
            return default
        return v

    doc.inspection_type = doc.inspection_type or "Final"
    card = frappe.db.get_value("Production Card", doc.production_card, ["sales_order", "sales_contract", "customer", "style_item", "status", "docstatus"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    doc.sales_contract = card.sales_contract
    doc.sales_order = card.sales_order
    doc.customer = card.customer
    doc.style_item = card.style_item

    # ---- the lot
    if not doc.lots:
        frappe.throw("Add the packing lists in the lot.")
    seen = []
    pieces = 0
    cartons = 0
    for l in doc.lots:
        pl = frappe.db.get_value("Packing List", l.packing_list, ["docstatus", "production_card", "total_pieces", "total_cartons"], as_dict=True)
        if not pl or pl.docstatus != 1:
            frappe.throw("Packing list %s must be submitted." % l.packing_list)
        if pl.production_card != doc.production_card:
            frappe.throw("Packing list %s belongs to another production card." % l.packing_list)
        if l.packing_list in seen:
            frappe.throw("Packing list %s is in the lot twice." % l.packing_list)
        seen.append(l.packing_list)
        l.pieces = pl.total_pieces
        l.cartons = pl.total_cartons
        pieces = pieces + cint(pl.total_pieces)
        cartons = cartons + cint(pl.total_cartons)
    doc.offered_qty = pieces
    doc.total_cartons = cartons
    doc.po_qty = sum([cint(r.order_qty) for r in frappe.get_all("Production Card Line", {"parent": doc.production_card}, ["order_qty"])])
    doc.packed_pct = round((float(pieces) / float(doc.po_qty) * 100.0) if doc.po_qty else 0, 2)
    if doc.inspection_type in FINAL_TYPES and doc.docstatus == 0:
        blocked_below = flt(setting("final_block_packed_pct", 50))
        warn_below = flt(setting("final_min_packed_pct", 80))
        if doc.packed_pct < blocked_below:
            frappe.throw("Only %s %% of the order is packed. A final inspection needs at least %s %%; use Pre-Final for an earlier look." % (doc.packed_pct, blocked_below))
        if doc.packed_pct < warn_below:
            frappe.msgprint("Only %s %% of the order is packed (%s %% is expected for a final inspection)." % (doc.packed_pct, warn_below), indicator="orange")

    # ---- the AQL sample
    doc.aql_plan = doc.aql_plan or setting("final_inspection_plan", None)
    if not doc.aql_plan:
        frappe.throw("Choose the AQL Plan, or set one in Apparel Settings.")
    doc.inspection_level = frappe.db.get_value("AQL Plan", doc.aql_plan, "inspection_level")
    row = aql_row(doc.aql_plan, cint(doc.offered_qty))
    if not row or not cint(row.confirmed):
        frappe.throw("The AQL plan has no confirmed row for a lot of %s pieces. QA must fill in and confirm that row from ISO 2859-1 Table 2-A first." % doc.offered_qty)
    doc.sample_size = cint(row.sample_size)
    doc.critical_ac = cint(row.critical_ac)
    doc.critical_re = cint(row.critical_re) or 1
    doc.major_ac = cint(row.major_ac)
    doc.major_re = cint(row.major_re)
    doc.minor_ac = cint(row.minor_ac)
    doc.minor_re = cint(row.minor_re)
    if setting("carton_pick_rule", "Square Root") == "Fixed Pct":
        doc.inspected_cartons = max(1, int(frappe.utils.ceil(cint(doc.total_cartons) * 10 / 100.0))) if cint(doc.total_cartons) > 0 else 0
    else:
        doc.inspected_cartons = int(frappe.utils.ceil(cint(doc.total_cartons) ** 0.5)) if cint(doc.total_cartons) > 0 else 0
    if doc.sample_size > cint(doc.offered_qty):
        doc.sample_size = cint(doc.offered_qty)

    # ---- the defects found against the plan
    tot = {"Critical": 0, "Major": 0, "Minor": 0}
    for d in doc.defects:
        d.qty = cint(d.qty)
        if d.qty <= 0:
            frappe.throw("Defect %s: enter a quantity above zero." % d.defect_code)
        sev = frappe.db.get_value("Apparel Defect Code", d.defect_code, "severity") or "Minor"
        d.severity = sev
        tot[sev] = tot.get(sev, 0) + d.qty
    doc.critical_found = tot["Critical"]
    doc.major_found = tot["Major"]
    doc.minor_found = tot["Minor"]
    if doc.critical_found >= doc.critical_re or doc.major_found >= doc.major_re or doc.minor_found >= doc.minor_re:
        doc.computed_result = "Rejected"
    else:
        doc.computed_result = "Accepted"

    # ---- a re-inspection follows a rejected or on-hold inspection of the same lot; too many needs a manager
    if doc.inspection_type in ("Re-inspection", "2nd Re-inspection") and not doc.previous_inspection:
        frappe.throw("Name the inspection this one follows.")
    n = 0
    prev = doc.previous_inspection
    chain = []
    while prev and prev not in chain:
        chain.append(prev)
        n = n + 1
        prev = frappe.db.get_value("Final Inspection", prev, "previous_inspection")
    limit = cint(setting("reinspection_limit", 2))
    if n >= limit and "Apparel Production Manager" not in mine and "System Manager" not in mine:
        frappe.throw("This lot has already been inspected %s times. A Production Manager must approve another." % n)

    # ---- the result
    if doc.result:
        if doc.result == "Accepted":
            if doc.computed_result == "Rejected":
                frappe.throw("The defects found fail the AQL plan (%s critical, %s major, %s minor). Choose Rejected, On Hold, or Accepted with Concession." % (doc.critical_found, doc.major_found, doc.minor_found))
            failed = [doc.meta.get_label(c) for c in CHECKS if doc.get(c) == "No"]
            if failed:
                frappe.throw("These checks failed: %s. They cannot be Accepted without a concession." % ", ".join(failed))
        if doc.result == "Accepted with Concession":
            if not (doc.concession_ref or "").strip() or not (doc.approved_by or "").strip():
                frappe.throw("A concession needs the buyer's approval reference and who approved it.")


run(doc)
