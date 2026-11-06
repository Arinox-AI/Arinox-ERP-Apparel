# Pilot Run, After Submit: the decision becomes the status; an approval stamps PILOT_RUN for each colour.
def run(doc):
    # include: lib_mat.py
    doc.db_set({"status": doc.decision, "approved_by": frappe.session.user, "approved_on": frappe.utils.now_datetime()})
    if doc.decision in ("Approved", "Approved with Comments"):
        card = frappe.db.get_value("Production Card", doc.production_card, ["sales_order", "style_item"], as_dict=True)
        for r in doc.colours:
            stamp_safe(card.sales_order, card.style_item, r.colour, "PILOT_RUN", doc.run_date, "Pilot Run", doc.name, False, False)


run(doc)
