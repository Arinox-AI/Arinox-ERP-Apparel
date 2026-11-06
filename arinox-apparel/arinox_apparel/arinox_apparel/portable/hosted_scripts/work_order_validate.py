# Work Order, Before Save: the bulk gate (G3) can be overridden only by an Apparel Merchandising Manager, with a reason.
def run(doc):
    if not frappe.utils.cint(doc.get("apparel_gate_override")):
        return
    if not doc.is_new() and not doc.has_value_changed("apparel_gate_override"):
        return
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if not [r for r in roles if r in ("Apparel Merchandising Manager", "System Manager")]:
        frappe.throw("Only an Apparel Merchandising Manager can override the bulk gate.")
    if not (doc.get("apparel_gate_override_reason") or "").strip():
        frappe.throw("Enter the reason for overriding the bulk gate.")


run(doc)
