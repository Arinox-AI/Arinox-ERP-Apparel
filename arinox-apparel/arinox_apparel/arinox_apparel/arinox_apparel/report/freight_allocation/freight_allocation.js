// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Freight Allocation"] = {
	filters: [{ fieldname: "shipment", label: __("Shipment"), fieldtype: "Link", options: "Shipment" }],
};
