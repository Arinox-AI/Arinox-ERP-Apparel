"""Cutting: roll suggestion for a cut plan, bundle numbering for a lay, kit components. Rules live here so the
Lay Report, the agent API and the tests share them."""

import math

import frappe
from frappe import _
from frappe.utils import cint, flt

from arinox_apparel.production.stock import roll_available, setting

OK_STATUS = ("Accepted", "Accepted by Lot")


def roll_info(batch):
	b = frappe.db.get_value(
		"Batch", batch,
		["item", "apparel_roll_no", "apparel_dye_lot", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status",
		 "apparel_shrinkage_warp_pct", "apparel_shrinkage_weft_pct"], as_dict=True)
	if not b:
		frappe.throw(_("Roll {0} not found.").format(batch))
	return b


def required_components(card, colour):
	"""Fabric roles that make up a garment of this colour on the production card (Shell, Lining, ...)."""
	roles = frappe.get_all("Production Card Fabric", {"parent": card, "colour": colour}, pluck="material_role")
	return sorted(set(roles or ["Shell"]))


def suggest_rolls(plan_name):
	"""Allocate the rolls in the Cutting WIP warehouse to the lays of a cut plan: group by shade band, then width, then
	longest roll first. Returns {'lays': [...], 'unallocated': [...], 'short': [...]}. Nothing is saved."""
	plan = frappe.get_doc("Cut Plan", plan_name)
	wh = setting("cutting_wip_warehouse")
	batches = frappe.get_all("Batch", {"item": plan.fabric_item, "disabled": 0},
							 ["name", "apparel_roll_no", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status", "apparel_dye_lot"])
	pool = []
	for b in batches:
		if b.apparel_inspection_status not in OK_STATUS:
			continue
		avail = roll_available(b.name, wh, plan.fabric_item)
		if avail > 0:
			pool.append(frappe._dict(batch=b.name, roll_no=b.apparel_roll_no, shade=b.apparel_shade_band or "", width=flt(b.apparel_width_cm), length=avail, dye_lot=b.apparel_dye_lot))
	out, short = [], []
	spread = flt(setting("max_width_spread_cm") or 1)
	for lay in sorted(plan.lays, key=lambda l: l.lay_no):
		need = flt(lay.planned_plies) * flt(lay.marker_length_m)
		cands = [r for r in pool if (not (lay.shade_band or "").strip() or r.shade == lay.shade_band)
				 and (not flt(lay.width_group_cm) or abs(r.width - flt(lay.width_group_cm)) <= spread)
				 and (not flt(lay.marker_width_cm) or not r.width or r.width >= flt(lay.marker_width_cm))]
		if not (lay.shade_band or "").strip() and cands:  # no shade named: keep to the shade band of the longest roll
			first = max(cands, key=lambda r: r.length)
			cands = [r for r in cands if r.shade == first.shade and abs(r.width - first.width) <= spread]
		cands.sort(key=lambda r: -r.length)
		taken, got = [], 0.0
		for r in cands:
			if got >= need - 1e-9:
				break
			use = min(r.length, need - got)
			plies = int(math.floor(use / flt(lay.marker_length_m))) if flt(lay.marker_length_m) else 0
			if plies <= 0:
				continue
			metres = plies * flt(lay.marker_length_m)
			taken.append({"batch": r.batch, "roll_no": r.roll_no, "plies": plies, "metres": round(metres, 3), "shade": r.shade, "width": r.width})
			got += metres
			r.length -= metres
		out.append({"lay_no": lay.lay_no, "needed_m": round(need, 3), "allocated_m": round(got, 3), "rolls": taken})
		if got < need - 1e-9:
			short.append({"lay_no": lay.lay_no, "short_m": round(need - got, 3)})
	left = [{"batch": r.batch, "roll_no": r.roll_no, "metres": round(r.length, 3), "shade": r.shade} for r in pool if r.length > 1e-9]
	return {"lays": out, "unallocated": left, "short": short}


def next_ply(card):
	"""First free ply number on a production card (sticker numbers never repeat on a card)."""
	return cint(frappe.db.sql("select ifnull(max(ply_to), 0) from `tabCut Bundle` where production_card = %s", card)[0][0]) + 1


def chunks(first, last, size):
	"""Ply ranges [(from, to)] of at most `size` plies covering first..last."""
	size = max(cint(size), 1)
	out, a = [], first
	while a <= last:
		b = min(a + size - 1, last)
		out.append((a, b))
		a = b + 1
	return out


def make_bundles(lay):
	"""Create the Cut Bundles of a submitted Lay Report. A paired (lining, pocketing) lay mirrors the ply ranges of its
	shell lay so every component of a garment carries the same ply number. Returns the bundle names."""
	card = lay.production_card
	size_bundle = cint(frappe.db.get_value("Production Card", card, "bundle_size")) or cint(setting("bundle_size")) or 20
	rolls = ", ".join(r.roll_no or r.batch for r in lay.rolls)
	names = []
	if lay.paired_with:
		src = frappe.get_all("Cut Bundle", {"lay_report": lay.paired_with, "status": ["!=", "Voided"]},
							 ["size", "body_no", "ply_from", "ply_to", "qty", "kit_key", "is_short", "bundle_no"], order_by="bundle_no")
		for b in src:
			names.append(_new_bundle(lay, card, b.size, b.body_no, b.ply_from, b.ply_to, b.qty, rolls, b.kit_key, b.is_short))
		return names
	first = next_ply(card)
	plies = cint(lay.total_plies)
	last = first + plies - 1
	n = cint(frappe.db.sql("select ifnull(max(bundle_no), 0) from `tabCut Bundle` where production_card = %s", card)[0][0])
	for s in lay.sizes:
		for body in range(1, max(cint(s.ratio), 1) + 1):
			for a, b in chunks(first, last, size_bundle):
				qty = b - a + 1
				key = f"{lay.colour}|{s.size}|{a}-{b}|{body}"
				n += 1
				names.append(_new_bundle(lay, card, s.size, body, a, b, qty, rolls, key, 1 if qty < size_bundle else 0, bundle_no=n))
	return names


def _new_bundle(lay, card, size, body, ply_from, ply_to, qty, rolls, kit_key, short, bundle_no=None):
	if bundle_no is None:
		bundle_no = cint(frappe.db.sql("select ifnull(max(bundle_no), 0) from `tabCut Bundle` where production_card = %s", card)[0][0]) + 1
	d = frappe.get_doc({
		"doctype": "Cut Bundle", "production_card": card, "lay_report": lay.name, "colour": lay.colour, "size": size,
		"component": lay.component or "Shell", "purpose": lay.purpose, "bundle_no": bundle_no, "body_no": body,
		"ply_from": ply_from, "ply_to": ply_to, "qty": qty, "shade_band": lay.shade_band, "roll_nos": rolls, "kit_key": kit_key,
		"status": "Cut", "is_short": cint(short),
	})
	d.insert(ignore_permissions=True)
	return d.name


def void_bundles(lay_name):
	"""Cancel of a lay: bundles are voided (their numbers are never reused). Blocked once any bundle left the cutting room."""
	moved = frappe.get_all("Cut Bundle", {"lay_report": lay_name, "status": ["not in", ("Cut", "Voided")]}, pluck="name")
	if moved:
		frappe.throw(_("Bundles {0} have already left the cutting room. Take them back before cancelling the lay.").format(", ".join(moved[:5])))
	for n in frappe.get_all("Cut Bundle", {"lay_report": lay_name}, pluck="name"):
		frappe.db.set_value("Cut Bundle", n, "status", "Voided", update_modified=False)


def kit_missing(bundle_names):
	"""For shell bundles about to go to a line: the kit keys whose lining / pocketing bundles are missing."""
	missing = []
	for n in bundle_names:
		b = frappe.db.get_value("Cut Bundle", n, ["production_card", "colour", "component", "kit_key"], as_dict=True)
		if b.component != "Shell":
			continue
		for comp in required_components(b.production_card, b.colour):
			if comp == "Shell":
				continue
			if not frappe.db.exists("Cut Bundle", {"production_card": b.production_card, "kit_key": b.kit_key, "component": comp, "status": ["!=", "Voided"]}):
				missing.append(f"{b.kit_key} ({comp})")
	return missing


# ---- agent / form entry points ---------------------------------------------------------------------------------------

@frappe.whitelist()
def get_issuable_rolls(card):
	"""Accepted rolls in the fabric store for the fabrics of a production card, with their free length."""
	if not frappe.has_permission("Production Card", "read", card):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	src = setting("store_warehouse_fabric")
	items = {f.fabric_item: f.colour for f in frappe.get_all("Production Card Fabric", {"parent": card}, ["fabric_item", "colour"]) if f.fabric_item}
	out = []
	for item, colour in items.items():
		for b in frappe.get_all("Batch", {"item": item, "disabled": 0}, ["name", "apparel_roll_no", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status"]):
			if b.apparel_inspection_status not in OK_STATUS:
				continue
			qty = roll_available(b.name, src, item)
			if qty > 0:
				out.append({"batch": b.name, "roll_no": b.apparel_roll_no, "item": item, "colour": colour, "shade": b.apparel_shade_band, "width": b.apparel_width_cm, "available_m": qty})
	return out


@frappe.whitelist()
def issue_fabric(card, rolls):
	"""Issue rolls to the cutting floor. `rolls` = [{batch_no, qty}] (JSON)."""
	import json

	from arinox_apparel.production.stock import issue_fabric_entry

	if not frappe.has_permission("Production Card", "write", card) and "Apparel Production User" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	rolls = json.loads(rolls) if isinstance(rolls, str) else rolls
	return issue_fabric_entry(card, rolls)


@frappe.whitelist()
def suggest_rolls_for_plan(plan):
	if not frappe.has_permission("Cut Plan", "read", plan):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return suggest_rolls(plan)
