// Copyright (c) 2026, Arinox AI and contributors
const PC = "arinox_apparel.arinox_apparel.doctype.production_card.production_card";

frappe.ui.form.on("Production Card", {
	setup(frm) {
		frm.set_query("sales_order", () => ({ filters: { docstatus: 1, ...(frm.doc.customer ? { customer: frm.doc.customer } : {}), ...(frm.doc.company ? { company: frm.doc.company } : {}) } }));
		frm.set_query("style_item", () => ({ filters: { has_variants: 1, name: ["in", frm.__styles || []] } }));
		frm.set_query("fabric_item", "fabrics", () => ({ filters: { disabled: 0, has_variants: 0 } }));
		frm.set_query("supplier", "processes", () => ({ filters: { disabled: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Lines from Sales Order"), () => get_lines(frm), __("Tools"));
		}
		if (frm.doc.docstatus === 1 && !["Superseded", "Cancelled", "Closed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Revise"), () =>
				frappe.call({ method: `${PC}.revise_production_card`, args: { source_name: frm.doc.name } }).then((r) => {
					const doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				}));
			frm.add_custom_button(__("Production Summary"), () => show_summary(frm));
			frm.add_custom_button(__("Issue Fabric to Cutting"), () => issue_fabric(frm), __("Stock"));
		}
		if (frm.doc.status === "Superseded") frm.dashboard.add_indicator(__("Superseded by a later revision"), "gray");
		if (frm.doc.pilot_required && !frm.doc.pilot_waiver) frm.dashboard.add_indicator(__("Pilot run required before bulk cutting"), "orange");
		if (frm.doc.red_flags) frm.dashboard.add_indicator(__("{0} red flag(s)", [frm.doc.red_flags.split("\n").length]), "red");
	},
	sales_order(frm) {
		if (!frm.doc.sales_order) return;
		frappe.db.get_value("Sales Order", frm.doc.sales_order, ["customer", "company"]).then((r) => {
			if (r.message) { frm.set_value("customer", r.message.customer); frm.set_value("company", r.message.company); }
		});
		frappe.call({ method: `${PC}.get_order_styles`, args: { sales_order: frm.doc.sales_order } }).then((r) => {
			frm.__styles = r.message || [];
			if (frm.__styles.length === 1) frm.set_value("style_item", frm.__styles[0]);
		});
	},
	style_item(frm) {
		if (frm.doc.style_item && frm.doc.sales_order && !(frm.doc.lines || []).length) get_lines(frm);
	},
});

function get_lines(frm) {
	if (!frm.doc.sales_order || !frm.doc.style_item) return frappe.msgprint(__("Choose the Sales Order and the style first."));
	frappe.call({ method: `${PC}.get_card_lines`, args: { sales_order: frm.doc.sales_order, style_item: frm.doc.style_item } }).then((r) => {
		const d = r.message;
		frm.clear_table("lines");
		(d.lines || []).forEach((l) => frm.add_child("lines", { colour: l.colour, size: l.size, order_qty: l.order_qty }));
		if (d.ex_factory_date && !frm.doc.ex_factory_date) frm.set_value("ex_factory_date", d.ex_factory_date);
		frm.refresh_field("lines");
		frappe.show_alert({ message: __("{0} colour x size rows loaded. Save to calculate the cutting quantities.", [(d.lines || []).length]), indicator: "green" });
	});
}

function show_summary(frm) {
	frm.call({ doc: frm.doc, method: "get_summary" }).then((r) => {
		const rows = (r.message || {}).rows || [];
		const cols = ["order_qty", "planned_cut_qty", "CUT", "CUT_REJECT", "SEW_IN", "SEW_OUT", "SEW_REJECT", "SC_OUT", "SC_BACK_GOOD", "FIN_IN", "FIN_A", "FIN_B", "FIN_REJECT", "PACKED", "SHIPPED"];
		const head = `<tr><th>${__("Colour")}</th><th>${__("Size")}</th>${cols.map((c) => `<th class="text-right">${c.replace(/_/g, " ")}</th>`).join("")}</tr>`;
		const body = rows.map((x) => `<tr><td>${frappe.utils.escape_html(x.colour)}</td><td>${frappe.utils.escape_html(x.size)}</td>${cols.map((c) => `<td class="text-right">${x[c] || 0}</td>`).join("")}</tr>`).join("");
		frappe.msgprint({ title: __("Production Summary"), wide: true, message: `<div style="overflow:auto"><table class="table table-bordered table-sm">${head}${body}</table></div>` });
	});
}

function issue_fabric(frm) {
	frappe.call({ method: "arinox_apparel.production.cutting.get_issuable_rolls", args: { card: frm.doc.name } }).then((r) => {
		const rolls = r.message || [];
		if (!rolls.length) return frappe.msgprint(__("No accepted rolls of this card's fabrics are in the fabric store."));
		const d = new frappe.ui.Dialog({
			title: __("Issue Fabric to Cutting"), size: "large",
			fields: [{ fieldname: "rolls", fieldtype: "Table", label: __("Rolls"), cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: false, data: rolls.map((x) => ({ batch: x.batch, roll_no: x.roll_no, colour: x.colour, shade: x.shade, available_m: x.available_m, qty: x.available_m, issue: 0 })),
				fields: [
					{ fieldname: "issue", fieldtype: "Check", label: __("Issue"), in_list_view: 1, columns: 1 },
					{ fieldname: "roll_no", fieldtype: "Data", label: __("Roll"), in_list_view: 1, read_only: 1, columns: 2 },
					{ fieldname: "colour", fieldtype: "Data", label: __("Colour"), in_list_view: 1, read_only: 1, columns: 2 },
					{ fieldname: "shade", fieldtype: "Data", label: __("Shade"), in_list_view: 1, read_only: 1, columns: 1 },
					{ fieldname: "available_m", fieldtype: "Float", label: __("Available (m)"), in_list_view: 1, read_only: 1, columns: 2 },
					{ fieldname: "qty", fieldtype: "Float", label: __("Issue (m)"), in_list_view: 1, columns: 2 },
					{ fieldname: "batch", fieldtype: "Data", hidden: 1 },
				] }],
			primary_action_label: __("Issue"),
			primary_action(v) {
				const chosen = (v.rolls || []).filter((x) => x.issue && x.qty > 0).map((x) => ({ batch_no: x.batch, qty: x.qty }));
				if (!chosen.length) return frappe.msgprint(__("Tick the rolls to issue."));
				frappe.call({ method: "arinox_apparel.production.cutting.issue_fabric", args: { card: frm.doc.name, rolls: chosen }, freeze: true })
					.then((res) => { d.hide(); frappe.show_alert({ message: __("Issued on {0}", [res.message]), indicator: "green" }); frm.reload_doc(); });
			},
		});
		d.show();
	});
}
