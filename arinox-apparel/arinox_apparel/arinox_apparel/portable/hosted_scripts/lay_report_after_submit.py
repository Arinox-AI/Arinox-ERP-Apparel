# Lay Report, After Submit: the cut pieces go to the production ledger (CUT and CUT_REJECT of the shell fabric), plies are numbered into Cut Bundles, remnants go back to the
# store, the card moves to In Cutting, a re-cut request is marked Cut, and a bulk shell lay stamps PCD.
def run(doc):
    # include: lib_mat.py
    # include: lib_cutting.py
    cint = frappe.utils.cint
    card = frappe.db.get_value("Production Card", doc.production_card, ["company", "sales_order", "style_item", "status"], as_dict=True)
    override = bool(cint(doc.gate_override) and (doc.gate_override_reason or "").strip())
    rows = []
    if doc.component == "Shell":      # the garment count follows the shell fabric
        for s in doc.sizes:
            rows.append({"stage": "CUT", "colour": doc.colour, "size": s.size, "qty": cint(s.pieces_cut), "purpose": doc.purpose, "shade_band": doc.shade_band, "line": doc.line, "source_row": s.name})
        for r in doc.panel_rejects:
            rows.append({"stage": "CUT_REJECT", "colour": doc.colour, "size": r.size, "qty": cint(r.qty), "purpose": doc.purpose, "shade_band": doc.shade_band, "fault_source": r.fault_source,
                         "source_row": r.name})
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Lay Report", source_name=doc.name, posting_date=str(doc.lay_date),
               override=1 if override else 0, check=1)
    make_bundles(doc)
    wh_cut = setting("cutting_wip_warehouse")
    wh_store = setting("store_warehouse_fabric")
    if wh_cut and wh_store:
        back = [{"item_code": doc.fabric_item, "qty": frappe.utils.flt(r.balance_returned_m), "s_warehouse": wh_cut, "t_warehouse": wh_store, "batch_no": r.batch}
                for r in doc.rolls if frappe.utils.flt(r.balance_returned_m) > 0]
        name = make_transfer(card.company, back, "Remnant Return", doc.production_card, "Remnants of %s" % doc.name, True)
        if name:
            doc.db_set("remnant_entry", name)
    if frappe.db.get_value("Production Card", doc.production_card, "status") == "Issued":
        frappe.db.set_value("Production Card", doc.production_card, "status", "In Cutting", update_modified=False)
    if doc.purpose == "Re-cut" and doc.recut_request:
        frappe.db.set_value("Recut Request", doc.recut_request, "status", "Cut")
    if doc.purpose == "Bulk" and doc.component == "Shell":
        stamp_safe(card.sales_order, card.style_item, doc.colour, "PCD", doc.lay_date, "Lay Report", doc.name, False, False)


run(doc)
