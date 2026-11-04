// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Tech Pack", {
	setup(frm) {
		frm.set_query("opportunity", () => ({ filters: { opportunity_from: "Customer", party_name: frm.doc.customer } }));
		frm.set_query("style_item", () => ({ filters: { has_variants: 1 } }));
	},
	refresh(frm) {
		render_measurement_matrix(frm);
		if (frm.is_new()) return;
		if (!frm.doc.style_item && frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Create Style Item"), () =>
				frappe.call({
					method: "arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack.create_style_item",
					args: { tech_pack: frm.doc.name },
					freeze: true,
					callback: (r) => { frappe.show_alert({ message: __("Style item {0} created", [r.message]), indicator: "green" }); frm.reload_doc(); },
				})
			);
		}
		if (frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Cost Sheet"), () =>
				frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack.make_cost_sheet", frm })
			, __("Create"));
		}
	},
	measurements_on_form_rendered: render_measurement_matrix,
});

frappe.ui.form.on("Tech Pack Measurement", {
	value: render_measurement_matrix,
	measurements_remove: render_measurement_matrix,
});

function render_measurement_matrix(frm) {
	frm = frm.doc ? frm : cur_frm;
	const rows = frm.doc.measurements || [];
	const wrapper = frm.get_field("measurement_matrix").$wrapper;
	if (!rows.length) { wrapper.html(""); return; }
	const sizes = (frm.doc.sizes || []).map((s) => s.size);
	rows.forEach((r) => { if (!sizes.includes(r.size)) sizes.push(r.size); });
	const poms = [];
	const grid = {};
	rows.forEach((r) => {
		const key = (r.pom_code ? r.pom_code + " · " : "") + r.point_of_measure;
		if (!poms.find((p) => p.key === key)) poms.push({ key, tol: [r.tolerance_plus, r.tolerance_minus] });
		grid[key + "|" + r.size] = r.value;
	});
	const esc = frappe.utils.escape_html;
	let html = '<div class="table-responsive"><table class="table table-bordered table-sm" style="font-size:12px"><thead><tr><th>' +
		__("Point of Measure") + "</th><th>" + __("Tol +/−") + "</th>" + sizes.map((s) => "<th class='text-right'>" + esc(s) + "</th>").join("") + "</tr></thead><tbody>";
	poms.forEach((p) => {
		html += "<tr><td>" + esc(p.key) + "</td><td>" + (p.tol[0] || 0) + " / " + (p.tol[1] || 0) + "</td>" +
			sizes.map((s) => "<td class='text-right'>" + (grid[p.key + "|" + s] ?? "") + "</td>").join("") + "</tr>";
	});
	html += "</tbody></table></div><p class='text-muted small'>" + __("Read-only view of the rows below ({0}).", [frm.doc.measurement_uom || "cm"]) + "</p>";
	wrapper.html(html);
}
