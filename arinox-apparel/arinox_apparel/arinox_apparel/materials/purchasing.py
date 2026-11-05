"""Pure rules for supplier terms (quantity bands, late-delivery penalties) and the roll-up of purchase and receipt
quantities back to the requisitions. Kept free of document state so each rule is easy to test."""

import frappe
from frappe.utils import cint, flt

from arinox_apparel.materials import common as mc


def pick_band(bands, qty):
	"""The Purchase Qty Band row covering `qty` (to_qty 0 = no upper limit); None when no band applies."""
	for b in sorted(bands, key=lambda b: flt(b.from_qty)):
		if flt(b.from_qty) <= flt(qty) and (not flt(b.to_qty) or flt(qty) <= flt(b.to_qty)):
			return b
	return None


def qty_tolerance(terms, ordered_qty):
	"""Tolerance % allowed on `ordered_qty` under `terms` (a Material Purchase Terms doc); 0 when none applies."""
	if not terms:
		return 0.0
	b = pick_band(terms.qty_bands, ordered_qty)
	return flt(b.tolerance_pct) if b else 0.0


def delay_penalty(terms, delay_days):
	"""(penalty %, action) for a delay under `terms`. Days <= 0 or inside a 0% band return 0."""
	if not terms or cint(delay_days) <= 0:
		return 0.0, None
	for b in sorted(terms.delay_bands, key=lambda b: cint(b.from_days)):
		if cint(b.from_days) <= cint(delay_days) and (not cint(b.to_days) or cint(delay_days) <= cint(b.to_days)):
			return flt(b.penalty_pct), b.action
	return 0.0, None


def terms_for(po_or_supplier_terms, supplier=None):
	"""The terms doc: the explicit one, else the supplier's, else the default in Apparel Settings."""
	name = po_or_supplier_terms or (frappe.db.get_value("Supplier", supplier, "apparel_purchase_terms") if supplier else None) \
		or mc.settings().get("default_purchase_terms")
	return frappe.get_cached_doc("Material Purchase Terms", name) if name else None


# ---- roll-up -------------------------------------------------------------------------------------------------------

REQ = {
	"FR": ("Fabric Requisition", "Fabric Requisition Item", "previous_fr"),
	"TR": ("Trim Requisition", "Trim Requisition Item", "previous_tr"),
}


def key_totals(requisition_type, chain, key):
	"""(ordered, received) in stock units for a line key across a revision chain, from the purchase orders that
	reference its Material Request rows."""
	rows = frappe.db.sql(
		"""select coalesce(sum(p.stock_qty), 0), coalesce(sum(p.received_qty * p.conversion_factor), 0)
		from `tabPurchase Order Item` p join `tabPurchase Order` o on o.name = p.parent
		join `tabMaterial Request Item` m on m.name = p.material_request_item
		where o.docstatus = 1 and m.apparel_requisition_type = %s and m.apparel_requisition in %s
		and m.apparel_requisition_item = %s""",
		(requisition_type, tuple(chain), key),
	)
	return flt(rows[0][0]), flt(rows[0][1])


def inspection_totals(requisition_type, chain, key):
	"""(accepted, rejected) in stock units for a line key, from the submitted inspections of the goods received for it."""
	if requisition_type == "FR":
		table, acc, rej = "Fabric Inspection", "i.accepted_m", "i.rejected_m"
	else:
		table, acc, rej = "Trim Inspection", "i.accepted_qty", "i.rejected_qty"
	rows = frappe.db.sql(
		f"""select coalesce(sum({acc}), 0), coalesce(sum({rej}), 0) from `tab{table}` i
		join `tabPurchase Receipt Item` r on r.name = i.purchase_receipt_item
		join `tabPurchase Order Item` p on p.name = r.purchase_order_item
		join `tabMaterial Request Item` m on m.name = p.material_request_item
		where i.docstatus = 1 and m.apparel_requisition_type = %s and m.apparel_requisition in %s and m.apparel_requisition_item = %s""",
		(requisition_type, tuple(chain), key),
	)
	return flt(rows[0][0]), flt(rows[0][1])


def refresh_requisition(requisition_type, name):
	"""Recompute ordered and received quantities and the status of one requisition."""
	dt, child_dt, prev_field = REQ[requisition_type]
	if not frappe.db.exists(dt, name):
		return
	doc = frappe.get_doc(dt, name)
	if doc.docstatus != 1:
		return
	from arinox_apparel.arinox_apparel.doctype.fabric_requisition.fabric_requisition import row_key as fr_key
	from arinox_apparel.arinox_apparel.doctype.trim_requisition.trim_requisition import row_key as tr_key

	key_of = fr_key if requisition_type == "FR" else tr_key
	chain = mc.revision_chain(dt, prev_field, name)
	for r in doc.items:
		ordered, received = key_totals(requisition_type, chain, key_of(r))
		accepted, rejected = inspection_totals(requisition_type, chain, key_of(r))
		r.db_set({"ordered_qty": ordered, "received_qty": received, "accepted_qty": accepted, "rejected_qty": rejected}, update_modified=False)
		r.accepted_qty, r.rejected_qty = accepted, rejected
	doc.set_status(save=True)
	return doc


def refresh_for_documents(doc):
	"""Refresh every requisition referenced by the items of a PO, PR or inspection document."""
	seen = set()
	for it in doc.get("items") or []:
		t, n = it.get("apparel_requisition_type"), it.get("apparel_requisition")
		if not (t and n) and it.get("material_request_item"):
			t, n = frappe.db.get_value("Material Request Item", it.material_request_item, ["apparel_requisition_type", "apparel_requisition"]) or (None, None)
		if t in REQ and n and (t, n) not in seen:
			seen.add((t, n))
			refresh_requisition(t, n)
	return seen
