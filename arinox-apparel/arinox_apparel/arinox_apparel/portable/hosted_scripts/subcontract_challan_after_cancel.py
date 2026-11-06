# Subcontract Challan, After Cancel: the ledger rows go.
run_script("arinox_engine", action="unpost", source_doctype="Subcontract Challan", source_name=doc.name)
