# TNA Milestone, Before Save: header copied from its Order TNA, label and department from the milestone type, the baseline lock, the revised-date reason,
# no actual date in the future, and the state (status, delay, progress, colour) from the dates.
def run(doc):
    # include: lib_tna.py
    getdate = frappe.utils.getdate
    cint = frappe.utils.cint
    tna = frappe.db.get_value("Order TNA", doc.order_tna, ["sales_order", "style_no", "colour", "factory", "baseline_locked", "customer", "status"], as_dict=True)
    if not tna:
        frappe.throw("Order T&A %s does not exist." % doc.order_tna)
    doc.sales_order = tna.sales_order
    doc.style_no = tna.style_no
    doc.colour = tna.colour
    doc.factory = tna.factory
    doc.customer = tna.customer
    mt = frappe.get_cached_doc("TNA Milestone Type", doc.milestone_type)
    doc.label = doc.label or mt.label
    doc.department = doc.department or mt.department
    if doc.planned_date and not doc.planned_start:
        doc.planned_start = doc.planned_date
    if doc.planned_start and doc.planned_date and getdate(doc.planned_start) > getdate(doc.planned_date):
        doc.planned_start = doc.planned_date
    if cint(tna.baseline_locked) and not doc.is_new() and doc.has_value_changed("planned_date") and not doc.flags.baseline_move:
        frappe.throw("The baseline is locked. Use the Revised Date (with a reason) to move this milestone.")
    if doc.revised_date and doc.planned_date and getdate(doc.revised_date) != getdate(doc.planned_date) and not (doc.revision_reason or "").strip() and not doc.actual_date:
        frappe.throw("Enter the reason for the revised date.")
    if doc.actual_date and getdate(doc.actual_date) > getdate(frappe.utils.nowdate()):
        frappe.throw("The actual date cannot be in the future.")
    st = milestone_state(doc.not_applicable, doc.actual_date, doc.partial, doc.planned_date, doc.revised_date)
    doc.status = st[0]
    doc.delay_days = st[1]
    doc.progress = st[2]
    doc.color = COLOURS[st[0]]


run(doc)
