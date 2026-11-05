# Copyright (c) 2026, Arinox AI and contributors
"""Subcontract Settlement: what the vendor is owed for one challan. Vendor-damaged and missing pieces are not paid;
vendor damage above the process's limit attracts a penalty. Drafts the vendor's invoice and a debit note for the
accountant; nothing is submitted here."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.production import maths
from arinox_apparel.shipping import common


def unit_value_for_card(card, basis):
	"""Value of one piece for the penalty: the Cost Sheet FOB price, the Sales Order rate, or nothing for a fixed basis."""
	if basis == "Fixed Per Piece":
		return 0.0
	c = common.card_context(card)
	rows = frappe.db.sql(
		"select i.rate, i.apparel_cost_sheet from `tabSales Order Item` i where i.parent = %s and i.item_code in "
		"(select name from `tabItem` where variant_of = %s or name = %s) order by i.idx limit 1", (c.sales_order, c.style_item, c.style_item), as_dict=True)
	if not rows:
		return 0.0
	if basis == "Cost Sheet FOB" and rows[0].apparel_cost_sheet:
		price = frappe.db.get_value("Cost Sheet", rows[0].apparel_cost_sheet, "approved_price")
		if price:
			return flt(price)
	return flt(rows[0].rate)


class SubcontractSettlement(Document):
	def autoname(self):
		root = common.card_root(frappe.db.get_value("Subcontract Challan", self.challan, "production_card"))
		self.name = common.next_serial(root, "SS")

	def validate(self):
		ch = frappe.db.get_value("Subcontract Challan", self.challan, ["docstatus", "production_card", "total_qty", "subcontract_process", "supplier", "purchase_order"], as_dict=True)
		if not ch or ch.docstatus != 1:
			frappe.throw(_("Challan {0} must be submitted.").format(self.challan))
		if frappe.db.exists("Subcontract Settlement", {"challan": self.challan, "docstatus": ["<", 2], "name": ["!=", self.name or ""]}):
			frappe.throw(_("Challan {0} already has a settlement.").format(self.challan))
		self.compute(ch)

	def compute(self, ch):
		proc = frappe.db.get_value("Subcontract Process", ch.subcontract_process, ["damage_threshold_pct", "qty_tolerance_pct"], as_dict=True)
		tot = frappe.db.sql(
			"""select ifnull(sum(r.good_qty), 0), ifnull(sum(r.reject_vendor_qty), 0), ifnull(sum(r.reject_factory_qty), 0)
			from `tabSubcontract Return Row` r join `tabSubcontract Return` p on p.name = r.parent where p.docstatus = 1 and p.challan = %s""", self.challan)[0]
		self.sent_qty = ch.total_qty
		self.good_qty, self.reject_vendor_qty, self.reject_factory_qty = (cint(x) for x in tot)
		self.short_qty = max(0, self.sent_qty - self.good_qty - self.reject_vendor_qty - self.reject_factory_qty)
		self.threshold_pct = flt(proc.damage_threshold_pct)
		self.qty_tolerance_pct = flt(proc.qty_tolerance_pct)
		basis = common.settings_value("subcontract_penalty_basis", "Cost Sheet FOB")
		scope = common.settings_value("subcontract_penalty_scope", "All Damaged")
		row_values = [(r.qty, flt(r.unit_value)) for r in frappe.get_all("Subcontract Challan Row", {"parent": self.challan}, ["qty", "unit_value"]) if flt(r.unit_value)]
		if row_values:
			self.unit_value = sum(q * v for q, v in row_values) / sum(q for q, _v in row_values)
		else:
			self.unit_value = unit_value_for_card(ch.production_card, basis)
		rate, qty, amount = maths.penalty(self.sent_qty, self.reject_vendor_qty, self.threshold_pct, self.unit_value, scope)
		self.vendor_reject_pct = round(rate or 0, 4)
		self.penalty_qty, self.penalty_amount = qty, round(amount, 2)
		self.payable_qty = self.good_qty + self.reject_factory_qty
		self.gross_amount = round(self.payable_qty * flt(self.rate), 2)
		self.net_amount = round(self.gross_amount - self.penalty_amount, 2)
		self.variance_note = ""
		if cint(self.invoiced_qty):
			self.invoice_variance_pct = round(maths.over_short_pct(self.invoiced_qty, self.sent_qty) or 0, 2)
			notes = []
			if abs(self.invoice_variance_pct) > self.qty_tolerance_pct:
				notes.append(_("The vendor invoices {0} pieces against {1} sent ({2} %), outside the ±{3} % allowed.").format(self.invoiced_qty, self.sent_qty, self.invoice_variance_pct, self.qty_tolerance_pct))
			if self.invoiced_qty > self.payable_qty:
				notes.append(_("The invoice charges {0} pieces more than the {1} we owe for.").format(self.invoiced_qty - self.payable_qty, self.payable_qty))
			self.variance_note = "\n".join(notes)
			if notes and self.docstatus == 0:
				frappe.msgprint("<br>".join(notes), indicator="orange")

	def before_submit(self):
		if not self.rate:
			frappe.throw(_("Enter the rate per piece."))


@frappe.whitelist()
def make_invoices(settlement):
	"""Draft the vendor's Purchase Invoice (and a debit note for the penalty). Accounts submits them."""
	if not frappe.has_permission("Purchase Invoice", "create"):
		frappe.throw(_("You cannot create purchase invoices."), frappe.PermissionError)
	doc = frappe.get_doc("Subcontract Settlement", settlement)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the settlement first."))
	item = frappe.db.get_value("Subcontract Process", doc.subcontract_process, "service_item")
	if not item:
		frappe.throw(_("Set the Service Item on process {0} first.").format(doc.subcontract_process))
	company = frappe.db.get_value("Production Card", doc.production_card, "company")
	if not doc.purchase_invoice and doc.payable_qty:
		pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": company, "supplier": doc.supplier, "bill_no": doc.vendor_invoice_ref,
							 "posting_date": doc.settlement_date, "items": [{"item_code": item, "qty": doc.payable_qty, "rate": doc.rate}]})
		pi.insert()
		doc.db_set("purchase_invoice", pi.name)
	if not doc.debit_note and doc.penalty_amount:
		dn = frappe.get_doc({"doctype": "Purchase Invoice", "company": company, "supplier": doc.supplier, "is_return": 1, "posting_date": doc.settlement_date,
							 "items": [{"item_code": item, "qty": -1, "rate": doc.penalty_amount, "description": _("Damage penalty, challan {0}").format(doc.challan)}]})
		dn.insert()
		doc.db_set("debit_note", dn.name)
	return {"purchase_invoice": doc.purchase_invoice or None, "debit_note": doc.debit_note or None}
