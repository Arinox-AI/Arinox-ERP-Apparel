# API arinox_operation_bulletin_activate: make this the Active bulletin of its style; the earlier one is superseded.
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    ob = frappe.get_doc("Operation Bulletin", frappe.form_dict.get("name"))
    if frappe.utils.flt(ob.total_sam) <= 0:
        frappe.throw("Add the operation times before activating.")
    for n in frappe.get_all("Operation Bulletin", filters={"style_item": ob.style_item, "status": "Active", "name": ["!=", ob.name]}, pluck="name"):
        frappe.db.set_value("Operation Bulletin", n, "status", "Superseded")
    ob.db_set("status", "Active")
    frappe.flags.arinox_result = "Active"


main()
