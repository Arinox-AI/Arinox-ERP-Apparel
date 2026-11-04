"""Bulk gate (G3): a Work Order for an apparel style cannot be submitted until the buyer has approved what the
rules require, and the PP meeting is held with every cutting-related action closed."""

import frappe
from frappe import _
from frappe.utils import cint

from arinox_apparel.arinox_apparel.doctype.pp_meeting.pp_meeting import cutting_actions_open
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import (
	GATE_OK,
	MANAGER_ROLES,
	effective_gate,
	get_rules,
	norm,
	scope_filters,
)


def style_and_colour(production_item):
	"""(style template, colour) of a variant item; (None, None) when the item is not an apparel style variant."""
	style = frappe.db.get_value("Item", production_item, "variant_of")
	if not style:
		return None, None
	if not (frappe.db.exists("Sales Contract Item", {"style_item": style}) or frappe.db.exists("Tech Pack", {"style_item": style})):
		return None, None
	attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
	colour = frappe.db.get_value("Item Variant Attribute", {"parent": production_item, "attribute": attr}, "attribute_value")
	return style, colour


@frappe.whitelist()
def get_bulk_gate(production_item, sales_order):
	"""List of blockers (empty = the gate is open) for bulk production of this item on this order."""
	style, colour = style_and_colour(production_item)
	if not style or not sales_order:
		return {"applies": False, "blockers": []}
	rules = get_rules(None, sales_order, style)
	samples = frappe.get_all(
		"Sample Approval", scope_filters(sales_order, style), ["name", "sample_type", "status", "colour"]
	)

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
	return {"applies": True, "style": style, "colour": colour, "blockers": blockers}


def has_manager_role():
	return bool(set(frappe.get_roles()) & set(MANAGER_ROLES))


def validate(doc, method=None):
	if cint(doc.get("apparel_gate_override")):
		if not doc.is_new() and not doc.has_value_changed("apparel_gate_override"):
			return
		if not has_manager_role():
			frappe.throw(_("Only an Apparel Merchandising Manager can override the bulk gate."))
		if not (doc.get("apparel_gate_override_reason") or "").strip():
			frappe.throw(_("Enter the reason for overriding the bulk gate."))


def before_submit(doc, method=None):
	if not cint(frappe.db.get_single_value("Apparel Settings", "enforce_bulk_gate")) or not doc.get("sales_order"):
		return
	gate = get_bulk_gate(doc.production_item, doc.sales_order)
	if not gate["blockers"]:
		return
	if cint(doc.get("apparel_gate_override")) and has_manager_role() and (doc.get("apparel_gate_override_reason") or "").strip():
		return
	frappe.throw(
		_("Bulk production is blocked until the buyer approvals are complete:") + "<br>• " + "<br>• ".join(gate["blockers"]),
		title=_("Bulk Gate (G3)"),
	)
