# Purchase Order, Before Submit: while a buyer approval is missing the order is held (when the setting says Block); a manager may override with a reason.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_po.py
    mode = frappe.db.get_single_value("Apparel Settings", "hold_po_until_approval") or "Warn"
    blockers = hold_blockers(doc)
    if blockers and mode == "Block":
        if frappe.utils.cint(doc.get("apparel_approval_override")) and (doc.get("apparel_approval_override_reason") or "").strip() and is_manager():
            return
        frappe.throw("This order is on hold until the buyer approvals are in:<br>• " + "<br>• ".join(blockers), title="Approval hold")


run(doc)
