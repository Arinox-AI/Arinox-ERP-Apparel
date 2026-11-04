// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Price Negotiation", {
	setup(frm) {
		const q = () => ({ filters: { customer: frm.doc.customer, docstatus: 1, currency: frm.doc.currency } });
		frm.set_query("cost_sheet", "rounds", q);
		frm.set_query("cost_sheet", "styles", q);
		frm.set_query("opportunity", () => ({ filters: { party_name: frm.doc.customer } }));
	},
	refresh(frm) {
		if (!frm.is_new() && !["Lost"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Quotation"), () =>
				frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation.make_quotation", frm })
			, __("Create"));
		}
		frm.fields_dict.rounds.grid.get_field("cost_sheet").get_query = () =>
			({ filters: { customer: frm.doc.customer, docstatus: 1 } });
	},
});

frappe.ui.form.on("Price Negotiation Round", {
	rounds_add(frm, cdt, cdn) {
		const prev = (frm.doc.rounds || []).filter((r) => r.name !== cdn).slice(-1)[0];
		if (prev) frappe.model.set_value(cdt, cdn, "cost_sheet", prev.cost_sheet);
	},
	price(frm, cdt, cdn) {
		const r = locals[cdt][cdn];
		if (!r.cost_sheet || !r.price) return;
		frappe.call({
			method: "arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet.get_margin_at_price",
			args: { cost_sheet: r.cost_sheet, price: r.price },
		}).then((res) => {
			frappe.model.set_value(cdt, cdn, "margin_pct", res.message.margin_pct);
			frappe.model.set_value(cdt, cdn, "below_floor", res.message.below_floor ? 1 : 0);
			if (res.message.below_floor) frappe.show_alert({ message: __("{0}% is below the {1}% floor", [res.message.margin_pct, res.message.floor]), indicator: "red" });
		});
	},
});
