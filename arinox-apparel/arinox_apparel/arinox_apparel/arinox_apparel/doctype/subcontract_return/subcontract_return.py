# Copyright (c) 2026, Arinox AI and contributors
"""Subcontract Return: pieces that came back from the vendor, split into good, vendor fault and factory fault.
A vendor cannot return more than was sent on the challan. Posts SC_BACK_* to the production ledger."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate

from arinox_apparel.arinox_apparel.doctype.subcontract_challan.subcontract_challan import refresh_returns
from arinox_apparel.production import ledger
from arinox_apparel.shipping import common


class SubcontractReturn(Document):
	def autoname(self):
		root = common.card_root(frappe.db.get_value("Subcontract Challan", self.challan, "production_card"))
		self.name = common.next_serial(root, "SR")

	def validate(self):
		ch = frappe.db.get_value("Subcontract Challan", self.challan, ["docstatus", "status", "production_card", "supplier", "subcontract_process", "expected_return_date", "sales_contract"], as_dict=True)
		if not ch or ch.docstatus != 1:
			frappe.throw(_("Challan {0} must be submitted.").format(self.challan))
		if ch.status == "Short Closed":
			frappe.throw(_("Challan {0} was short-closed; nothing more can be received on it.").format(self.challan))
		self.production_card, self.supplier, self.subcontract_process, self.sales_contract = ch.production_card, ch.supplier, ch.subcontract_process, ch.sales_contract
		if not self.rows:
			frappe.throw(_("Add the pieces received."))
		sent, back = {}, {}
		for r in frappe.get_all("Subcontract Challan Row", {"parent": self.challan}, ["colour", "size", "qty"]):
			sent[(r.colour, r.size)] = sent.get((r.colour, r.size), 0) + r.qty
		for colour, size, qty in frappe.db.sql(
			"""select r.colour, r.size, sum(r.good_qty + r.reject_vendor_qty + r.reject_factory_qty) from `tabSubcontract Return Row` r
			join `tabSubcontract Return` p on p.name = r.parent where p.docstatus = 1 and p.challan = %s and p.name != %s group by r.colour, r.size""",
			(self.challan, self.name or "")):
			back[(colour, size)] = qty or 0
		good = rv = rf = 0
		now = {}
		for r in self.rows:
			r.production_card = self.production_card
			for fld in ("good_qty", "reject_vendor_qty", "reject_factory_qty", "accepted_for_repair"):
				setattr(r, fld, cint(r.get(fld)))
				if r.get(fld) < 0:
					frappe.throw(_("Row {0}: quantities cannot be negative.").format(r.idx))
			key = (r.colour, r.size)
			if key not in sent:
				frappe.throw(_("Row {0}: {1} {2} was not sent on challan {3}.").format(r.idx, r.colour, r.size, self.challan))
			r.sent_qty = sent[key]
			got = r.good_qty + r.reject_vendor_qty + r.reject_factory_qty
			if got <= 0:
				frappe.throw(_("Row {0}: enter the pieces received.").format(r.idx))
			if r.accepted_for_repair > r.reject_factory_qty:
				frappe.throw(_("Row {0}: only factory-fault pieces can be taken back to repair.").format(r.idx))
			now[key] = now.get(key, 0) + got
			if now[key] + back.get(key, 0) > sent[key]:
				frappe.throw(_("Row {0}: {1} {2} — {3} received in all, only {4} were sent.").format(r.idx, r.colour, r.size, now[key] + back.get(key, 0), sent[key]))
			good += r.good_qty
			rv += r.reject_vendor_qty
			rf += r.reject_factory_qty
		self.total_good, self.total_reject_vendor, self.total_reject_factory = good, rv, rf
		if ch.expected_return_date and getdate(self.return_date) > getdate(ch.expected_return_date) and self.docstatus == 0:
			frappe.msgprint(_("This return is {0} day(s) after the date agreed ({1}).").format((getdate(self.return_date) - getdate(ch.expected_return_date)).days, ch.expected_return_date), indicator="orange")

	def rows_to_post(self):
		out = []
		for r in self.rows:
			base = {"colour": r.colour, "size": r.size, "process": self.subcontract_process, "supplier": self.supplier, "shade_band": r.shade_band, "source_row": r.name}
			if r.good_qty:
				out.append(dict(base, stage="SC_BACK_GOOD", qty=r.good_qty))
			if r.reject_vendor_qty:
				out.append(dict(base, stage="SC_BACK_REJECT_VENDOR", qty=r.reject_vendor_qty, fault_source="Subcontractor"))
			if r.reject_factory_qty:
				fault = (frappe.db.get_value("Apparel Defect Code", r.defect_code, "fault_source") if r.defect_code else None) or "Unknown"
				out.append(dict(base, stage="SC_BACK_REJECT_FACTORY", qty=r.reject_factory_qty, fault_source=fault))
		return out

	def post_movements(self, check=False):
		ledger.post(self.production_card, self.rows_to_post(), "Subcontract Return", self.name, self.return_date, check=check)

	def on_submit(self):
		self.post_movements(check=False)
		refresh_returns(self.challan)

	def before_cancel(self):
		if frappe.db.exists("Subcontract Settlement", {"challan": self.challan, "docstatus": 1}):
			frappe.throw(_("Cancel the settlement of challan {0} first.").format(self.challan))
		if frappe.db.exists("Finishing Receipt", {"production_card": self.production_card, "docstatus": 1}):
			frappe.msgprint(_("Finishing receipts exist for this card; the flow check will stop the cancel if they used these pieces."), indicator="orange")

	def on_cancel(self):
		ledger.unpost("Subcontract Return", self.name)
		refresh_returns(self.challan)
