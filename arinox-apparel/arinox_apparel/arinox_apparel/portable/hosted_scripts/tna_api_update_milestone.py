# API arinox_api_update_milestone: set the revised or actual date of a milestone, with the same rules as the form.
def main():
    f = frappe.form_dict
    ms = frappe.get_doc("TNA Milestone", f.get("name"))
    ms.check_permission("write")
    if frappe.utils.cint(f.get("clear_actual")):
        ms.actual_date = None
        ms.partial = 0
        ms.source_doctype = None
        ms.source_name = None
    if f.get("actual_date"):
        ms.actual_date = frappe.utils.getdate(f.get("actual_date"))
        ms.partial = 0
        ms.source_doctype = "Manual"
        ms.source_name = frappe.session.user
    if f.get("revised_date"):
        ms.revised_date = frappe.utils.getdate(f.get("revised_date"))
    if f.get("reason"):
        ms.revision_reason = f.get("reason")
    if f.get("delay_reason"):
        ms.delay_reason_category = f.get("delay_reason")
    ms.save()
    frappe.flags.arinox_result = {"name": ms.name, "status": ms.status, "delay_days": ms.delay_days}


main()
