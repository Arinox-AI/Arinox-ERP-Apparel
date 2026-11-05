// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Contract Trail"] = {
	filters: [{ fieldname: "contract", label: __("Contract"), fieldtype: "Link", options: "Sales Contract", reqd: 1 }],
};
