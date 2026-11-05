// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Import Roll List"), () => import_rolls(frm), __("Tools"));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Fabric Inspection"), () => inspect(frm, "Fabric"), __("Inspect"));
			frm.add_custom_button(__("Trim Inspection"), () => inspect(frm, "Trim"), __("Inspect"));
		}
		if (frm.doc.apparel_penalty_pct) {
			frm.dashboard.add_indicator(__("Late by {0} days: {1}% penalty ({2})", [frm.doc.apparel_delay_days, frm.doc.apparel_penalty_pct,
				format_currency(frm.doc.apparel_penalty_amount, frm.doc.currency)]), "red");
		}
		if (frm.doc.apparel_qty_band_note) frm.dashboard.add_comment(frm.doc.apparel_qty_band_note.replace(/\n/g, "<br>"), "orange", true);
	},
});

function import_rolls(frm) {
	const rows = (frm.doc.items || []).filter((r) => r.name && !r.__islocal);
	if (!rows.length) return frappe.msgprint(__("Save the receipt first."));
	const d = new frappe.ui.Dialog({
		title: __("Import Roll List"),
		fields: [
			{ fieldname: "row", fieldtype: "Select", label: __("Item Row"), reqd: 1, options: rows.map((r) => `${r.idx}: ${r.item_code}`).join("\n"), default: `${rows[0].idx}: ${rows[0].item_code}` },
			{ fieldname: "uom", fieldtype: "Select", label: __("Length Unit in the List"), options: "Meter\nYard\nKg", default: "Meter" },
			{ fieldname: "rolls", fieldtype: "Small Text", label: __("Rolls: roll no, dye lot, length[, width cm] — one per line"), reqd: 1 },
			{ fieldname: "update_row_qty", fieldtype: "Check", label: __("Set the row quantity to the roll total") },
		],
		primary_action_label: __("Import"),
		primary_action(v) {
			const row = rows.find((r) => `${r.idx}: ${r.item_code}` === v.row);
			frappe.call({
				method: "arinox_apparel.materials.rolls.import_roll_list",
				args: { pr_name: frm.doc.name, row_name: row.name, rolls: v.rolls, length_uom: v.uom, update_row_qty: v.update_row_qty ? 1 : 0 },
			}).then((r) => { d.hide(); frappe.show_alert(__("{0} rolls, {1} m", [r.message.rolls, r.message.total])); frm.reload_doc(); });
		},
	});
	d.show();
}

function inspect(frm, kind) {
	const rows = (frm.doc.items || []).map((r) => `${r.idx}: ${r.item_code}`);
	frappe.prompt({ fieldname: "row", fieldtype: "Select", label: __("Item Row"), options: rows.join("\n"), reqd: 1, default: rows[0] }, (v) => {
		const row = frm.doc.items.find((r) => `${r.idx}: ${r.item_code}` === v.row);
		const dt = kind === "Fabric" ? "fabric_inspection" : "trim_inspection";
		frappe.call({ method: `arinox_apparel.arinox_apparel.doctype.${dt}.${dt}.make_inspection`, args: { purchase_receipt: frm.doc.name, purchase_receipt_item: row.name } })
			.then((r) => { frappe.model.sync(r.message); frappe.set_route("Form", r.message.doctype, r.message.name); });
	}, __("Which row?"), __("Start Inspection"));
}
