# Copyright (c) 2026, Arinox AI and contributors
"""Freight Allocation: a shipment's freight cost (the forwarder's bills, or the quote until they arrive) shared out over the
contracts on board by CBM at sea or weight by air. A report only: no accounting entry is made."""

import frappe
from frappe import _

from arinox_apparel.shipping import freight


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "shipment", "label": _("Shipment"), "fieldtype": "Link", "options": "Shipment", "width": 130},
		{"fieldname": "contract", "label": _("Contract / Order"), "fieldtype": "Data", "width": 190},
		{"fieldname": "basis", "label": _("Basis"), "fieldtype": "Data", "width": 90},
		{"fieldname": "share_pct", "label": _("Share %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "cost", "label": _("Allocated Cost"), "fieldtype": "Float", "width": 120},
		{"fieldname": "estimate", "label": _("Quote"), "fieldtype": "Float", "width": 110},
		{"fieldname": "actual", "label": _("Forwarder Bills"), "fieldtype": "Float", "width": 120},
		{"fieldname": "variance", "label": _("Bills vs Quote %"), "fieldtype": "Percent", "width": 120},
	]
	cond = {"docstatus": ["<", 2], "apparel_mode": ["is", "set"]}
	if filters.shipment:
		cond["name"] = filters.shipment
	data = []
	for s in frappe.get_all("Shipment", cond, ["name", "apparel_estimate_total", "apparel_actual_total", "apparel_cost_variance_pct"]):
		rows, basis, _total = freight.allocated_costs(s.name)
		for contract, share, cost in rows:
			data.append({"shipment": s.name, "contract": contract, "basis": "CBM" if basis == "cbm" else "kg", "share_pct": round(share * 100, 2), "cost": cost,
						 "estimate": s.apparel_estimate_total, "actual": s.apparel_actual_total, "variance": s.apparel_cost_variance_pct})
	return columns, data
