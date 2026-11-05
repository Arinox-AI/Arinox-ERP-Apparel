// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Sewing WIP"] = {
	filters: [
		{ fieldname: "line", label: __("Line"), fieldtype: "Link", options: "Workstation" },
		{ fieldname: "production_card", label: __("Production Card"), fieldtype: "Link", options: "Production Card" },
	],
};
