# Copyright (c) 2026, Arinox AI and contributors
"""Order Desk: every open order-win document on one board, by stage."""

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

LIMIT = 40


@frappe.whitelist()
def get_pipeline(customer=None):
	c = {"customer": customer} if customer else {}
	cols = []

	opps = frappe.get_all(
		"Opportunity",
		filters={"opportunity_from": "Customer", "status": ("in", ["Open", "Replied", "Quotation"]),
				 **({"party_name": customer} if customer else {})},
		fields=["name", "party_name", "customer_name", "transaction_date", "apparel_product_type", "apparel_season"],
		order_by="transaction_date desc", limit=LIMIT * 2,
	)
	with_tp = set(frappe.get_all("Tech Pack", filters={"opportunity": ("in", [o.name for o in opps] or [""])}, pluck="opportunity"))
	cols.append(col("inquiry", _("Inquiry"), "Opportunity", [
		card(o.name, o.customer_name or o.party_name, " · ".join(x for x in (o.apparel_product_type, o.apparel_season) if x),
			 o.transaction_date) for o in opps if o.name not in with_tp][:LIMIT]))

	tps = frappe.get_all("Tech Pack", filters={"docstatus": ("<", 2), **c},
						 fields=["name", "style_no", "customer_name", "status", "received_on", "docstatus"],
						 order_by="received_on desc", limit=LIMIT * 2)
	costed = set(frappe.get_all("Cost Sheet", filters={"tech_pack": ("in", [t.name for t in tps] or [""]), "docstatus": ("<", 2)},
								pluck="tech_pack"))
	cols.append(col("techpack", _("Tech Pack"), "Tech Pack", [
		card(t.name, t.style_no, t.customer_name, t.received_on, badge=t.status) for t in tps if t.name not in costed][:LIMIT]))

	cs = frappe.get_all("Cost Sheet", filters={"docstatus": 0, **c},
						fields=["name", "style_no", "customer_name", "margin_pct", "below_floor", "approval_status",
								"quoted_price", "currency", "costing_date"],
						order_by="costing_date desc", limit=LIMIT)
	cols.append(col("costing", _("Costing"), "Cost Sheet", [
		card(x.name, x.style_no, x.customer_name, x.costing_date,
			 badge=f"{x.margin_pct or 0:.1f}%" + (f" · {x.approval_status}" if x.below_floor else ""),
			 tone="red" if x.below_floor and x.approval_status != "Approved" else "green",
			 amount=(x.quoted_price, x.currency)) for x in cs]))

	pns = frappe.get_all("Price Negotiation", filters={"status": ("in", ["Open", "Partly Agreed", "On Hold"]), **c},
						 fields=["name", "customer_name", "status", "modified", "currency"], order_by="modified desc", limit=LIMIT)
	cards = []
	for p in pns:
		last = frappe.get_all("Price Negotiation Round", filters={"parent": p.name, "parenttype": "Price Negotiation"},
							  fields=["direction", "price", "style_no"], order_by="round_date desc, idx desc", limit=1)
		sub = f"{last[0].style_no}: {last[0].direction} {last[0].price}" if last else ""
		cards.append(card(p.name, p.customer_name, sub, p.modified, badge=p.status,
						  tone="orange" if p.status == "On Hold" else "blue"))
	cols.append(col("negotiation", _("Negotiating"), "Price Negotiation", cards))

	quoted = frappe.db.sql(
		"""select distinct q.name, q.customer_name, q.transaction_date, q.grand_total, q.currency, q.status
		from `tabQuotation` q join `tabQuotation Item` qi on qi.parent = q.name
		where q.docstatus = 1 and q.status in ('Open', 'Replied', 'Partially Ordered')
		and ifnull(qi.apparel_cost_sheet, '') != ''
		and not exists (select 1 from `tabSales Contract` sc where sc.quotation = q.name and sc.docstatus < 2)
		{cust} order by q.transaction_date desc limit {limit}""".format(
			cust="and q.party_name = %(customer)s" if customer else "", limit=LIMIT),
		{"customer": customer}, as_dict=True)
	cols.append(col("quoted", _("Quoted"), "Quotation", [
		card(q.name, q.customer_name, q.status, q.transaction_date, amount=(q.grand_total, q.currency)) for q in quoted]))

	scs = frappe.get_all("Sales Contract", filters={"docstatus": ("<", 2), "status": ("in", ["Draft", "Signed"]), **c},
						 fields=["name", "customer_name", "status", "contract_date", "total_amount", "currency", "sku_count", "total_qty"],
						 order_by="contract_date desc", limit=LIMIT)
	cols.append(col("contract", _("Contract"), "Sales Contract", [
		card(s.name, s.customer_name, _("{0} SKUs · {1} pcs").format(s.sku_count or 0, s.total_qty or 0), s.contract_date,
			 badge=s.status, tone="green" if s.status == "Signed" else "gray", amount=(s.total_amount, s.currency)) for s in scs]))

	done = frappe.get_all("Sales Contract", filters={"status": "Ordered", "modified": (">=", add_days(nowdate(), -30)), **c},
						  fields=["name", "customer_name", "sales_order", "contract_date", "total_amount", "currency"],
						  order_by="modified desc", limit=LIMIT)
	cols.append(col("ordered", _("Ordered (30 days)"), "Sales Contract", [
		card(s.name, s.customer_name, s.sales_order, s.contract_date, amount=(s.total_amount, s.currency)) for s in done]))
	return cols


def col(key, label, doctype, cards):
	return {"key": key, "label": label, "doctype": doctype, "cards": cards, "count": len(cards)}


def card(name, title, subtitle=None, date=None, badge=None, tone="gray", amount=None):
	return {"name": name, "title": title, "subtitle": subtitle, "date": str(date) if date else None,
			"badge": badge, "tone": tone, "amount": amount[0] if amount else None,
			"currency": amount[1] if amount else None}
