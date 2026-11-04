// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Sales Contract", {
	setup(frm) {
		frm.set_query("quotation", () => ({ filters: { party_name: frm.doc.customer, docstatus: 1 } }));
		frm.set_query("contract_template", () => ({ filters: { enabled: 1, customer: ["in", [frm.doc.customer, ""]] } }));
		frm.set_query("style_item", "items", () => ({ filters: { has_variants: 1 } }));
		frm.set_query("cost_sheet", "items", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fill Size Rows from Tech Packs"), () => fill_sizes(frm), __("Tools"));
		}
		if (frm.doc.docstatus === 1 && !frm.doc.sales_order) {
			frm.add_custom_button(__("Sales Order"), () =>
				frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract.make_sales_order", frm })
			, __("Create"));
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}
		if (frm.doc.sku_count) {
			frm.dashboard.add_indicator(__("{0} SKUs · {1} pcs", [frm.doc.sku_count, frm.doc.total_qty]), "blue");
		}
	},
	contract_template(frm) {
		if (frm.doc.contract_template) frm.call("apply_template").then(() => frm.refresh_fields());
	},
});

frappe.ui.form.on("Sales Contract Item", {
	qty: (frm, cdt, cdn) => line_amount(cdt, cdn),
	rate: (frm, cdt, cdn) => line_amount(cdt, cdn),
});

function line_amount(cdt, cdn) {
	const r = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", cint(r.qty) * flt(r.rate));
}

function fill_sizes(frm) {
	const have = new Set((frm.doc.sizes || []).map((s) => [s.style_item, s.colour, s.size].join("|")));
	const tps = [...new Set((frm.doc.items || []).map((i) => i.tech_pack).filter(Boolean))];
	if (!tps.length) { frappe.msgprint(__("No line has a Tech Pack (through its Cost Sheet).")); return; }
	Promise.all(tps.map((tp) => frappe.db.get_doc("Tech Pack", tp))).then((docs) => {
		const sizes_of = {};
		docs.forEach((d) => (sizes_of[d.name] = (d.sizes || []).map((s) => s.size)));
		let added = 0;
		frm.doc.items.forEach((it) => (sizes_of[it.tech_pack] || []).forEach((size) => {
			const key = [it.style_item, it.colour, size].join("|");
			if (have.has(key)) return;
			frm.add_child("sizes", { style_item: it.style_item, colour: it.colour, size, qty: 0 });
			added++;
		}));
		frm.refresh_field("sizes");
		frappe.show_alert(__("{0} size rows added. Enter quantities per size.", [added]));
	});
}
