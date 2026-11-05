"""Delivery Note hooks: the final-inspection ship gate, the over-ship check, and the SHIPPED posting.

A Delivery Note made from a Shipment carries a Packing List and a production card on each row. Those rows are what
the gate looks at and what is written to the production ledger."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from arinox_apparel.production import ledger, maths
from arinox_apparel.shipping import common

MANAGER_ROLES = {"Apparel Production Manager", "Apparel Merchandising Manager", "System Manager"}


def _is_manager():
	return bool(MANAGER_ROLES & set(frappe.get_roles()))


def _lists(doc):
	return sorted({it.apparel_packing_list for it in doc.items if it.get("apparel_packing_list")})


def validate(doc, method=None):
	"""Copy the production card and contract down from the packing list on each row."""
	for it in doc.items:
		if it.get("apparel_packing_list"):
			it.apparel_production_card = frappe.db.get_value("Packing List", it.apparel_packing_list, "production_card")
	first = next((it.against_sales_order for it in doc.items if it.get("against_sales_order")), None)
	if first and _lists(doc):
		doc.apparel_sales_contract = common.contract_of_order(first)


def before_submit(doc, method=None):
	lists = _lists(doc)
	if not lists:
		return
	for pl in lists:
		row = frappe.db.get_value("Packing List", pl, ["docstatus", "status"], as_dict=True)
		if not row or row.docstatus != 1:
			frappe.throw(_("Packing list {0} must be submitted before it ships.").format(pl))
		if row.status == "Shipped":
			frappe.throw(_("Packing list {0} has already shipped.").format(pl))
	check_gate(doc, lists)
	check_over_ship(doc)


def check_gate(doc, lists):
	from arinox_apparel.arinox_apparel.doctype.final_inspection.final_inspection import gate_problems

	mode = common.settings_value("ship_gate_final_inspection", "Block")
	if mode == "Off":
		return
	problems = gate_problems(lists)
	if not problems:
		return
	if doc.get("apparel_gate_override"):
		if not _is_manager():
			frappe.throw(_("Only a manager can override the inspection gate."))
		if not (doc.get("apparel_gate_override_reason") or "").strip():
			frappe.throw(_("Write the reason for overriding the inspection gate."))
		return
	if mode == "Block":
		frappe.throw("<br>".join(problems), title=_("Final inspection"))
	frappe.msgprint("<br>".join(problems), indicator="orange", title=_("Final inspection"))


def check_over_ship(doc):
	"""Pieces shipped against each Sales Order line, with this note, must stay inside the contract's allowance. Checked
	per size, in total, or both, as set in Apparel Settings."""
	basis = common.settings_value("ship_tolerance_basis", "Both")
	by_row, by_order = {}, {}
	for it in doc.items:
		if not it.get("so_detail") or not it.get("apparel_packing_list"):
			continue
		by_row[it.so_detail] = by_row.get(it.so_detail, 0) + flt(it.stock_qty or it.qty)
	problems = []
	ordered_total, shipped_total, tol_by_order = {}, {}, {}
	orders = {frappe.db.get_value("Sales Order Item", d, "parent") for d in by_row}
	for so in orders:   # the whole order, not only the lines on this note
		ordered_total[so] = flt(frappe.db.sql("select ifnull(sum(qty), 0) from `tabSales Order Item` where parent = %s", so)[0][0])
		shipped_total[so] = flt(frappe.db.sql("select ifnull(sum(i.stock_qty), 0) from `tabDelivery Note Item` i where i.against_sales_order = %s and i.docstatus = 1 and i.parent != %s",
											  (so, doc.name or ""))[0][0])
	for so_detail, qty in by_row.items():
		line = frappe.db.get_value("Sales Order Item", so_detail, ["parent", "qty", "apparel_qty_tolerance_pct", "apparel_colour", "apparel_size"], as_dict=True)
		if not line:
			continue
		before = frappe.db.sql(
			"select ifnull(sum(stock_qty), 0) from `tabDelivery Note Item` where so_detail = %s and docstatus = 1 and parent != %s", (so_detail, doc.name or ""))[0][0]
		shipped = flt(before) + qty
		limit = maths.max_ship_qty(line.qty, line.apparel_qty_tolerance_pct or 0)
		if basis in ("Each Size", "Both") and shipped > limit + 1e-9:
			problems.append(_("{0} {1}: {2} shipped against {3} ordered (allowed up to {4}).").format(line.apparel_colour, line.apparel_size, int(shipped), int(line.qty), int(limit)))
		shipped_total[line.parent] += qty
		tol_by_order[line.parent] = flt(line.apparel_qty_tolerance_pct)
	if basis in ("Total", "Both"):
		for so, tot in shipped_total.items():
			limit = maths.max_ship_qty(ordered_total[so], tol_by_order[so])
			if tot > limit + 1e-9:
				problems.append(_("{0}: {1} shipped in all against {2} ordered (allowed up to {3}).").format(so, int(tot), int(ordered_total[so]), int(limit)))
	if not problems:
		return
	if doc.get("apparel_over_ship_override"):
		if not _is_manager():
			frappe.throw(_("Only a manager can approve shipping outside the allowance."))
		if not (doc.get("apparel_over_ship_override_reason") or "").strip():
			frappe.throw(_("Write the reason for shipping outside the allowance."))
		return
	frappe.throw("<br>".join(problems), title=_("Over-shipment"))


def post_movements(doc, check=False, only_card=None):
	by_card = {}
	for it in doc.items:
		card = it.get("apparel_production_card")
		if not card or (only_card and card != only_card) or not it.get("so_detail"):
			continue
		colour, size = frappe.db.get_value("Sales Order Item", it.so_detail, ["apparel_colour", "apparel_size"])
		rows = by_card.setdefault(card, {})
		rows[(colour, size)] = rows.get((colour, size), 0) + cint(it.stock_qty or it.qty)
	for card, rows in by_card.items():
		ledger.post(card, [{"stage": "SHIPPED", "colour": c, "size": s, "qty": q} for (c, s), q in rows.items()],
					"Delivery Note", doc.name, doc.posting_date, check=check)


def on_submit(doc, method=None):
	lists = _lists(doc)
	if not lists:
		return
	post_movements(doc, check=True)
	for pl in lists:
		frappe.db.set_value("Packing List", pl, "status", "Shipped", update_modified=False)
	for card in {it.apparel_production_card for it in doc.items if it.get("apparel_production_card")}:
		common.stamp_card(card, "EX_FACTORY", doc.posting_date, "Delivery Note", doc.name)
	if doc.get("apparel_shipment"):
		from arinox_apparel.shipping import shipment

		shipment.refresh_status(doc.apparel_shipment)


def on_cancel(doc, method=None):
	lists = _lists(doc)
	if not lists:
		return
	if frappe.db.exists("Sales Invoice Item", {"delivery_note": doc.name, "docstatus": 1}) or (
		doc.get("apparel_shipment") and frappe.db.exists("Sales Invoice", {"apparel_shipment": doc.apparel_shipment, "docstatus": 1})):
		frappe.throw(_("Invoices of this shipment are submitted. Cancel them before cancelling the Delivery Note."))
	ledger.unpost("Delivery Note", doc.name)
	for pl in lists:
		shipment = frappe.db.get_value("Packing List", pl, "shipment")
		frappe.db.set_value("Packing List", pl, "status", "On Shipment" if shipment else "Open", update_modified=False)
	common.unstamp_doc("Delivery Note", doc.name)
