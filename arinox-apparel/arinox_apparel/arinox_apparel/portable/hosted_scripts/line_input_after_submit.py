# Line Input, After Submit: SEW_IN goes to the ledger (shell bundles only) and the bundles are marked Issued to the line.
def run(doc):
    cint = frappe.utils.cint
    rows = []
    for r in doc.bundles:
        if (r.component or "Shell") != "Shell":
            continue
        rows.append({"stage": "SEW_IN", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": doc.purpose, "line": doc.line, "shade_band": r.shade_band, "source_row": r.name})
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Line Input", source_name=doc.name, posting_date=str(doc.input_date), override=0, check=1)
    for r in doc.bundles:
        if r.bundle:
            frappe.db.set_value("Cut Bundle", r.bundle, {"status": "Issued", "line": doc.line})


run(doc)
