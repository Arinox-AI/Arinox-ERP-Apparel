from frappe import _


def get_data():
	return {
		"fieldname": "apparel_sales_contract",
		"internal_links": {"Quotation": "quotation", "Price Negotiation": "price_negotiation"},
		"transactions": [
			{"label": _("Order"), "items": ["Sales Order"]},
			{"label": _("Came From"), "items": ["Quotation", "Price Negotiation"]},
		],
	}
