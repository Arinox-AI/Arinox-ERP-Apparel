# Subcontract Challan, After Submit: SC_OUT to the ledger against the process on the card's route; status Open.
def run(doc):
    rows = [{"stage": "SC_OUT", "colour": r.colour, "size": r.size, "qty": r.qty, "process": doc.subcontract_process, "supplier": doc.supplier, "shade_band": r.shade_band, "source_row": r.name}
            for r in doc.rows]
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Subcontract Challan", source_name=doc.name,
               posting_date=str(doc.challan_date), override=0, check=1)
    frappe.db.set_value("Subcontract Challan", doc.name, "status", "Open", update_modified=False)


run(doc)
