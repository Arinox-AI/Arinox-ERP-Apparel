// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Sample Approval", {
	setup(frm) {
		frm.set_query("style_item", () => ({ filters: { has_variants: 1 } }));
		frm.set_query("sales_order", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("tech_pack", () => ({ filters: { style_item: frm.doc.style_item || undefined, docstatus: 1 } }));
	},
	refresh(frm) {
		const colours = { Approved: "green", "Approved with Comments": "green", "Not Required": "gray", Rejected: "red", Resubmit: "orange", Submitted: "blue", Open: "orange" };
		if (frm.doc.status) frm.dashboard.add_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");
		if (frm.doc.due_date && !["Approved", "Approved with Comments", "Not Required"].includes(frm.doc.status) && frappe.datetime.get_diff(frappe.datetime.nowdate(), frm.doc.due_date) > 0) {
			frm.dashboard.add_indicator(__("Overdue since {0}", [frappe.datetime.str_to_user(frm.doc.due_date)]), "red");
		}
		if (frm.doc.late_chargeback) frm.dashboard.add_indicator(__("Chargeback exposure {0}", [format_currency(frm.doc.late_chargeback)]), "red");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Load Spec from Tech Pack"), () => frm.call("load_spec_from_tech_pack").then(() => frm.refresh_fields()), __("Tools"));
		if (frm.doc.sample_type === "Garment Test (GPT)") {
			frm.add_custom_button(__("Load Standard GPT Tests"), () => frm.call("load_standard_tests").then(() => frm.refresh_fields()), __("Tools"));
		}
	},
	sales_order(frm) {
		if (!frm.doc.sales_order) return;
		frappe.db.get_value("Sales Order", frm.doc.sales_order, "customer").then((r) => frm.set_value("customer", r.message.customer));
	},
});
