"""Quotation joins the apparel flow: lines carrying a Cost Sheet are held to its margin floor."""

import frappe
from frappe import _
from frappe.utils import flt


def validate(doc, method=None):
	for it in doc.items:
		if not it.get("apparel_cost_sheet"):
			continue
		cs = frappe.get_doc("Cost Sheet", it.apparel_cost_sheet)
		if cs.docstatus != 1:
			frappe.throw(_("Row {0}: Cost Sheet {1} is not submitted. Only a submitted costing can be quoted.").format(
				it.idx, cs.name))
		if doc.quotation_to == "Customer" and cs.customer != doc.party_name:
			frappe.throw(_("Row {0}: Cost Sheet {1} belongs to {2}.").format(it.idx, cs.name, cs.customer))
		if cs.currency != doc.currency:
			frappe.throw(_("Row {0}: Cost Sheet {1} is in {2}, the Quotation in {3}.").format(
				it.idx, cs.name, cs.currency, doc.currency))
		it.apparel_style_item = it.apparel_style_item or cs.style_item
		it.apparel_style_no = it.apparel_style_no or cs.style_no
		margin = cs.margin_at_price(it.rate)["margin_pct"]
		approved_at = flt(cs.approved_price) if cs.approval_status == "Approved" else None
		if margin < flt(cs.margin_floor_pct) and not (approved_at and flt(it.rate) >= approved_at - 0.0001):
			frappe.throw(
				_("Row {0} ({1}): {2} leaves a margin of {3}%, below the floor of {4}%. Amend the Cost Sheet at this price and get it approved first.").format(
					it.idx, cs.style_no, flt(it.rate), margin, flt(cs.margin_floor_pct)),
				title=_("Below Margin Floor"),
			)


def on_submit(doc, method=None):
	from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import log_quotation_rounds

	log_quotation_rounds(doc)
