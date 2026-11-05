# Copyright (c) 2026, Arinox AI and contributors
"""Receivables Follow-up: customer invoices with the date payment is expected (by the contract's basis), what has been received,
promises and the last action. Replaces the company's receivables workbook. Ageing runs on the expected due date."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

BUCKETS = [(0, 0, "not_due"), (1, 30, "d1_30"), (31, 60, "d31_60"), (61, 90, "d61_90"), (91, 10**6, "d90_plus")]


def bucket(days_overdue):
	if days_overdue <= 0:
		return "not_due"
	for lo, hi, key in BUCKETS[1:]:
		if lo <= days_overdue <= hi:
			return key
	return "d90_plus"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sales_invoice", "label": _("Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"fieldname": "commercial_invoice_no", "label": _("Commercial Invoice No"), "fieldtype": "Data", "width": 190},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 130},
		{"fieldname": "shipment", "label": _("Shipment"), "fieldtype": "Link", "options": "Shipment", "width": 120},
		{"fieldname": "basis", "label": _("Payment Basis"), "fieldtype": "Data", "width": 170},
		{"fieldname": "basis_date", "label": _("Basis Date"), "fieldtype": "Date", "width": 95},
		{"fieldname": "basis_source", "label": _("From"), "fieldtype": "Data", "width": 110},
		{"fieldname": "expected_due", "label": _("Expected Due"), "fieldtype": "Date", "width": 100},
		{"fieldname": "erp_due", "label": _("ERP Due"), "fieldtype": "Date", "width": 95},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 70},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "received", "label": _("Received"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "outstanding", "label": _("Outstanding"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "days_overdue", "label": _("Days Overdue"), "fieldtype": "Int", "width": 90},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "promise_date", "label": _("Promise"), "fieldtype": "Date", "width": 95},
		{"fieldname": "next_action", "label": _("Next Action"), "fieldtype": "Date", "width": 95},
		{"fieldname": "dispute", "label": _("Dispute"), "fieldtype": "Data", "width": 160},
	]
	for _lo, _hi, key in BUCKETS:
		columns.append({"fieldname": key, "label": {"not_due": _("Not Due"), "d1_30": "1-30", "d31_60": "31-60", "d61_90": "61-90", "d90_plus": "90+"}[key], "fieldtype": "Currency", "options": "currency", "width": 100})
	cond = {"docstatus": 1, "is_internal_customer": 0, "is_return": 0}
	for f in ("customer", "company"):
		if filters.get(f):
			cond[f] = filters[f]
	if filters.contract:
		cond["apparel_sales_contract"] = filters.contract
	today = getdate(filters.as_on or nowdate())
	data = []
	for si in frappe.get_all("Sales Invoice", cond, ["name", "apparel_commercial_invoice_no", "customer", "company", "apparel_shipment", "apparel_due_basis", "apparel_basis_date",
							"apparel_basis_source", "apparel_expected_due_date", "due_date", "currency", "grand_total", "outstanding_amount", "apparel_promise_date",
							"apparel_next_action_date", "apparel_dispute_reason", "apparel_followup_status"], order_by="apparel_expected_due_date",
							or_filters=[["apparel_shipment", "is", "set"], ["apparel_is_sample_invoice", "=", 1]]):
		out = flt(si.outstanding_amount)
		if not filters.show_paid and out <= 0.005:
			continue
		due = si.apparel_expected_due_date or si.due_date
		days = (today - getdate(due)).days if due and out > 0.005 else 0
		row = {"sales_invoice": si.name, "commercial_invoice_no": si.apparel_commercial_invoice_no, "customer": si.customer, "company": si.company, "shipment": si.apparel_shipment,
			   "basis": si.apparel_due_basis, "basis_date": si.apparel_basis_date, "basis_source": si.apparel_basis_source, "expected_due": due, "erp_due": si.due_date,
			   "currency": si.currency, "amount": flt(si.grand_total), "received": flt(si.grand_total) - out, "outstanding": out, "days_overdue": max(days, 0),
			   "status": si.apparel_followup_status, "promise_date": si.apparel_promise_date, "next_action": si.apparel_next_action_date, "dispute": si.apparel_dispute_reason}
		for _lo, _hi, key in BUCKETS:
			row[key] = 0
		if out > 0.005:
			row[bucket(days)] = out
		data.append(row)
	return columns, data
