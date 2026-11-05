// Copyright (c) 2026, Arinox AI and contributors
// Payment follow-up on the customer's invoice.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.apparel_shipment || frm.doc.is_internal_customer) return;
		frm.add_custom_button(__("Log Follow-up"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Payment Follow-up"),
				fields: [
					{ fieldname: "note", label: __("What was said or agreed"), fieldtype: "Small Text", reqd: 1 },
					{ fieldname: "promise_date", label: __("Customer promises to pay on"), fieldtype: "Date" },
					{ fieldname: "promise_amount", label: __("Promised amount"), fieldtype: "Currency", depends_on: "promise_date" },
					{ fieldname: "next_action_date", label: __("Next action on"), fieldtype: "Date" },
					{ fieldname: "dispute_reason", label: __("Dispute (leave blank if none)"), fieldtype: "Small Text", default: frm.doc.apparel_dispute_reason || "" },
				],
				primary_action_label: __("Save"),
				primary_action(v) {
					frappe.call({ method: "arinox_apparel.shipping.followup.log_follow_up", args: Object.assign({ invoice: frm.doc.name }, v),
						callback: () => { d.hide(); frm.reload_doc(); } });
				},
			});
			d.show();
		}, __("Apparel"));
	},
});
