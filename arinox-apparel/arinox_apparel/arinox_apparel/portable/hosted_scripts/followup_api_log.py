# API arinox_followup_log_follow_up: record a call or a promise on a customer invoice. The note becomes a comment; the promise and the next
# action are fields; the status is recomputed.
def main():
    # include: lib_followup.py
    f = frappe.form_dict
    invoice = f.get("invoice")
    doc = frappe.get_doc("Sales Invoice", invoice)
    doc.check_permission("read")
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    allowed = False
    for r in ("Accounts User", "Accounts Manager", "Apparel Merchandising Manager", "System Manager"):
        if r in mine:
            allowed = True
    if not allowed:
        frappe.throw("Only accounts or merchandising managers log payment follow-up.")
    note = f.get("note")
    if not (note or "").strip():
        frappe.throw("Write what was said or agreed.")
    changes = {}
    if f.get("promise_date"):
        promised_on = frappe.utils.getdate(f.get("promise_date"))
        promised = frappe.utils.flt(f.get("promise_amount"))
        owed = frappe.utils.flt(doc.outstanding_amount)
        if promised_on < frappe.utils.getdate(frappe.utils.nowdate()):
            frappe.throw("The promised date is in the past. Log the new date the buyer gave.")
        if promised <= 0:
            frappe.throw("Enter the amount the buyer promised to pay.")
        if promised > owed + 0.005:
            frappe.throw("The promised amount %s is more than the %s still owed on this invoice." % (promised, owed))
        changes["apparel_promise_date"] = promised_on
        changes["apparel_promise_amount"] = promised
    if f.get("next_action_date"):
        changes["apparel_next_action_date"] = frappe.utils.getdate(f.get("next_action_date"))
    if f.get("dispute_reason") is not None:
        changes["apparel_dispute_reason"] = f.get("dispute_reason")
    if changes:
        frappe.db.set_value("Sales Invoice", invoice, changes, update_modified=False)
    doc.add_comment("Comment", note)
    si = frappe.db.get_value("Sales Invoice", invoice, ["outstanding_amount", "grand_total", "apparel_expected_due_date", "apparel_promise_date", "apparel_dispute_reason"], as_dict=True)
    got = status_for(si.outstanding_amount, si.grand_total, si.apparel_expected_due_date, frappe.utils.nowdate(), si.apparel_promise_date, bool(si.apparel_dispute_reason), 7)
    frappe.db.set_value("Sales Invoice", invoice, {"apparel_followup_status": got[0], "apparel_days_overdue": got[1]}, update_modified=False)
    frappe.flags.arinox_result = got[0]


main()
