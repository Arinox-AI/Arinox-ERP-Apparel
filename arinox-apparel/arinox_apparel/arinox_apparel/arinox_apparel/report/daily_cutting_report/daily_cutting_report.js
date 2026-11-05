// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Daily Cutting Report"] = {
	filters: [
		{ fieldname: "production_card", label: __("Production Card"), fieldtype: "Link", options: "Production Card" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
};
