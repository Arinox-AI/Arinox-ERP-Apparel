# PP Meeting, Before Submit: the production card was issued first, the required departments attended, every action has an owner and a date; a PP Meeting
# (not a pilot-run meeting) also needs its PP sample buyer-approved when the rules require one, and every open buyer comment listed.
def run(doc):
    # include: lib_samples.py
    # include: lib_pp.py
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    if not doc.production_card_issued_on:
        frappe.throw("Enter the date the production card was issued. The meeting is held after it.")
    if getdate(doc.meeting_date) < getdate(doc.production_card_issued_on):
        frappe.throw("The meeting date is before the production card was issued.")
    present = [(p.department or "").strip() for p in doc.participants if cint(p.attended)]
    missing = [d for d in required_departments(doc.meeting_type, doc.is_washed) if d not in present]
    if missing:
        frappe.throw("These departments must attend: %s" % ", ".join(sorted(missing)))
    for a in doc.actions:
        if not (a.action_taken and a.action_owner and a.target_date):
            frappe.throw("Action row %s needs the action, an owner and a target date." % a.idx)
    if doc.meeting_type == "PP Meeting":   # the pilot run follows the PP meeting; it has no buyer comments of its own
        rule = get_rules(doc.customer, doc.sales_order, doc.style_item).get("PP")
        if doc.pp_sample or (rule and rule["gate"] == "Required"):
            status = frappe.db.get_value("Sample Approval", doc.pp_sample, "status") if doc.pp_sample else None
            if status not in APPROVED:
                frappe.throw("The PP sample must be buyer approved before the PP meeting is issued.")
        listed = [a.comment_ref for a in doc.actions if a.comment_ref]
        unlisted = [c for c in open_buyer_comments(doc.sales_order, doc.style_item) if c["name"] not in listed]
        if unlisted:
            frappe.throw("Every buyer comment must be reviewed. %s open comment(s) are not in the action list, for example: %s. Use Get Buyer Comments." %
                         (len(unlisted), (unlisted[0]["comment"] or "")[:80]))


run(doc)
