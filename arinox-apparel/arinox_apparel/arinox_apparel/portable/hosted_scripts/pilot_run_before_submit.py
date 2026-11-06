# Pilot Run, Before Submit: a decision, by QA or a production manager; an approval needs the checks answered, pilot pieces sewn (and washed for a washed style) and
# out-of-tolerance measurements explained; any other decision needs notes.
def run(doc):
    cint = frappe.utils.cint
    APPROVE = ("Approved", "Approved with Comments")
    if not doc.decision:
        frappe.throw("Choose the decision (Approved, Approved with Comments, Rejected or Re-run) before submitting.")
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if not [r for r in roles if r in ("Apparel QA", "Apparel Production Manager", "System Manager")]:
        frappe.throw("Only Apparel QA or a production manager can submit a pilot run decision.")
    if doc.decision in APPROVE:
        if not doc.checks:
            frappe.throw("Record the pilot run checks before approving.")
        unanswered = [c.check_item for c in doc.checks if not c.result]
        if unanswered:
            frappe.throw("Answer every check before approving: %s" % ", ".join(unanswered))
        no_action = [c.check_item for c in doc.checks if c.result == "No" and not (c.action_taken or "").strip()]
        if no_action:
            frappe.throw("Write the action taken for each failed check: %s" % ", ".join(no_action))
        if not [r for r in doc.colours if cint(r.sewn_qty)]:
            frappe.throw("No pilot pieces have been sewn for these colours yet (post them through a Lay Report and Daily Line Report with purpose Pilot).")
        if cint(frappe.db.get_value("Production Card", doc.production_card, "is_washed")):
            dry = [r.colour for r in doc.colours if cint(r.sewn_qty) and not cint(r.washed_qty)]
            if dry:
                frappe.throw("The style is washed: the pilot pieces must come back from the wash before approval. Not washed: %s" % ", ".join(dry))
        off = [m.point_of_measure for m in doc.measurements if m.actual not in (None, "") and not cint(m.in_tolerance)]
        if off and not (doc.measurement_note or "").strip():
            frappe.throw("Measurements are out of tolerance (%s). Write the reason, or choose Re-run." % ", ".join(off))
    elif not (doc.result_notes or "").strip():
        frappe.throw("Write the notes that explain why the pilot run was %s." % doc.decision.lower())


run(doc)
