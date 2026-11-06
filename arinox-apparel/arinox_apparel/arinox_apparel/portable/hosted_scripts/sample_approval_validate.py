# Sample Approval, Before Save: scope, waiver, rounds, process rules (washed bulk, PP in bulk fabric, failed lab tests), measurements and shrinkage,
# status from the last round, the rule's defaults, the due date and the late-sample chargeback.
def run(doc):
    # include: lib_samples.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    getdate = frappe.utils.getdate
    DECIDED_NEEDS_COMMENT = ("Approved with Comments", "Rejected", "Resubmit")

    def my_roles():
        return (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))

    rule = get_rules(doc.customer, doc.sales_order, doc.style_item).get(doc.sample_type) or make_rule()

    # ---- links and scope
    if doc.sales_order:
        so = frappe.db.get_value("Sales Order", doc.sales_order, ["customer", "apparel_sales_contract", "docstatus"], as_dict=True)
        if not so:
            frappe.throw("Sales Order %s does not exist." % doc.sales_order)
        doc.customer = so.customer
        doc.sales_contract = so.apparel_sales_contract
    if not doc.customer and doc.tech_pack:
        doc.customer = frappe.db.get_value("Tech Pack", doc.tech_pack, "customer")
    if not doc.style_no:
        doc.style_no = frappe.db.get_value("Tech Pack", doc.tech_pack, "style_no") if doc.tech_pack else doc.style_item
    if doc.style_item and frappe.db.get_value("Item", doc.style_item, "variant_of"):
        frappe.throw("Pick the style (template item), not a size or colour variant.")
    if rule["per_colour"] and not (doc.colour or "").strip():
        frappe.throw("%s is approved per colour. Enter the colour." % doc.sample_type)
    if doc.sample_type in ("Bulk Fabric", "Bulk Trim") and not (doc.material_item or doc.material_description):
        frappe.throw("Enter the material (item or description) being approved.")

    # ---- waiver
    changed = (doc.is_new() and doc.waived) or (not doc.is_new() and doc.has_value_changed("waived"))
    if doc.waived:
        if changed and not [r for r in my_roles() if r in MANAGER_ROLES]:
            frappe.throw("Only an Apparel Merchandising Manager can mark a sample as not required.")
        if not (doc.waiver_reason or "").strip():
            frappe.throw("Enter the reason this approval is not required.")
        if changed:
            doc.waived_by = frappe.session.user
    else:
        doc.waived_by = None

    # ---- rounds
    i = 1
    for r in doc.rounds:
        r.round_no = i
        i = i + 1
    today = getdate(frappe.utils.nowdate())
    by_round = {}
    for c in doc.comments:
        by_round[cint(c.round_no)] = by_round.get(cint(c.round_no), 0) + 1
    for r in doc.rounds:
        if r.sent_on and r.decision_on and getdate(r.decision_on) < getdate(r.sent_on):
            frappe.throw("Round %s: decision date is before the sent date." % r.round_no)
        if r.decision_on and getdate(r.decision_on) > today:
            frappe.throw("Round %s: decision date cannot be in the future." % r.round_no)
        if r.decision != "Pending" and not r.decision_on:
            frappe.throw("Round %s: enter the decision date." % r.round_no)
        if r.decision in DECIDED_NEEDS_COMMENT and not by_round.get(cint(r.round_no)):
            frappe.throw("Round %s is '%s': add the buyer's comment for that round." % (r.round_no, r.decision))
    last = doc.rounds[-1] if doc.rounds else None

    # ---- process rules (only when the last round approves)
    if last and last.decision in APPROVED and not doc.waived:
        if doc.sample_type in ("Bulk Fabric", "Bulk Trim") and cint(doc.is_washed) and not cint(last.tested_after_wash):
            frappe.throw("This material is washed. The approval must come from a submission tested after wash.")
        if doc.sample_type == "PP" and not cint(doc.in_bulk_fabric):
            frappe.throw("A PP sample can only be approved when it is made in bulk fabric.")
        if doc.sample_type in ("Garment Test (GPT)", "Fabric Test (FPT)"):
            failed = [t.test_property for t in doc.tests if t.result == "Fail"]
            if failed:
                frappe.throw("The lab test cannot be approved while these tests fail: %s" % ", ".join(failed))
        off = [m.point_of_measure for m in doc.measurements if m.actual not in (None, "") and not cint(m.in_tolerance)]
        if off:
            frappe.msgprint("Approved with measurements out of tolerance: %s" % ", ".join(off), indicator="orange")

    # ---- measurements: up to five readings per point; in tolerance only when every reading is
    for m in doc.measurements:
        readings = [flt(v) for v in (m.actual, m.reading_2, m.reading_3, m.reading_4, m.reading_5) if v not in (None, "")]
        if not readings or m.spec is None:
            m.deviation = 0
            m.in_tolerance = 0
            continue
        devs = [round(x - flt(m.spec), 3) for x in readings]
        m.deviation = max(devs, key=abs)
        lo = -abs(flt(m.tol_minus))
        hi = abs(flt(m.tol_plus))
        m.in_tolerance = 1 if len([d for d in devs if lo <= d <= hi]) == len(devs) else 0

    # ---- fabric shrinkage
    limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
    over = []
    for r in doc.shrinkage:
        for d in ("warp", "weft", "bias"):
            before = flt(r.get("before_" + d))
            after = flt(r.get("after_" + d))
            r.set("shrink_" + d + "_pct", round((after - before) / before * 100, 2) if before else 0)
        if limit and (abs(flt(r.get("shrink_warp_pct"))) > limit or abs(flt(r.get("shrink_weft_pct"))) > limit):
            over.append(r.roll_no or r.idx)
    if over:
        frappe.msgprint("Shrinkage above %s%% on: %s" % (limit, ", ".join([str(x) for x in over])), indicator="orange")

    # ---- status follows the last round
    if doc.waived:
        doc.status = "Not Required"
    elif not last:
        doc.status = "Open"
    elif last.decision == "Pending":
        doc.status = "Submitted" if last.sent_on else "Open"
    else:
        doc.status = last.decision
    sent = [r.sent_on for r in doc.rounds if r.sent_on]
    doc.submitted_on = max(sent) if sent else None
    doc.approved_on = last.decision_on if last and last.decision in APPROVED and not doc.waived else None

    # ---- the rule's defaults
    doc.chargeback_amount = rule["chargeback_amount"] or 0
    if not doc.sample_qty and rule["qty"]:
        doc.sample_qty = rule["qty"]
    if not doc.sample_size and rule["sample_size"]:
        doc.sample_size = rule["sample_size"]

    # ---- due date, counted from the basis date of the rule
    if not doc.due_date and (rule["days_before"] or rule["due_basis"] == "After Fit Approval"):
        dates = get_style_dates(doc.sales_order, doc.style_item, doc.colour)
        doc.pcd = doc.pcd or dates[0]
        doc.ex_factory_date = doc.ex_factory_date or dates[1]
        doc.in_warehouse_date = doc.in_warehouse_date or dates[2]
        basis = doc.pcd
        direction = -1
        if rule["due_basis"] == "Ex-Factory":
            basis = doc.ex_factory_date
        elif rule["due_basis"] == "In-Warehouse":
            basis = doc.in_warehouse_date
        elif rule["due_basis"] == "After Fit Approval":
            basis = fit_approved_on(doc.sales_order, doc.style_item)
            direction = 1
        if basis:
            doc.due_date = frappe.utils.add_days(basis, direction * rule["days_before"])

    # ---- chargeback exposure: the sample went out late, or is overdue and still not sent
    doc.late_chargeback = 0
    if flt(doc.chargeback_amount) and doc.due_date and not doc.waived:
        due = getdate(doc.due_date)
        sent_dates = [getdate(r.sent_on) for r in doc.rounds if r.sent_on]
        if (sent_dates and min(sent_dates) > due) or (not sent_dates and today > due):
            doc.late_chargeback = doc.chargeback_amount


run(doc)
