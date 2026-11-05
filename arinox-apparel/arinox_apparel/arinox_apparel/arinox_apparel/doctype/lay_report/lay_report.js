// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Lay Report", {
	setup(frm) {
		frm.set_query("production_card", () => ({ filters: { docstatus: 1, status: ["not in", ["Superseded", "Cancelled", "Closed"]] } }));
		frm.set_query("cut_plan", () => ({ filters: { production_card: frm.doc.production_card, colour: frm.doc.colour } }));
		frm.set_query("paired_with", () => ({ filters: { production_card: frm.doc.production_card, colour: frm.doc.colour, component: "Shell", docstatus: 1 } }));
		frm.set_query("batch", "rolls", () => ({ filters: { item: frm.doc.fabric_item, disabled: 0, apparel_inspection_status: ["in", ["Accepted", "Accepted by Lot"]] } }));
		frm.set_query("recut_request", () => ({ filters: { production_card: frm.doc.production_card, status: "Open", docstatus: 1 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Bundles"), () => frappe.set_route("List", "Cut Bundle", { lay_report: frm.doc.name }));
		}
		if (frm.doc.shade_band) frm.dashboard.add_indicator(__("Shade {0}", [frm.doc.shade_band]), "blue");
	},
	cut_plan(frm) {
		if (!frm.doc.cut_plan || !frm.doc.lay_no) return;
		frappe.db.get_doc("Cut Plan", frm.doc.cut_plan).then((plan) => {
			const lay = (plan.lays || []).find((l) => l.lay_no === frm.doc.lay_no);
			if (!lay) return;
			frm.set_value("marker_length_m", lay.marker_length_m);
			frm.set_value("marker_width_cm", lay.marker_width_cm);
			frm.set_value("marker_ref", lay.marker_ref);
			frm.clear_table("sizes");
			(plan.ratios || []).filter((r) => r.lay_no === frm.doc.lay_no).forEach((r) => frm.add_child("sizes", { size: r.size, ratio: r.ratio }));
			frm.refresh_field("sizes");
		});
	},
});
