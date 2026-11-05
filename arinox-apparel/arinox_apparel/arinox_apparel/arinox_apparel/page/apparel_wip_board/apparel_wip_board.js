// WIP Board: one row per order (style x colour x ex-factory date), one column per milestone. Three views of the same data:
// grid, Gantt and calendar. Status is always shown as an icon AND a word, never colour alone.
frappe.pages["apparel-wip-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("WIP Board"), single_column: true });
	const F = {};
	const add = (fieldname, label, fieldtype, options) => (F[fieldname] = page.add_field({ fieldname, label: __(label), fieldtype, options, change: () => load(0) }));
	add("customer", "Buyer", "Link", "Customer");
	add("merchant", "Merchant", "Link", "User");
	add("factory", "Factory", "Link", "Plant Floor");
	add("sales_order", "Sales Order", "Link", "Sales Order");
	add("ex_factory_from", "Ex-Factory From", "Date");
	add("ex_factory_to", "Ex-Factory To", "Date");
	add("late_only", "Late or at risk only", "Check");
	page.add_inner_button(__("Refresh"), () => load(0));
	page.add_menu_item(__("WIP Report"), () => frappe.set_route("query-report", "WIP Report"));
	page.add_menu_item(__("Milestone List"), () => frappe.set_route("List", "TNA Milestone", "Gantt"));

	let view = "grid", data = null, cal = null, start = 0;
	const $tabs = $(`<div class="wip-tabs"></div>`).appendTo(page.main);
	const $body = $(`<div class="wip-body"></div>`).appendTo(page.main);
	const $more = $(`<div class="wip-more"></div>`).appendTo(page.main);
	[["grid", __("WIP Grid")], ["gantt", __("Gantt")], ["calendar", __("Calendar")]].forEach(([k, l]) =>
		$(`<button class="btn btn-sm btn-default" data-v="${k}">${l}</button>`).appendTo($tabs).on("click", () => { view = k; draw(); }));
	$(`<style>
		.wip-tabs{margin:0 0 10px;display:flex;gap:6px}
		.wip-tabs .btn.active{background:var(--gray-900);color:var(--white)}
		.wip-legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--text-muted);margin:0 0 8px}
		.wip-scroll{overflow:auto;max-height:70vh;border:1px solid var(--border-color);border-radius:var(--border-radius)}
		table.wip{border-collapse:separate;border-spacing:0;font-size:12px;width:max-content}
		table.wip th,table.wip td{border-bottom:1px solid var(--border-color);border-right:1px solid var(--border-color);padding:4px 6px;white-space:nowrap;background:var(--card-bg)}
		table.wip thead th{position:sticky;top:0;z-index:2;background:var(--subtle-fg);font-weight:600;color:var(--text-color);writing-mode:horizontal-tb;max-width:92px;white-space:normal;vertical-align:bottom}
		table.wip .stick{position:sticky;left:0;z-index:1;background:var(--card-bg);min-width:210px;max-width:210px;white-space:normal}
		table.wip thead .stick{z-index:3;background:var(--subtle-fg)}
		table.wip .stick b{color:var(--text-color)}
		table.wip .stick .sub{color:var(--text-muted);font-size:11px}
		table.wip td.c{text-align:center;cursor:pointer;min-width:78px;color:var(--text-color)}
		td.c .ic{font-weight:700;margin-right:3px}
		td.c.done{background:var(--bg-green);color:var(--text-on-green)}
		td.c.done_late{background:var(--bg-orange);color:var(--text-on-orange)}
		td.c.soon{background:var(--bg-blue);color:var(--text-on-blue)}
		td.c.late{background:var(--bg-red);color:var(--text-on-red);font-weight:600}
		td.c.na{color:var(--text-light)}
		td.c.future{color:var(--text-muted)}
		td.c.crit{box-shadow:inset 0 -2px 0 var(--gray-700)}
		.wip-pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600}
		.wip-pill.ok{background:var(--bg-green);color:var(--text-on-green)}.wip-pill.warn{background:var(--bg-orange);color:var(--text-on-orange)}
		.wip-pill.bad{background:var(--bg-red);color:var(--text-on-red)}.wip-pill.done{background:var(--bg-blue);color:var(--text-on-blue)}
		.wip-empty{padding:30px;text-align:center;color:var(--text-muted)}
		.wip-more{text-align:center;margin:10px 0}
		.wip-gantt-wrap{overflow:auto;border:1px solid var(--border-color);border-radius:var(--border-radius);padding:6px}
		.wip-gantt-wrap .gantt .bar-label{font-size:11px}
		.wip-note{font-size:12px;color:var(--text-muted);margin:6px 0}
	</style>`).appendTo(page.main);

	const SYMBOL = { done: ["✓", __("Done")], done_late: ["✓!", __("Done late")], soon: ["◔", __("Due soon")], late: ["⚠", __("Late")], na: ["–", __("Not applicable")], future: ["", ""] };
	const esc = frappe.utils.escape_html;
	const fmt = (d) => (d ? moment(d).format("DD MMM") : "");

	function filters() {
		const f = {};
		Object.entries(F).forEach(([k, fld]) => { const v = fld.get_value(); if (v) f[k] = v; });
		return f;
	}

	function load(from) {
		start = from;
		$body.html(`<div class="wip-empty">${__("Loading…")}</div>`);
		frappe.call({ method: "arinox_apparel.tna.api.wip_board_data", args: { filters: filters(), limit: 200, start } }).then((r) => {
			const d = r.message;
			if (start && data) { d.orders = data.orders.concat(d.orders); Object.assign(d.milestones, data.milestones); }
			data = d; draw();
		});
	}

	function draw() {
		$tabs.find("button").removeClass("active").filter(`[data-v=${view}]`).addClass("active");
		if (!data) return;
		if (!data.orders.length) { $body.html(`<div class="wip-empty">${__("No orders match. A T&A is made automatically when a Sales Order from a contract is submitted, or use Create > T&A on the Sales Order.")}</div>`); $more.empty(); return; }
		({ grid: draw_grid, gantt: draw_gantt, calendar: draw_calendar })[view]();
		$more.empty();
		if (data.orders.length < data.total) $(`<button class="btn btn-default btn-sm">${__("Load more ({0} of {1})", [data.orders.length, data.total])}</button>`).appendTo($more).on("click", () => load(data.orders.length));
	}

	function legend() {
		return `<div class="wip-legend">${["done", "done_late", "soon", "late", "na"].map((k) => `<span><span class="wip-pill ${({ done: "ok", done_late: "warn", soon: "done", late: "bad", na: "" })[k]}">${SYMBOL[k][0]}</span> ${SYMBOL[k][1]}</span>`).join("")}
			<span>${__("Underlined cell = critical milestone")}</span></div>`;
	}

	function status_pill(o) {
		const m = { "On Track": "ok", "At Risk": "warn", Late: "bad", Completed: "done" }[o.status_live] || "";
		const icon = { "On Track": "✓", "At Risk": "!", Late: "⚠", Completed: "●" }[o.status_live] || "";
		return `<span class="wip-pill ${m}">${icon} ${__(o.status_live)}${o.critical_delay_days ? ` · ${o.critical_delay_days}d` : ""}</span>`;
	}

	function draw_grid() {
		const th = data.types.map((t) => `<th>${esc(t.label)}</th>`).join("");
		const rows = data.orders.map((o) => {
			const ms = data.milestones[o.name] || {};
			const cells = data.types.map((t) => {
				const m = ms[t.code];
				if (!m) return `<td class="c na">–</td>`;
				const [ic, word] = SYMBOL[m.cell];
				const date = m.actual_date || m.revised_date || m.planned_date;
				const tip = [t.label, `${__("Planned")}: ${m.planned_date || ""}`, m.revised_date ? `${__("Revised")}: ${m.revised_date}` : "", m.actual_date ? `${__("Actual")}: ${m.actual_date}` : "", word,
					m.delay_days ? `${m.delay_days} ${__("days")}` : "", m.source_name ? `${m.source_doctype} ${m.source_name}` : ""].filter(Boolean).join("\n");
				return `<td class="c ${m.cell} ${m.is_critical ? "crit" : ""}" data-n="${esc(m.name)}" data-o="${esc(o.name)}" title="${esc(tip)}">${m.cell === "na" ? "–" : `${ic ? `<span class="ic">${ic}</span>` : ""}${fmt(date)}${m.revised_date && !m.actual_date ? "*" : ""}`}</td>`;
			}).join("");
			return `<tr><td class="stick"><b>${esc(o.style_no || "")}</b> ${esc(o.colour || "")} <span class="sub">· ${o.order_qty || 0} pcs</span><br>
				<span class="sub">${esc(o.sales_order)} · ${__("ex-factory")} ${fmt(o.ex_factory_date)}</span><br>${status_pill(o)}${o.plan_feasible ? "" : ` <span class="wip-pill bad" title="${esc(o.feasibility_note || "")}">${__("plan too long")}</span>`}</td>${cells}</tr>`;
		}).join("");
		$body.html(`${legend()}<div class="wip-scroll"><table class="wip"><thead><tr><th class="stick">${__("Order")}</th>${th}</tr></thead><tbody>${rows}</tbody></table></div>
			<div class="wip-note">${__("* = revised date. Click a cell to change dates or open the milestone.")}</div>`);
		$body.find("td.c[data-n]").on("click", function () { open_milestone($(this).data("n"), $(this).data("o")); });
	}

	function open_milestone(name, order) {
		const m = Object.values(data.milestones[order]).find((x) => x.name === name);
		const d = new frappe.ui.Dialog({
			title: `${m.label}`,
			fields: [
				{ fieldtype: "HTML", options: `<div class="wip-note">${__("Planned")} ${m.planned_date || "-"} · ${__("Status")} ${__(m.status)}${m.source_name ? ` · ${m.source_doctype} ${m.source_name}` : ""}</div>` },
				{ fieldname: "revised_date", fieldtype: "Date", label: __("Revised Date"), default: m.revised_date },
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for the change") },
				{ fieldname: "delay_reason", fieldtype: "Select", label: __("Delay Caused By"), options: "\nBuyer\nSupplier\nFactory\nLogistics\nOther", default: m.delay_reason_category },
				{ fieldname: "actual_date", fieldtype: "Date", label: __("Actual Date"), default: m.actual_date },
			],
			primary_action_label: __("Save"),
			primary_action(v) {
				frappe.call({ method: "arinox_apparel.tna.api.update_milestone", args: { name, revised_date: v.revised_date, actual_date: v.actual_date, reason: v.reason, delay_reason: v.delay_reason } })
					.then(() => { d.hide(); load(0); });
			},
			secondary_action_label: __("Open"),
			secondary_action() { frappe.set_route("Form", "TNA Milestone", name); },
		});
		d.show();
	}

	function draw_gantt() {
		const need = ["assets/frappe/node_modules/frappe-gantt/dist/frappe-gantt.css", "assets/frappe/node_modules/frappe-gantt/dist/frappe-gantt.min.js"];
		frappe.require(need, () => {
			const tasks = [];
			data.orders.slice(0, 40).forEach((o) => {
				Object.values(data.milestones[o.name] || {}).filter((m) => !m.not_applicable && m.planned_date).forEach((m) => {
					const end = m.actual_date || m.revised_date || m.planned_date;
					const s = m.planned_start && m.planned_start <= end ? m.planned_start : end;
					tasks.push({ id: m.name, name: `${o.style_no || ""} ${o.colour || ""}: ${m.label} (${__(m.status)})`, start: s, end, progress: m.progress, dependencies: m.depends_on_tasks || "", custom_class: `st-${m.status.replace(/ /g, "")}` });
				});
			});
			if (!tasks.length) return $body.html(`<div class="wip-empty">${__("Nothing to chart.")}</div>`);
			$body.html(`${legend()}<div class="wip-gantt-wrap"><svg id="wip-gantt"></svg></div>
				<style>
					.gantt .bar-wrapper.st-Done .bar,.gantt .bar-wrapper.st-Done .bar-progress{fill:#2f855a}
					.gantt .bar-wrapper.st-InProgress .bar{fill:#9ec5f0}.gantt .bar-wrapper.st-InProgress .bar-progress{fill:#2b6cb0}
					.gantt .bar-wrapper.st-Late .bar,.gantt .bar-wrapper.st-Late .bar-progress{fill:#c53030}
					.gantt .bar-wrapper.st-NotStarted .bar,.gantt .bar-wrapper.st-NotStarted .bar-progress{fill:#718096}
					.gantt .bar-label,.gantt .bar-label.big{fill:var(--text-color)!important;font-weight:500}
					.gantt .grid-header{fill:var(--card-bg)}.gantt .grid-row{fill:var(--card-bg)}.gantt .row-line,.gantt .tick{stroke:var(--border-color)}
					.gantt .lower-text,.gantt .upper-text{fill:var(--text-muted)}
				</style>
				<div class="wip-note">${data.orders.length > 40 ? __("Showing the first 40 orders. Filter to see others. ") : ""}${__("Bars end on the actual date once done, else the revised or planned date.")}</div>`);
			new Gantt("#wip-gantt", tasks, { view_mode: "Week", custom_popup_html: null, on_click: (t) => frappe.set_route("Form", "TNA Milestone", t.id) });
		});
	}

	function draw_calendar() {
		frappe.require("calendar.bundle.js", () => {
			$body.html(`${legend()}<div id="wip-cal"></div>`);
			const events = [];
			data.orders.forEach((o) => Object.values(data.milestones[o.name] || {}).filter((m) => !m.not_applicable).forEach((m) => {
				const date = m.actual_date || m.revised_date || m.planned_date;
				events.push({ id: m.name, title: `${o.style_no || ""} ${o.colour || ""}: ${m.label}`, start: date, allDay: true, color: m.color });
			}));
			cal = new frappe.FullCalendar(document.getElementById("wip-cal"), {
				plugins: frappe.FullCalendar.Plugins, initialView: "dayGridMonth", height: "auto", events, firstDay: 1, dayMaxEvents: 4,
				headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,listMonth" },
				eventClick: (i) => frappe.set_route("Form", "TNA Milestone", i.event.id),
			});
			cal.render();
		});
	}

	load(0);
};
