// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Fabric Consumption"] = {
	filters: [
		{ fieldname: "production_card", label: __("Production Card"), fieldtype: "Link", options: "Production Card" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
	],
};
