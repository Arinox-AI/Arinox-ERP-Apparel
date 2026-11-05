frappe.query_reports["Material Status"] = {
	filters: [
		{ fieldname: "customer", label: __("Buyer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "material_type", label: __("Material"), fieldtype: "Select", options: "\nFabric\nTrim" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nRequested\nOn Hold\nOrdered\nIn Transit\nIn House - QC Pending\nAccepted\nShort\nRejected" },
		{ fieldname: "only_late", label: __("Late only"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data) {
			const c = { Accepted: "green", "In House - QC Pending": "blue", "In Transit": "blue", Ordered: "blue", Requested: "gray", "On Hold": "orange", Short: "orange", Rejected: "red" }[data.status] || "gray";
			return `<span style="color:var(--${c}-600);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "days_late" && data && data.days_late) return `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		return value;
	},
};
