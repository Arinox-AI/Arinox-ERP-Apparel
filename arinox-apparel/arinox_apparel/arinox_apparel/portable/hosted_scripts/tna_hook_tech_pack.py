# Tech Pack, After Submit: the tech pack (and BOM) received milestones of every plan of this style.
def run(doc):
    if doc.docstatus != 1 or not doc.style_item:
        return
    try:
        for t in frappe.get_all("Order TNA", filters={"style_item": doc.style_item, "status": ["!=", "Cancelled"]}, fields=["sales_order", "colour"]):
            run_script("arinox_tna", action="stamp", sales_order=t.sales_order, style_item=doc.style_item, colour=t.colour, code="TECH_PACK_RECEIVED",
                       date=str(doc.received_on or frappe.utils.nowdate()), source_doctype="Tech Pack", source_name=doc.name, partial=0, planned=0)
            if doc.buyer_bom_file:
                run_script("arinox_tna", action="stamp", sales_order=t.sales_order, style_item=doc.style_item, colour=t.colour, code="BOM_RECEIVED",
                           date=str(doc.received_on or frappe.utils.nowdate()), source_doctype="Tech Pack", source_name=doc.name, partial=0, planned=0)
    except Exception:
        frappe.log_error(title="T&A hook tech pack failed", message=frappe.get_traceback())


run(doc)
