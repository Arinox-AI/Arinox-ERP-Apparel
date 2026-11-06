# shared helpers from tna/status.py: the state of a milestone and of an order, computed from today's date and never trusted from a stored value
COLOURS = {"Done": "#2f855a", "In Progress": "#2b6cb0", "Late": "#c53030", "Not Started": "#718096", "Not Applicable": "#cbd5e0"}


def milestone_state(not_applicable, actual_date, partial, planned_date, revised_date):
    """[status, delay_days, progress]. Late = the current target (revised, else planned) has passed and it is not done.
    Delay is measured against the baseline: days late if done late, days overdue if still open, days slipped if revised."""
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    today = getdate(frappe.utils.nowdate())
    if cint(not_applicable):
        return ["Not Applicable", 0, 0]
    due = getdate(revised_date or planned_date) if (revised_date or planned_date) else None
    base = getdate(planned_date) if planned_date else None
    if actual_date:
        return ["Done", max(frappe.utils.date_diff(actual_date, base), 0) if base else 0, 100]
    if due and due < today:
        return ["Late", max(frappe.utils.date_diff(today, base), 0) if base else 0, 50 if cint(partial) else 0]
    delay = max(frappe.utils.date_diff(due, base), 0) if (revised_date and base and due) else 0
    return ["In Progress" if cint(partial) else "Not Started", delay, 50 if cint(partial) else 0]


def order_state(milestones, plan_feasible, cancelled):
    """[status, critical_delay_days] of an order from its milestone dicts."""
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    today = getdate(frappe.utils.nowdate())
    if cancelled:
        return ["Cancelled", 0]
    live = [m for m in milestones if not cint(m.get("not_applicable"))]
    if live and len([m for m in live if m.get("actual_date")]) == len(live):
        return ["Completed", 0]
    crit_late = [m for m in live if cint(m.get("is_critical")) and not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date"))
                 and getdate(m.get("revised_date") or m.get("planned_date")) < today]
    delays = [max(frappe.utils.date_diff(m.get("actual_date") or today, m["planned_date"]), 0) for m in live
              if cint(m.get("is_critical")) and m.get("planned_date") and (m.get("actual_date") or m in crit_late)]
    worst = max(delays) if delays else 0
    if crit_late:
        return ["Late", worst]
    other_late = [m for m in live if not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date")) and getdate(m.get("revised_date") or m.get("planned_date")) < today]
    soon = [m for m in live if cint(m.get("is_critical")) and not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date"))
            and 0 <= frappe.utils.date_diff(m.get("revised_date") or m.get("planned_date"), today) <= 3]
    if other_late or soon or not cint(plan_feasible):
        return ["At Risk", worst]
    return ["On Track", worst]


def refresh_order_tna(name):
    """Recompute and store every milestone's status and the order's status."""
    if not frappe.db.exists("Order TNA", name):
        return
    t = frappe.db.get_value("Order TNA", name, ["status", "plan_feasible", "critical_delay_days"], as_dict=True)
    ms = frappe.get_all("TNA Milestone", filters={"order_tna": name}, fields=["name", "not_applicable", "actual_date", "partial", "planned_date", "revised_date", "is_critical",
                                                                              "status", "delay_days", "color", "progress"])
    for m in ms:
        st = milestone_state(m.not_applicable, m.actual_date, m.partial, m.planned_date, m.revised_date)
        colour = COLOURS[st[0]]
        if m.status != st[0] or m.delay_days != st[1] or m.progress != st[2] or m.color != colour:
            frappe.db.set_value("TNA Milestone", m.name, {"status": st[0], "delay_days": st[1], "progress": st[2], "color": colour}, update_modified=False)
        m["status"] = st[0]
    if t.status == "Cancelled":
        return
    o = order_state(ms, t.plan_feasible, False)
    if o[0] != t.status or o[1] != t.critical_delay_days:
        frappe.db.set_value("Order TNA", name, {"status": o[0], "critical_delay_days": o[1]}, update_modified=False)
