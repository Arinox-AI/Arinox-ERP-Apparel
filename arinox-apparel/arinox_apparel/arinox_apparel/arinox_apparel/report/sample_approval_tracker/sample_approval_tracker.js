frappe.query_reports["Sample Approval Tracker"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "only_blocked", label: __("Only orders blocked from bulk"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const colours = { Approved: "green", "Approved with Comments": "green", Missing: "red", Rejected: "red", Resubmit: "orange",
			Open: "orange", Submitted: "blue", Blocked: "red", Open_: "green", "Not Required": "gray" };
		const text = frappe.utils.html2text(value);
		if (column.fieldname === "gate") return `<span style="color:var(--${text === "Open" ? "green" : "red"}-600);font-weight:600">${value}</span>`;
		if (column.fieldname.startsWith("t_") && colours[text]) return `<span style="color:var(--${colours[text]}-600)">${value}</span>`;
		if (column.fieldname === "overdue" && data && data.overdue) return `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		return value;
	},
};
