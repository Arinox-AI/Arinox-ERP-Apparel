"""The export shipment: ERPNext's Shipment, extended with the booking, vessel or flight, bill of lading, customs
declarations and the packing lists on board. Nothing new is invented for what Shipment already holds (forwarder,
AWB, incoterm, delivery notes, parcels); the apparel fields are custom fields on it (setup/shipping.py)."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from arinox_apparel.production import maths
from arinox_apparel.shipping import common

PL_FIELDS = ["name", "sales_contract", "buyer_po", "total_cartons", "total_pieces", "total_net_kg", "total_gross_kg", "total_cbm",
			 "customer", "sales_order", "production_card", "ship_to", "docstatus", "shipment", "status"]


def lists_of(doc):
	return [r.packing_list for r in (doc.get("apparel_packing_lists") or []) if r.packing_list]


def before_validate(doc, method=None):
	"""Shipment insists on pickup details a freight forwarder booking does not have; give them sensible defaults."""
	if not lists_of(doc):
		return
	doc.pickup_date = doc.pickup_date or nowdate()
	doc.pickup_from = doc.pickup_from or "00:00:00"
	doc.pickup_to = doc.pickup_to or "23:59:00"
	doc.shipment_type = doc.shipment_type or "Goods"
	doc.pickup_type = doc.pickup_type or "Self delivery"


def validate(doc, method=None):
	lists = lists_of(doc)
	before = doc.get_doc_before_save()
	if before:
		for r in before.get("apparel_packing_lists") or []:
			if r.packing_list not in lists and frappe.db.get_value("Packing List", r.packing_list, "status") == "Shipped":
				frappe.throw(_("Packing list {0} has shipped on a Delivery Note and cannot be taken off the shipment.").format(r.packing_list))
	if not lists:
		return
	seen = set()
	rows = {}
	for r in doc.apparel_packing_lists:
		if r.packing_list in seen:
			frappe.throw(_("Packing list {0} is on this shipment twice.").format(r.packing_list))
		seen.add(r.packing_list)
		pl = frappe.db.get_value("Packing List", r.packing_list, PL_FIELDS, as_dict=True)
		if not pl or pl.docstatus != 1:
			frappe.throw(_("Packing list {0} must be submitted.").format(r.packing_list))
		if pl.shipment and pl.shipment != doc.name:
			frappe.throw(_("Packing list {0} is already on shipment {1}.").format(r.packing_list, pl.shipment))
		rows[r.packing_list] = pl
		r.sales_contract, r.buyer_po, r.cartons, r.pieces = pl.sales_contract, pl.buyer_po, pl.total_cartons, pl.total_pieces
		r.net_kg, r.gross_kg, r.cbm = pl.total_net_kg, pl.total_gross_kg, pl.total_cbm
	customers = {p.customer for p in rows.values()}
	if len(customers) > 1:
		frappe.throw(_("All packing lists on a shipment must be for one customer ({0}).").format(", ".join(sorted(c or "-" for c in customers))))
	doc.apparel_contracts = "\n".join(sorted({p.sales_contract or p.sales_order for p in rows.values()}))
	doc.apparel_declared_cbm = round(sum(flt(p.total_cbm) for p in rows.values()), 6)
	doc.apparel_declared_gross_kg = round(sum(flt(p.total_gross_kg) for p in rows.values()), 3)
	if not doc.shipment_parcel:
		fill_parcels(doc, rows)
	doc.description_of_content = doc.description_of_content or _("Garments, contract(s) {0}").format(", ".join(sorted({p.sales_contract or p.sales_order for p in rows.values()})))
	if not flt(doc.value_of_goods):
		doc.value_of_goods = goods_value(rows)
	check_mode(doc)
	check_measures(doc)


def fill_parcels(doc, rows):
	"""One parcel line per carton size and weight, with the number of cartons: ERPNext's own way to say 'these boxes'."""
	groups = {}
	for pl in rows:
		for c in frappe.get_all("Packing List Carton", {"parent": pl}, ["length_cm", "width_cm", "height_cm", "gross_weight_kg", "carton_count"]):
			key = (flt(c.length_cm), flt(c.width_cm), flt(c.height_cm), flt(c.gross_weight_kg))
			groups[key] = groups.get(key, 0) + cint(c.carton_count)
	for (l, w, h, kg), count in sorted(groups.items()):
		doc.append("shipment_parcel", {"length": l, "width": w, "height": h, "weight": kg, "count": count})


