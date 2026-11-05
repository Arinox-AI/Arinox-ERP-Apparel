// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Fabric Requisition", {
	setup(frm) {
		frm.set_query("fabric_item", "items", () => ({ filters: { disabled: 0, has_variants: 0 } }));
		frm.set_query("style_item", "items", () => ({ filters: { has_variants: 1 } }));
		frm.set_query("sales_order", "items", () => ({ filters: { customer: frm.doc.customer, company: frm.doc.company, docstatus: 1 } }));
		frm.set_query("stock_warehouse", "items", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Lines from Sales Orders"), () => pick_orders(frm), __("Tools"));
			frm.add_custom_button(__("Create Missing Fabric Items"), () =>
				frm.call({ doc: frm.doc, method: "create_fabric_items" }).then(() => frm.refresh_fields()), __("Tools"));
		}
		if (frm.doc.docstatus === 1 && !["Superseded", "Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Purchase Orders"), () =>
				frappe.call({ method: "arinox_apparel.overrides.purchase_order.make_purchase_orders", args: { requisition_type: "FR", name: frm.doc.name } })
					.then((r) => frappe.msgprint(r.message && r.message.length ? __("Draft purchase orders made: {0}", [r.message.join(", ")]) : __("Nothing left to order.")))
				, __("Create"));
			frm.add_custom_button(__("Revise"), () =>
				frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.fabric_requisition.fabric_requisition.revise_fabric_requisition", frm }));
		}
		if (frm.doc.status === "Superseded") frm.dashboard.add_indicator(__("Superseded by a later revision"), "gray");
		if (frm.doc.red_flags) frm.dashboard.add_indicator(__("{0} red flag(s)", [frm.doc.red_flags.split("\n").length]), "red");
	},
});

function pick_orders(frm) {
	if (!frm.doc.customer || !frm.doc.company) return frappe.msgprint(__("Choose the company and buyer first."));
	const d = new frappe.ui.Dialog({
		title: __("Sales Orders"),
		fields: [{ fieldname: "sales_orders", fieldtype: "MultiSelectList", label: __("Sales Orders"), reqd: 1,
			get_data: (txt) => frappe.db.get_link_options("Sales Order", txt, { customer: frm.doc.customer, company: frm.doc.company, docstatus: 1 }) }],
		primary_action_label: __("Get Lines"),
		primary_action(v) {
			frm.call({ doc: frm.doc, method: "get_lines_from_sales_orders", args: { sales_orders: v.sales_orders.map((x) => x.value || x) } })
				.then((r) => { frappe.show_alert(__("{0} line(s) added", [r.message || 0])); frm.refresh_fields(); });
			d.hide();
		},
	});
	d.show();
}
