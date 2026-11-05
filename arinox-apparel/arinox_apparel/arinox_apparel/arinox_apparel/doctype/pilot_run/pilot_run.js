// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Pilot Run", {
	setup(frm) {
		frm.set_query("production_card", () => ({ filters: { docstatus: 1, status: ["not in", ["Superseded", "Cancelled", "Closed"]] } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Load Checklist"), () => load_checks(frm), __("Tools"));
			frm.add_custom_button(__("Colours from Production Card"), () => load_colours(frm), __("Tools"));
		}
		if (frm.doc.status === "Approved" || frm.doc.status === "Approved with Comments") frm.dashboard.add_indicator(__(frm.doc.status), "green");
		else if (["Rejected", "Re-run"].includes(frm.doc.status)) frm.dashboard.add_indicator(__(frm.doc.status), "red");
	},
	production_card(frm) {
		if (frm.doc.production_card && !(frm.doc.colours || []).length) load_colours(frm);
	},
});

function load_checks(frm) {
	frappe.db.get_list("Production Check Item", { filters: { applies_to: "Pilot Run" }, fields: ["name"], order_by: "sequence asc", limit: 100 }).then((rows) => {
		const have = new Set((frm.doc.checks || []).map((c) => c.check_item));
		rows.filter((r) => !have.has(r.name)).forEach((r) => frm.add_child("checks", { check_item: r.name }));
		frm.refresh_field("checks");
	});
}

function load_colours(frm) {
	if (!frm.doc.production_card) return;
	frappe.db.get_doc("Production Card", frm.doc.production_card).then((card) => {
		const have = new Set((frm.doc.colours || []).map((c) => c.colour));
		const colours = [...new Set((card.lines || []).map((l) => l.colour))];
		colours.filter((c) => !have.has(c)).forEach((c) => {
			const sizes = (card.lines || []).filter((l) => l.colour === c).map((l) => l.size).join(", ");
			frm.add_child("colours", { colour: c, sizes_run: sizes });
		});
		frm.refresh_field("colours");
	});
}
