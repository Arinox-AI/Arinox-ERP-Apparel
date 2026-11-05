// Copyright (c) 2026, Arinox AI and contributors
frappe.ui.form.on("Cut Plan", {
	setup(frm) {
		frm.set_query("production_card", () => ({ filters: { docstatus: 1, status: ["not in", ["Superseded", "Cancelled", "Closed"]] } }));
		frm.set_query("fabric_item", () => ({ query: "frappe.desk.search.search_link", filters: { has_variants: 0 } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args) => frm.call({ doc: frm.doc, method, args }).then(() => frm.reload_doc());
		if (frm.doc.status === "Draft") frm.add_custom_button(__("Release"), () => call("release"));
		if (frm.doc.status === "Pending Approval") {
			frm.dashboard.add_indicator(__("Marker consumption needs approval"), "orange");
			frm.add_custom_button(__("Approve"), () =>
				frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("Reason for accepting this marker consumption"), reqd: 1 },
					(v) => call("approve", { note: v.note }), __("Approve Marker Consumption")));
		}
		if (["Released", "Pending Approval"].includes(frm.doc.status)) frm.add_custom_button(__("Reopen"), () => call("reopen"));
		frm.add_custom_button(__("Suggest Rolls"), () => suggest(frm), __("Tools"));
		if (frm.doc.red_flags) frm.dashboard.add_indicator(__("{0} red flag(s)", [frm.doc.red_flags.split("\n").length]), "red");
	},
});

function suggest(frm) {
	frm.call({ doc: frm.doc, method: "suggest_rolls" }).then((r) => {
		const res = r.message || {};
		const esc = frappe.utils.escape_html;
		let html = (res.lays || []).map((l) => `<h6>${__("Lay")} ${l.lay_no}: ${l.allocated_m} / ${l.needed_m} m</h6><table class="table table-sm table-bordered"><tr><th>${__("Roll")}</th><th>${__("Shade")}</th><th>${__("Width")}</th><th class="text-right">${__("Plies")}</th><th class="text-right">${__("Metres")}</th></tr>` +
			l.rolls.map((x) => `<tr><td>${esc(x.roll_no || x.batch)}</td><td>${esc(x.shade || "")}</td><td>${x.width || ""}</td><td class="text-right">${x.plies}</td><td class="text-right">${x.metres}</td></tr>`).join("") + "</table>").join("");
		if ((res.short || []).length) html += `<p class="text-danger">${res.short.map((s) => __("Lay {0} is short by {1} m", [s.lay_no, s.short_m])).join("<br>")}</p>`;
		html += `<p class="text-muted">${__("{0} roll(s) left unallocated.", [(res.unallocated || []).length])}</p>`;
		frappe.msgprint({ title: __("Roll Suggestion (not saved)"), wide: true, message: html });
	});
}
