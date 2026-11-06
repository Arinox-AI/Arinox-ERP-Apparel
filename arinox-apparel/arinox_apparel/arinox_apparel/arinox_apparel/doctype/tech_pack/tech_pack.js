// Copyright (c) 2026, Arinox AI and contributors
// Picking an Inquiry (Opportunity) fills the customer, product type, season and source reference from it.
frappe.ui.form.on("Tech Pack", {
	opportunity(frm) {
		if (!frm.doc.opportunity) return;
		frappe.db
			.get_value("Opportunity", frm.doc.opportunity, [
				"opportunity_from", "party_name", "apparel_product_type", "apparel_season", "apparel_source_email",
			])
			.then((r) => {
				const o = r && r.message;
				if (!o) return;
				if (o.opportunity_from === "Customer" && o.party_name) frm.set_value("customer", o.party_name);
				if (o.apparel_product_type) frm.set_value("product_type", o.apparel_product_type);
				if (o.apparel_season) frm.set_value("season", o.apparel_season);
				if (o.apparel_source_email) frm.set_value("source_reference", o.apparel_source_email);
			});
	},
});

frappe.ui.form.on("Tech Pack", {
	setup(frm) {
		frm.set_query("opportunity", () => ({ filters: { opportunity_from: "Customer", party_name: frm.doc.customer } }));
		frm.set_query("style_item", () => ({ filters: { has_variants: 1 } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frm.doc.style_item && frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Create Style Item"), () =>
				frappe.call({
					method: "arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack.create_style_item",
					args: { tech_pack: frm.doc.name },
					freeze: true,
					callback: (r) => { frappe.show_alert({ message: __("Style item {0} created", [r.message]), indicator: "green" }); frm.reload_doc(); },
				})
			);
		}
		if (frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Cost Sheet"), () =>
				frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack.make_cost_sheet", frm })
			, __("Create"));
		}
	},
});
