// Apparel: an inquiry becomes a Tech Pack, then a Cost Sheet.
frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.opportunity_from !== "Customer" || ["Lost", "Closed"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Tech Pack"), () =>
			frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack.make_tech_pack", frm })
		, __("Create"));
	},
});
