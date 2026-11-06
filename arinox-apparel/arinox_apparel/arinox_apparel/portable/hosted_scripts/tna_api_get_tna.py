# API arinox_api_get_tna: agent API, every Order TNA of a Sales Order with its milestones.
def main():
    so = frappe.get_doc("Sales Order", frappe.form_dict.get("sales_order"))
    so.check_permission("read")
    out = []
    for t in frappe.get_all("Order TNA", filters={"sales_order": so.name}, fields=["*"]):
        t["milestones"] = frappe.get_all("TNA Milestone", filters={"order_tna": t.name}, order_by="sequence asc",
                                         fields=["name", "milestone_type", "label", "planned_date", "revised_date", "actual_date", "status", "delay_days", "is_critical",
                                                 "not_applicable", "owner_user", "source_doctype", "source_name"])
        out.append(t)
    frappe.flags.arinox_result = out


main()
