// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("PP Meeting", {
	setup(frm) {
		frm.set_query("style_item", () => ({ filters: { has_variants: 1 } }));
		frm.set_query("sales_order", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("pp_sample", () => ({ filters: { style_item: frm.doc.style_item, sample_type: "PP" } }));
		frm.set_query("size_set_sample", () => ({ filters: { style_item: frm.doc.style_item, sample_type: "Size Set" } }));
		frm.set_query("line", () => ({ filters: frm.doc.factory ? { plant_floor: frm.doc.factory } : {} }));
	},
	refresh(frm) {
		if (frm.doc.status && frm.doc.docstatus === 1) {
			frm.dashboard.add_indicator(__(frm.doc.status), frm.doc.status === "Closed" ? "green" : "orange");
		}
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Get Buyer Comments"), () =>
				frm.call("get_buyer_comments").then((r) => { frm.refresh_fields(); frappe.show_alert(__("{0} comment(s) added", [r.message])); }), __("Tools"));
			frm.add_custom_button(__("Add Required Departments"), () => frm.call("add_standard_participants").then(() => frm.refresh_fields()), __("Tools"));
		}
	},
});
