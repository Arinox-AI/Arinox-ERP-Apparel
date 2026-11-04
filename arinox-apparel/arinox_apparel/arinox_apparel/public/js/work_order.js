// Apparel: show the bulk gate (G3) state on a Work Order made for a Sales Order.
frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.sales_order || !frm.doc.production_item) return;
		frappe.call({
			method: "arinox_apparel.overrides.work_order.get_bulk_gate",
			args: { production_item: frm.doc.production_item, sales_order: frm.doc.sales_order },
			callback: (r) => {
				const g = r.message;
				if (!g || !g.applies) return;
				if (g.blockers.length) {
					frm.dashboard.add_indicator(__("Bulk gate: {0} blocker(s)", [g.blockers.length]), "red");
					frm.dashboard.set_headline_alert(
						"<b>" + __("Bulk gate (G3)") + "</b><br>• " + g.blockers.map(frappe.utils.escape_html).join("<br>• "), "red");
				} else {
					frm.dashboard.add_indicator(__("Bulk gate open"), "green");
				}
			},
		});
	},
});
