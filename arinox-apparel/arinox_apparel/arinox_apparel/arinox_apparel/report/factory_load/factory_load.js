frappe.query_reports["Factory Load"] = {
	filters: [
		{ fieldname: "factory", label: __("Factory"), fieldtype: "Link", options: "Plant Floor" },
		{ fieldname: "from_date", label: __("PCD From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("PCD To"), fieldtype: "Date" },
	],
};
