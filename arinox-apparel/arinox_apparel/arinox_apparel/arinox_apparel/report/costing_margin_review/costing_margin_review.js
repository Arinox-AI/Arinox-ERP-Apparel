frappe.query_reports["Costing Margin Review"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "product_type", label: __("Product Type"), fieldtype: "Link", options: "Product Type" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "approval_status", label: __("Approval"), fieldtype: "Select", options: ["", "Not Required", "Pending", "Approved", "Rejected"] },
		{ fieldname: "below_floor", label: __("Below Floor Only"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "margin_pct" && data && data.below_floor) value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		return value;
	},
};
