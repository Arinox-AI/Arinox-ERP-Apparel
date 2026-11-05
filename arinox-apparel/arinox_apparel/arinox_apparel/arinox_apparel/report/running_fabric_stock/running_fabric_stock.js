frappe.query_reports["Running Fabric Stock"] = {
	filters: [
		{ fieldname: "customer", label: __("Buyer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
	],
};
