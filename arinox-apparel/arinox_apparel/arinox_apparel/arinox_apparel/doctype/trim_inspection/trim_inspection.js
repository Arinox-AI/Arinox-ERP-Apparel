// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Trim Inspection", {
	refresh(frm) {
		const colours = { Pass: "green", Fail: "red", Hold: "orange" };
		if (frm.doc.result) frm.dashboard.add_indicator(__(frm.doc.result), colours[frm.doc.result] || "gray");
		if (frm.doc.sample_size) frm.dashboard.add_comment(__("Sample size for this lot: {0}", [frm.doc.sample_size]), "blue", true);
	},
});
