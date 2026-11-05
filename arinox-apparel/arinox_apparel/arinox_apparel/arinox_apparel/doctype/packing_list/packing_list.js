// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Packing List", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Generate Cartons"), () => {
				frm.save().then(() => frm.call("generate_cartons").then((r) => {
					frappe.show_alert({ message: __("{0} carton rows made. Check the sizes and weights.", [r.message]), indicator: "green" });
					frm.dirty(); frm.refresh();
				}));
			});
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Contract Trail"), () => frappe.set_route("query-report", "Contract Trail", { contract: frm.doc.sales_contract }));
		}
	},
	carton_type(frm) {
		if (!frm.doc.carton_type) return;
		frappe.db.get_value("Shipment Parcel Template", frm.doc.carton_type, ["length", "width", "height"]).then((r) => {
			(frm.doc.cartons || []).forEach((c) => { if (!c.length_cm) Object.assign(c, { length_cm: r.message.length, width_cm: r.message.width, height_cm: r.message.height }); });
			frm.refresh_field("cartons");
		});
	},
});
