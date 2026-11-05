// Copyright (c) 2026, Arinox AI and contributors
// Apparel export shipment: choose the packing lists, make the delivery notes, draft and submit the invoices.
frappe.ui.form.on("Shipment", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		const call = (method, args, done) =>
			frappe.call({ method: `arinox_apparel.shipping.${method}`, args, freeze: true, callback: (r) => done && done(r.message) });
		if (frm.doc.docstatus === 0 || frm.doc.apparel_mode) {
			frm.add_custom_button(__("Get Packing Lists"), () => {
				call("shipment.get_available_packing_lists", { customer: frm.doc.delivery_customer }, (rows) => {
					if (!rows || !rows.length) return frappe.msgprint(__("No submitted packing list is waiting for a shipment."));
					const d = new frappe.ui.Dialog({
						title: __("Packing Lists"),
						fields: rows.map((r) => ({
							fieldtype: "Check", fieldname: r.name,
							label: `${r.name} · ${r.buyer_po || ""} · ${r.total_pieces} pcs · ${r.total_cartons} ctns · ${r.inspection_result || __("not inspected")}`,
						})),
						primary_action_label: __("Add"),
						primary_action(v) {
							rows.filter((r) => v[r.name] && !(frm.doc.apparel_packing_lists || []).some((x) => x.packing_list === r.name))
								.forEach((r) => frm.add_child("apparel_packing_lists", { packing_list: r.name }));
							frm.refresh_field("apparel_packing_lists");
							d.hide();
						},
					});
					d.show();
				});
			}, __("Apparel"));
		}
		if ((frm.doc.apparel_packing_lists || []).length) {
			frm.add_custom_button(__("Make Delivery Notes"), () => call("shipment.make_delivery_notes", { shipment: frm.doc.name }, (r) => { frappe.msgprint(__("Created: {0}", [r.join(", ")])); frm.reload_doc(); }), __("Apparel"));
			frm.add_custom_button(__("Prepare Invoices"), () => call("invoicing.prepare_invoices", { shipment: frm.doc.name }, (r) => { frappe.msgprint(__("Drafted: {0}", [(r || []).join(", ") || "-"])); frm.reload_doc(); }), __("Apparel"));
			frm.add_custom_button(__("Submit Invoices"), () => frappe.confirm(__("Submit all draft invoices of this shipment?"), () => call("invoicing.submit_invoices", { shipment: frm.doc.name }, (r) => { frappe.msgprint(__("Submitted: {0}", [(r || []).join(", ")])); frm.reload_doc(); })), __("Apparel"));
		}
	},
});
