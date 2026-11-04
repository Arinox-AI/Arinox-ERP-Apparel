frappe.query_reports["Inquiry to Contract Tracker"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "stage", label: __("Stage"), fieldtype: "Select",
		  options: ["", "Inquiry", "Tech Pack", "Costing", "Negotiating", "Quoted", "Contract", "Ordered", "Lost"] },
	],
};
