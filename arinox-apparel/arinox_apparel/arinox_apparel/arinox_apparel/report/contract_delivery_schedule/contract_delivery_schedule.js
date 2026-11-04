frappe.query_reports["Contract Delivery Schedule"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "from_date", label: __("Ex-Factory From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Ex-Factory To"), fieldtype: "Date" },
		{ fieldname: "include_ordered", label: __("Include contracts already ordered"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_to_ex_factory" && data && data.days_to_ex_factory !== null && data.days_to_ex_factory < 15)
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		return value;
	},
};
