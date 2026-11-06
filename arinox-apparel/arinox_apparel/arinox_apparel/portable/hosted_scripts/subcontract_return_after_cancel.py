# Subcontract Return, After Cancel: the ledger rows go and the challan is refreshed.
def run(doc):
    # include: lib_shipping.py
    # include: lib_subcontract.py
    run_script("arinox_engine", action="unpost", source_doctype="Subcontract Return", source_name=doc.name)
    refresh_returns(doc.challan)


run(doc)
