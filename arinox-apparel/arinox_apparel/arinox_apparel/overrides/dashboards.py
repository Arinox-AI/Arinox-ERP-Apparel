"""Show the apparel documents in the Connections tab of ERPNext forms."""

from frappe import _


def _add(data, label, items, fieldnames=None):
	data.setdefault("transactions", []).append({"label": _(label), "items": items})
	if fieldnames:
		data.setdefault("non_standard_fieldnames", {}).update(fieldnames)
	return data


def opportunity(data):
	return _add(data, "Apparel", ["Tech Pack", "Cost Sheet", "Price Negotiation", "Sales Contract"])


def customer(data):
	_add(data, "Apparel Pre-Sales", ["Tech Pack", "Cost Sheet", "Price Negotiation"])
	return _add(data, "Apparel Contracts", ["Sales Contract", "Sales Contract Template", "Costing Parameter"])


def quotation(data):
	return _add(
		data,
		"Apparel",
		["Sales Contract", "Price Negotiation"],
		{"Sales Contract": "quotation", "Price Negotiation": "quotation"},
	)


def sales_order(data):
	data.setdefault("internal_links", {})["Sales Contract"] = "apparel_sales_contract"
	return _add(data, "Apparel", ["Sales Contract", "Factory Allocation", "Sample Approval", "PP Meeting"])
