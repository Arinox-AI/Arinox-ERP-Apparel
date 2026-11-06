# API arinox_api_wip_board_data: one Order TNA per row and one milestone per column, for the WIP board built outside this app. Status is computed from today's date.
def main():
    # include: lib_tna.py
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    f = frappe.form_dict.get("filters")
    f = json.loads(f) if isinstance(f, str) and f else (f or {})
    today = getdate(frappe.utils.nowdate())

    def cell_class(m):
        if cint(m.get("not_applicable")):
            return "na"
        due = m.get("revised_date") or m.get("planned_date")
        if m.get("actual_date"):
            return "done_late" if m.get("planned_date") and getdate(m["actual_date"]) > getdate(m["planned_date"]) else "done"
        if due and getdate(due) < today:
            return "late"
        if due and frappe.utils.date_diff(due, today) <= 7:
            return "soon"
        return "future"

    cond = [["status", "!=", "Cancelled"]] if not f.get("include_cancelled") else []
    for k in ("customer", "merchant", "factory", "sales_order", "status"):
        if f.get(k):
            cond.append([k, "=", f[k]])
    if f.get("ex_factory_from"):
        cond.append(["ex_factory_date", ">=", f["ex_factory_from"]])
    if f.get("ex_factory_to"):
        cond.append(["ex_factory_date", "<=", f["ex_factory_to"]])
    limit = min(cint(frappe.form_dict.get("limit")) or 200, 200)
    orders = frappe.get_list("Order TNA", filters=cond, order_by="ex_factory_date asc, name asc", limit_start=cint(frappe.form_dict.get("start")), limit_page_length=limit,
                             fields=["name", "sales_order", "customer", "style_no", "colour", "order_qty", "merchant", "factory", "ex_factory_date", "pcd", "status",
                                     "critical_delay_days", "plan_feasible", "feasibility_note", "baseline_locked", "ship_tos"])
    total = len(frappe.get_list("Order TNA", filters=cond, pluck="name", limit_page_length=0))
    names = [o.name for o in orders]
    ms = frappe.get_all("TNA Milestone", filters={"order_tna": ["in", names or [""]]}, order_by="sequence asc", limit_page_length=0,
                        fields=["name", "order_tna", "milestone_type", "label", "sequence", "planned_start", "planned_date", "revised_date", "actual_date", "partial", "not_applicable",
                                "is_critical", "depends_on_tasks", "owner_user", "delay_reason_category", "source_doctype", "source_name"])
    by_order = {}
    types = {}
    for m in ms:
        st = milestone_state(m.not_applicable, m.actual_date, m.partial, m.planned_date, m.revised_date)
        m["status"] = st[0]
        m["delay_days"] = st[1]
        m["progress"] = st[2]
        m["color"] = COLOURS[st[0]]
        m["cell"] = cell_class(m)
        if m.order_tna not in by_order:
            by_order[m.order_tna] = {}
        by_order[m.order_tna][m.milestone_type] = m
        if m.milestone_type not in types:
            types[m.milestone_type] = [m.sequence, m.label]
    for o in orders:
        res = order_state([by_order.get(o.name)[k] for k in by_order.get(o.name)] if by_order.get(o.name) else [], o.plan_feasible, False)
        o["status_live"] = res[0]
        o["critical_delay_days"] = res[1]
    if cint(f.get("late_only")):
        orders = [o for o in orders if o.status_live in ("Late", "At Risk")]
    kept = [o.name for o in orders]
    frappe.flags.arinox_result = {"orders": orders, "total": total, "today": frappe.utils.nowdate(),
                                  "types": [{"code": c, "label": types[c][1]} for c in sorted(types, key=lambda c: types[c][0])],
                                  "milestones": {k: by_order[k] for k in by_order if k in kept}}


main()
