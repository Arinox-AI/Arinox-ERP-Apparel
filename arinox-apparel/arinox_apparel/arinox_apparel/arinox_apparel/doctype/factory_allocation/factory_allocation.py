# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Which factory and line makes which style x colour of a Sales Order. Decided by the AI agent or a planner;
the ERP stores it and checks it is consistent. One allocation per Sales Order, named FA-<Sales Order>."""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate


def norm(colour):
	return (colour or "").strip().upper()


def get_order_lines(sales_order):
	"""Sales Order grouped to the order grain: (style, colour, ship-to, buyer PO) -> qty, tolerance %, earliest
	ex-factory date."""
	lines = {}
	for it in frappe.get_all(
		"Sales Order Item", {"parent": sales_order},
		["item_code", "qty", "apparel_colour", "apparel_ship_to", "apparel_buyer_po", "apparel_qty_tolerance_pct", "delivery_date"],
	):
		style = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
		key = (style, norm(it.apparel_colour), norm(it.apparel_ship_to), norm(it.apparel_buyer_po))
		row = lines.setdefault(key, frappe._dict(
			style_item=style, colour=(it.apparel_colour or "").strip(), ship_to=(it.apparel_ship_to or "").strip(),
			buyer_po=(it.apparel_buyer_po or "").strip(), qty=0, tolerance_pct=0, ex_factory_date=None,
		))
		row.qty += cint(it.qty)
		row.tolerance_pct = max(flt(row.tolerance_pct), flt(it.apparel_qty_tolerance_pct))
		if it.delivery_date and (not row.ex_factory_date or getdate(it.delivery_date) < getdate(row.ex_factory_date)):
			row.ex_factory_date = it.delivery_date
	return lines


def colour_level(order):
	"""The order lines rolled up to style x colour."""
	out = {}
	for (style, colour, _ship, _po), o in order.items():
		row = out.setdefault((style, colour), frappe._dict(
			style_item=style, colour=o.colour, qty=0, tolerance_pct=0, ex_factory_date=None))
		row.qty += o.qty
		row.tolerance_pct = max(flt(row.tolerance_pct), flt(o.tolerance_pct))
		if o.ex_factory_date and (not row.ex_factory_date or getdate(o.ex_factory_date) < getdate(row.ex_factory_date)):
			row.ex_factory_date = o.ex_factory_date
	return out


def cap_of(qty, tolerance_pct):
	return int(qty * (1 + flt(tolerance_pct) / 100))


class FactoryAllocation(Document):
	def autoname(self):
		self.name = f"FA-{self.sales_order}"

	def validate(self):
		so = frappe.db.get_value(
			"Sales Order", self.sales_order, ["docstatus", "customer", "company", "apparel_sales_contract"], as_dict=True
		)
		if not so or so.docstatus != 1:
			frappe.throw(_("Sales Order {0} must be submitted (order confirmed) before it is planned.").format(self.sales_order))
		self.customer, self.company, self.sales_contract = so.customer, so.company, so.apparel_sales_contract
		order = get_order_lines(self.sales_order)
		self.order_qty = sum(o.qty for o in order.values())
		self.validate_lines(order)
		self.set_status(order)

	def validate_lines(self, order):
		"""A row is for a style x colour, optionally narrowed to a ship-to and/or buyer PO. Blank = the whole colour."""
		colours = colour_level(order)
		by_colour, by_group, groups = defaultdict(int), defaultdict(int), {}
		for r in self.lines:
			ckey = (r.style_item, norm(r.colour))
			c = colours.get(ckey)
			if not c:
				frappe.throw(_("Row {0}: {1} / {2} is not on Sales Order {3}.").format(r.idx, r.style_item, r.colour, self.sales_order))
			if cint(r.qty) <= 0:
				frappe.throw(_("Row {0}: allocated qty must be above zero.").format(r.idx))
			narrowed = r.ship_to or r.buyer_po
			if narrowed:
				match = [
					o for k, o in order.items()
					if k[:2] == ckey and (not r.ship_to or k[2] == norm(r.ship_to)) and (not r.buyer_po or k[3] == norm(r.buyer_po))
				]
				if not match:
					frappe.throw(_("Row {0}: {1} / {2} has no order line for ship-to '{3}' PO '{4}'.").format(
						r.idx, r.style_item, r.colour, r.ship_to or "-", r.buyer_po or "-"))
				gkey = ckey + (norm(r.ship_to), norm(r.buyer_po))
				groups[gkey] = (sum(o.qty for o in match), max(flt(o.tolerance_pct) for o in match))
				by_group[gkey] += cint(r.qty)
				r.order_qty = groups[gkey][0]
				dates = [o.ex_factory_date for o in match if o.ex_factory_date]
				r.ex_factory_date = min(dates) if dates else None
			else:
				r.order_qty, r.ex_factory_date = c.qty, c.ex_factory_date
			r.style_no = r.style_no or r.style_item
			by_colour[ckey] += cint(r.qty)
			if r.line:
				floor = frappe.db.get_value("Workstation", r.line, "plant_floor")
				if floor != r.factory:
					frappe.throw(_("Row {0}: line {1} does not belong to factory {2}.").format(r.idx, r.line, r.factory))
			self.check_dates(r)
		for ckey, qty in by_colour.items():
			c = colours[ckey]
			if qty > cap_of(c.qty, c.tolerance_pct):
				frappe.throw(_("{0} / {1}: allocated {2} is more than the order {3} plus tolerance ({4}).").format(
					ckey[0], c.colour, qty, c.qty, cap_of(c.qty, c.tolerance_pct)))
		for gkey, qty in by_group.items():
			total, tol = groups[gkey]
			if qty > cap_of(total, tol):
				frappe.throw(_("{0} / {1} (ship-to {2}, PO {3}): allocated {4} is more than the order {5} plus tolerance ({6}).").format(
					gkey[0], gkey[1], gkey[2] or "-", gkey[3] or "-", qty, total, cap_of(total, tol)))
		self.allocated_qty = sum(by_colour.values())
		self._allocated = by_colour

	def check_dates(self, r):
		chain = [("PCD", r.pcd), ("Sewing start", r.sewing_start), ("Sewing end", r.sewing_end), ("Ex-factory", r.ex_factory_date)]
		chain = [(n, getdate(d)) for n, d in chain if d]
		for (n1, d1), (n2, d2) in zip(chain, chain[1:]):
			if d1 > d2:
				frappe.throw(_("Row {0}: {1} ({2}) is after {3} ({4}).").format(r.idx, n1, d1, n2, d2))

	def set_status(self, order):
		allocated, colours = self._allocated, colour_level(order)
		if not allocated:
			self.status = "Unplanned"
		elif all(allocated.get(k, 0) >= o.qty for k, o in colours.items()):
			self.status = "Planned"
		else:
			self.status = "Partly Planned"


@frappe.whitelist()
def get_planning_context(sales_order):
	"""Everything the planning agent needs in one call: the order lines, the factories and their lines,
	and what other orders already load into the same window."""
	frappe.has_permission("Factory Allocation", "read", throw=True)
	order = list(get_order_lines(sales_order).values())
	dates = [getdate(o.ex_factory_date) for o in order if o.ex_factory_date]
	lo, hi = (add_days(min(dates), -45), max(dates)) if dates else (None, None)
	factories = []
	for f in frappe.get_all("Plant Floor", ["name", "company", "warehouse"]):
		f["lines"] = frappe.get_all(
			"Workstation", {"plant_floor": f.name, "disabled": 0}, ["name", "production_capacity", "status"]
		)
		factories.append(f)
	busy = []
	if lo:
		busy = frappe.db.sql(
			"""select l.parent as allocation, l.style_item, l.colour, l.qty, l.factory, l.line, l.pcd, l.sewing_start, l.sewing_end
			from `tabFactory Allocation Line` l where l.parent != %s and l.sewing_end between %s and %s""",
			(f"FA-{sales_order}", lo, add_days(hi, 30)), as_dict=True,
		)
	existing = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
	return {
		"sales_order": sales_order,
		"order_lines": [dict(o) for o in order],
		"factories": factories,
		"other_allocations_in_window": busy,
		"current_allocation": frappe.get_doc("Factory Allocation", existing).as_dict() if existing else None,
	}


@frappe.whitelist()
def save_allocation(sales_order, lines, agent_notes=None, planned_by="AI Agent"):
	"""Create or replace the allocation of a Sales Order. `lines` is a list (or JSON) of
	{style_item, colour, qty, factory, line, pcd, sewing_start, sewing_end, reason}."""
	if isinstance(lines, str):
		lines = json.loads(lines)
	name = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
	doc = frappe.get_doc("Factory Allocation", name) if name else frappe.new_doc("Factory Allocation")
	doc.sales_order = sales_order
	doc.planned_by = planned_by
	if agent_notes is not None:
		doc.agent_notes = agent_notes
	doc.set("lines", [])
	for ln in lines:
		doc.append("lines", ln)
	doc.save()
	return doc.name


@frappe.whitelist()
def get_lines_from_order(sales_order):
	"""One blank allocation row per style x colour of the order, for the form's Get Order Lines button."""
	return [
		{"style_item": o.style_item, "colour": o.colour, "ship_to": o.ship_to, "buyer_po": o.buyer_po, "qty": o.qty,
		 "order_qty": o.qty, "ex_factory_date": o.ex_factory_date}
		for o in get_order_lines(sales_order).values()
	]
