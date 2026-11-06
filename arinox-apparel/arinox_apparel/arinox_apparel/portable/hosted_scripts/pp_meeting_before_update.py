# PP Meeting, Before Save (Submitted Document): actions stay editable so they can be closed later; stamp them and keep the status in step.
def run(doc):
    for a in doc.actions:
        if a.status == "Closed" and not a.closed_on:
            a.closed_on = frappe.utils.nowdate()
        elif a.status == "Open":
            a.closed_on = None
    doc.status = "Open Actions" if [a for a in doc.actions if a.status == "Open"] else "Closed"
    for a in doc.actions:
        if not (a.action_taken and a.action_owner and a.target_date):
            frappe.throw("Action row %s needs the action, an owner and a target date." % a.idx)


run(doc)
