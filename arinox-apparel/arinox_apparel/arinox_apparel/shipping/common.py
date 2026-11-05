"""Shared helpers for Phase E: the contract-wide serial and the plain lookups every shipping document needs.

One number runs through a contract from start to end: the Sales Contract number. Every Phase E document is named
`<contract no>-<code>-<nn>` and carries the contract in a filterable field, so one search shows the whole trail.
An order without a contract falls back to its Sales Order name."""

import frappe
from frappe import _
from frappe.model.naming import getseries


def contract_of_order(sales_order):
	if not sales_order:
		return None
	return frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract") or None


def serial_root(sales_order):
	"""The number the whole trail hangs on: the contract, or the order when it has none."""
	return contract_of_order(sales_order) or sales_order


def card_root(production_card):
	so = frappe.db.get_value("Production Card", production_card, "sales_order")
	return serial_root(so)


def next_serial(root, code, digits=2):
	"""`<root>-<code>-<nn>`; the counter is per root and code and never goes back, so a number is not reused."""
	key = f"{root}-{code}-"
	return key + getseries(key, digits)


def card_context(production_card):
	"""The fields every document copies from its production card."""
	return frappe.db.get_value(
		"Production Card", production_card,
		["sales_order", "sales_contract", "customer", "style_item", "company", "status", "docstatus", "line"], as_dict=True,
	) or frappe._dict()


def require_open_card(production_card):
	card = card_context(production_card)
	if not card or card.docstatus != 1 or card.status in ("Superseded", "Cancelled", "Closed"):
		frappe.throw(_("Production card {0} must be issued and open.").format(production_card))
	return card


def settings_value(field, default=None):
	v = frappe.db.get_single_value("Apparel Settings", field)
	return default if v in (None, "") else v


def stamp_card(card, code, date, source_doctype, source_name, colours=None, partial=False):
	"""Stamp a T&A milestone for every colour of the card's order. Never raises: a T&A fault must not stop shipping."""
	try:
		from arinox_apparel.tna.events import stamp

		c = card_context(card)
		colours = colours or sorted({r.colour for r in frappe.get_all("Production Card Line", {"parent": card}, ["colour"])})
		for colour in colours:
			stamp(c.sales_order, c.style_item, colour, code, date, source_doctype, source_name, partial=partial)
	except Exception:
		frappe.log_error(title=f"T&A stamp {code} failed", message=frappe.get_traceback())


def unstamp_doc(source_doctype, source_name):
	try:
		from arinox_apparel.tna.events import unstamp

		unstamp(source_doctype, source_name)
	except Exception:
		frappe.log_error(title="T&A unstamp failed", message=frappe.get_traceback())
