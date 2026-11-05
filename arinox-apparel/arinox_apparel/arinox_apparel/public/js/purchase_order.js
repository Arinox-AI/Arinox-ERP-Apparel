// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		const reqs = [...new Set((frm.doc.items || []).map((i) => i.apparel_requisition).filter(Boolean))];
		if (reqs.length) frm.dashboard.add_comment(__("From requisition(s): {0}", [reqs.join(", ")]), "blue", true);
		if ((frm.doc.items || []).some((i) => i.apparel_hold_reason) && frm.doc.docstatus === 0) {
			frm.dashboard.add_comment(__("Some rows are held until the buyer approval is in. Check the Hold Reason on each row."), "orange", true);
		}
	},
});
