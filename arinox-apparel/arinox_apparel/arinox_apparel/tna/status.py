"""Status of milestones and orders. Always computed from today's date, never trusted from a stored value, so the
board is right even when the site's scheduler is off. The stored values are refreshed on every change and by a daily job."""

import frappe
from frappe.utils import cint, date_diff, getdate, nowdate

COLOURS = {  # chart colours: done, in progress, late, not started, not applicable
	"Done": "#2f855a", "In Progress": "#2b6cb0", "Late": "#c53030", "Not Started": "#718096", "Not Applicable": "#cbd5e0",
}


def milestone_state(not_applicable, actual_date, partial, planned_date, revised_date, today=None):
	"""(status, delay_days, progress). Late = the current target (revised, else planned) has passed and it is not done.
	Delay is measured against the baseline: days late if done late, days overdue if still open, days slipped if revised."""
	today = getdate(today or nowdate())
	if cint(not_applicable):
		return "Not Applicable", 0, 0
	due = getdate(revised_date or planned_date) if (revised_date or planned_date) else None
	base = getdate(planned_date) if planned_date else None
	if actual_date:
		return "Done", max(date_diff(actual_date, base), 0) if base else 0, 100
	if due and due < today:
		return "Late", max(date_diff(today, base), 0) if base else 0, 50 if cint(partial) else 0
	delay = max(date_diff(due, base), 0) if (revised_date and base and due) else 0
	return ("In Progress" if cint(partial) else "Not Started"), delay, 50 if cint(partial) else 0


def order_state(milestones, plan_feasible=1, cancelled=False, today=None):
	"""(status, critical_delay_days) of an order from its milestone dicts."""
	today = getdate(today or nowdate())
	if cancelled:
		return "Cancelled", 0
	live = [m for m in milestones if not cint(m.get("not_applicable"))]
	if live and all(m.get("actual_date") for m in live):
		return "Completed", 0
	crit_late = [m for m in live if cint(m.get("is_critical")) and not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date"))
		and getdate(m.get("revised_date") or m.get("planned_date")) < today]
	delays = [max(date_diff(m.get("actual_date") or today, m["planned_date"]), 0) for m in live if cint(m.get("is_critical")) and m.get("planned_date")
		and (m.get("actual_date") or m in crit_late)]
	worst = max(delays, default=0)
	if crit_late:
		return "Late", worst
	other_late = any(not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date")) and getdate(m.get("revised_date") or m.get("planned_date")) < today for m in live)
	soon = any(cint(m.get("is_critical")) and not m.get("actual_date") and (m.get("revised_date") or m.get("planned_date"))
		and 0 <= date_diff(m.get("revised_date") or m.get("planned_date"), today) <= 3 for m in live)
	if other_late or soon or not cint(plan_feasible):
		return "At Risk", worst
	return "On Track", worst


def refresh_order_tna(name):
	"""Recompute and store every milestone's status and the order's status."""
	if not frappe.db.exists("Order TNA", name):
		return
	t = frappe.db.get_value("Order TNA", name, ["status", "plan_feasible", "critical_delay_days"], as_dict=True)
	ms = frappe.get_all("TNA Milestone", {"order_tna": name}, ["name", "not_applicable", "actual_date", "partial", "planned_date", "revised_date", "is_critical",
		"status", "delay_days", "color", "progress"])
	for m in ms:
		status, delay, progress = milestone_state(m.not_applicable, m.actual_date, m.partial, m.planned_date, m.revised_date)
		colour = COLOURS[status]
		if (status, delay, progress, m.color) != (m.status, m.delay_days, m.progress, m.color if m.color == colour else None):
			frappe.db.set_value("TNA Milestone", m.name, {"status": status, "delay_days": delay, "progress": progress, "color": colour}, update_modified=False)
		m.update(status=status)
	if t.status == "Cancelled":
		return
	status, worst = order_state(ms, t.plan_feasible)
	if (status, worst) != (t.status, t.critical_delay_days):
		frappe.db.set_value("Order TNA", name, {"status": status, "critical_delay_days": worst}, update_modified=False)


def refresh_all():
	"""Daily job: refresh every open order and tell owners about milestones due tomorrow or overdue. Optional; the board does
	not depend on it."""
	for name in frappe.get_all("Order TNA", {"status": ["not in", ["Completed", "Cancelled"]]}, pluck="name"):
		try:
			refresh_order_tna(name)
		except Exception:
			frappe.log_error(title="T&A refresh failed", message=frappe.get_traceback())
	notify_owners()


def notify_owners():
	from frappe.utils import add_days

	tomorrow = add_days(nowdate(), 1)
	rows = frappe.db.sql(
		"""select m.name, m.label, m.style_no, m.colour, m.planned_date, m.revised_date, m.status, coalesce(m.owner_user, t.merchant) as who
		from `tabTNA Milestone` m join `tabOrder TNA` t on t.name = m.order_tna
		where m.status in ('Not Started', 'In Progress', 'Late') and m.not_applicable = 0 and t.status not in ('Completed', 'Cancelled')
		and (coalesce(m.revised_date, m.planned_date) = %s or m.status = 'Late')""", tomorrow, as_dict=True)
	by_user = {}
	for r in rows:
		if r.who:
			by_user.setdefault(r.who, []).append(r)
	for user, items in by_user.items():
		lines = "".join(f"<li>{i.style_no} {i.colour or ''}: {i.label} ({i.status}, due {i.revised_date or i.planned_date})</li>" for i in items[:50])
		try:
			frappe.sendmail(recipients=[user], subject="T&A: milestones due tomorrow or overdue", message=f"<ul>{lines}</ul>", now=False)
		except Exception:
			frappe.log_error(title="T&A reminder failed", message=frappe.get_traceback())
