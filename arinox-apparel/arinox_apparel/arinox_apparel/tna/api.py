"""Whitelisted calls: the WIP board's data, milestone updates, and the agent API for the T&A."""

import json

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate, nowdate

from arinox_apparel.tna.status import COLOURS, milestone_state, order_state


def cell_class(m, today=None):
	"""done / done_late / soon / late / na / future, from the dates alone."""
	today = getdate(today or nowdate())
	if cint(m.get("not_applicable")):
		return "na"
	due = m.get("revised_date") or m.get("planned_date")
	if m.get("actual_date"):
		return "done_late" if m.get("planned_date") and getdate(m["actual_date"]) > getdate(m["planned_date"]) else "done"
	if due and getdate(due) < today:
		return "late"
	if due and date_diff(due, today) <= 7:
		return "soon"
	return "future"


@frappe.whitelist()
def wip_board_data(filters=None, limit=200, start=0):
	"""One Order TNA per row and one milestone per column. Two queries in total (orders, then every milestone of those
	orders), grouped in Python. Status is computed from today's date here."""
	f = json.loads(filters) if isinstance(filters, str) and filters else (filters or {})
	cond = [["status", "!=", "Cancelled"]] if not f.get("include_cancelled") else []
	for k in ("customer", "merchant", "factory", "sales_order", "status"):
		if f.get(k):
			cond.append([k, "=", f[k]])
	if f.get("ex_factory_from"):
		cond.append(["ex_factory_date", ">=", f["ex_factory_from"]])
	if f.get("ex_factory_to"):
		cond.append(["ex_factory_date", "<=", f["ex_factory_to"]])
	limit = min(cint(limit) or 200, 200)
	orders = frappe.get_list("Order TNA", cond, ["name", "sales_order", "customer", "style_no", "colour", "order_qty", "merchant", "factory", "ex_factory_date", "pcd",
		"status", "critical_delay_days", "plan_feasible", "feasibility_note", "baseline_locked", "ship_tos"], order_by="ex_factory_date asc, name asc",
		limit_start=cint(start), limit_page_length=limit)
	total = len(frappe.get_list("Order TNA", cond, pluck="name", limit_page_length=0))
	names = [o.name for o in orders]
	ms = frappe.get_all("TNA Milestone", {"order_tna": ["in", names or [""]]}, ["name", "order_tna", "milestone_type", "label", "sequence", "planned_start", "planned_date",
		"revised_date", "actual_date", "partial", "not_applicable", "is_critical", "depends_on_tasks", "owner_user", "delay_reason_category", "source_doctype", "source_name"],
		order_by="sequence asc", limit_page_length=0)
	by_order, types = {}, {}
	for m in ms:
		status, delay, progress = milestone_state(m.not_applicable, m.actual_date, m.partial, m.planned_date, m.revised_date)
		m.update(status=status, delay_days=delay, progress=progress, color=COLOURS[status], cell=cell_class(m))
		by_order.setdefault(m.order_tna, {})[m.milestone_type] = m
		types.setdefault(m.milestone_type, (m.sequence, m.label))
	for o in orders:
		o.status_live, o.critical_delay_days = order_state(list(by_order.get(o.name, {}).values()), o.plan_feasible)
	if cint(f.get("late_only")):
		orders = [o for o in orders if o.status_live in ("Late", "At Risk")]
	return {
		"orders": orders, "total": total, "today": nowdate(),
		"types": [{"code": c, "label": v[1]} for c, v in sorted(types.items(), key=lambda kv: kv[1][0])],
		"milestones": {k: v for k, v in by_order.items() if k in {o.name for o in orders}},
	}


@frappe.whitelist()
def update_milestone(name, revised_date=None, actual_date=None, reason=None, delay_reason=None, clear_actual=0):
	"""Set the revised or actual date of a milestone, with the same rules as the form."""
	ms = frappe.get_doc("TNA Milestone", name)
	ms.check_permission("write")
	if cint(clear_actual):
		ms.actual_date, ms.partial, ms.source_doctype, ms.source_name = None, 0, None, None
	if actual_date:
		ms.actual_date, ms.partial = getdate(actual_date), 0
		ms.source_doctype, ms.source_name = "Manual", frappe.session.user
	if revised_date:
		ms.revised_date = getdate(revised_date)
	if reason:
		ms.revision_reason = reason
	if delay_reason:
		ms.delay_reason_category = delay_reason
	ms.save()
	return {"name": ms.name, "status": ms.status, "delay_days": ms.delay_days}


@frappe.whitelist()
def get_tna(sales_order):
	"""Agent API: every Order TNA of a Sales Order with its milestones."""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	out = []
	for t in frappe.get_all("Order TNA", {"sales_order": sales_order}, ["*"]):
		t["milestones"] = frappe.get_all("TNA Milestone", {"order_tna": t.name}, ["name", "milestone_type", "label", "planned_date", "revised_date", "actual_date",
			"status", "delay_days", "is_critical", "not_applicable", "owner_user", "source_doctype", "source_name"], order_by="sequence asc")
		out.append(t)
	return out
