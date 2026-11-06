# PP Meeting, After Cancel: the buyer comments of its actions are open again.
def run(doc):
    for a in doc.actions:
        if a.comment_ref:
            frappe.db.set_value("Sample Approval Comment", a.comment_ref, {"status": "Open", "closed_in": None})


run(doc)
