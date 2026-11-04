// Copyright (c) 2026, Arinox AI and contributors
// Totals are computed on the server at every save; the client only previews row amounts.
const CS = "arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet";

frappe.ui.form.on("Cost Sheet", {
	setup(frm) {
		frm.set_query("tech_pack", () => ({ filters: { customer: frm.doc.customer, docstatus: ["<", 2] } }));
		frm.set_query("reference_cost_sheet", () => ({ filters: { customer: frm.doc.customer, docstatus: 1 } }));
		frm.set_query("costing_parameter", () => ({ filters: { enabled: 1, currency: frm.doc.currency } }));
	},
	refresh(frm) {
		show_margin_banner(frm);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Copy from Previous Costing"), () => copy_previous(frm), __("Tools"));
			frm.add_custom_button(__("Sign Off"), () => sign_off(frm), __("Tools"));
			frm.add_custom_button(__("Reload Rates from Parameter"), () =>
				frm.call("set_charges_from_parameter").then(() => { frm.refresh_field("charges"); frm.dirty(); })
			, __("Tools"));
			if (!frm.is_new() && frm.doc.below_floor && frappe.user.has_role("Apparel Costing Manager")) {
				frm.add_custom_button(__("Approve Margin"), () => approval(frm, "approve"), __("Approval"));
				frm.add_custom_button(__("Reject"), () => approval(frm, "reject"), __("Approval"));
			}
		}
		if (!frm.is_new()) frm.add_custom_button(__("Price What-If"), () => what_if(frm), __("Tools"));
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Price Negotiation"), () =>
				frappe.call({ method: CS + ".make_price_negotiation", args: { source_name: frm.doc.name }, freeze: true })
					.then((r) => frappe.set_route("Form", "Price Negotiation", r.message))
			, __("Create"));
			frm.add_custom_button(__("Quotation"), () =>
				frappe.model.open_mapped_doc({ method: CS + ".make_quotation", frm })
			, __("Create"));
		}
	},
});

frappe.ui.form.on("Cost Sheet Material", {
	consumption: row_amount, wastage_pct: row_amount, rate: row_amount, conversion_factor: row_amount,
	exchange_rate: row_amount, per_carton: row_amount, price_currency: row_amount,
});

// Preview only: the server recalculates every figure on save, including the cost heads.
function row_amount(frm, cdt, cdn) {
	const r = locals[cdt][cdn];
	const consumption = r.per_carton && cint(frm.doc.pcs_per_carton) ? 1 / cint(frm.doc.pcs_per_carton) : flt(r.consumption);
	const fx = r.price_currency && r.price_currency !== frm.doc.currency ? flt(r.exchange_rate) || 1 : 1;
	frappe.model.set_value(cdt, cdn, "amount",
		consumption * (1 + flt(r.wastage_pct) / 100) * (flt(r.conversion_factor) || 1) * flt(r.rate) * fx);
}

function sign_off(frm) {
	const next = (frm.doc.signoffs || []).find((r) => !r.signed_by);
	if (!next) { frappe.msgprint(__("All four steps are signed.")); return; }
	frappe.prompt({ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }, (v) =>
		frappe.call({ method: CS + ".sign_off", args: { name: frm.doc.name, step: next.step, remarks: v.remarks }, freeze: true })
			.then(() => frm.reload_doc())
	, __("Sign off: {0}", [__(next.step)]));
}

function show_margin_banner(frm) {
	if (frm.is_new() || !frm.doc.quoted_price) return;
	const color = frm.doc.below_floor ? (frm.doc.approval_status === "Approved" ? "orange" : "red") : "green";
	frm.dashboard.add_indicator(__("Margin {0}% (floor {1}%)", [flt(frm.doc.margin_pct, 2), flt(frm.doc.margin_floor_pct, 2)]), color);
	frm.dashboard.add_indicator(__("Quoted {0}", [format_currency(frm.doc.quoted_price, frm.doc.currency)]), "blue");
	if (frm.doc.below_floor) frm.dashboard.add_indicator(__("Approval: {0}", [frm.doc.approval_status]), color);
}

function approval(frm, action) {
	frappe.prompt({ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks"), reqd: action === "reject" }, (v) =>
		frappe.call({ method: CS + "." + action, args: { name: frm.doc.name, remarks: v.remarks }, freeze: true })
			.then(() => frm.reload_doc())
	, action === "approve" ? __("Approve margin below floor") : __("Reject costing"));
}

function copy_previous(frm) {
	frappe.prompt({
		fieldname: "source", fieldtype: "Link", options: "Cost Sheet", label: __("Previous Cost Sheet"), reqd: 1,
		get_query: () => ({ filters: { docstatus: 1, customer: frm.doc.customer } }),
	}, (v) => frappe.call({ method: CS + ".get_previous_costing", args: { cost_sheet: v.source } }).then((r) => {
		frm.clear_table("materials"); frm.clear_table("charges");
		r.message.materials.forEach((m) => frm.add_child("materials", m));
		r.message.charges.forEach((c) => frm.add_child("charges", c));
		frm.set_value("reference_cost_sheet", v.source);
		if (r.message.sam && !frm.doc.sam) frm.set_value("sam", r.message.sam);
		frm.refresh_fields();
		frappe.show_alert(__("Copied. Review wastage and rates for this order, then save."));
	}), __("Copy materials and cost heads"));
}

function what_if(frm) {
	frappe.prompt({ fieldname: "price", fieldtype: "Currency", label: __("Price / pc"), reqd: 1, default: frm.doc.quoted_price }, (v) =>
		frappe.call({ method: CS + ".get_margin_at_price", args: { cost_sheet: frm.doc.name, price: v.price } }).then((r) => {
			const m = r.message;
			frappe.msgprint(__("At {0}: cost {1}, margin {2} ({3}%). Floor {4}% — {5}.", [
				format_currency(v.price, frm.doc.currency), format_currency(m.cost, frm.doc.currency),
				format_currency(m.margin, frm.doc.currency), m.margin_pct, m.floor,
				m.below_floor ? __("BELOW floor, needs approval") : __("above floor")]), __("Price What-If"));
		})
	, __("Margin at another price"));
}
