frappe.query_reports["WIP Report"] = {
	filters: [
		{ fieldname: "customer", label: __("Buyer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "merchant", label: __("Merchant"), fieldtype: "Link", options: "User" },
		{ fieldname: "factory", label: __("Factory"), fieldtype: "Link", options: "Plant Floor" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "ex_factory_from", label: __("Ex-Factory From"), fieldtype: "Date" },
		{ fieldname: "ex_factory_to", label: __("Ex-Factory To"), fieldtype: "Date" },
		{ fieldname: "late_only", label: __("Late or at risk only"), fieldtype: "Check" },
	],
};
