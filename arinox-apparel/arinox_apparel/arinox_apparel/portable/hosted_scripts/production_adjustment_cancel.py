# Production Adjustment, After Cancel: remove what it wrote to the ledger.
run_script("arinox_engine", action="unpost", source_doctype="Production Adjustment", source_name=doc.name)
