# PP Meeting, After Submit: stamp the PP meeting (or pilot run) milestone.
def run(doc):
    try:
        run_script("arinox_tna", action="stamp", sales_order=doc.sales_order, style_item=doc.style_item, colour=None, code="PILOT_RUN" if doc.meeting_type == "Pilot Run" else "PP_MEETING",
                   date=str(doc.meeting_date), source_doctype="PP Meeting", source_name=doc.name, partial=0, planned=0)
    except Exception:
        frappe.log_error(title="T&A hook PP meeting failed", message=frappe.get_traceback())


run(doc)
