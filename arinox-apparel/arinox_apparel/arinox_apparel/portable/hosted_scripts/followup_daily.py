# Scheduler (Daily): refresh every open customer invoice's follow-up status and raise a ToDo when it crosses a reminder or escalation line.
def main():
    # include: lib_followup.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt

    def setting(field, default):
        v = frappe.db.get_single_value("Apparel Settings", field)
        if v is None or v == "":
            return default
        return v

    today = frappe.utils.getdate(frappe.utils.nowdate())
    soon = cint(setting("reminder_days_before_due", 7))
    levels = [[cint(setting("escalation_days_1", 15)), "Send a payment reminder (Dunning level 1)"], [cint(setting("escalation_days_2", 30)), "Second reminder and manager attention"],
              [cint(setting("escalation_days_3", 60)), "Escalate to management"]]

    def todo(si, description, key):
        ref = si.name + ":" + key
        if frappe.db.exists("ToDo", {"reference_type": "Sales Invoice", "reference_name": si.name, "description": ["like", "%[" + ref + "]%"]}):
            return
        frappe.get_doc({"doctype": "ToDo", "allocated_to": si.owner, "reference_type": "Sales Invoice", "reference_name": si.name,
                        "description": description + " [" + ref + "]", "priority": "Medium"}).insert(ignore_permissions=True)

    rows = frappe.get_all("Sales Invoice", {"docstatus": 1, "is_internal_customer": 0, "is_return": 0},
                          ["name", "outstanding_amount", "grand_total", "apparel_expected_due_date", "apparel_promise_date", "apparel_dispute_reason", "customer", "owner", "apparel_followup_status"],
                          or_filters=[["apparel_shipment", "is", "set"], ["apparel_is_sample_invoice", "=", 1]])
    for si in rows:
        if flt(si.outstanding_amount) <= 0 and si.apparel_followup_status == "Paid":
            continue
        if not si.apparel_expected_due_date:
            refresh_invoice(si.name)
            si.apparel_expected_due_date = frappe.db.get_value("Sales Invoice", si.name, "apparel_expected_due_date")
        got = status_for(si.outstanding_amount, si.grand_total, si.apparel_expected_due_date, today, si.apparel_promise_date, bool(si.apparel_dispute_reason), soon)
        frappe.db.set_value("Sales Invoice", si.name, {"apparel_followup_status": got[0], "apparel_days_overdue": got[1]}, update_modified=False)
        if got[0] == "Due Soon":
            todo(si, "Payment of %s from %s falls due on %s: send a reminder." % (si.name, si.customer, si.apparel_expected_due_date), "due-soon")
        if got[0] == "Overdue":
            hit = [l for l in levels if got[1] >= l[0]]
            if hit:
                last = hit[len(hit) - 1]
                todo(si, "%s: %s is %s days overdue (%s)." % (si.name, si.customer, got[1], last[1]), "overdue-" + str(last[0]))


main()
