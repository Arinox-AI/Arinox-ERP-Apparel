// Apparel: show which contract this order carries, and create the planning documents.
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.apparel_sales_contract) {
			frm.dashboard.add_indicator(__("Contract {0}", [frm.doc.apparel_sales_contract]), "blue");
		}
		if (frm.doc.docstatus === 1) {
			const go = (doctype) => () => frappe.new_doc(doctype, { sales_order: frm.doc.name });
			frm.add_custom_button(__("Factory Allocation"), () =>
				frappe.db.exists("Factory Allocation", "FA-" + frm.doc.name).then((e) =>
					e ? frappe.set_route("Form", "Factory Allocation", "FA-" + frm.doc.name) : go("Factory Allocation")()), __("Plan and Approve"));
			frm.add_custom_button(__("Sample Approval"), go("Sample Approval"), __("Plan and Approve"));
			frm.add_custom_button(__("PP Meeting"), go("PP Meeting"), __("Plan and Approve"));
		}
	},
});
