# Copyright (c) 2026, Arinox AI and contributors
"""Fabric Consumption: the cutting reconciliation per production card x colour x fabric. Definitions (kept here so the
print and the report agree):
  lay consumption    = metres laid / pieces cut in those lays
  actual consumption = (metres issued - remnants returned) / good garments cut      (end bits and waste included)
  marker efficiency  = weighted by plies
Variance is actual against the consumption on the card."""

import frappe
from frappe import _
from frappe.utils import flt

from arinox_apparel.production import maths
from arinox_apparel.production.stock import moved


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "production_card", "label": _("Production Card"), "fieldtype": "Link", "options": "Production Card", "width": 130},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 90},
		{"fieldname": "fabric_item", "label": _("Fabric"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "required_m", "label": _("Required (m)"), "fieldtype": "Float", "width": 100},
		{"fieldname": "issued_m", "label": _("Issued (m)"), "fieldtype": "Float", "width": 100},
		{"fieldname": "returned_m", "label": _("Remnants Returned (m)"), "fieldtype": "Float", "width": 130},
		{"fieldname": "laid_m", "label": _("Laid (m)"), "fieldtype": "Float", "width": 90},
		{"fieldname": "end_bit_m", "label": _("End Bits (m)"), "fieldtype": "Float", "width": 90},
		{"fieldname": "damage_m", "label": _("Damage (m)"), "fieldtype": "Float", "width": 90},
		{"fieldname": "pieces_cut", "label": _("Pieces Cut"), "fieldtype": "Int", "width": 90},
		{"fieldname": "good_cut", "label": _("Good Garments"), "fieldtype": "Int", "width": 100},
		{"fieldname": "card_consumption", "label": _("Card (m / pc)"), "fieldtype": "Float", "precision": 4, "width": 100},
		{"fieldname": "lay_consumption", "label": _("Lay (m / pc)"), "fieldtype": "Float", "precision": 4, "width": 100},
		{"fieldname": "actual_consumption", "label": _("Actual (m / pc)"), "fieldtype": "Float", "precision": 4, "width": 110},
		{"fieldname": "variance_pct", "label": _("Actual vs Card %"), "fieldtype": "Percent", "width": 110},
		{"fieldname": "marker_efficiency", "label": _("Marker Efficiency %"), "fieldtype": "Percent", "width": 120},
		{"fieldname": "shortage_m", "label": _("Fabric Short (m)"), "fieldtype": "Float", "width": 110},
	]
	cond, args = ["c.docstatus = 1", "c.status not in ('Superseded', 'Cancelled')"], {}
	for key, col in (("production_card", "c.name"), ("sales_order", "c.sales_order"), ("customer", "c.customer")):
		if filters.get(key):
			cond.append(f"{col} = %({key})s")
			args[key] = filters[key]
	cards = frappe.db.sql(f"select c.name from `tabProduction Card` c where {' and '.join(cond)} order by c.creation desc limit 200", args, pluck="name")
	data = []
	for card in cards:
		for f in frappe.get_all("Production Card Fabric", {"parent": card}, ["colour", "fabric_item", "required_m", "consumption", "consumption_uom"], order_by="idx"):
			lays = frappe.get_all("Lay Report", {"production_card": card, "colour": f.colour, "fabric_item": f.fabric_item, "docstatus": 1, "purpose": ["!=", "Sample"]},
								  ["name", "laid_m", "pieces_cut", "marker_efficiency_pct", "total_plies"])
			laid = sum(flt(l.laid_m) for l in lays)
			pieces = sum(flt(l.pieces_cut) for l in lays)
			ends = frappe.db.sql("select ifnull(sum(r.end_bit_m), 0), ifnull(sum(r.damage_m), 0) from `tabLay Roll` r where r.parent in %s", (tuple([l.name for l in lays] or [""]),))[0]
			issued, returned = moved(card, "Fabric Issue", f.fabric_item), moved(card, "Remnant Return", f.fabric_item)
			good = flt(frappe.db.sql("select ifnull(sum(case when stage = 'CUT' then qty else -qty end), 0) from `tabProduction Movement` where production_card = %s and colour = %s and stage in ('CUT', 'CUT_REJECT')", (card, f.colour))[0][0])
			actual = maths.actual_consumption(issued, returned, good) if issued else None
			from arinox_apparel.materials import common as mc

			card_cons = mc.to_metres(flt(f.consumption), f.consumption_uom or "Meter")
			eff = maths.weighted_marker_efficiency([(flt(l.marker_efficiency_pct), flt(l.total_plies)) for l in lays if flt(l.marker_efficiency_pct)])
			data.append({
				"production_card": card, "colour": f.colour, "fabric_item": f.fabric_item, "required_m": f.required_m, "issued_m": issued, "returned_m": returned,
				"laid_m": laid, "end_bit_m": ends[0], "damage_m": ends[1], "pieces_cut": pieces, "good_cut": good, "card_consumption": card_cons,
				"lay_consumption": maths.lay_consumption(laid, pieces), "actual_consumption": actual,
				"variance_pct": (actual - card_cons) / card_cons * 100 if actual and card_cons else None, "marker_efficiency": eff,
				"shortage_m": max(flt(f.required_m) - (issued - returned), 0) if f.required_m else None,
			})
	return columns, data
