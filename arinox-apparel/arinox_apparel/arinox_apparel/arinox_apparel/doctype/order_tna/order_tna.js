// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Order TNA", {
	refresh(frm) {
		const c = { "On Track": "green", "At Risk": "orange", Late: "red", Completed: "blue", Cancelled: "gray" };
		if (frm.doc.status) frm.dashboard.add_indicator(__(frm.doc.status) + (frm.doc.critical_delay_days ? ` (${frm.doc.critical_delay_days} d)` : ""), c[frm.doc.status] || "gray");
		if (!frm.doc.plan_feasible && frm.doc.feasibility_note) frm.dashboard.add_comment(frm.doc.feasibility_note, "red", true);
		if (frm.doc.order_date_missing) frm.dashboard.add_comment(__("The buyer PO date is missing, so the Sales Order date was used as the order received date."), "orange", true);
		if (frm.is_new()) return;
		frm.add_custom_button(__("Milestones"), () => frappe.set_route("List", "TNA Milestone", "Gantt", { order_tna: frm.doc.name }));
		if (!frm.doc.baseline_locked) {
			frm.add_custom_button(__("Lock Baseline"), () => frm.call("lock_baseline").then(() => frm.reload_doc()), __("Plan"));
			frm.add_custom_button(__("Re-plan Dates"), () => frm.call("replan").then(() => frm.reload_doc()), __("Plan"));
		} else {
			frm.dashboard.add_indicator(__("Baseline locked"), "blue");
			frm.add_custom_button(__("Re-plan (revised dates)"), () => frm.call("replan").then(() => frm.reload_doc()), __("Plan"));
			frm.add_custom_button(__("Unlock Baseline"), () => frm.call("unlock_baseline").then(() => frm.reload_doc()), __("Plan"));
		}
	},
});
