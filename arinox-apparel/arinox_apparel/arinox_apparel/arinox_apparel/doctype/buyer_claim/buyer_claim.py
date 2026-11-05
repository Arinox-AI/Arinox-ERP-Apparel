# Copyright (c) 2026, Arinox AI and contributors
"""Buyer Claim: a complaint, short-shipment claim, chargeback or concession against a customer invoice. The contract sets
the window (quality 60 days, quantity 30 days after arrival) and caps what is payable at the CIF value of the pieces.
Settling drafts a credit note; a deduction is recorded on the payment. Nothing is submitted for the accountant."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from arinox_apparel.shipping import common

NO_WINDOW = ("Chargeback", "Concession")
MANAGERS = {"Accounts Manager", "Apparel Merchandising Manager", "System Manager"}


def window_check(claim_type, arrival, on_date, quality_days, quantity_days):
	"""(days allowed, days since arrival, ok). Pure, for tests: a claim after the window needs a reason to be accepted."""
	if claim_type in NO_WINDOW:
		return 0, 0, True
	allowed = cint(quality_days if claim_type in ("Quality", "Wrong Item", "Other") else quantity_days)
	if not arrival or not allowed:
		return allowed, 0, True
	since = date_diff(getdate(on_date), getdate(arrival))
	return allowed, since, since <= allowed


class BuyerClaim(Document):
	def autoname(self):
		inv = frappe.db.get_value("Sales Invoice", self.sales_invoice, "apparel_sales_contract") or self.sales_invoice
		self.name = common.next_serial(inv, "CL")

	def validate(self):
		si = frappe.db.get_value("Sales Invoice", self.sales_invoice, ["docstatus", "apparel_sales_contract", "apparel_shipment", "net_total", "total_qty", "is_internal_customer", "company"], as_dict=True)
		if not si or si.docstatus != 1:
			frappe.throw(_("Invoice {0} must be submitted.").format(self.sales_invoice))
		if cint(si.is_internal_customer):
			frappe.throw(_("Claims are raised against the buyer's invoice, not the group invoice."))
		self.sales_contract, self.shipment = si.apparel_sales_contract, si.apparel_shipment
		if flt(self.claimed_amount) <= 0:
			frappe.throw(_("Enter the amount claimed."))
		for r in self.rows:
			if cint(r.pieces) <= 0:
				frappe.throw(_("Claim row {0}: enter the pieces.").format(r.idx))
		pieces = sum(cint(r.pieces) for r in self.rows)
		unit = flt(si.net_total) / flt(si.total_qty) if flt(si.total_qty) else 0
		self.cap_amount = round(unit * pieces, 2) if pieces else flt(si.net_total)
		self.set_window()
		if self.docstatus == 0 and self.settlement == "Credit Note" and not self.rows and self.claim_type not in NO_WINDOW:
			frappe.msgprint(_("Add the pieces claimed so the cap can be worked out."), indicator="orange")
		if self.evidence is None and self.claim_type not in NO_WINDOW and cint(common.settings_value("claim_requires_evidence", 1)) and self.docstatus == 0:
			frappe.msgprint(_("Attach the buyer's evidence (photos or report) before accepting the claim."), indicator="orange")

	def set_window(self):
		arrival = None
		if self.shipment:
			arrival = frappe.db.get_value("Shipment", self.shipment, "apparel_arrival_date") or frappe.db.get_value("Shipment", self.shipment, "apparel_delivery_date")
		self.arrival_date = arrival
		q, n = (frappe.db.get_value("Sales Contract", self.sales_contract, ["quality_claim_days", "quantity_claim_days"]) or (0, 0)) if self.sales_contract and frappe.db.exists("Sales Contract", self.sales_contract) else (0, 0)
		allowed, since, ok = window_check(self.claim_type, arrival, self.reported_on or nowdate(), q, n)
		self.window_days, self.days_since_arrival = allowed, since
		self.window_note = "" if ok else _("Reported {0} days after arrival; the contract allows {1}.").format(since, allowed)

	def before_submit(self):
		if self.status in ("Accepted", "Partly Accepted"):
			if flt(self.accepted_amount) <= 0:
				frappe.throw(_("Enter the amount accepted."))
			if not self.settlement:
				frappe.throw(_("Choose how it is settled."))
			outside = bool(self.window_note) or flt(self.accepted_amount) > flt(self.cap_amount) + 0.005
			if outside:
				if not (MANAGERS & set(frappe.get_roles())):
					frappe.throw(_("Accepting outside the claim window or above the cap needs a manager."))
				if not (self.override_reason or "").strip():
					frappe.throw(_("Write why this is accepted outside the window or above the cap."))
		elif self.status == "Open":
			frappe.throw(_("Decide the claim before submitting: Under Review is saved as a draft, then Accepted, Partly Accepted or Rejected."))

	def on_update(self):
		self.sync_invoice()

	def on_submit(self):
		self.sync_invoice()

	def on_cancel(self):
		self.sync_invoice(cancelled=True)

	def sync_invoice(self, cancelled=False):
		"""While a claim is undecided or being settled, the invoice is Disputed so no reminders go out."""
		if not self.sales_invoice:
			return
		open_claims = frappe.db.count("Buyer Claim", {"sales_invoice": self.sales_invoice, "docstatus": ["<", 2], "status": ["in", ["Open", "Under Review"]], "name": ["!=", self.name if cancelled else ""]})
		if cancelled:
			open_claims = frappe.db.count("Buyer Claim", {"sales_invoice": self.sales_invoice, "docstatus": ["<", 2], "status": ["in", ["Open", "Under Review"]], "name": ["!=", self.name]})
		frappe.db.set_value("Sales Invoice", self.sales_invoice, "apparel_dispute_reason", (_("Open claim {0}").format(self.name) if open_claims else ""), update_modified=False)


@frappe.whitelist()
def make_credit_note(claim):
	"""Draft the credit note for an accepted claim against the customer invoice (the accountant submits it)."""
	if not frappe.has_permission("Sales Invoice", "create"):
		frappe.throw(_("You cannot create sales invoices."), frappe.PermissionError)
	c = frappe.get_doc("Buyer Claim", claim)
	c.check_permission("read")
	if c.docstatus != 1 or c.settlement != "Credit Note" or flt(c.accepted_amount) <= 0:
		frappe.throw(_("Only a submitted claim settled by credit note can be credited."))
	if c.credit_note:
		return c.credit_note
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	cn = make_sales_return(c.sales_invoice)
	item = cn.items[0]
	cn.set("items", [{"item_code": item.item_code, "item_name": item.item_name, "description": _("Claim {0}: {1}").format(c.name, c.claim_type), "qty": -1,
					  "uom": item.uom, "rate": flt(c.accepted_amount), "income_account": item.income_account, "cost_center": item.cost_center}])
	cn.update_stock = 0
	cn.run_method("calculate_taxes_and_totals")
	cn.insert()
	c.db_set("credit_note", cn.name)
	return cn.name