def goods_value(rows):
	"""Order value of the pieces on the packing lists (the commercial invoice value, before the invoices exist)."""
	total = 0.0
	for pl in rows:
		for ct in frappe.get_all("Packing List Content", {"parent": pl}, ["pieces_total", "sales_order_item"]):
			rate = frappe.db.get_value("Sales Order Item", ct.sales_order_item, "rate") if ct.sales_order_item else 0
			total += cint(ct.pieces_total) * flt(rate)
	return round(total, 2)


def check_mode(doc):
	contract_mode = None
	for c in (doc.apparel_contracts or "").splitlines():
		contract_mode = frappe.db.get_value("Sales Contract", c, "shipment_mode") if frappe.db.exists("Sales Contract", c) else contract_mode
	if doc.apparel_mode == "Air" and contract_mode == "Sea":
		if not (doc.apparel_reason_for_air or "").strip() or not doc.apparel_air_cost_borne_by:
			frappe.throw(_("The contract is for sea freight. Say why this goes by air and who pays the difference."))


def check_measures(doc):
	"""Declared, booked, carrier and customs figures are kept apart; a big difference is shown, never overwritten."""
	notes = []
	cbm_tol = flt(common.settings_value("measure_variance_warn_pct", 5))
	kg_tol = flt(common.settings_value("weight_variance_warn_pct", 2))
	for label, declared, other, tol in (
		(_("Booked CBM"), doc.apparel_declared_cbm, doc.apparel_booked_cbm, cbm_tol), (_("Carrier CBM"), doc.apparel_declared_cbm, doc.apparel_carrier_cbm, cbm_tol),
		(_("Booked weight"), doc.apparel_declared_gross_kg, doc.apparel_booked_gross_kg, kg_tol), (_("Carrier weight"), doc.apparel_declared_gross_kg, doc.apparel_carrier_gross_kg, kg_tol),
		(_("Customs weight"), doc.apparel_declared_gross_kg, doc.apparel_customs_gross_kg, kg_tol)):
		if flt(other) and flt(declared):
			diff = maths.over_short_pct(other, declared)
			if abs(diff) > tol:
				notes.append(_("{0} {1} against {2} on the packing lists ({3:+.2f} %).").format(label, other, declared, diff))
	doc.apparel_measure_note = "\n".join(notes)
	if notes and doc.docstatus == 0:
		frappe.msgprint("<br>".join(notes), indicator="orange", title=_("Measures differ"))


def on_update(doc, method=None):
	"""Tie the packing lists to this shipment, and release any that were taken off."""
	if not lists_of(doc) and not frappe.db.exists("Packing List", {"shipment": doc.name}):
		return
	now = set(lists_of(doc))
	for pl in frappe.get_all("Packing List", {"shipment": doc.name, "status": ["!=", "Shipped"]}, pluck="name"):
		if pl not in now:
			frappe.db.set_value("Packing List", pl, {"shipment": None, "status": "Open"}, update_modified=False)
	for pl in now:
		if frappe.db.get_value("Packing List", pl, "status") != "Shipped":
			frappe.db.set_value("Packing List", pl, {"shipment": doc.name, "status": "On Shipment"}, update_modified=False)
	if doc.apparel_booking_no:
		for card in {frappe.db.get_value("Packing List", pl, "production_card") for pl in now}:
			common.stamp_card(card, "FREIGHT_BOOKING", doc.apparel_booking_date or nowdate(), "Shipment", doc.name)
	refresh_status(doc.name)
	from arinox_apparel.shipping import followup, freight

	followup.refresh_for_shipment(doc.name)
	freight.refresh_costs(doc.name)


def on_cancel(doc, method=None):
	if frappe.db.exists("Delivery Note", {"apparel_shipment": doc.name, "docstatus": 1}):
		frappe.throw(_("Delivery notes of this shipment are submitted. Cancel them first."))
	for pl in frappe.get_all("Packing List", {"shipment": doc.name}, pluck="name"):
		frappe.db.set_value("Packing List", pl, {"shipment": None, "status": "Open"}, update_modified=False)
	common.unstamp_doc("Shipment", doc.name)


