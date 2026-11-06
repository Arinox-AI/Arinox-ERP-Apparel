# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""The legal garment contract. Freezes price, colours, quantities and three dates per SKU.
A SKU here is one style x colour line; the size breakdown becomes variant lines on the Sales Order."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import add_days, cint, flt, getdate, nowdate

TERM_FIELDS = (
	"incoterm", "named_place", "shipment_mode", "port_of_loading", "port_of_discharge",
	"days_ex_factory_to_etd", "transit_days", "late_shipment_terms", "quantity_claim_days",
	"quality_claim_days", "aql_level", "inspection_terms", "packing_instructions", "shipping_marks",
	"payment_terms_template", "terms_and_conditions", "arbitration", "country_of_origin", "freight_by",
	"insurance_by", "delay_days_allowed", "objection_days", "discrepancy_days", "payment_basis",
	"payment_days", "documents_list",
)
TEXT_TYPES = ("Data", "Small Text", "Text", "Long Text")
PLACEHOLDER_OK = ("shipping_marks",)   # marks on the carton are advised at booking; the real contracts print TBA here


class SalesContract(Document):
	def autoname(self):
		"""PREFIX + YY.MM.### with a counter that restarts each month, e.g. SC26.09.001.
		The prefix is the issuing Company's, falling back to Apparel Settings."""
		prefix = (
			frappe.db.get_value("Company", self.company, "apparel_contract_prefix")
			or frappe.db.get_single_value("Apparel Settings", "contract_prefix")
			or "SC"
		).strip()
		on = getdate(self.contract_date or nowdate())
		key = f"{prefix}{on.strftime('%y')}.{on.strftime('%m')}."
		self.name = key + getseries(key, 3)

	def validate(self):
		if not self.company:
			from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import get_default_company

			self.company = get_default_company()
		if self.contract_template and not self.tolerance_bands:
			self.apply_template(overwrite=False)
		self.set_bank_account()
		self.set_revision()
		from arinox_apparel.arinox_apparel.doctype.sales_contract_template.sales_contract_template import validate_bands

		validate_bands(self.tolerance_bands)
		self.validate_lines()
		self.validate_price_lock()
		self.validate_sizes()
		self.set_totals()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		self.drop_empty_size_rows()
		self.check_ready_to_sign()
		self.check_placeholders()

	def on_submit(self):
		self.db_set("status", "Signed")

	def before_cancel(self):
		if self.sales_order and frappe.db.get_value("Sales Order", self.sales_order, "docstatus") == 1:
			frappe.throw(_("Cancel Sales Order {0} before cancelling this contract.").format(self.sales_order))

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def set_bank_account(self):
		"""The Company's own default bank account prints on the contract. Bank details are never stored here."""
		if not self.bank_account and self.company:
			self.bank_account = frappe.db.get_value("Company", self.company, "default_bank_account")

	def set_revision(self):
		if self.amended_from:
			prev = frappe.db.get_value("Sales Contract", self.amended_from, "revision_no") or 0
			self.revision_no = cint(prev) + 1
			self.revision_date = self.revision_date or nowdate()
		elif not self.revision_no:
			self.revision_no = 0

	# ------------------------------------------------------------------ template
	@frappe.whitelist()
	def apply_template(self, overwrite=True):
		if not self.contract_template:
			return
		tpl = frappe.get_doc("Sales Contract Template", self.contract_template)
		for f in TERM_FIELDS:
			if overwrite or not self.get(f):
				self.set(f, tpl.get(f))
		if overwrite or not self.tolerance_bands:
			self.set("tolerance_bands", [])
			for b in tpl.tolerance_bands:
				self.append("tolerance_bands", {"from_qty": b.from_qty, "to_qty": b.to_qty, "tolerance_pct": b.tolerance_pct})
		if self.terms_and_conditions and (overwrite or not self.terms):
			self.terms = frappe.db.get_value("Terms and Conditions", self.terms_and_conditions, "terms")

	# ------------------------------------------------------------------ rules
	def validate_lines(self):
		max_skus = cint(frappe.db.get_single_value("Apparel Settings", "max_skus_per_contract")) or 8
		keys = set()
		for it in self.items:
			# a line is style x colour x buyer PO: one contract often carries the same style and colour once per PO
			key = (it.style_item, (it.colour or "").strip().upper(), (it.buyer_po_code or "").strip().upper())
			if key in keys:
				frappe.throw(_("Row {0}: {1} / {2} is already on this contract for PO {3}. One line per style, colour and PO.").format(
					it.idx, it.style_item, it.colour, it.buyer_po_code or "-"))
			keys.add(key)
			if not it.style_no:
				it.style_no = frappe.db.get_value("Item", it.style_item, "item_name")
			it.amount = flt(cint(it.qty) * flt(it.rate), 2)
			it.tolerance_pct = self.tolerance_for(cint(it.qty))
			if self.tolerance_bands and not self.tolerance_covers(cint(it.qty)):
				frappe.msgprint(
					_("Row {0}: quantity {1} is above the highest tolerance band, so no tolerance applies. Add a band for it.").format(
						it.idx, cint(it.qty)
					),
					indicator="orange",
				)
			if it.ex_factory_date and not it.etd:
				it.etd = add_days(it.ex_factory_date, cint(self.days_ex_factory_to_etd))
			if it.etd and not it.in_warehouse_date:
				it.in_warehouse_date = add_days(it.etd, cint(self.transit_days))
			if it.ex_factory_date and it.etd and getdate(it.etd) < getdate(it.ex_factory_date):
				frappe.throw(_("Row {0}: ETD is before the ex-factory date.").format(it.idx))
			if it.etd and it.in_warehouse_date and getdate(it.in_warehouse_date) < getdate(it.etd):
				frappe.throw(_("Row {0}: in-warehouse date is before ETD.").format(it.idx))
		if len(keys) > max_skus:
			frappe.throw(
				_("This contract has {0} SKUs. The maximum is {1}; put the rest on a new contract.").format(len(keys), max_skus),
				title=_("Too Many SKUs"),
			)
		self.sku_count = len(keys)

	def tolerance_for(self, qty):
		for b in sorted(self.tolerance_bands, key=lambda b: cint(b.from_qty)):
			if qty >= cint(b.from_qty) and (not cint(b.to_qty) or qty <= cint(b.to_qty)):
				return flt(b.tolerance_pct)
		return 0

	def tolerance_covers(self, qty):
		return any(
			qty >= cint(b.from_qty) and (not cint(b.to_qty) or qty <= cint(b.to_qty)) for b in self.tolerance_bands
		)

	def validate_price_lock(self):
		"""G2: the price agreed on the quotation is the price on the contract."""
		if not self.quotation:
			return
		q = frappe.db.get_value("Quotation", self.quotation, ["docstatus", "party_name", "currency"], as_dict=True)
		if not q or q.docstatus != 1:
			frappe.throw(_("Quotation {0} must be submitted before it can become a contract.").format(self.quotation))
		if q.party_name != self.customer:
			frappe.throw(_("Quotation {0} is for {1}, not {2}.").format(self.quotation, q.party_name, self.customer))
		if q.currency != self.currency:
			frappe.throw(_("Quotation {0} is in {1}, not {2}.").format(self.quotation, q.currency, self.currency))
		quoted = {
			r.apparel_cost_sheet: flt(r.rate)
			for r in frappe.get_all(
				"Quotation Item", filters={"parent": self.quotation}, fields=["apparel_cost_sheet", "rate"]
			)
			if r.apparel_cost_sheet
		}
		for it in self.items:
			if not it.cost_sheet:
				continue
			if it.cost_sheet not in quoted:
				frappe.throw(_("Row {0}: Cost Sheet {1} is not on Quotation {2}.").format(it.idx, it.cost_sheet, self.quotation))
			if abs(flt(it.rate) - quoted[it.cost_sheet]) > 0.0001:
				frappe.throw(
					_("Row {0}: rate {1} differs from the quoted {2}. A contract carries the locked price; amend the Quotation to change it.").format(
						it.idx, flt(it.rate), quoted[it.cost_sheet]),
					title=_("Price Lock"),
				)

	def line_index(self, style_item, colour, po):
		"""Index of the contract line a size row belongs to. A size row names its PO; one without a PO belongs to the only line of
		that style and colour. None = no such line, -1 = several lines and no PO to tell them apart."""
		cands = [i for i, it in enumerate(self.items) if it.style_item == style_item and (it.colour or "").strip().upper() == (colour or "").strip().upper()]
		if po:
			cands = [i for i in cands if (self.items[i].buyer_po_code or "").strip().upper() == po.strip().upper()]
		if not cands:
			return None
		return cands[0] if len(cands) == 1 else -1

	def validate_sizes(self):
		seen = set()
		for s in self.sizes:
			i = self.line_index(s.style_item, s.colour, s.buyer_po_no)
			if i is None:
				frappe.throw(_("Size row {0}: {1} / {2} (PO {3}) is not a line on this contract.").format(s.idx, s.style_item, s.colour, s.buyer_po_no or "-"))
			if i == -1:
				frappe.throw(_("Size row {0}: {1} / {2} is on several lines (one per PO). Enter the buyer PO on the size row.").format(s.idx, s.style_item, s.colour))
			# One size can appear once per destination on a line: the same PO is often split across ship-to points.
			k2 = (i, s.size.strip().upper(), (s.ship_to or "").strip().upper())
			if k2 in seen:
				frappe.throw(
					_("Size row {0}: size {1} is entered twice for {2} / {3} to the same ship-to and PO.").format(
						s.idx, s.size, s.style_item, s.colour
					)
				)
			seen.add(k2)
			if cint(s.qty) < 0:
				frappe.throw(_("Size row {0}: quantity cannot be negative.").format(s.idx))

	def set_totals(self):
		self.total_qty = sum(cint(it.qty) for it in self.items)
		self.total_amount = flt(sum(flt(it.amount) for it in self.items), 2)

	def drop_empty_size_rows(self):
		self.set("sizes", [s for s in self.sizes if cint(s.qty)])
		for i, s in enumerate(self.sizes, 1):
			s.idx = i

	def check_ready_to_sign(self):
		problems = []
		by_line = defaultdict(int)
		for s in self.sizes:
			by_line[self.line_index(s.style_item, s.colour, s.buyer_po_no)] += cint(s.qty)
		for pos, it in enumerate(self.items):
			label = f"{it.style_no or it.style_item} / {it.colour or '-'}"
			if not it.colour:
				problems.append(_("{0}: colour is missing").format(label))
			if cint(it.qty) <= 0:
				problems.append(_("{0}: quantity is missing").format(label))
			if not flt(it.rate):
				problems.append(_("{0}: rate is missing").format(label))
			for f, lbl in (("ex_factory_date", _("ex-factory date")), ("etd", _("ETD")), ("in_warehouse_date", _("in-warehouse date"))):
				if not it.get(f):
					problems.append(_("{0}: {1} is missing").format(label, lbl))
			sized = by_line.get(pos, 0)
			if sized != cint(it.qty):
				problems.append(_("{0}: size breakdown totals {1}, line quantity is {2}").format(label, sized, cint(it.qty)))
		for f, lbl in (("incoterm", _("Incoterm")), ("port_of_loading", _("Port of loading"))):
			if not self.get(f):
				problems.append(_("{0} is missing").format(lbl))
		if not ((self.payment_basis and cint(self.payment_days)) or self.payment_basis in ("Advance",) or self.payment_terms_template):
			problems.append(_("Payment terms are missing (basis and days, or a payment terms template)"))
		if problems:
			frappe.throw("<br>".join(problems), title=_("Contract not ready to sign"))

	def check_placeholders(self):
		"""Nothing is left TBA on a signed contract."""
		words = frappe.db.get_single_value("Apparel Settings", "placeholder_words") or ""
		words = {w.strip().upper() for w in words.splitlines() if w.strip()}
		if not words:
			return
		hits = []

		def scan(doc, label):
			for df in doc.meta.fields:
				if df.fieldtype not in TEXT_TYPES or df.fieldname in PLACEHOLDER_OK:
					continue
				val = (doc.get(df.fieldname) or "").strip()
				if val and (val.upper() in words or any(tok in words for tok in val.upper().replace(",", " ").split() if len(tok) > 2)):
					hits.append(f"{label}{df.label}: {val}")

		scan(self, "")
		for it in self.items:
			scan(it, _("Row {0} ").format(it.idx))
		if hits:
			frappe.throw(
				_("Nothing may be left as a placeholder on a signed contract:") + "<br>" + "<br>".join(hits),
				title=_("Placeholders found"),
			)


