# Work Order, After Save: the PCD milestone is the day cutting really started.
def run(doc):
    if not doc.get("sales_order") or not doc.get("actual_start_date"):
        return
    try:
        style = frappe.db.get_value("Item", doc.production_item, "variant_of")
        if style:
            attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
            colour = frappe.db.get_value("Item Variant Attribute", {"parent": doc.production_item, "attribute": attr}, "attribute_value")
            run_script("arinox_tna", action="stamp", sales_order=doc.sales_order, style_item=style, colour=colour, code="PCD", date=str(frappe.utils.getdate(doc.actual_start_date)),
                       source_doctype="Work Order", source_name=doc.name, partial=0, planned=0)
    except Exception:
        frappe.log_error(title="T&A hook work order failed", message=frappe.get_traceback())


run(doc)
