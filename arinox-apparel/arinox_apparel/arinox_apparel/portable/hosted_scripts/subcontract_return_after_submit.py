# Subcontract Return, After Submit: SC_BACK_GOOD / SC_BACK_REJECT_VENDOR / SC_BACK_REJECT_FACTORY to the ledger, and the challan's returned quantities and status are refreshed.
def run(doc):
    # include: lib_shipping.py
    # include: lib_subcontract.py
    rows = []
    for r in doc.rows:
        base = {"colour": r.colour, "size": r.size, "process": doc.subcontract_process, "supplier": doc.supplier, "shade_band": r.shade_band, "source_row": r.name}
        if r.good_qty:
            d = dict(base)
            d.update({"stage": "SC_BACK_GOOD", "qty": r.good_qty})
            rows.append(d)
        if r.reject_vendor_qty:
            d = dict(base)
            d.update({"stage": "SC_BACK_REJECT_VENDOR", "qty": r.reject_vendor_qty, "fault_source": "Subcontractor"})
            rows.append(d)
        if r.reject_factory_qty:
            fault = (frappe.db.get_value("Apparel Defect Code", r.defect_code, "fault_source") if r.defect_code else None) or "Unknown"
            d = dict(base)
            d.update({"stage": "SC_BACK_REJECT_FACTORY", "qty": r.reject_factory_qty, "fault_source": fault})
            rows.append(d)
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Subcontract Return", source_name=doc.name,
               posting_date=str(doc.return_date), override=0, check=0)
    refresh_returns(doc.challan)


run(doc)
