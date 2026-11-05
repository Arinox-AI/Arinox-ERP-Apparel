# Production Adjustment, Before Save: a manager's correction of a counting mistake needs an open card, a quantity and a reason.
def run(doc):
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    if not frappe.utils.flt(doc.qty):
        frappe.throw("Enter a quantity other than zero.")
    if not (doc.reason or "").strip():
        frappe.throw("Enter the reason for the adjustment.")
    if doc.stage in ("SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY") and not doc.subcontract_process:
        frappe.throw("Choose the process for stage %s." % doc.stage)
    if not frappe.db.exists("Production Card Line", {"parent": doc.production_card, "colour": doc.colour, "size": doc.size}):
        frappe.throw("%s %s is not on production card %s." % (doc.colour, doc.size, doc.production_card))


run(doc)
