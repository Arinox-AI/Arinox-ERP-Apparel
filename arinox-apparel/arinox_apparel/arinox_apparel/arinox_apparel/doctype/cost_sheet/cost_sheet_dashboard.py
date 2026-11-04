from frappe import _


def get_data():
	return {
		"fieldname": "cost_sheet",
		"non_standard_fieldnames": {
			"Quotation": "apparel_cost_sheet",
			"Sales Order": "apparel_cost_sheet",
			"Cost Sheet": "reference_cost_sheet",
		},
		"transactions": [
			{"label": _("Negotiation & Quote"), "items": ["Price Negotiation", "Quotation"]},
			{"label": _("Contract & Order"), "items": ["Sales Contract", "Sales Order"]},
			{"label": _("Reused By"), "items": ["Cost Sheet"]},
		],
	}
