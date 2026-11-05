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
			const req = (doctype) => () => frappe.new_doc(doctype, { company: frm.doc.company, customer: frm.doc.customer });
			frm.add_custom_button(__("Fabric Requisition"), req("Fabric Requisition"), __("Materials"));
			frm.add_custom_button(__("Trim Requisition"), req("Trim Requisition"), __("Materials"));
			frm.add_custom_button(__("Material Status"), () => { frappe.route_options = { sales_order: frm.doc.name }; frappe.set_route("query-report", "Material Status"); }, __("Materials"));
			frm.add_custom_button(__("Make T&A"), () =>
				frappe.call({ method: "arinox_apparel.tna.planner.make_order_tnas", args: { sales_order: frm.doc.name } })
					.then((r) => { frappe.show_alert(r.message && r.message.length ? __("{0} T&A plan(s) made", [r.message.length]) : __("T&A already exists")); frm.reload_doc(); }), __("Time and Action"));
			frm.add_custom_button(__("WIP Board"), () => { frappe.route_options = { sales_order: frm.doc.name }; frappe.set_route("apparel-wip-board"); }, __("Time and Action"));
		}
	},
});
