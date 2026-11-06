# Line Input, After Cancel: the ledger rows go and the bundles return to the cutting room (or to "Back" when a before-sewing process is on the route).
def run(doc):
    run_script("arinox_engine", action="unpost", source_doctype="Line Input", source_name=doc.name)
    back = frappe.db.exists("Production Card Process", {"parent": doc.production_card, "position": "Before Sewing"})
    for r in doc.bundles:
        if r.bundle:
            frappe.db.set_value("Cut Bundle", r.bundle, {"status": "Back" if back else "Cut", "line": None})


run(doc)
