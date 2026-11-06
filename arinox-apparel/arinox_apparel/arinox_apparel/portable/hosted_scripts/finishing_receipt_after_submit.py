# Finishing Receipt, After Submit: FIN_IN to the ledger, which the flow rules cap at what the previous route step released.
def run(doc):
    rows = [{"stage": "FIN_IN", "colour": r.colour, "size": r.size, "qty": r.qty, "line": doc.line, "supplier": doc.supplier, "shade_band": r.shade_band, "source_row": r.name} for r in doc.rows]
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Finishing Receipt", source_name=doc.name, posting_date=str(doc.receipt_date),
               override=0, check=1)


run(doc)
