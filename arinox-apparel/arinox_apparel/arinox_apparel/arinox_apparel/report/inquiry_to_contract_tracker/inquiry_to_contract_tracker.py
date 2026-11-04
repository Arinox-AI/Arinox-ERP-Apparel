# Copyright (c) 2026, Arinox AI and contributors
"""One row per buyer inquiry: how far it has travelled from tech pack to sales order."""

import frappe
from frappe import _

STAGES = ["Inquiry", "Tech Pack", "Costing", "Negotiating", "Quoted", "Contract", "Ordered", "Lost"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters), None, chart_for(data(filters))


def columns():
	return [
		{"label": _("Inquiry"), "fieldname": "opportunity", "fieldtype": "Link", "options": "Opportunity", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 105},
		{"label": _("Product Type"), "fieldname": "product_type", "fieldtype": "Link", "options": "Product Type", "width": 110},
		{"label": _("Target FOB"), "fieldname": "target_fob", "fieldtype": "Currency", "options": "currency", "width": 95},
		{"label": _("Tech Packs"), "fieldname": "tech_packs", "fieldtype": "Int", "width": 85},
		{"label": _("Cost Sheets"), "fieldname": "cost_sheets", "fieldtype": "Int", "width": 90},
		{"label": _("Avg Costed FOB"), "fieldname": "costed_fob", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("Negotiation"), "fieldname": "negotiation", "fieldtype": "Link", "options": "Price Negotiation", "width": 130},
		{"label": _("Negotiation Status"), "fieldname": "negotiation_status", "fieldtype": "Data", "width": 110},
		{"label": _("Rounds"), "fieldname": "rounds", "fieldtype": "Int", "width": 70},
		{"label": _("Quotation"), "fieldname": "quotation", "fieldtype": "Link", "options": "Quotation", "width": 140},
		{"label": _("Contract"), "fieldname": "contract", "fieldtype": "Link", "options": "Sales Contract", "width": 150},
		{"label": _("Contract Value"), "fieldname": "contract_value", "fieldtype": "Currency", "options": "currency", "width": 115},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
	]


def data(f):
	cond = {"opportunity_from": "Customer"}
	if f.customer:
		cond["party_name"] = f.customer
	if f.from_date and f.to_date:
		cond["transaction_date"] = ("between", [f.from_date, f.to_date])
	opps = frappe.get_all(
		"Opportunity",
		filters=cond,
		fields=["name", "party_name", "transaction_date", "status", "currency",
				"apparel_product_type", "apparel_target_fob"],
		order_by="transaction_date desc",
	)
	out = []
	for o in opps:
		n = o.name
		tps = frappe.db.count("Tech Pack", {"opportunity": n, "docstatus": ("<", 2)})
		cs = frappe.get_all("Cost Sheet", {"opportunity": n, "docstatus": 1}, ["quoted_price"])
		cs_any = frappe.db.count("Cost Sheet", {"opportunity": n, "docstatus": ("<", 2)})
		pn = frappe.db.get_value("Price Negotiation", {"opportunity": n}, ["name", "status"], as_dict=True, order_by="creation desc")
		rounds = frappe.db.count("Price Negotiation Round", {"parent": pn.name}) if pn else 0
		q = frappe.db.get_value("Quotation", {"opportunity": n, "docstatus": 1}, "name", order_by="creation desc")
		sc = frappe.db.get_value("Sales Contract", {"opportunity": n, "docstatus": ("<", 2)},
								 ["name", "total_amount", "sales_order", "docstatus"], as_dict=True, order_by="creation desc")
		stage = "Inquiry"
		if tps: stage = "Tech Pack"
		if cs_any: stage = "Costing"
		if pn: stage = "Negotiating"
		if q: stage = "Quoted"
		if sc: stage = "Contract"
		if sc and sc.sales_order: stage = "Ordered"
		if o.status == "Lost" or (pn and pn.status == "Lost"): stage = "Lost"
		if f.stage and f.stage != stage:
			continue
		out.append({
			"opportunity": n, "customer": o.party_name, "transaction_date": o.transaction_date, "stage": stage,
			"product_type": o.apparel_product_type, "target_fob": o.apparel_target_fob, "currency": o.currency,
			"tech_packs": tps, "cost_sheets": cs_any,
			"costed_fob": (sum(c.quoted_price for c in cs) / len(cs)) if cs else None,
			"negotiation": pn.name if pn else None, "negotiation_status": pn.status if pn else None, "rounds": rounds,
			"quotation": q, "contract": sc.name if sc else None,
			"contract_value": sc.total_amount if sc else None, "sales_order": sc.sales_order if sc else None,
		})
	return out


def chart_for(rows):
	counts = [sum(1 for r in rows if r["stage"] == s) for s in STAGES]
	return {"data": {"labels": STAGES, "datasets": [{"name": _("Inquiries"), "values": counts}]}, "type": "bar",
			"colors": ["#e8590c"]}
