// Order Desk: inquiry -> tech pack -> costing -> negotiation -> quotation -> contract -> order.
frappe.pages["apparel-order-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Order Desk"), single_column: true });
	const customer = page.add_field({
		fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer",
		change: () => load(),
	});
	page.set_primary_action(__("New Inquiry"), () => frappe.new_doc("Opportunity", { opportunity_from: "Customer" }), "add");
	page.add_inner_button(__("Refresh"), () => load());
	page.add_menu_item(__("Inquiry to Contract Tracker"), () => frappe.set_route("query-report", "Inquiry to Contract Tracker"));

	const $board = $(`<div class="apparel-board"></div>`).appendTo(page.main);
	$(`<style>
		.apparel-board{display:grid;grid-template-columns:repeat(7,minmax(210px,1fr));gap:12px;overflow-x:auto;padding:4px 0 16px}
		.apparel-col{background:var(--subtle-fg);border-radius:var(--border-radius-md);padding:8px;min-height:300px}
		.apparel-col h6{display:flex;justify-content:space-between;align-items:center;margin:2px 4px 10px;font-size:12px;
			text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);border-bottom:2px solid #e8590c;padding-bottom:6px}
		.apparel-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius);
			padding:8px 10px;margin-bottom:8px;cursor:pointer;font-size:12.5px}
		.apparel-card:hover{border-color:#e8590c}
		.apparel-card .t{font-weight:600;color:var(--text-color)}
		.apparel-card .s,.apparel-card .m{color:var(--text-muted);font-size:11.5px}
		.apparel-card .m{display:flex;justify-content:space-between;margin-top:4px}
		.apparel-empty{color:var(--text-light);font-size:12px;text-align:center;padding:16px 0}
	</style>`).appendTo(page.main);

	function load() {
		frappe.call({
			method: "arinox_apparel.arinox_apparel.page.apparel_order_desk.apparel_order_desk.get_pipeline",
			args: { customer: customer.get_value() || null },
		}).then((r) => render(r.message || []));
	}

	function render(cols) {
		const esc = frappe.utils.escape_html;
		$board.empty();
		cols.forEach((c) => {
			const $c = $(`<div class="apparel-col"><h6><span>${esc(c.label)}</span>
				<span class="indicator-pill gray">${c.count}</span></h6></div>`).appendTo($board);
			if (!c.cards.length) $c.append(`<div class="apparel-empty">${__("Nothing here")}</div>`);
			c.cards.forEach((k) => {
				const amt = k.amount ? format_currency(k.amount, k.currency) : "";
				const badge = k.badge ? `<span class="indicator-pill ${k.tone}">${esc(k.badge)}</span>` : "";
				$(`<div class="apparel-card">
					<div class="t">${esc(k.title || k.name)}</div>
					<div class="s">${esc(k.name)}${k.subtitle ? " · " + esc(String(k.subtitle)) : ""}</div>
					<div class="m"><span>${k.date ? frappe.datetime.str_to_user(k.date.slice(0, 10)) : ""}</span><span>${amt}</span></div>
					${badge ? `<div style="margin-top:4px">${badge}</div>` : ""}
				</div>`).on("click", () => frappe.set_route("Form", c.doctype, k.name)).appendTo($c);
			});
		});
	}

	load();
};
