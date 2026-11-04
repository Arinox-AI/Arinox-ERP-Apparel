from frappe import _


def get_data():
	return {
		"fieldname": "price_negotiation",
		"non_standard_fieldnames": {"Quotation": "apparel_price_negotiation"},
		"transactions": [{"label": _("Outcome"), "items": ["Quotation", "Sales Contract"]}],
	}
