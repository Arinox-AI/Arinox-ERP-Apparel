# Daily Line Report, After Submit: SEW_OUT goes to the ledger per card, and the bundles move (sewn quantity, Complete when fully reported).
def run(doc):
    cint = frappe.utils.cint
    by_card = {}
    order = []
    for r in doc.outputs:
        k = "c|" + r.production_card
        if k not in by_card:
            by_card[k] = []
            order.append(r.production_card)
        by_card[k].append({"stage": "SEW_OUT", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": r.purpose or "Bulk", "line": doc.line, "source_row": r.name})
    for card in order:
        run_script("arinox_engine", action="post", card=card, rows=json.dumps(by_card["c|" + card]), source_doctype="Daily Line Report", source_name=doc.name,
                   posting_date=str(doc.report_date), override=0, check=1)
    for r in doc.outputs:
        if r.bundle:
            b = frappe.db.get_value("Cut Bundle", r.bundle, ["qty", "sewn_qty", "rejected_qty"], as_dict=True)
            sewn = max(cint(b.sewn_qty) + cint(r.qty), 0)
            frappe.db.set_value("Cut Bundle", r.bundle, {"sewn_qty": sewn, "status": "Complete" if sewn + cint(b.rejected_qty) >= cint(b.qty) else "Issued"})


run(doc)
