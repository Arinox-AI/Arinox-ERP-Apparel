// Apparel: a submitted Quotation becomes a Sales Contract.
//
// A quotation is read in the buyer's currency. When the company's currency is different (VND, HKD, AED ...) ERPNext also shows a
// "(Company Currency)" copy of every total, every item column, the taxes columns and "In Words", so the company currency ends up
// everywhere on the form. Keep those hidden. ERPNext shows them again each time the form refreshes (transaction.js
// set_dynamic_labels -> frm.toggle_display / grid.set_column_disp), so the two calls it uses are wrapped, not just called once.
// The exchange rate and price-list currency fields stay visible: they are what the base amounts are worked out from.
const QUOTATION_COMPANY_CURRENCY_FIELDS = new Set([
	"base_total", "base_net_total", "base_tax_withholding_net_total", "base_total_taxes_and_charges", "base_taxes_and_charges_added",
	"base_taxes_and_charges_deducted", "base_grand_total", "base_rounded_total", "base_in_words", "base_discount_amount", "base_rounding_adjustment",
]);
const QUOTATION_COMPANY_CURRENCY_COLUMNS = new Set([
	"base_rate", "base_price_list_rate", "base_amount", "base_rate_with_margin", "base_net_rate", "base_net_amount",
	"base_tax_amount", "base_total", "base_tax_amount_after_discount_amount",
]);

function hide_company_currency_columns(frm) {
	["items", "taxes"].forEach((table) => {
		const field = frm.fields_dict[table];
		const grid = field && field.grid;
		if (!grid) return;
		if (!grid.__arinox_columns_wrapped) {
			grid.__arinox_columns_wrapped = true;
			const set_column_disp = grid.set_column_disp.bind(grid);
			grid.set_column_disp = function (fieldname, show) {
				const names = [].concat(fieldname);
				names.filter((f) => QUOTATION_COMPANY_CURRENCY_COLUMNS.has(f)).forEach((f) => set_column_disp(f, false));
				const rest = names.filter((f) => !QUOTATION_COMPANY_CURRENCY_COLUMNS.has(f));
				if (rest.length) return set_column_disp(Array.isArray(fieldname) ? rest : rest[0], show);
			};
		}
		QUOTATION_COMPANY_CURRENCY_COLUMNS.forEach((fieldname) => {
			if (frappe.meta.get_docfield(grid.doctype, fieldname)) grid.set_column_disp(fieldname, false);
		});
	});
}

frappe.ui.form.on("Quotation", {
	setup(frm) {
		const toggle_display = frm.toggle_display.bind(frm);
		frm.toggle_display = function (fields, show) {
			const names = [].concat(fields);
			if (!names.some((f) => QUOTATION_COMPANY_CURRENCY_FIELDS.has(f))) return toggle_display(fields, show);
			const rest = names.filter((f) => !QUOTATION_COMPANY_CURRENCY_FIELDS.has(f));
			if (rest.length) toggle_display(rest, show);
			return toggle_display(names.filter((f) => QUOTATION_COMPANY_CURRENCY_FIELDS.has(f)), false);
		};
	},
	refresh(frm) {
		hide_company_currency_columns(frm);
		if (frm.doc.docstatus !== 1 || frm.doc.quotation_to !== "Customer") return;
		if (!(frm.doc.items || []).some((i) => i.apparel_cost_sheet)) return;
		frm.add_custom_button(__("Sales Contract"), () =>
			frappe.model.open_mapped_doc({ method: "arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract.make_sales_contract", frm })
		, __("Create"));
	},
});
