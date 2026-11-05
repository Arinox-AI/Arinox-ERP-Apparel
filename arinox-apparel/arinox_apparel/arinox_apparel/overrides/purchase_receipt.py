"""Purchase Receipt extensions: receive into the inspection warehouse, quantity bands, delay penalty, roll-ups."""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate

from arinox_apparel.materials import common as mc
from arinox_apparel.materials import purchasing


def po_row(pri):
	if not pri.get("purchase_order_item"):
		return None
	return frappe.db.get_value("Purchase Order Item", pri.purchase_order_item,
		["name", "parent", "stock_qty", "schedule_date", "conversion_factor", "apparel_requisition", "apparel_requisition_type", "qty"], as_dict=True)


def from_requisition(poi):
	return poi and poi.apparel_requisition


def validate(doc, method=None):
	notes = []
	for pri in doc.items:
		poi = po_row(pri)
		if not from_requisition(poi):
			continue
		kind = "Fabric" if poi.apparel_requisition_type == "FR" else "Trim"
		if not pri.warehouse:
			pri.warehouse = mc.company_warehouse("inspection_warehouse_fabric" if kind == "Fabric" else "inspection_warehouse_trim", doc.company)
		po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier", "status"], as_dict=True)
		terms = purchasing.terms_for(po.apparel_purchase_terms, po.supplier)
		check_band(doc, pri, poi, po, terms, notes)
	doc.apparel_qty_band_note = "\n".join(notes) if notes else None


def check_band(doc, pri, poi, po, terms, notes):
	"""Cumulative received (incl. this row) against the ordered quantity and its tolerance band."""
	if not terms:
		return
	ordered = flt(poi.stock_qty)
	already = flt(frappe.db.get_value("Purchase Order Item", poi.name, "received_qty")) * flt(poi.conversion_factor)
	this = flt(pri.stock_qty) if pri.get("stock_qty") else flt(pri.qty) * (flt(pri.conversion_factor) or 1)
	cumulative = already + this
	tol = purchasing.qty_tolerance(terms, ordered)
	upper, lower = ordered * (1 + tol / 100), ordered * (1 - tol / 100)
	if cumulative > upper + 0.0005:
		excess = flt(cumulative - upper, 2)
		if terms.extra_qty_policy == "Reject":
			frappe.throw(_("Row {0}: {1} received against {2} ordered is over the +{3}% band by {4}.").format(
				pri.idx, flt(cumulative, 2), flt(ordered, 2), tol, excess))
		note = _("Row {0}: {1} over the +{2}% band.").format(pri.idx, excess, tol)
		if terms.extra_qty_policy == "Accept Unpaid":
			note += " " + _("The excess must not be invoiced.")
		notes.append(note)
	if po.status == "Closed" and cumulative < lower - 0.0005:
		notes.append(_("Row {0}: short by {1} against the order (below the -{2}% band).").format(pri.idx, flt(lower - cumulative, 2), tol))


def before_submit(doc, method=None):
	from arinox_apparel.materials.rolls import check_rolls_before_submit

	check_rolls_before_submit(doc)


def on_submit(doc, method=None):
	apply_delay_penalty(doc)
	refresh_and_stamp(doc)


def refresh_and_stamp(doc):
	seen = set()
	for pri in doc.items:
		poi = po_row(pri)
		if not from_requisition(poi):
			continue
		t, n = poi.apparel_requisition_type, poi.apparel_requisition
		if (t, n) not in seen:
			seen.add((t, n))
			req = purchasing.refresh_requisition(t, n)
			stamp_receipt(req, t)


def stamp_receipt(req, t):
	if not req:
		return
	code = "FABRIC_IN_HOUSE" if t == "FR" else "TRIMS_IN_HOUSE"
	done = req.status == "Received"
	seen = set()
	for r in req.items:
		k = (r.sales_order, r.style_item, (r.colour or "").strip())
		if k in seen or flt(r.received_qty) <= 0:
			continue
		seen.add(k)
		mc.stamp_safe(r.sales_order, r.style_item, r.colour or None, code, frappe.utils.nowdate(), "Purchase Receipt", req.name, partial=not done)


def apply_delay_penalty(doc):
	"""Late delivery under the PO terms: store the delay, the penalty % and the amount. No accounting entry is posted."""
	worst, terms_doc, value = 0, None, 0.0
	for pri in doc.items:
		poi = po_row(pri)
		if not from_requisition(poi):
			continue
		po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier", "apparel_etd_actual"], as_dict=True)
		terms = purchasing.terms_for(po.apparel_purchase_terms, po.supplier)
		arrival = po.apparel_etd_actual or doc.posting_date
		days = date_diff(getdate(arrival), getdate(poi.schedule_date)) if poi.schedule_date else 0
		if days > worst:
			worst, terms_doc = days, terms
		if days > 0:
			value += flt(pri.net_amount)
	pct, action = purchasing.delay_penalty(terms_doc, worst)
	doc.db_set({"apparel_delay_days": max(worst, 0), "apparel_penalty_pct": pct, "apparel_penalty_amount": flt(value * pct / 100, 2)}, update_modified=False)
	if action == "Cancel or Discount" and pct:
		doc.db_set("apparel_qty_band_note", ((doc.apparel_qty_band_note or "") + "\n" + _("Delay of {0} days: the order may be cancelled or discounted {1}%.").format(worst, pct)).strip(), update_modified=False)


def on_cancel(doc, method=None):
	refresh_and_stamp(doc)
	mc.unstamp_safe("Purchase Receipt", doc.name)
