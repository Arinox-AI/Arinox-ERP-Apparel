# Cost Sheet, Before Submit: every mandatory cost head is priced (a cost left out comes straight out of margin), the sign-off chain is
# complete when the settings ask for it, and a margin below the floor needs a Costing Manager.
def run(doc):
    # include: lib_costing.py
    flt = frappe.utils.flt
    mine = (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    FABRIC_TYPES = ("Fabric", "Lining", "Contrast Fabric")

    present = {}
    for c in doc.charges:
        present[c.cost_head] = c
    missing = []
    zero = []
    for head in get_cost_heads():
        if not head.is_mandatory:
            continue
        if head.calc_type == "From Materials":
            found = False
            for m in doc.materials:
                in_fabric = m.material_type in FABRIC_TYPES
                if head.material_scope == "Fabric" and in_fabric:
                    found = True
                elif head.material_scope == "Non-Fabric" and not in_fabric:
                    found = True
                elif head.material_scope not in ("Fabric", "Non-Fabric"):
                    found = True
            if not found:
                missing.append(head.name)
            continue
        row = present.get(head.name)
        if not row:
            missing.append(head.name)
        elif not flt(row.rate) and not row.not_applicable:
            zero.append(head.name)
    if missing or zero:
        msg = []
        if missing:
            msg.append("Missing: " + ", ".join(missing))
        if zero:
            msg.append("Zero rate without N/A: " + ", ".join(zero))
        frappe.throw("<br>".join(msg), title="Cost Sheet Incomplete")

    if frappe.db.get_single_value("Apparel Settings", "require_costing_signoff"):
        open_steps = [r.step for r in doc.signoffs if not r.signed_by]
        if open_steps:
            frappe.throw("Costing sign-off incomplete. Still to sign: " + ", ".join(open_steps), title="Sign-off Required")

    if doc.below_floor and doc.approval_status != "Approved":
        if "Apparel Costing Manager" in mine:
            doc.approval_status = "Approved"
            doc.approved_by = frappe.session.user
            doc.approved_on = frappe.utils.now_datetime()
            doc.approved_price = doc.quoted_price
            if not doc.approval_remarks:
                doc.approval_remarks = "Approved at submit by Costing Manager"
        else:
            frappe.throw("Margin %s%% is below the floor of %s%%. A Costing Manager must approve this Cost Sheet before it can be submitted." % (flt(doc.margin_pct, 2), flt(doc.margin_floor_pct, 2)),
                         title="Below Margin Floor")


run(doc)
