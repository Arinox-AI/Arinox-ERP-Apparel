from frappe import _


def get_data():
	return {
		"fieldname": "tech_pack",
		"transactions": [{"label": _("Costing & Contract"), "items": ["Cost Sheet", "Sales Contract"]}],
	}
