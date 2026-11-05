# Copyright (c) 2026, Arinox AI and contributors
"""The WIP workbook as a report: one row per style x colour x ex-factory date, milestones in the workbook's order. A milestone
shows its actual date, else the revised date, else the plan. Cut, sew, wash, pack and ship quantities stay empty until the
production phase exists."""

import frappe
from frappe import _
from frappe.utils import flt

from arinox_apparel.tna.api import wip_board_data

# (fieldname, label, milestone code or None)
DATE_COLS = [
	("order_received", "Order Received", "ORDER_RECEIVED"), ("tech_pack", "Tech Pack Received", "TECH_PACK_RECEIVED"), ("bom", "BOM Received", "BOM_RECEIVED"),
	("bulk_standard", "Bulk Standard Received", "BULK_STANDARD_RECEIVED"), ("fr_raised", "FR Raised", "FR_RAISED"), ("tr_raised", "TR Raised", "TR_RAISED"),
	("fabric_ready_mill", "Bulk Fabric Ready at Mill", "BULK_FABRIC_READY_MILL"), ("fabric_etd", "Fabric ETD", "FABRIC_ETD"), ("fabric_in_house", "Fabric In-house", "FABRIC_IN_HOUSE"),
	("fabric_qc", "Fabric QC Passed", "FABRIC_QC_PASSED"), ("trim_pi", "Trim PI Date", "TRIM_PI"), ("trims_in_house", "Trims In-house", "TRIMS_IN_HOUSE"),
	("lab_dip", "Lab Dip Approved", "LAB_DIP"), ("fit_approved", "Fit Approved", "FIT"), ("trims_approved", "Trims Approved", "TRIMS_APPROVED"),
	("bulk_fabric_approved", "Bulk Fabric Approved", "BULK_FABRIC_APPROVED"), ("pp_approval", "PP + GPT Approval", "PP_GPT"), ("pp_meeting", "PP Meeting", "PP_MEETING"),
	("pcd", "PCD", "PCD"), ("pilot_run", "Pilot Run", "PILOT_RUN"), ("top", "TOP / Size Set", "TOP"), ("bulk_finish", "Bulk Finish", "BULK_FINISH"),
	("wash_finished", "Washing Finished", "WASH_FINISHED"), ("pack_finished", "Packing Finished", "PACK_FINISHED"), ("final_inspection", "Final Inspection", "FINAL_INSPECTION"),
	("freight_booking", "Freight Booking", "FREIGHT_BOOKING"),
]


def execute(filters=None):
	return columns(), data(filters)


def columns():
	C = lambda f, l, t="Data", w=110, o=None: {"fieldname": f, "label": _(l), "fieldtype": t, "width": w, **({"options": o} if o else {})}
	cols = [
		C("status", "T&A Status", w=90), C("factory", "Factory", "Link", 120, "Plant Floor"), C("merchant", "Merchant", w=110), C("customer", "Buyer", "Link", 120, "Customer"),
		C("contract", "Contract", w=130), C("buyer_po", "PO", w=100), C("style_no", "Style", w=100), C("description", "Description", w=160), C("wash", "Wash", w=110),
		C("colour", "Colour", w=100), C("qty", "Order Qty", "Int", 80), C("ship_to", "Ship To", w=110), C("ex_factory", "Delivery (Ex-Factory)", "Date", 110),
		C("revised_ex_factory", "Revised Delivery", "Date", 100),
	]
	cols += [C(f, l, "Date", 100) for f, l, _c in DATE_COLS[:3]]
	for n in range(1, 5):
		cols += [C(f"fit{n}_submit", f"Fit {n} Submitted", "Date", 95), C(f"fit{n}_comments", f"Fit {n} Comments", "Date", 95)]
	cols += [C(f, l, "Date", 100) for f, l, _c in DATE_COLS[3:]]
	cols += [C("fabric_ordered", "Fabric Ordered (m)", "Float", 100), C("fabric_received", "Fabric Received (m)", "Float", 100), C("fabric_yy", "Fabric Yield (m/pc)", "Float", 90),
		C("cut_qty", "Cut Qty (production phase)", "Int", 110), C("sew_qty", "Sew Qty (production phase)", "Int", 110), C("wash_qty", "Wash Qty (production phase)", "Int", 110),
		C("pack_qty", "Pack Qty (production phase)", "Int", 110), C("ship_qty", "Ship Qty (production phase)", "Int", 110), C("price", "Price", "Currency", 80), C("total_value", "Total", "Currency", 100)]
	return cols


def data(filters):
	board = wip_board_data(dict(filters or {}), 200, 0)
	out = []
	for o in board["orders"]:
		ms = board["milestones"].get(o.name, {})
		so = frappe.db.get_value("Sales Order", o.sales_order, ["apparel_sales_contract"], as_dict=True)
		item = frappe.get_all("Sales Order Item", {"parent": o.sales_order, "apparel_colour": o.colour or ["is", "set"]}, ["apparel_buyer_po", "rate"], limit_page_length=1)
		tp = frappe.db.get_value("Tech Pack", {"style_item": o.style_no and frappe.db.get_value("Tech Pack", {"style_no": o.style_no}, "style_item")}, ["style_name", "wash_description"], as_dict=True) or {}
		row = {
			"status": o.status_live, "factory": o.factory, "merchant": frappe.db.get_value("User", o.merchant, "full_name") if o.merchant else None, "customer": o.customer,
			"contract": so.apparel_sales_contract if so else None, "buyer_po": item[0].apparel_buyer_po if item else None, "style_no": o.style_no, "description": tp.get("style_name"),
			"wash": tp.get("wash_description"), "colour": o.colour, "qty": o.order_qty, "ship_to": o.ship_tos, "ex_factory": o.ex_factory_date,
			"revised_ex_factory": (ms.get("EX_FACTORY") or {}).get("revised_date"),
		}
		for f, _l, code in DATE_COLS:
			m = ms.get(code)
			row[f] = None if not m or m.not_applicable else (m.actual_date or m.revised_date or m.planned_date)
		style_item = frappe.db.get_value("Order TNA", o.name, "style_item")
		rounds = frappe.db.sql(
			"""select r.round_no, r.sent_on, r.decision_on from `tabSample Approval Round` r join `tabSample Approval` s on s.name = r.parent
			where s.sample_type = 'Fit' and s.style_item = %s and (s.sales_order = %s or s.sales_order is null or s.sales_order = '') order by r.round_no limit 4""",
			(style_item, o.sales_order), as_dict=True)
		for n, r in enumerate(rounds, 1):
			row[f"fit{n}_submit"], row[f"fit{n}_comments"] = r.sent_on, r.decision_on
		fab = frappe.db.sql(
			"""select coalesce(sum(c.net_qty), 0) net, coalesce(sum(c.received_qty), 0) received from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent
			where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s and upper(c.colour) = upper(%s)""",
			(o.sales_order, style_item, o.colour or ""), as_dict=True)[0]
		row["fabric_ordered"], row["fabric_received"] = fab.net, fab.received
		row["fabric_yy"] = flt(fab.net) / flt(o.order_qty) if flt(o.order_qty) and flt(fab.net) else None
		row["price"] = item[0].rate if item else None
		row["total_value"] = flt(row["price"]) * flt(o.order_qty) if row["price"] else None
		out.append(row)
	return out
