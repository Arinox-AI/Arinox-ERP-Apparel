"""Bulk gate (G3): a Work Order for an apparel style cannot be submitted until the buyer has approved what the
rules require, and the PP meeting is held with every cutting-related action closed."""

import frappe
from frappe import _
from frappe.utils import cint

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import MANAGER_ROLES


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
	from arinox_apparel.production.gate import bulk_gate_for

	return bulk_gate_for(sales_order, style, colour, stage="bulk")


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
	for w in gate.get("warnings") or []:
		frappe.msgprint(w, indicator="orange", title=_("Materials"))
	if not gate["blockers"]:
		return
	if cint(doc.get("apparel_gate_override")) and has_manager_role() and (doc.get("apparel_gate_override_reason") or "").strip():
		return
	frappe.throw(
		_("Bulk production is blocked until the buyer approvals and materials are complete:") + "<br>• " + "<br>• ".join(gate["blockers"]),
		title=_("Bulk Gate (G3)"),
	)
