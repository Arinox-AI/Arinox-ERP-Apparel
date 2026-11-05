"""Payment follow-up on the customer's Sales Invoice. ERPNext keeps the due date fixed once an invoice is submitted, and
the contract may count the days from the bill of lading, the arrival or the receipt of goods. So the *expected* due date
lives in custom fields on the invoice, recomputed whenever the shipment's dates change, and reminders follow that date.
Reminder letters are ERPNext Dunnings, created as drafts; the log of calls is the invoice's own comments."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from arinox_apparel.shipping import common

ROG, INVOICE, BL, ETA = "Days after Receipt of Goods (ROG)", "Days after Invoice Date", "Days after B/L Date", "Days after ETA"


def expected_due(basis, days, invoice_date, on_board=None, eta=None, delivery=None, buffer_days=5, transit_days=0):
	"""(basis date, where it came from, expected due date). ROG counts from the recorded delivery; until then from the
	arrival plus a buffer; until there is an arrival, from the sailing date plus the transit time."""
	days = cint(days)
	invoice_date = getdate(invoice_date)
	if basis == BL:
		d, src = (getdate(on_board), "B/L") if on_board else (invoice_date, "Invoice (no B/L yet)")
	elif basis == ETA:
		d, src = (getdate(eta), "ETA") if eta else (invoice_date, "Invoice (no ETA yet)")
	elif basis == ROG:
		if delivery:
			d, src = getdate(delivery), "Delivery"
		elif eta:
			d, src = getdate(eta) + timedelta(days=cint(buffer_days)), "ETA + buffer"
		elif on_board:
			d, src = getdate(on_board) + timedelta(days=cint(transit_days) + cint(buffer_days)), "B/L + transit + buffer"
		else:
			d, src = invoice_date, "Invoice (no dates yet)"
	else:
		d, src = invoice_date, "Invoice"
	return d, src, d + timedelta(days=days)


def contract_terms(contract):
	if not contract or not frappe.db.exists("Sales Contract", contract):
		return None, 0, 0
	return frappe.db.get_value("Sales Contract", contract, ["payment_basis", "payment_days", "transit_days"]) or (None, 0, 0)


def refresh_invoice(name):
	"""Recompute the expected due date of one invoice from its contract terms and its shipment's dates."""
	si = frappe.db.get_value("Sales Invoice", name, ["apparel_sales_contract", "apparel_shipment", "posting_date", "docstatus", "apparel_route_leg", "is_internal_customer"], as_dict=True)
	if not si or si.docstatus == 2 or cint(si.is_internal_customer):
		return
	basis, days, transit = contract_terms(si.apparel_sales_contract)
	ship = frappe.db.get_value("Shipment", si.apparel_shipment, ["apparel_on_board_date", "apparel_eta", "apparel_delivery_date", "apparel_arrival_date"], as_dict=True) if si.apparel_shipment else None
	arrival = (ship.apparel_arrival_date or ship.apparel_eta) if ship else None
	d, src, due = expected_due(basis, days, si.posting_date, ship.apparel_on_board_date if ship else None, arrival,
							   ship.apparel_delivery_date if ship else None, common.settings_value("rog_buffer_days", 5), transit)
	frappe.db.set_value("Sales Invoice", name, {"apparel_due_basis": basis or "", "apparel_basis_date": d, "apparel_expected_due_date": due, "apparel_basis_source": src}, update_modified=False)
	return due


def refresh_for_shipment(shipment):
	for name in frappe.get_all("Sales Invoice", {"apparel_shipment": shipment, "docstatus": ["<", 2]}, pluck="name"):
		refresh_invoice(name)


def status_for(outstanding, grand_total, due, today, promise=None, disputed=False, soon_days=7):
	"""Follow-up status for one invoice. Pure, so it can be tested with fixed dates."""
	today = getdate(today)
	if flt(outstanding) <= 0.005:
		return "Paid", 0
	overdue = (today - getdate(due)).days if due else 0
	if disputed:
		return "Disputed", max(overdue, 0)
	if overdue > 0:
		if promise and getdate(promise) >= today:
			return "Promised", overdue
		return "Overdue", overdue
	if flt(outstanding) < flt(grand_total) - 0.005:
		return "Partly Paid", 0
	if due and (getdate(due) - today).days <= soon_days:
		return "Due Soon", 0
	return "Not Due", 0


