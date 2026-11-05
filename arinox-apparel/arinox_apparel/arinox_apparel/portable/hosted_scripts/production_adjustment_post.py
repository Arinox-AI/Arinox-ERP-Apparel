# Production Adjustment, After Submit: write the signed quantity to the production ledger (never checked against the flow).
def run(doc):
    rows = [{"stage": doc.stage, "colour": doc.colour, "size": doc.size, "qty": frappe.utils.flt(doc.qty), "purpose": doc.purpose or "Bulk",
             "process": doc.subcontract_process, "source_row": doc.name}]
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Production Adjustment",
               source_name=doc.name, posting_date=str(doc.posting_date), check="0")


run(doc)
