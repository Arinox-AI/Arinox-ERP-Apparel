# Buyer Claim, Before Submit: an accepted claim needs the amount and the settlement; outside the window or above the cap it needs a manager and a reason; an undecided claim cannot be submitted.
def run(doc):
    flt = frappe.utils.flt
    if doc.status in ("Accepted", "Partly Accepted"):
        if flt(doc.accepted_amount) <= 0:
            frappe.throw("Enter the amount accepted.")
        if not doc.settlement:
            frappe.throw("Choose how it is settled.")
        outside = bool(doc.window_note) or flt(doc.accepted_amount) > flt(doc.cap_amount) + 0.005
        if outside:
            roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
            if not [r for r in roles if r in ("Accounts Manager", "Apparel Merchandising Manager", "System Manager")]:
                frappe.throw("Accepting outside the claim window or above the cap needs a manager.")
            if not (doc.override_reason or "").strip():
                frappe.throw("Write why this is accepted outside the window or above the cap.")
    elif doc.status == "Open":
        frappe.throw("Decide the claim before submitting: Under Review is saved as a draft, then Accepted, Partly Accepted or Rejected.")


run(doc)
