"""Quantities read back from the ledger for reports: one place so the WIP report, the stock report and the production
summary agree."""

import frappe
from frappe.utils import flt

LIVE = ("Superseded", "Cancelled")


def live_cards(sales_order=None, style_item=None):
	filters = {"docstatus": 1, "status": ["not in", LIVE]}
	if sales_order:
		filters["sales_order"] = sales_order
	if style_item:
		filters["style_item"] = style_item
	return frappe.get_all("Production Card", filters, pluck="name")


def stage_qty(sales_order, style_item, colour, stages, purpose=None, process=None):
	"""Sum of ledger quantity for stages of one order x style x colour across its live cards."""
	cards = live_cards(sales_order, style_item)
	if not cards:
		return 0
	cond, args = "", [tuple(cards), tuple(stages)]
	if colour:
		cond += " and upper(colour) = upper(%s)"
		args.append(colour)
	if purpose:
		cond += " and purpose = %s"
		args.append(purpose)
	if process:
		cond += " and subcontract_process = %s"
		args.append(process)
	return flt(frappe.db.sql(f"select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card in %s and stage in %s{cond}", args)[0][0])


def good_cut(sales_order, style_item, colour):
	return stage_qty(sales_order, style_item, colour, ["CUT"]) - stage_qty(sales_order, style_item, colour, ["CUT_REJECT"])


def fabric_usage(sales_order, style_item, colour, fabric_item):
	"""(good garments cut, metres drawn net of remnants returned, actual consumption per garment) for one fabric."""
	from arinox_apparel.production.stock import moved

	cut = good_cut(sales_order, style_item, colour)
	net = 0.0
	for card in live_cards(sales_order, style_item):
		net += moved(card, "Fabric Issue", fabric_item) - moved(card, "Remnant Return", fabric_item)
	return cut, net, (net / cut if cut and net else None)
