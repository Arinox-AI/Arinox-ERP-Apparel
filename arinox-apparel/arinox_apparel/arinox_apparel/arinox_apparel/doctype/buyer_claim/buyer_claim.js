// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Buyer Claim", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.settlement === "Credit Note" && !frm.doc.credit_note) {
			frm.add_custom_button(__("Draft Credit Note"), () => {
				frappe.call({ method: "arinox_apparel.arinox_apparel.doctype.buyer_claim.buyer_claim.make_credit_note",
					args: { claim: frm.doc.name }, freeze: true, callback: () => frm.reload_doc() });
			});
		}
	},
});
