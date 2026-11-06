# API arinox_cut_plan_release: release the plan. A variance above the limit sends it to a manager instead. Answers the status.
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    plan = frappe.get_doc(d) if d.get("name") and d.get("modified") else frappe.get_doc("Cut Plan", frappe.form_dict.get("name"))
    plan.save()
    limit = frappe.utils.flt(frappe.db.get_single_value("Apparel Settings", "marker_variance_pct") or 5)
    if not plan.lays:
        frappe.throw("Add at least one lay.")
    if abs(frappe.utils.flt(plan.variance_pct)) > limit and not plan.approved_by:
        plan.db_set("status", "Pending Approval")
        frappe.msgprint("Marker consumption is outside the %s%% limit. A manager must approve the plan." % limit, indicator="orange")
    else:
        plan.db_set("status", "Released")
    frappe.flags.arinox_result = plan.status


main()
