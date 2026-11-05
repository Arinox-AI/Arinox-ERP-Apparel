// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("TNA Milestone", {
	refresh(frm) {
		if (frm.doc.status) {
			const c = { Done: "green", "In Progress": "blue", Late: "red", "Not Started": "gray", "Not Applicable": "gray" };
			frm.dashboard.add_indicator(__(frm.doc.status) + (frm.doc.delay_days ? ` (${frm.doc.delay_days} d)` : ""), c[frm.doc.status] || "gray");
		}
		if (frm.doc.source_name) frm.dashboard.add_comment(__("Stamped by {0} {1}", [frm.doc.source_doctype, frm.doc.source_name]), "blue", true);
	},
});
