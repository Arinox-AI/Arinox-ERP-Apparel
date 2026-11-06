# Daily Line Report, After Cancel: the ledger rows go and the bundle quantities are taken back.
def run(doc):
    cint = frappe.utils.cint
    run_script("arinox_engine", action="unpost", source_doctype="Daily Line Report", source_name=doc.name)
    for r in doc.outputs:
        if r.bundle:
            b = frappe.db.get_value("Cut Bundle", r.bundle, ["qty", "sewn_qty", "rejected_qty"], as_dict=True)
            sewn = max(cint(b.sewn_qty) - cint(r.qty), 0)
            frappe.db.set_value("Cut Bundle", r.bundle, {"sewn_qty": sewn, "status": "Complete" if sewn + cint(b.rejected_qty) >= cint(b.qty) else "Issued"})


run(doc)
