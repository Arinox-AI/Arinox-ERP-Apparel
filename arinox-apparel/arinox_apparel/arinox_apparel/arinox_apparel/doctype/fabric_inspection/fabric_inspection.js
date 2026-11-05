// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Fabric Inspection", {
	setup(frm) {
		frm.set_query("batch", "rolls", () => ({ filters: { item: frm.doc.fabric_item } }));
		frm.set_query("defect_code", "defects", () => ({}));
	},
	refresh(frm) {
		const colours = { Pass: "green", Fail: "red", "Re-inspect 100%": "orange", Hold: "orange" };
		if (frm.doc.lot_result) frm.dashboard.add_indicator(__("Lot: {0}", [frm.doc.lot_result]), colours[frm.doc.lot_result] || "gray");
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Load Rolls from Receipt"), () => frm.call({ doc: frm.doc, method: "load_rolls" }).then(() => frm.refresh_fields()), __("Tools"));
		}
		if (frm.doc.docstatus === 1 && frm.doc.rejected_m > 0) {
			frm.add_custom_button(__("Purchase Return of Rejected Rolls"), () =>
				frappe.call({ method: "arinox_apparel.arinox_apparel.doctype.fabric_inspection.fabric_inspection.make_purchase_return", args: { inspection: frm.doc.name } })
					.then((r) => { frappe.model.sync(r.message); frappe.set_route("Form", r.message.doctype, r.message.name); }), __("Create"));
		}
		if (frm.doc.claim_deadline) frm.dashboard.add_indicator(__("Claim by {0}", [frappe.datetime.str_to_user(frm.doc.claim_deadline)]), "blue");
	},
});
