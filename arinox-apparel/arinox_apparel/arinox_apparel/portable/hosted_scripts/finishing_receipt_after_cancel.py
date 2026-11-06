# Finishing Receipt, After Cancel: the ledger rows go.
run_script("arinox_engine", action="unpost", source_doctype="Finishing Receipt", source_name=doc.name)
