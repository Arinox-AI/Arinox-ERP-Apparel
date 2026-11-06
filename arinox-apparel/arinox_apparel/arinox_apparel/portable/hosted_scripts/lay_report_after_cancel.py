# Lay Report, After Cancel: bundles voided (their numbers never reused; blocked once a bundle left the cutting room), ledger rows removed, remnant entry cancelled,
# a re-cut request is open again, the PCD stamp cleared.
def run(doc):
    # include: lib_mat.py
    # include: lib_cutting.py
    void_bundles(doc.name)
    run_script("arinox_engine", action="unpost", source_doctype="Lay Report", source_name=doc.name)
    if doc.remnant_entry:
        cancel_entry(doc.remnant_entry)
        doc.db_set("remnant_entry", None)
    if doc.purpose == "Re-cut" and doc.recut_request:
        frappe.db.set_value("Recut Request", doc.recut_request, "status", "Open")
    unstamp_safe("Lay Report", doc.name)


run(doc)
