# API arinox_production_card_revise_production_card: a new draft from an issued card, quantities refreshed from the current Sales Order
# when it is saved. (Cancel-and-amend is not used: cutting may already have started.)
def main():
    src = frappe.get_doc("Production Card", frappe.form_dict.get("source_name"))
    src.check_permission("read")
    if src.docstatus != 1 or src.status in ("Superseded", "Cancelled"):
        frappe.throw("Only an issued, current production card can be revised.")
    new = frappe.copy_doc(src)
    new.previous_card = src.name
    new.revision_no = frappe.utils.cint(src.revision_no) + 1
    new.revision_reason = None
    new.status = "Draft"
    new.issue_date = None
    new.arinox_name = None
    for r in new.lines:
        r.planned_cut_qty = None
    frappe.flags.arinox_result = new.as_dict()


main()