def daily():
	"""Scheduler: refresh every open customer invoice, and raise a ToDo when it crosses a reminder or escalation line."""
	today = getdate(nowdate())
	soon = cint(common.settings_value("reminder_days_before_due", 7))
	levels = [(cint(common.settings_value("escalation_days_1", 15)), "Send a payment reminder (Dunning level 1)"),
			  (cint(common.settings_value("escalation_days_2", 30)), "Second reminder and manager attention"),
			  (cint(common.settings_value("escalation_days_3", 60)), "Escalate to management")]
	rows = frappe.get_all("Sales Invoice", {"docstatus": 1, "is_internal_customer": 0, "is_return": 0},
						  ["name", "outstanding_amount", "grand_total", "apparel_expected_due_date", "apparel_promise_date", "apparel_dispute_reason", "customer", "owner", "apparel_followup_status"],
						  or_filters=[["apparel_shipment", "is", "set"], ["apparel_is_sample_invoice", "=", 1]])
	for si in rows:
		if flt(si.outstanding_amount) <= 0 and si.apparel_followup_status == "Paid":
			continue   # paid and already marked: nothing to refresh
		if not si.apparel_expected_due_date:
			refresh_invoice(si.name)
			si.apparel_expected_due_date = frappe.db.get_value("Sales Invoice", si.name, "apparel_expected_due_date")
		status, overdue = status_for(si.outstanding_amount, si.grand_total, si.apparel_expected_due_date, today, si.apparel_promise_date, bool(si.apparel_dispute_reason), soon)
		frappe.db.set_value("Sales Invoice", si.name, {"apparel_followup_status": status, "apparel_days_overdue": overdue}, update_modified=False)
		if status == "Due Soon":
			_todo(si, _("Payment of {0} from {1} falls due on {2}: send a reminder.").format(si.name, si.customer, si.apparel_expected_due_date), "due-soon")
		if status == "Overdue":
			hit = [(d, a) for d, a in levels if overdue >= d]
			if hit:
				d, action = hit[-1]
				_todo(si, _("{0}: {1} is {2} days overdue ({3}).").format(si.name, si.customer, overdue, action), f"overdue-{d}")


def _todo(si, description, key):
	ref = f"{si.name}:{key}"
	if frappe.db.exists("ToDo", {"reference_type": "Sales Invoice", "reference_name": si.name, "description": ["like", f"%[{ref}]%"]}):
		return
	frappe.get_doc({"doctype": "ToDo", "allocated_to": si.owner, "reference_type": "Sales Invoice", "reference_name": si.name,
					"description": f"{description} [{ref}]", "priority": "Medium"}).insert(ignore_permissions=True)


@frappe.whitelist()
def log_follow_up(invoice, note, promise_date=None, promise_amount=None, next_action_date=None, dispute_reason=None):
	"""Record a call or a promise on a customer invoice. The note becomes a comment; the promise and the next action are fields."""
	if not frappe.has_permission("Sales Invoice", "read", invoice):
		frappe.throw(_("You cannot read this invoice."), frappe.PermissionError)
	if not ({"Accounts User", "Accounts Manager", "Apparel Merchandising Manager", "System Manager"} & set(frappe.get_roles())):
		frappe.throw(_("Only accounts or merchandising managers log payment follow-up."))
	if not (note or "").strip():
		frappe.throw(_("Write what was said or agreed."))
	changes = {}
	if promise_date:
		changes["apparel_promise_date"] = getdate(promise_date)
		changes["apparel_promise_amount"] = flt(promise_amount)
	if next_action_date:
		changes["apparel_next_action_date"] = getdate(next_action_date)
	if dispute_reason is not None:
		changes["apparel_dispute_reason"] = dispute_reason
	if changes:
		frappe.db.set_value("Sales Invoice", invoice, changes, update_modified=False)
	frappe.get_doc("Sales Invoice", invoice).add_comment("Comment", note)
	si = frappe.db.get_value("Sales Invoice", invoice, ["outstanding_amount", "grand_total", "apparel_expected_due_date", "apparel_promise_date", "apparel_dispute_reason"], as_dict=True)
	status, overdue = status_for(si.outstanding_amount, si.grand_total, si.apparel_expected_due_date, nowdate(), si.apparel_promise_date, bool(si.apparel_dispute_reason))
	frappe.db.set_value("Sales Invoice", invoice, {"apparel_followup_status": status, "apparel_days_overdue": overdue}, update_modified=False)
	return status
