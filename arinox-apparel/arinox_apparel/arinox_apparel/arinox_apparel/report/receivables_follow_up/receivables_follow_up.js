// Copyright (c) 2026, Arinox AI and contributors
frappe.query_reports["Receivables Follow-up"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "contract", label: __("Contract"), fieldtype: "Link", options: "Sales Contract" },
		{ fieldname: "as_on", label: __("As on"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "show_paid", label: __("Include paid"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data) {
			const colour = { Overdue: "red", Disputed: "orange", Promised: "blue", "Due Soon": "orange", Paid: "green" }[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
