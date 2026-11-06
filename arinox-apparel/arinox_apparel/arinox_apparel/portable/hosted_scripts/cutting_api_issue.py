# API arinox_cutting_issue_fabric: issue rolls to the cutting floor (a Stock Entry). `rolls` = [{batch_no, qty}] (JSON). Answers the Stock Entry name.
def main():
    # include: lib_cutting.py
    card = frappe.form_dict.get("card")
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    c = frappe.get_doc("Production Card", card)
    if "Apparel Production User" not in roles:
        c.check_permission("write")
    rolls = frappe.form_dict.get("rolls")
    rolls = json.loads(rolls) if isinstance(rolls, str) else rolls
    frappe.flags.arinox_result = issue_fabric_entry(card, rolls)


main()
