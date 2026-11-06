# Lay Report, Before Submit: the bulk gate is checked at the first bulk lay (not when the card is issued); a pilot lay needs the pilot-stage checks.
def run(doc):
    cint = frappe.utils.cint
    card = frappe.db.get_value("Production Card", doc.production_card, ["status", "style_item", "sales_order"], as_dict=True)
    if card.status in ("Superseded", "Cancelled", "Closed"):
        frappe.throw("Production card %s is not open for cutting." % doc.production_card)
    stage = "bulk" if doc.purpose == "Bulk" else "pilot"
    res = run_script("arinox_engine", action="bulk_gate", sales_order=card.sales_order, style=card.style_item, colour=doc.colour, stage=stage).get("arinox_result")
    for w in res.get("warnings") or []:
        frappe.msgprint(w, indicator="orange", title="Materials")
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    manager = [r for r in roles if r in ("Apparel Production Manager", "Apparel Merchandising Manager", "System Manager")]
    if res["blockers"] and not (cint(doc.gate_override) and manager and (doc.gate_override_reason or "").strip()):
        frappe.throw("Cutting is blocked until the buyer approvals, the PP meeting, the materials and the pilot run are complete:<br>• " + "<br>• ".join(res["blockers"]), title="Bulk Gate")


run(doc)
