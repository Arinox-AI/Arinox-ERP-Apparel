# PP Meeting, After Cancel: clear what it stamped.
def run(doc):
    try:
        run_script("arinox_tna", action="unstamp", source_doctype="PP Meeting", source_name=doc.name)
    except Exception:
        frappe.log_error(title="T&A hook PP meeting cancel failed", message=frappe.get_traceback())


run(doc)
