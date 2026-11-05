// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Line Loading"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "line", label: __("Line"), fieldtype: "Link", options: "Workstation" },
		{ fieldname: "production_card", label: __("Production Card"), fieldtype: "Link", options: "Production Card" },
	],
};
