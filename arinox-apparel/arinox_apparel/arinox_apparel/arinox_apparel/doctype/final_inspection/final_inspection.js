// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Final Inspection", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Pick Cartons"), () => {
				frm.save().then(() => frm.call("pick_cartons").then(() => { frm.dirty(); frm.refresh(); }));
			});
		}
	},
	production_card(frm) {
		if (!frm.doc.production_card || (frm.doc.lots || []).length) return;
		frappe.db.get_list("Packing List", { filters: { production_card: frm.doc.production_card, docstatus: 1 }, fields: ["name"] }).then((rows) => {
			rows.forEach((r) => frm.add_child("lots", { packing_list: r.name }));
			frm.refresh_field("lots");
		});
	},
});
