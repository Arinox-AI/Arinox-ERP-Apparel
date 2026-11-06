# TNA Template, Before Save: each milestone once, "after" rows name another milestone of the template, no loops, daily output where the duration needs it, one default.
def run(doc):
    codes = [r.milestone_type for r in doc.milestones]
    for c in codes:
        if codes.count(c) > 1:
            frappe.throw("A milestone can appear only once in a template.")
    for r in doc.milestones:
        if r.basis == "After Milestone":
            if not r.after_milestone:
                frappe.throw("Row %s: choose the milestone this one follows." % r.idx)
            if r.after_milestone == r.milestone_type:
                frappe.throw("Row %s: a milestone cannot follow itself." % r.idx)
            if r.after_milestone not in codes:
                frappe.throw("Row %s: %s is not in this template." % (r.idx, r.after_milestone))
        if r.duration_rule == "Qty / Daily Output" and frappe.utils.cint(r.daily_output) <= 0:
            frappe.throw("Row %s: enter the daily output." % r.idx)
    after = {}
    for r in doc.milestones:
        if r.basis == "After Milestone":
            after[r.milestone_type] = r.after_milestone
    for start in after:
        seen = []
        cur = start
        while cur in after:
            if cur in seen:
                frappe.throw("The milestones %s follow each other in a loop." % ", ".join(sorted(seen)))
            seen.append(cur)
            cur = after[cur]
    if frappe.utils.cint(doc.is_default):
        for other in frappe.get_all("TNA Template", filters={"is_default": 1, "name": ["!=", doc.name or ""]}, pluck="name"):
            frappe.db.set_value("TNA Template", other, "is_default", 0)


run(doc)
