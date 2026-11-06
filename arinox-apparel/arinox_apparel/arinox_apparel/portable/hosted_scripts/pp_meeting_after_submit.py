# PP Meeting, After Submit and After Save (Submitted Document): the buyer comment of each action follows the action (closed in this meeting, or open again).
def run(doc):
    for a in doc.actions:
        if a.comment_ref and frappe.db.exists("Sample Approval Comment", a.comment_ref):
            closed = a.status == "Closed"
            frappe.db.set_value("Sample Approval Comment", a.comment_ref, {"status": "Closed" if closed else "Open", "closed_in": doc.name if closed else None})


run(doc)
