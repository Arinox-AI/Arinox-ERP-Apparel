// Apparel: a submitted Quotation becomes a Sales Contract.
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.quotation_to !== "Customer") return;
		if (!(frm.doc.items || []).some((i) => i.apparel_cost_sheet)) return;
		frm.add_custom_button(__("Sales Contract"), () =>
			frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract.make_sales_contract", frm })
		, __("Create"));
	},
});
