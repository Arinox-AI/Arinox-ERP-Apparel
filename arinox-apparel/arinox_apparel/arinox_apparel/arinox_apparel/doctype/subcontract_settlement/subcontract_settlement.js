// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Subcontract Settlement", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && (!frm.doc.purchase_invoice || (frm.doc.penalty_amount && !frm.doc.debit_note))) {
			frm.add_custom_button(__("Draft Vendor Invoice and Debit Note"), () => {
				frappe.call({ method: "arinox_apparel.arinox_apparel.doctype.subcontract_settlement.subcontract_settlement.make_invoices",
					args: { settlement: frm.doc.name }, freeze: true, callback: () => frm.reload_doc() });
			});
		}
	},
});
