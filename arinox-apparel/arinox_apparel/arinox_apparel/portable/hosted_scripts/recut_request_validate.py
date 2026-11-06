# Recut Request, Before Save: only rejected, not yet replaced pieces can be re-cut; a roll of a different shade needs a production manager's approval.
def run(doc):
    cint = frappe.utils.cint
    card = frappe.db.get_value("Production Card", doc.production_card, ["docstatus", "status"], as_dict=True)
    if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s must be issued and open." % doc.production_card)
    if not frappe.db.exists("Production Card Line", {"parent": doc.production_card, "colour": doc.colour, "size": doc.size}):
        frappe.throw("%s %s is not on production card %s." % (doc.colour, doc.size, doc.production_card))
    if cint(doc.qty) <= 0:
        frappe.throw("Enter the quantity to re-cut.")
    stages = ("CUT_REJECT", "SEW_REJECT", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_REJECT")
    lost = frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card=%s and colour=%s and size=%s and stage in %s",
                         (doc.production_card, doc.colour, doc.size, stages))[0][0]
    asked = cint(frappe.db.sql("select ifnull(sum(qty), 0) from `tabRecut Request` where production_card=%s and colour=%s and size=%s and docstatus=1 and name != %s",
                               (doc.production_card, doc.colour, doc.size, doc.name or ""))[0][0])
    if cint(doc.qty) > lost - asked:
        frappe.throw("Only %s %s %s pieces are rejected and not yet replaced; cannot re-cut %s." % (max(lost - asked, 0), doc.colour, doc.size, doc.qty))
    if doc.source_roll:
        original = None
        if doc.replaces_lay:
            original = frappe.db.get_value("Lay Report", doc.replaces_lay, "shade_band")
        if doc.replaces_bundle:
            original = frappe.db.get_value("Cut Bundle", doc.replaces_bundle, "shade_band") or original
        shade = frappe.db.get_value("Batch", doc.source_roll, "apparel_shade_band")
        if original and shade and shade != original:
            if not cint(doc.different_roll_approved):
                frappe.throw("Roll %s is shade %s but the original panels are shade %s. Cut from the same roll, or have a manager approve a different roll." % (doc.source_roll, shade, original))
            roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
            if not [r for r in roles if r in ("Apparel Production Manager", "System Manager")]:
                frappe.throw("Only a production manager can approve a roll of a different shade.")
        if cint(doc.different_roll_approved):
            doc.approved_by = frappe.session.user


run(doc)