def refresh_status(shipment):
	if not frappe.db.exists("Shipment", shipment):
		return
	d = frappe.db.get_value("Shipment", shipment, ["apparel_ship_status", "apparel_booking_no", "apparel_on_board_date", "apparel_arrival_date", "apparel_delivery_date"], as_dict=True)
	if d.apparel_ship_status in ("On Hold", "Closed"):
		return  # set by a person; the dates and documents do not reopen it
	cleared = frappe.db.exists("Shipment Declaration", {"parent": shipment, "status": "Cleared"})
	handed = frappe.db.exists("Delivery Note", {"apparel_shipment": shipment, "docstatus": 1})
	prepared = frappe.db.exists("Sales Invoice", {"apparel_shipment": shipment, "docstatus": ["<", 2]})
	status = ("Delivered" if d.apparel_delivery_date else "Arrived" if d.apparel_arrival_date else "On Board" if d.apparel_on_board_date
			  else "Customs Cleared" if cleared else "Cargo Handed Over" if handed else "Documents Prepared" if prepared
			  else "Booked" if d.apparel_booking_no else "Planned")
	if status != d.apparel_ship_status:
		frappe.db.set_value("Shipment", shipment, "apparel_ship_status", status, update_modified=False)


@frappe.whitelist()
def get_available_packing_lists(customer=None):
	"""Submitted packing lists not on any shipment, with the state of their final inspection."""
	if not frappe.has_permission("Packing List", "read"):
		frappe.throw(_("You cannot read packing lists."), frappe.PermissionError)
	filters = {"docstatus": 1, "shipment": ["is", "not set"], "status": "Open"}
	if customer:
		filters["customer"] = customer
	rows = frappe.get_all("Packing List", filters, PL_FIELDS + ["final_inspection"], order_by="creation")
	for r in rows:
		r["inspection_result"] = frappe.db.get_value("Final Inspection", r.final_inspection, "result") if r.final_inspection else None
	return rows


@frappe.whitelist()
def make_delivery_notes(shipment):
	"""One draft Delivery Note per Sales Order on the shipment, quantities exactly as packed, each row tied to its packing list."""
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	doc = frappe.get_doc("Shipment", shipment)
	doc.check_permission("write")
	if not frappe.has_permission("Delivery Note", "create"):
		frappe.throw(_("You cannot create delivery notes."), frappe.PermissionError)
	if doc.docstatus == 2:
		frappe.throw(_("This shipment is cancelled."))
	made = []
	existing = {r.delivery_note for r in doc.shipment_delivery_note}
	by_order = {}
	for pl in lists_of(doc):
		by_order.setdefault(frappe.db.get_value("Packing List", pl, "sales_order"), []).append(pl)
	for so, pls in by_order.items():
		if frappe.db.exists("Delivery Note Item", {"apparel_packing_list": ["in", pls], "docstatus": ["<", 2]}):
			frappe.throw(_("Sales order {0} already has a delivery note for these packing lists.").format(so))
		dn = make_delivery_note(so)
		templates = {i.so_detail: i.as_dict() for i in dn.items}
		fg = common.settings_value("fg_warehouse")
		items = []
		for pl in pls:
			card = frappe.db.get_value("Packing List", pl, "production_card")
			qty = {}
			for ct in frappe.get_all("Packing List Content", {"parent": pl}, ["sales_order_item", "pieces_total"]):
				if not ct.sales_order_item or not frappe.db.exists("Sales Order Item", ct.sales_order_item):
					frappe.throw(_("Packing list {0} has a carton row that is not tied to a Sales Order line. Open it and save the packing list again.").format(pl))
				qty[ct.sales_order_item] = qty.get(ct.sales_order_item, 0) + cint(ct.pieces_total)
			for so_detail, q in qty.items():
				row = dict(templates.get(so_detail) or fallback_row(so_detail))
				for k in ("name", "parent", "parenttype", "parentfield", "idx", "creation", "modified", "owner", "modified_by", "docstatus"):
					row.pop(k, None)
				row.update({"qty": q, "so_detail": so_detail, "against_sales_order": so, "apparel_packing_list": pl, "apparel_production_card": card})
				if fg:
					row["warehouse"] = fg
				items.append(row)
		dn.set("items", items)
		dn.apparel_shipment = shipment
		dn.apparel_sales_contract = common.contract_of_order(so)
		if doc.incoterm:
			dn.incoterm = doc.incoterm
		if doc.apparel_forwarder:
			dn.transporter = doc.apparel_forwarder
		dn.lr_no = doc.apparel_booking_no
		dn.run_method("set_missing_values")
		dn.run_method("calculate_taxes_and_totals")
		dn.insert()
		made.append(dn.name)
		if dn.name not in existing:
			doc.append("shipment_delivery_note", {"delivery_note": dn.name, "grand_total": dn.grand_total})
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	return made


def fallback_row(so_detail):
	line = frappe.db.get_value("Sales Order Item", so_detail, ["item_code", "item_name", "description", "uom", "stock_uom", "conversion_factor", "rate", "warehouse"], as_dict=True)
	return {"doctype": "Delivery Note Item", **line}
