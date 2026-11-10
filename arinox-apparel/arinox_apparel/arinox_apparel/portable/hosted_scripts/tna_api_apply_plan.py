# API arinox_tna_apply_plan: write a plan computed by the Cortex Tower onto an Order TNA, in one call. `rows` is a list (or JSON) of
# {milestone_type, planned_start, planned_date, sequence, is_critical}. Missing milestones are made; on an unlocked plan the planned dates are set
# (a milestone that already has an actual date is left alone); on a locked plan the planned dates are never touched and each row's `revised_date`
# (with the one `reason`) is set where it differs. The order's feasibility fields are set from `plan_feasible`, `feasibility_note`, `critical_delay_days`.
def main():
    f = frappe.form_dict
    rows = f.get("rows")
    if isinstance(rows, str):
        rows = json.loads(rows)
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    tna = frappe.get_doc("Order TNA", f.get("order_tna"))
    tna.check_permission("write")
    if tna.status == "Cancelled":
        frappe.throw("Order T&A %s is cancelled; its plan is closed." % tna.name)
    locked = cint(tna.baseline_locked)
    made = 0
    moved = 0
    revised = 0
    kept = 0
    for r in rows:
        name = frappe.db.get_value("TNA Milestone", {"order_tna": tna.name, "milestone_type": r.get("milestone_type")}, "name")
        if not name:
            if locked:
                kept = kept + 1
                continue
            ms = frappe.new_doc("TNA Milestone")
            ms.order_tna = tna.name
            ms.milestone_type = r.get("milestone_type")
            ms.planned_date = getdate(r.get("planned_date"))
            ms.planned_start = getdate(r.get("planned_start") or r.get("planned_date"))
            ms.sequence = cint(r.get("sequence"))
            ms.is_critical = cint(r.get("is_critical"))
            ms.flags.ignore_permissions = True
            ms.insert()
            made = made + 1
            continue
        ms = frappe.get_doc("TNA Milestone", name)
        if ms.actual_date:
            kept = kept + 1
            continue
        if locked:
            want = r.get("revised_date")
            if want and getdate(want) != getdate(ms.revised_date or ms.planned_date):
                ms.revised_date = getdate(want)
                ms.revision_reason = f.get("reason") or ms.revision_reason
                ms.flags.ignore_permissions = True
                ms.save()
                revised = revised + 1
            else:
                kept = kept + 1
            continue
        if getdate(r.get("planned_date")) != getdate(ms.planned_date) or (r.get("planned_start") and getdate(r.get("planned_start")) != getdate(ms.planned_start)):
            ms.planned_date = getdate(r.get("planned_date"))
            ms.planned_start = getdate(r.get("planned_start") or r.get("planned_date"))
            ms.flags.ignore_permissions = True
            ms.save()
            moved = moved + 1
        else:
            kept = kept + 1
    if f.get("plan_feasible") is not None:
        tna.db_set("plan_feasible", cint(f.get("plan_feasible")))
    if f.get("feasibility_note") is not None:
        tna.db_set("feasibility_note", (f.get("feasibility_note") or "")[:140])
    if f.get("critical_delay_days") is not None:
        tna.db_set("critical_delay_days", cint(f.get("critical_delay_days")))
    frappe.flags.arinox_result = {"order_tna": tna.name, "made": made, "moved": moved, "revised": revised, "kept": kept, "locked": locked}


main()
