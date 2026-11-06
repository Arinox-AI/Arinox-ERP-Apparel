# Work Order, Before Submit: bulk gate (G3). A Work Order for an apparel style cannot be submitted until the buyer has approved what the rules require, the PP meeting
# is held with every cutting-related action closed, and the materials are in. A manager may override with a reason.
def run(doc):
    cint = frappe.utils.cint
    if not cint(frappe.db.get_single_value("Apparel Settings", "enforce_bulk_gate")) or not doc.get("sales_order"):
        return
    gate = run_script("arinox_work_order_api_get_bulk_gate", production_item=doc.production_item, sales_order=doc.sales_order).get("arinox_result")
    for w in gate.get("warnings") or []:
        frappe.msgprint(w, indicator="orange", title="Materials")
    if not gate["blockers"]:
        return
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    manager = [r for r in roles if r in ("Apparel Merchandising Manager", "System Manager")]
    if cint(doc.get("apparel_gate_override")) and manager and (doc.get("apparel_gate_override_reason") or "").strip():
        return
    frappe.throw("Bulk production is blocked until the buyer approvals and materials are complete:<br>• " + "<br>• ".join(gate["blockers"]), title="Bulk Gate (G3)")


run(doc)
