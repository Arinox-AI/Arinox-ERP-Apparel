# API arinox_scripts_switch  (state = off | on | status): the kill switch. Turns every Arinox RULE script off or on in one call, so a faulty
# script can be stopped without server access. The naming scripts, the ledger engine and this switch stay on: without them the numbered
# documents could not even be created, and a document-event script that is off simply stops enforcing its rule.
# Needs System Manager or Script Manager. Also possible by hand: Server Script list -> select -> Disable.
def main():
    mine = frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if frappe.session.user != "Administrator" and "System Manager" not in mine and "Script Manager" not in mine:
        frappe.throw("Only a System Manager or Script Manager can use the kill switch.")
    state = frappe.form_dict.get("state") or "status"
    if state not in ("off", "on", "status"):
        frappe.throw("state must be off, on or status.")
    keep = ("arinox_engine", "arinox_scripts_switch")
    rules = []
    for r in frappe.get_all("Server Script", {"name": ["like", "arinox_%"]}, ["name", "disabled"]):
        if r.name in keep or r.name.startswith("arinox_naming_"):
            continue
        rules.append(r)
    if state != "status":
        want = 1 if state == "off" else 0
        for r in rules:
            if r.disabled != want:
                doc = frappe.get_doc("Server Script", r.name)       # a save, not db.set_value: saving clears the script cache
                doc.disabled = want
                doc.save(ignore_permissions=True)
        rules = frappe.get_all("Server Script", {"name": ["in", [x.name for x in rules]]}, ["name", "disabled"])
    off = len([r for r in rules if r.disabled])
    frappe.flags.arinox_result = {"rule_scripts": len(rules), "off": off, "on": len(rules) - off}


main()
