# Copyright (c) 2026, Arinox AI and contributors
"""Subcontract Challan: pieces sent to a vendor for a process (wash, embroidery, print, appliqué). Posts SC_OUT to the
production ledger against the process on the card's route. The vendor's work is priced on a Purchase Order."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from arinox_apparel.production import ledger, maths
from arinox_apparel.shipping import common
from arinox_apparel.tna.planner import holiday_dates


class SubcontractChallan(Document):
	def autoname(self):
		self.name = common.next_serial(common.card_root(self.production_card), "SC")

	def validate(self):
		card = common.require_open_card(self.production_card)
		self.sales_contract = card.sales_contract
		self.sales_order = card.sales_order
		if not self.rows:
			frappe.throw(_("Add the pieces being sent."))
		on_card = {(l.colour, l.size) for l in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["colour", "size"])}
		total = 0
		for r in self.rows:
			r.qty = cint(r.qty)
			if r.qty <= 0:
				frappe.throw(_("Row {0}: enter a quantity above zero.").format(r.idx))
			if (r.colour, r.size) not in on_card:
				frappe.throw(_("Row {0}: {1} {2} is not on production card {3}.").format(r.idx, r.colour, r.size, self.production_card))
			total += r.qty
		self.total_qty = total
		proc = frappe.db.get_value("Subcontract Process", self.subcontract_process, ["enabled", "turnaround_days"], as_dict=True)
		if not proc or not proc.enabled:
			frappe.throw(_("Process {0} is not enabled.").format(self.subcontract_process))
		self.set_return_date(proc.turnaround_days)
		self.check_order()

	def set_return_date(self, days):
		if cint(days) and self.challan_date:
			self.expected_return_date = maths.add_working_days(getdate(self.challan_date), cint(days), holiday_dates(self.company_name()))

	def company_name(self):
		return frappe.db.get_value("Production Card", self.production_card, "company")

	def check_order(self):
		"""Warn when the pieces sent on all challans against one order exceed what the order allows."""
		if not self.purchase_order:
			return
		po_qty = frappe.db.sql("select ifnull(sum(qty), 0) from `tabPurchase Order Item` where parent = %s", self.purchase_order)[0][0]
		tol = flt(frappe.db.get_value("Subcontract Process", self.subcontract_process, "qty_tolerance_pct"))
		sent = frappe.db.sql(
			"select ifnull(sum(total_qty), 0) from `tabSubcontract Challan` where purchase_order = %s and docstatus = 1 and name != %s",
			(self.purchase_order, self.name or ""))[0][0]
		if po_qty and sent + self.total_qty > po_qty * (1 + tol / 100.0) + 1e-9:
			frappe.msgprint(_("Pieces sent on this order would be {0}; the order is for {1} (+{2} %).").format(sent + self.total_qty, int(po_qty), tol), indicator="orange")

	def rows_to_post(self):
		return [{"stage": "SC_OUT", "colour": r.colour, "size": r.size, "qty": r.qty, "process": self.subcontract_process,
				 "supplier": self.supplier, "shade_band": r.shade_band, "source_row": r.name} for r in self.rows]

	def post_movements(self, check=False):
		ledger.post(self.production_card, self.rows_to_post(), "Subcontract Challan", self.name, self.challan_date, check=check)

	def on_submit(self):
		self.post_movements(check=True)
		frappe.db.set_value("Subcontract Challan", self.name, "status", "Open", update_modified=False)

	def before_cancel(self):
		if frappe.db.exists("Subcontract Return", {"challan": self.name, "docstatus": 1}):
			frappe.throw(_("Cancel the returns against this challan first."))
		if frappe.db.exists("Subcontract Settlement", {"challan": self.name, "docstatus": 1}):
			frappe.throw(_("Cancel the settlement of this challan first."))

	def on_cancel(self):
		ledger.unpost("Subcontract Challan", self.name)


def refresh_returns(challan):
	"""Recompute what came back against each challan row and the challan status from the submitted returns."""
	doc = frappe.get_doc("Subcontract Challan", challan)
	back = {}
	for colour, size, qty in frappe.db.sql(
		"""select r.colour, r.size, sum(r.good_qty + r.reject_vendor_qty + r.reject_factory_qty) from `tabSubcontract Return Row` r
		join `tabSubcontract Return` p on p.name = r.parent where p.docstatus = 1 and p.challan = %s group by r.colour, r.size""", challan):
		back[(colour, size)] = qty or 0
	total = 0
	for r in doc.rows:
		take = min(r.qty, back.get((r.colour, r.size), 0))
		back[(r.colour, r.size)] = back.get((r.colour, r.size), 0) - take
		total += take
		frappe.db.set_value("Subcontract Challan Row", r.name, "returned_qty", take, update_modified=False)
	status = doc.status
	if status != "Short Closed":
		status = "Returned" if total >= doc.total_qty else ("Partly Returned" if total else "Open")
	frappe.db.set_value("Subcontract Challan", challan, {"returned_qty": total, "status": status}, update_modified=False)


@frappe.whitelist()
def short_close(challan, reason):
	"""Accept that the rest will not come back. Production Manager only; the gap shows as Short on the settlement."""
	if "Apparel Production Manager" not in frappe.get_roles() and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a Production Manager can short-close a challan."))
	if not (reason or "").strip():
		frappe.throw(_("Write the reason."))
	doc = frappe.get_doc("Subcontract Challan", challan)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted challan can be short-closed."))
	frappe.db.set_value("Subcontract Challan", challan, {"status": "Short Closed", "short_close_reason": reason})
