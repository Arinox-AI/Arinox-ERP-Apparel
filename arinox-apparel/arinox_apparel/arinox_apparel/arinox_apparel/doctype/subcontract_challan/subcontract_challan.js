// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Subcontract Challan", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (["Open", "Partly Returned"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Receive Pieces"), () => frappe.new_doc("Subcontract Return", { challan: frm.doc.name }));
			frm.add_custom_button(__("Short Close"), () => {
				frappe.prompt({ fieldname: "reason", label: __("Why the rest will not come back"), fieldtype: "Small Text", reqd: 1 }, (v) => {
					frappe.call({ method: "arinox_apparel.arinox_apparel.doctype.subcontract_challan.subcontract_challan.short_close",
						args: { challan: frm.doc.name, reason: v.reason }, callback: () => frm.reload_doc() });
				}, __("Short Close"));
			}, __("Actions"));
		}
		if (["Returned", "Short Closed", "Partly Returned"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Settle"), () => frappe.new_doc("Subcontract Settlement", { challan: frm.doc.name }), __("Actions"));
		}
	},
});
