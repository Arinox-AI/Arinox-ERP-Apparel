# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Trim Inspection: the visual inspection of a trim received on one Purchase Receipt row (labels, buttons, tags ...).
A sampling plan sets how many pieces are checked; submit makes the Quality Inspection and releases or rejects the stock."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import MANAGER_ROLES
from arinox_apparel.materials import common as mc
from arinox_apparel.materials import inspection as ins


class TrimInspection(Document):
	def validate(self):
		self.ctx = ins.receipt_context(self.purchase_receipt, self.purchase_receipt_item, "Trim")
		c = self.ctx
		self.company, self.supplier, self.trim_item = c.pr.company, c.pr.supplier, c.row.item_code
		self.purchase_order, self.trim_requisition = c.get("purchase_order"), c.requisition
		self.customer, self.style_nos = c.customer, ", ".join(c.styles)
		self.received_qty = flt(c.row.stock_qty)
		self.material_description = self.material_description or frappe.db.get_value("Item", self.trim_item, "item_name")
		if cint(self.result_override):
			if not set(frappe.get_roles()) & set(MANAGER_ROLES):
				frappe.throw(_("Only an Apparel Merchandising Manager can override the inspection rules."))
			if not (self.override_reason or "").strip():
				frappe.throw(_("Enter the reason for overriding the inspection rules."))
		plan_name = self.sampling_plan or mc.settings().get("default_trim_sampling_plan")
		if not plan_name:
			frappe.throw(_("Choose a sampling plan, or set a default in Apparel Settings."))
		self.sampling_plan = plan_name
		plan = frappe.get_doc("Trim Sampling Plan", plan_name)
		self.sample_size, self.accept_max, self.reject_min = ins.trim_sample(plan, self.received_qty)
		if flt(self.inspected_qty) <= 0:
			frappe.throw(_("Enter the quantity inspected."))
		if flt(self.inspected_qty) > self.received_qty + 0.0001:
			frappe.throw(_("Inspected qty cannot be more than the received qty ({0}).").format(self.received_qty))
		self.defective_qty = sum(cint(d.count) for d in self.defects)
		if flt(self.defective_qty) > flt(self.inspected_qty):
			frappe.throw(_("More defects ({0}) than pieces inspected ({1}).").format(self.defective_qty, self.inspected_qty))
		self.defective_pct = flt(self.defective_qty * 100 / flt(self.inspected_qty), 2)
		mixup = any((d.defect_type or "").lower().replace("-", " ") == "size mix up" and cint(d.count) for d in self.defects)
		held = self.result == "Hold"
		self.result = "Hold" if held else ins.trim_result(plan, self.defective_qty, self.inspected_qty, self.reject_min, mixup)
		if self.result == "Pass":
			self.rejected_qty, self.accepted_qty = flt(self.defective_qty), flt(self.received_qty - self.defective_qty)
		elif self.result == "Fail":
			self.rejected_qty, self.accepted_qty = flt(self.received_qty), 0
		else:
			self.rejected_qty = self.accepted_qty = 0
		self.rejected_pct = flt(self.rejected_qty * 100 / self.received_qty, 2) if self.received_qty else 0

	def before_submit(self):
		if flt(self.inspected_qty) + 0.0001 < flt(self.sample_size) and not cint(self.result_override):
			frappe.throw(_("Inspect at least {0} pieces for this lot ({1} inspected).").format(flt(self.sample_size), flt(self.inspected_qty)))

	def on_submit(self):
		ok = self.result == "Pass"
		mixup = any((d.defect_type or "").lower().replace("-", " ") == "size mix up" and cint(d.count) for d in self.defects)
		qi = ins.make_quality_inspection(self.ctx, self.trim_item, ok, [
			("Trim Defective %", self.defective_pct, "Accepted" if ok else "Rejected"),
			("Trim Size Mix-up", "Yes" if mixup else "No", "Rejected" if mixup else "Accepted"),
		], self.inspected_qty, self.remarks)
		store = mc.company_warehouse("store_warehouse_trim", self.company)
		reject = mc.company_warehouse("rejected_warehouse", self.company)
		rows = [{"item_code": self.trim_item, "qty": self.accepted_qty, "target": store},
			{"item_code": self.trim_item, "qty": self.rejected_qty, "target": reject}]
		se = ins.make_stock_entry(self.ctx, rows, "Trim", cint(mc.settings().get("submit_inspection_stock_entry")))
		self.db_set({"quality_inspection": qi, "stock_entry": se})
		self.update_requisition()

	def update_requisition(self):
		if not self.trim_requisition:
			return
		from arinox_apparel.materials import purchasing

		req = purchasing.refresh_requisition("TR", self.trim_requisition)
		if not req:
			return
		need = mc.settings().get("material_gate_min_pct") or 100
		seen = {}
		for r in req.items:
			k = (r.sales_order, r.style_item, (r.colour or "").strip())
			seen[k] = seen.get(k, True) and flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * flt(need) / 100
		for (so, style, colour), full in seen.items():
			mc.stamp_safe(so, style, colour or None, "TRIMS_QC_PASSED", self.received_date, "Trim Inspection", self.name, partial=not full)

	def on_cancel(self):
		ins.cancel_linked("Stock Entry", self.stock_entry)
		ins.cancel_linked("Quality Inspection", self.quality_inspection)
		self.db_set({"stock_entry": None, "quality_inspection": None})
		if self.trim_requisition:
			from arinox_apparel.materials import purchasing

			purchasing.refresh_requisition("TR", self.trim_requisition)
		mc.unstamp_safe("Trim Inspection", self.name)


@frappe.whitelist()
def make_inspection(purchase_receipt, purchase_receipt_item):
	frappe.has_permission("Trim Inspection", "create", throw=True)
	frappe.has_permission("Purchase Receipt", "read", purchase_receipt, throw=True)
	ctx = ins.receipt_context(purchase_receipt, purchase_receipt_item, "Trim")
	doc = frappe.new_doc("Trim Inspection")
	doc.update({"purchase_receipt": purchase_receipt, "purchase_receipt_item": purchase_receipt_item, "received_date": ctx.pr.posting_date,
		"received_qty": flt(ctx.row.stock_qty), "warehouse_incharge": frappe.session.user})
	return doc
