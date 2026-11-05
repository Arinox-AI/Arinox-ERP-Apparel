"""Purchase Order extensions: link back to the requisition, supplier terms, approval hold, costing check, ETD dates."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import MANAGER_ROLES
from arinox_apparel.materials import common as mc
from arinox_apparel.materials import purchasing

COPY = ("apparel_requisition_type", "apparel_requisition", "apparel_requisition_item", "apparel_style_no", "apparel_colour", "apparel_hold_reason")


def requisition_row(poi):
	"""The FR / TR row behind a PO row (or None)."""
	if not poi.get("apparel_requisition"):
		return None
	dt = "Fabric Requisition Item" if poi.apparel_requisition_type == "FR" else "Trim Requisition Item"
	r = frappe.db.get_value(dt, {"parent": poi.apparel_requisition, "material_request_item": poi.get("material_request_item")},
		["sales_order", "style_item", "colour"], as_dict=True)
	return r


def validate(doc, method=None):
	for poi in doc.items:
		if poi.get("material_request_item") and not poi.get("apparel_requisition"):
			vals = frappe.db.get_value("Material Request Item", poi.material_request_item, list(COPY), as_dict=True) or {}
			for f in COPY:
				if vals.get(f):
					poi.set(f, vals[f])
	if not doc.get("apparel_purchase_terms") and any(poi.get("apparel_requisition") for poi in doc.items):
		doc.apparel_purchase_terms = frappe.db.get_value("Supplier", doc.supplier, "apparel_purchase_terms") or mc.settings().get("default_purchase_terms")
	check_override(doc)
	check_dates(doc)
	for msg in hold_blockers(doc) + cost_warnings(doc):
		frappe.msgprint(msg, indicator="orange", title=_("Apparel check"))


def check_override(doc):
	if not cint(doc.get("apparel_approval_override")):
		return
	if not doc.is_new() and not doc.has_value_changed("apparel_approval_override"):
		return
	if not set(frappe.get_roles()) & set(MANAGER_ROLES):
		frappe.throw(_("Only an Apparel Merchandising Manager can override the approval hold."))
	if not (doc.get("apparel_approval_override_reason") or "").strip():
		frappe.throw(_("Enter the reason for overriding the approval hold."))


def check_dates(doc):
	plan, eta, actual = doc.get("apparel_etd_planned"), doc.get("apparel_eta"), doc.get("apparel_etd_actual")
	if plan and eta and getdate(plan) > getdate(eta):
		frappe.throw(_("ETD (plan) cannot be after the ETA."))
	if actual and getdate(actual) > getdate(nowdate()):
		frappe.throw(_("ETD (actual) cannot be in the future."))


def hold_blockers(doc):
	"""Messages for rows whose lab dip (FR) or trim approval (TR) is still missing, re-checked now."""
	out = []
	for poi in doc.items:
		if not poi.get("apparel_hold_reason"):
			continue
		r = requisition_row(poi)
		if not r:
			continue
		stype, colour = ("Lab Dip", r.colour) if poi.apparel_requisition_type == "FR" else ("Bulk Trim", None)
		status, ok = mc.approval_info(r.sales_order, r.style_item, stype, colour, frappe.db.get_value("Sales Order", r.sales_order, "customer"))
		if not ok:
			out.append(_("Row {0} ({1}): {2} is {3}.").format(poi.idx, poi.item_code, stype, status))
	return out


def cost_warnings(doc):
	"""PO rate against the Cost Sheet material rate, when currency and unit are comparable."""
	limit = flt(mc.settings().get("cost_overrun_warn_pct") or 5)
	out = []
	for poi in doc.items:
		r = requisition_row(poi)
		if not r or not flt(poi.rate):
			continue
		cs = mc.cost_sheet_for(r.sales_order, r.style_item)
		if not cs:
			continue
		desc_item = poi.item_code
		for cm in cs.materials:
			if not (cm.item and cm.item == desc_item) and (cm.description or "").strip().lower() != (poi.item_name or "").strip().lower():
				continue
			if (cm.price_currency or cs.currency) != doc.currency:
				break
			cost_rate = flt(cm.rate)
			if (cm.rate_uom or cm.uom) != poi.uom or not cost_rate:
				break
			if flt(poi.rate) > cost_rate * (1 + limit / 100):
				out.append(_("Row {0}: rate {1} is more than {2}% above the costed {3}.").format(poi.idx, poi.rate, limit, cost_rate))
			break
	return out


def before_submit(doc, method=None):
	mode = mc.settings().get("hold_po_until_approval") or "Warn"
	blockers = hold_blockers(doc)
	if blockers and mode == "Block":
		if cint(doc.get("apparel_approval_override")) and (doc.get("apparel_approval_override_reason") or "").strip() and set(frappe.get_roles()) & set(MANAGER_ROLES):
			return
		frappe.throw(_("This order is on hold until the buyer approvals are in:") + "<br>• " + "<br>• ".join(blockers), title=_("Approval hold"))


def on_submit(doc, method=None):
	touched = purchasing.refresh_for_documents(doc)
	stamp_po(doc, touched)


def on_update_after_submit(doc, method=None):
	stamp_po(doc, purchasing.refresh_for_documents(doc))


def on_cancel(doc, method=None):
	purchasing.refresh_for_documents(doc)
	mc.unstamp_safe("Purchase Order", doc.name)


def stamp_po(doc, touched):
	"""Booked / PI / ETD milestones for every style x colour on the order."""
	seen = set()
	for poi in doc.items:
		r = requisition_row(poi)
		if not r:
			continue
		k = (r.sales_order, r.style_item, r.colour, poi.apparel_requisition_type)
		if k in seen:
			continue
		seen.add(k)
		so, style, colour, typ = k
		if typ == "FR":
			mc.stamp_safe(so, style, colour, "FABRIC_BOOKED", nowdate(), "Purchase Order", doc.name)
			if doc.get("apparel_mill_ready_date"):
				mc.stamp_safe(so, style, colour, "BULK_FABRIC_READY_MILL", doc.apparel_mill_ready_date, "Purchase Order", doc.name)
			if doc.get("apparel_etd_actual"):
				mc.stamp_safe(so, style, colour, "FABRIC_ETD", doc.apparel_etd_actual, "Purchase Order", doc.name)
			elif doc.get("apparel_etd_revised") or doc.get("apparel_etd_planned"):
				mc.stamp_safe(so, style, colour, "FABRIC_ETD", doc.get("apparel_etd_revised") or doc.apparel_etd_planned, "Purchase Order", doc.name, planned=True)
		elif doc.get("apparel_pi_date"):
			mc.stamp_safe(so, style, colour, "TRIM_PI", doc.apparel_pi_date, "Purchase Order", doc.name)


@frappe.whitelist()
def make_purchase_orders(requisition_type, name):
	"""Draft Purchase Orders from an approved FR / TR: one per supplier, for the Material Request rows not yet ordered.
	Buyer-supplied trims are skipped. Returns the PO names."""
	dt = "Fabric Requisition" if requisition_type == "FR" else "Trim Requisition"
	req = frappe.get_doc(dt, name)
	req.check_permission("read")
	frappe.has_permission("Purchase Order", "create", throw=True)
	if req.docstatus != 1:
		frappe.throw(_("Approve (submit) the requisition first."))
	groups = {}
	for r in req.items:
		if not r.material_request_item or cint(r.get("customer_provided")) or not r.supplier:
			continue
		if frappe.db.exists("Purchase Order Item", {"material_request_item": r.material_request_item, "docstatus": ["<", 2]}):
			continue
		groups.setdefault(r.supplier, []).append(r)
	made = []
	for supplier, rows in groups.items():
		po = frappe.new_doc("Purchase Order")
		po.company, po.supplier = req.company, supplier
		po.transaction_date = nowdate()
		po.schedule_date = min(getdate(r.required_by) for r in rows if r.required_by) if any(r.required_by for r in rows) else getdate(nowdate())
		po.apparel_purchase_terms = frappe.db.get_value("Supplier", supplier, "apparel_purchase_terms") or mc.settings().get("default_purchase_terms")
		for r in rows:
			mri = frappe.db.get_value("Material Request Item", r.material_request_item,
				["name", "parent", "item_code", "qty", "uom", "conversion_factor", "warehouse", "schedule_date", "sales_order"], as_dict=True)
			po.append("items", {
				"item_code": mri.item_code, "qty": mri.qty, "uom": mri.uom, "conversion_factor": mri.conversion_factor,
				"warehouse": mri.warehouse, "schedule_date": mri.schedule_date, "sales_order": mri.sales_order,
				"material_request": mri.parent, "material_request_item": mri.name,
			})
		po.run_method("set_missing_values")
		po.insert()
		made.append(po.name)
	return made
