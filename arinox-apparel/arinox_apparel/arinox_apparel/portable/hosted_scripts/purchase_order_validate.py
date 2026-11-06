# Purchase Order, Before Save: link back to the requisition (copied from the Material Request row), supplier terms, the approval-hold override, ETD dates, warnings.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_po.py
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    for poi in doc.items:
        if poi.get("material_request_item") and not poi.get("apparel_requisition"):
            vals = frappe.db.get_value("Material Request Item", poi.material_request_item, list(COPY_FIELDS), as_dict=True) or {}
            for f in COPY_FIELDS:
                if vals.get(f):
                    poi.set(f, vals[f])
    if not doc.get("apparel_purchase_terms") and [p for p in doc.items if p.get("apparel_requisition")]:
        doc.apparel_purchase_terms = frappe.db.get_value("Supplier", doc.supplier, "apparel_purchase_terms") or frappe.db.get_single_value("Apparel Settings", "default_purchase_terms")
    if cint(doc.get("apparel_approval_override")) and (doc.is_new() or doc.has_value_changed("apparel_approval_override")):
        if not is_manager():
            frappe.throw("Only an Apparel Merchandising Manager can override the approval hold.")
        if not (doc.get("apparel_approval_override_reason") or "").strip():
            frappe.throw("Enter the reason for overriding the approval hold.")
    plan = doc.get("apparel_etd_planned")
    eta = doc.get("apparel_eta")
    actual = doc.get("apparel_etd_actual")
    if plan and eta and getdate(plan) > getdate(eta):
        frappe.throw("ETD (plan) cannot be after the ETA.")
    if actual and getdate(actual) > getdate(frappe.utils.nowdate()):
        frappe.throw("ETD (actual) cannot be in the future.")
    for msg in hold_blockers(doc) + cost_warnings(doc):
        frappe.msgprint(msg, indicator="orange", title="Apparel check")


run(doc)
