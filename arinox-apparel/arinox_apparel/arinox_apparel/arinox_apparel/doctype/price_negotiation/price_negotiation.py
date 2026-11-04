# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Every offer and counter on a style, with the margin each price would leave."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

OUR = ("Our Offer", "Our Counter")
BUYER = ("Buyer Target", "Buyer Counter")
MANUAL_STATUS = ("On Hold", "Lost")


class PriceNegotiation(Document):
	def validate(self):
		self.validate_rounds()
		self.summarise_styles()
		self.set_status()

	def validate_rounds(self):
		cache = {}
		for r in self.rounds:
			cs = cache.get(r.cost_sheet) or frappe.get_doc("Cost Sheet", r.cost_sheet)
			cache[r.cost_sheet] = cs
			if cs.customer != self.customer:
				frappe.throw(_("Round {0}: Cost Sheet {1} belongs to another customer.").format(r.idx, cs.name))
			if cs.currency != self.currency:
				frappe.throw(_("Round {0}: Cost Sheet {1} is in {2}, not {3}.").format(r.idx, cs.name, cs.currency, self.currency))
			if cs.docstatus == 2:
				frappe.throw(_("Round {0}: Cost Sheet {1} is cancelled. Use its amended revision.").format(r.idx, cs.name))
			r.style_no = cs.style_no
			if r.direction != "Dropped" and not flt(r.price):
				frappe.throw(_("Round {0}: enter the price.").format(r.idx))
			if flt(r.price):
				m = cs.margin_at_price(r.price)
				r.margin_pct = m["margin_pct"]
				r.below_floor = 1 if m["margin_pct"] < flt(cs.margin_floor_pct) else 0
			if not r.recorded_by:
				r.recorded_by = frappe.session.user
			if r.direction == "Agreed" and r.below_floor:
				frappe.msgprint(
					_("Style {0} agreed at {1}, margin {2}% is below the floor. The Quotation will need an approved Cost Sheet revision.").format(
						r.style_no, r.price, r.margin_pct
					),
					indicator="orange",
				)
			if not any(s.cost_sheet == r.cost_sheet for s in self.styles):
				self.append("styles", {"cost_sheet": r.cost_sheet, "qty": r.qty or cs.order_qty})

	def summarise_styles(self):
		rounds = sorted(self.rounds, key=lambda r: (getdate(r.round_date), r.idx))
		for s in self.styles:
			cs = frappe.get_doc("Cost Sheet", s.cost_sheet)
			s.style_no, s.cost_price = cs.style_no, cs.quoted_price
			s.our_last_offer = s.buyer_last_offer = s.agreed_price = s.margin_at_agreed = 0
			status = "Open"
			for r in rounds:
				if r.cost_sheet != s.cost_sheet:
					continue
				if r.direction in OUR:
					s.our_last_offer = r.price
				elif r.direction in BUYER:
					s.buyer_last_offer = r.price
				elif r.direction == "Agreed":
					s.agreed_price, s.margin_at_agreed, status = r.price, r.margin_pct, "Agreed"
				elif r.direction == "Dropped":
					status = "Dropped"
				if r.qty:
					s.qty = r.qty
			s.style_status = status

	def set_status(self):
		if self.status in MANUAL_STATUS:
			return
		live = [s for s in self.styles if s.style_status != "Dropped"]
		agreed = [s for s in live if s.style_status == "Agreed"]
		if live and len(agreed) == len(live):
			self.status = "Agreed"
		elif agreed:
			self.status = "Partly Agreed"
		else:
			self.status = "Open"


def build_quotation(customer, currency, opportunity=None, lines=None, price_negotiation=None):
	"""Unsaved Quotation with one line per style. Lines use the generic style item because ERPNext
	refuses a template item on a Quotation (erpnext/stock/get_item_details.py)."""
	quote_item = get_quote_item()
	q = frappe.new_doc("Quotation")
	q.company = get_default_company()
	q.quotation_to = "Customer"
	q.party_name = customer
	q.currency = currency
	q.opportunity = opportunity
	q.apparel_price_negotiation = price_negotiation
	for line in lines or []:
		cs = frappe.get_doc("Cost Sheet", line["cost_sheet"])
		label = " - ".join(x for x in (cs.style_no, cs.style_name) if x)
		q.append(
			"items",
			{
				"item_code": quote_item,
				"item_name": label[:140],
				"description": label,
				"qty": line.get("qty") or 1,
				"rate": line["rate"],
				"apparel_cost_sheet": cs.name,
				"apparel_style_item": cs.style_item,
				"apparel_style_no": cs.style_no,
			},
		)
	q.run_method("set_missing_values")
	for row, line in zip(q.items, lines or []):
		row.rate = line["rate"]
		row.price_list_rate = 0
	q.run_method("calculate_taxes_and_totals")
	return q


def get_default_company():
	"""User default in the desk; the global default for API and AI-agent calls."""
	return (
		frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	)


def get_quote_item():
	item = frappe.db.get_single_value("Apparel Settings", "quote_item")
	if item:
		return item
	if not frappe.db.exists("Item", "APPAREL-STYLE"):
		group = frappe.db.get_single_value("Apparel Settings", "style_item_group") or frappe.db.get_value(
			"Item Group", {"is_group": 0}, "name"
		)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "APPAREL-STYLE",
				"item_name": "Apparel Style (quotation line)",
				"item_group": group,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_sales_item": 1,
				"is_purchase_item": 0,
				"include_item_in_manufacturing": 0,
				"description": "Generic line item for quoting a garment style. The style is on the line.",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_single_value("Apparel Settings", "quote_item", "APPAREL-STYLE")
	return "APPAREL-STYLE"


@frappe.whitelist()
def make_quotation(source_name):
	pn = frappe.get_doc("Price Negotiation", source_name)
	pn.check_permission("read")
	lines = []
	for s in pn.styles:
		if s.style_status == "Dropped":
			continue
		rate = flt(s.agreed_price) or flt(s.our_last_offer) or flt(s.cost_price)
		lines.append({"cost_sheet": s.cost_sheet, "qty": s.qty or 1, "rate": rate})
	if not lines:
		frappe.throw(_("No live styles to quote."))
	return build_quotation(pn.customer, pn.currency, pn.opportunity, lines, price_negotiation=pn.name)


def log_quotation_rounds(quotation):
	"""Called when a Quotation is submitted: the quote is our offer, so it becomes a round."""
	if not quotation.get("apparel_price_negotiation"):
		return
	pn = frappe.get_doc("Price Negotiation", quotation.apparel_price_negotiation)
	for it in quotation.items:
		if not it.get("apparel_cost_sheet"):
			continue
		pn.append(
			"rounds",
			{
				"round_date": quotation.transaction_date,
				"cost_sheet": it.apparel_cost_sheet,
				"direction": "Our Offer",
				"price": it.rate,
				"qty": it.qty,
				"channel": "Email",
				"quotation": quotation.name,
				"remarks": _("Quotation {0} submitted").format(quotation.name),
			},
		)
	pn.quotation = quotation.name
	pn.flags.ignore_permissions = True
	pn.save()
