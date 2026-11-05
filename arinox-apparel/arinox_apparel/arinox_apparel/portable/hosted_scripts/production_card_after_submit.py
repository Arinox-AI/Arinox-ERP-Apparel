# Production Card, After Submit: mark issued; a revision supersedes its predecessor and takes over its history.
def run(doc):
    doc.db_set({"issue_date": frappe.utils.nowdate(), "status": "Issued"})
    if doc.previous_card:
        frappe.db.set_value("Production Card", doc.previous_card, "status", "Superseded")
        run_script("arinox_engine", action="transfer", old=doc.previous_card, new=doc.name)
    for name in frappe.get_all("PP Meeting", {"sales_order": doc.sales_order, "style_item": doc.style_item, "docstatus": 0}, pluck="name"):
        frappe.db.set_value("PP Meeting", name, {"production_card_ref": doc.name, "production_card_issued_on": frappe.utils.nowdate()}, update_modified=False)


run(doc)