# ---------------------------------------------------------------------- mapping


def default_template(customer):
	return (
		frappe.db.get_value("Sales Contract Template", {"customer": customer, "is_default": 1, "enabled": 1}, "name")
		or frappe.db.get_value("Sales Contract Template", {"customer": customer, "enabled": 1}, "name")
		or frappe.db.get_single_value("Apparel Settings", "default_contract_template")
	)


@frappe.whitelist()
def make_sales_contract(source_name):
	"""Quotation -> Sales Contract (unsaved). One line per quoted style and tech-pack colour,
	with the size rows pre-filled from the tech pack (quantities left for the merchandiser)."""
	q = frappe.get_doc("Quotation", source_name)
	q.check_permission("read")
	if q.docstatus != 1:
		frappe.throw(_("Submit the Quotation first."))
	if q.quotation_to != "Customer":
		frappe.throw(_("The Quotation must be addressed to a Customer."))

	sc = frappe.new_doc("Sales Contract")
	sc.update(
		{
			"customer": q.party_name,
			"quotation": q.name,
			"price_negotiation": q.get("apparel_price_negotiation"),
			"opportunity": q.opportunity,
			"currency": q.currency,
			"company": q.company,
			"contract_template": default_template(q.party_name),
		}
	)
	if sc.contract_template:
		sc.apply_template(overwrite=True)
	if q.incoterm:
		sc.incoterm = q.incoterm
	if q.payment_terms_template:
		sc.payment_terms_template = q.payment_terms_template
		first = frappe.db.get_value(
			"Payment Terms Template Detail", {"parent": q.payment_terms_template}, ["credit_days", "due_date_based_on"], as_dict=True
		)
		if first and not sc.payment_basis:
			sc.payment_days = cint(first.credit_days)
			sc.payment_basis = "Days after Invoice Date"

	for qi in q.items:
		cs = frappe.get_doc("Cost Sheet", qi.apparel_cost_sheet) if qi.get("apparel_cost_sheet") else None
		style_item = qi.get("apparel_style_item") or (cs.style_item if cs else None) or qi.item_code
		tp = frappe.get_doc("Tech Pack", cs.tech_pack) if cs and cs.tech_pack else None
		colours = [c.colour for c in tp.colours] if tp and tp.colours else [None]
		for colour in colours:
			sc.append(
				"items",
				{
					"style_item": style_item,
					"style_no": qi.get("apparel_style_no") or (cs.style_no if cs else qi.item_name),
					"colour": colour,
					"qty": qi.qty if len(colours) == 1 else 0,
					"rate": qi.rate,
					"description": qi.description,
					"cost_sheet": cs.name if cs else None,
					"tech_pack": tp.name if tp else None,
				},
			)
			for size in (tp.sizes if tp else []):
				sc.append("sizes", {"style_item": style_item, "colour": colour, "size": size.size, "qty": 0})
	return sc


