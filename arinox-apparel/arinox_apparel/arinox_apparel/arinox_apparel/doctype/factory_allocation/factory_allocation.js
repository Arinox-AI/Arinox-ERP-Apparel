// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Factory Allocation", {
	setup(frm) {
		frm.set_query("sales_order", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("line", "lines", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: row.factory ? { plant_floor: row.factory } : {} };
		});
	},
	refresh(frm) {
		if (frm.doc.status) {
			frm.dashboard.add_indicator(__("{0}: {1} of {2} pcs", [frm.doc.status, frm.doc.allocated_qty || 0, frm.doc.order_qty || 0]),
				frm.doc.status === "Planned" ? "green" : "orange");
		}
		if (frm.doc.docstatus === 0 && frm.doc.sales_order) {
			frm.add_custom_button(__("Get Order Lines"), () =>
				frappe.call({
					method: "arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation.get_lines_from_order",
					args: { sales_order: frm.doc.sales_order },
					callback: (r) => {
						const have = new Set((frm.doc.lines || []).map((l) => [l.style_item, l.colour, l.ship_to, l.buyer_po].map((x) => (x || "").toUpperCase()).join("|")));
						(r.message || []).forEach((l) => {
							if (!have.has([l.style_item, l.colour, l.ship_to, l.buyer_po].map((x) => (x || "").toUpperCase()).join("|"))) frm.add_child("lines", l);
						});
						frm.refresh_field("lines");
					},
				}));
		}
	},
});
