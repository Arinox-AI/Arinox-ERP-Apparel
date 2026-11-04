frappe.query_reports["Negotiation History"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "price_negotiation", label: __("Negotiation"), fieldtype: "Link", options: "Price Negotiation" },
		{ fieldname: "cost_sheet", label: __("Cost Sheet"), fieldtype: "Link", options: "Cost Sheet" },
		{ fieldname: "style_no", label: __("Style"), fieldtype: "Data" },
		{ fieldname: "direction", label: __("Who / What"), fieldtype: "Select",
		  options: ["", "Buyer Target", "Our Offer", "Buyer Counter", "Our Counter", "Agreed", "Dropped"] },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "direction" && data) {
			const c = data.direction.startsWith("Buyer") ? "var(--blue-600)" : data.direction === "Agreed" ? "var(--green-600)" : "inherit";
			value = `<span style="color:${c};font-weight:500">${value}</span>`;
		}
		return value;
	},
};
