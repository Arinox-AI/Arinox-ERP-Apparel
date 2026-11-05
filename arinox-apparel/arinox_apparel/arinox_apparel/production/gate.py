"""The bulk gate, as a plain function so the Work Order hook, the Production Card and the first bulk lay all use the
same rules. `stage` is "pilot" (PP meeting, buyer approvals, materials) or "bulk" (all of that plus an approved pilot
run when the production card says one is required)."""

import frappe
from frappe import _
from frappe.utils import cint

from arinox_apparel.arinox_apparel.doctype.pp_meeting.pp_meeting import cutting_actions_open
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import (
	GATE_OK,
	effective_gate,
	get_rules,
	norm,
	scope_filters,
)

PILOT_OK = ("Approved", "Approved with Comments")


def active_card(sales_order, style_item):
	"""The live (issued, not superseded) production card for an order and style, or None."""
	if not frappe.db.exists("DocType", "Production Card"):
		return None
	rows = frappe.get_all(
		"Production Card",
		{"sales_order": sales_order, "style_item": style_item, "docstatus": 1, "status": ["not in", ("Superseded", "Cancelled")]},
		["name", "pilot_required", "pilot_waiver"], order_by="creation desc", limit=1)
	return rows[0] if rows else None


def pilot_blockers(sales_order, style, colour):
	"""Blockers from the pilot run. Only applies when a live production card exists and requires a pilot."""
	card = active_card(sales_order, style)
	if not card or not cint(card.pilot_required) or cint(card.pilot_waiver):
		return []
	if not frappe.db.exists("DocType", "Pilot Run"):
		return []
	runs = frappe.get_all("Pilot Run", {"production_card": card.name, "docstatus": 1}, ["name", "status"])
	if not runs:
		return [_("Pilot Run: no pilot run recorded for production card {0}.").format(card.name)]
	good = []
	for r in runs:
		if r.status not in PILOT_OK:
			continue
		colours = frappe.get_all("Pilot Run Colour", {"parent": r.name}, pluck="colour")
		if not colours or not colour or norm(colour) in {norm(c) for c in colours}:
			good.append(r.name)
	if good:
		return []
	return [_("Pilot Run: no approved pilot run for {0} (production card {1}).").format(colour or _("this colour"), card.name)]


def bulk_gate_for(sales_order, style, colour, stage="bulk"):
	"""{'applies', 'style', 'colour', 'blockers', 'warnings'} for bulk production of this style x colour on this order."""
	if not style or not sales_order:
		return {"applies": False, "blockers": [], "warnings": []}
	rules = get_rules(None, sales_order, style)
	samples = frappe.get_all("Sample Approval", scope_filters(sales_order, style), ["name", "sample_type", "status", "colour"])

	def in_scope(s, rule):
		return not rule.per_colour or not (s.colour or "").strip() or norm(s.colour) == norm(colour)

	blockers = []
	for stype, rule in rules.items():
		gate = effective_gate(rule, sales_order)
		if gate == "No":
			continue
		mine = [s for s in samples if s.sample_type == stype and in_scope(s, rule)]
		where = f"{stype}" + (f" ({colour})" if rule.per_colour and colour else "")
		if gate == "Required" and not mine:
			blockers.append(_("{0}: no approval record yet.").format(where))
		for s in mine:
			if s.status not in GATE_OK:
				blockers.append(_("{0}: {1} is {2}.").format(where, s.name, s.status))
	if cint(frappe.db.get_single_value("Apparel Settings", "require_pp_meeting")):
		meetings, open_rows = cutting_actions_open(sales_order, style)
		if not meetings:
			blockers.append(_("PP Meeting: not held (no submitted PP Meeting for this style on this order)."))
		for r in open_rows:
			blockers.append(_("PP Meeting: cutting comment still open: {0}").format((r.comment or "")[:80]))
	from arinox_apparel.materials.status import material_gate

	m_blockers, m_warnings = material_gate(sales_order, style, colour)
	blockers += m_blockers
	if stage == "bulk":
		blockers += pilot_blockers(sales_order, style, colour)
	return {"applies": True, "style": style, "colour": colour, "blockers": blockers, "warnings": m_warnings}