@frappe.whitelist()
def make_sales_order(source_name):
	"""Sales Contract -> Sales Order (unsaved): one line per style x colour x size variant."""
	from erpnext.controllers.item_variant import create_variant, get_variant

	sc = frappe.get_doc("Sales Contract", source_name)
	sc.check_permission("read")
	if sc.docstatus != 1:
		frappe.throw(_("Submit (sign) the contract first."))
	if sc.sales_order and frappe.db.get_value("Sales Order", sc.sales_order, "docstatus") != 2:
		frappe.throw(_("Sales Order {0} already exists for this contract.").format(sc.sales_order))

	settings = frappe.get_single("Apparel Settings")
	colour_attr, size_attr = settings.colour_attribute or "Colour", settings.size_attribute or "Size"
	def line_of(size_row):
		i = sc.line_index(size_row.style_item, size_row.colour, size_row.buyer_po_no)
		if i is None or i == -1:
			frappe.throw(_("Size row {0}: cannot tell which contract line it belongs to. Enter the buyer PO on it.").format(size_row.idx))
		return sc.items[i]

	warehouse = None
	for wh in (settings.fg_warehouse, frappe.db.get_single_value("Stock Settings", "default_warehouse")):
		if wh and frappe.db.get_value("Warehouse", wh, "company") == sc.company:
			warehouse = wh
			break

	so = frappe.new_doc("Sales Order")
	so.update(
		{
			"customer": sc.customer,
			"company": sc.company,
			"currency": sc.currency,
			"po_no": sc.buyer_po_no,
			"po_date": sc.contract_date,
			"delivery_date": min(getdate(it.ex_factory_date) for it in sc.items),
			"incoterm": sc.incoterm,
			"named_place": sc.named_place,
			"payment_terms_template": sc.payment_terms_template,
			"tc_name": sc.terms_and_conditions,
			"terms": sc.terms,
			"apparel_sales_contract": sc.name,
			"set_warehouse": warehouse,
		}
	)
	for s in sc.sizes:
		line = line_of(s)
		item_code = s.style_item
		if frappe.db.get_value("Item", s.style_item, "has_variants"):
			args = {colour_attr: s.colour, size_attr: s.size}
			item_code = get_variant(s.style_item, args=args)
			if not item_code:
				variant = create_variant(s.style_item, args)
				variant.insert()
				item_code = variant.name
			s.db_set("item_code", item_code)
		so.append(
			"items",
			{
				"item_code": item_code,
				"qty": s.qty,
				"rate": line.rate,
				"uom": line.uom or "Nos",
				"delivery_date": line.ex_factory_date,
				"warehouse": warehouse,
				"apparel_colour": s.colour,
				"apparel_size": s.size,
				"apparel_ship_to": s.ship_to,
				"apparel_buyer_po": s.buyer_po_no or line.buyer_po_code,
				"apparel_etd": line.etd,
				"apparel_in_warehouse_date": line.in_warehouse_date,
				"apparel_qty_tolerance_pct": line.tolerance_pct,
				"apparel_cost_sheet": line.cost_sheet,
			},
		)
	so.run_method("set_missing_values")
	for row, s in zip(so.items, sc.sizes):
		row.rate = line_of(s).rate
		row.price_list_rate = 0
	so.run_method("calculate_taxes_and_totals")
	return so
