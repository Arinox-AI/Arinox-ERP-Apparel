# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""What the buyer sent for one style: images, sizes, measurements, colourways and their BOM."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class TechPack(Document):
	def validate(self):
		if self.status in ("Accepted", "Cancelled"):
			self.status = "Draft"
		self.validate_sizes()
		self.validate_measurements()
		self.validate_fit_rounds()
		self.check_duplicate_style()

	def on_submit(self):
		self.db_set("status", "Accepted")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def validate_sizes(self):
		seen = set()
		for s in self.sizes:
			key = s.size.strip().upper()
			if key in seen:
				frappe.throw(_("Size {0} is listed twice.").format(s.size))
			seen.add(key)
		bases = [s.size for s in self.sizes if s.is_base_size]
		if len(bases) > 1:
			frappe.throw(_("Only one base size is allowed."))
		self.base_size = bases[0] if bases else None
		total = sum(flt(s.ratio) for s in self.sizes)
		if total and abs(total - 1) > 0.001 and abs(total - 100) > 0.1:
			frappe.msgprint(
				_("Size ratios add up to {0}. They usually total 1 or 100.").format(flt(total, 3)), indicator="orange"
			)

	def validate_measurements(self):
		sizes = {s.size.strip().upper() for s in self.sizes}
		seen = set()
		for m in self.measurements:
			if sizes and m.size.strip().upper() not in sizes:
				frappe.throw(_("Measurement row {0}: size {1} is not in the size list.").format(m.idx, m.size))
			# The same POM code can describe two measures (T210: neck and armhole), so the name is part of the key.
			key = ((m.pom_code or "").strip().upper(), m.point_of_measure.strip().upper(), m.size.strip().upper())
			if key in seen:
				frappe.throw(
					_("Measurement row {0}: {1} {2} / {3} is entered twice.").format(
						m.idx, key[0], m.point_of_measure, m.size
					)
				)
			seen.add(key)
			if m.tolerance_plus and not m.tolerance_minus:
				m.tolerance_minus = m.tolerance_plus  # buyers usually give one +/- figure

	def validate_fit_rounds(self):
		"""The header shows the result of the latest round."""
		rounds = sorted((r for r in self.fit_rounds if r.round_date), key=lambda r: str(r.round_date))
		last = rounds[-1] if rounds else (self.fit_rounds[-1] if self.fit_rounds else None)
		self.fit_status = last.round_status if last else None

	def check_duplicate_style(self):
		dup = frappe.db.get_value(
			"Tech Pack",
			{"customer": self.customer, "style_no": self.style_no, "docstatus": 1, "name": ("!=", self.name),
			 "season": self.season or ("is", "not set")},
			"name",
		)
		if dup and dup != self.amended_from:
			frappe.msgprint(
				_("Tech Pack {0} is already accepted for this style and season. Amend it to record a new buyer revision.").format(dup),
				indicator="orange",
			)


@frappe.whitelist()
def make_tech_pack(source_name):
	"""Opportunity -> new Tech Pack (unsaved)."""
	opp = frappe.get_doc("Opportunity", source_name)
	opp.check_permission("read")
	if opp.opportunity_from != "Customer":
		frappe.throw(_("Convert the Lead to a Customer before recording a Tech Pack for it."))
	tp = frappe.new_doc("Tech Pack")
	tp.customer = opp.party_name
	tp.opportunity = opp.name
	tp.product_type = opp.get("apparel_product_type")
	tp.season = opp.get("apparel_season")
	tp.source_reference = opp.get("apparel_source_email")
	return tp


@frappe.whitelist()
def make_cost_sheet(source_name):
	"""Tech Pack -> new Cost Sheet (unsaved), materials copied from the buyer BOM with buying rates."""
	from arinox_apparel.arinox_apparel.doctype.cost_sheet.cost_sheet import find_costing_parameter

	tp = frappe.get_doc("Tech Pack", source_name)
	tp.check_permission("read")
	if tp.docstatus == 2:
		frappe.throw(_("This Tech Pack is cancelled. Use its amended revision."))
	if not tp.product_type:
		frappe.throw(_("Set the Product Type on the Tech Pack first; costing rates depend on it."))

	cs = frappe.new_doc("Cost Sheet")
	cs.update(
		{
			"customer": tp.customer,
			"opportunity": tp.opportunity,
			"tech_pack": tp.name,
			"style_no": tp.style_no,
			"style_name": tp.style_name,
			"product_type": tp.product_type,
			"style_item": tp.style_item,
			"sam": frappe.db.get_value("Product Type", tp.product_type, "default_sam"),
			"season": tp.season,
		}
	)
	if tp.opportunity:
		cs.order_qty = frappe.db.get_value("Opportunity", tp.opportunity, "apparel_target_qty")
	cs.currency = (
		frappe.db.get_value("Customer", tp.customer, "default_currency")
		or frappe.db.get_value("Company", frappe.defaults.get_user_default("Company"), "default_currency")
		or frappe.db.get_default("currency")
	)
	cs.costing_parameter = find_costing_parameter(cs.customer, cs.product_type, None, cs.currency)
	price_list = frappe.db.get_single_value("Apparel Settings", "buying_price_list")
	for m in tp.materials:
		cs.append(
			"materials",
			{
				"material_type": m.material_type,
				"description": " ".join(x for x in (m.description, m.composition, m.gsm) if x),
				"item": m.item,
				"uom": m.uom,
				"consumption": flt(m.consumption),
				"conversion_factor": 1,
				"supplier": m.nominated_supplier,
				"rate": get_buying_rate(m.item, price_list),
				"is_selected": 1,
			},
		)
	cs.set_charges_from_parameter()
	return cs


def get_buying_rate(item, price_list=None):
	if not item:
		return 0
	filters = {"item_code": item, "buying": 1}
	if price_list:
		filters["price_list"] = price_list
	rate = frappe.db.get_value("Item Price", filters, "price_list_rate", order_by="valid_from desc")
	return flt(rate) or flt(frappe.db.get_value("Item", item, "last_purchase_rate"))


@frappe.whitelist()
def create_style_item(tech_pack):
	"""Create the style as an Item template with Colour and Size attributes, adding any of this
	Tech Pack's sizes and colours that the attribute lists do not have yet."""
	tp = frappe.get_doc("Tech Pack", tech_pack)
	tp.check_permission("write")
	frappe.has_permission("Item", "create", throw=True)
	if tp.style_item:
		return tp.style_item

	settings = frappe.get_single("Apparel Settings")
	colour_attr = settings.colour_attribute or "Colour"
	size_attr = settings.size_attribute or "Size"
	for attr, values in ((size_attr, [s.size for s in tp.sizes]), (colour_attr, [c.colour for c in tp.colours])):
		ensure_attribute_values(attr, values)

	item_code = tp.style_no.strip()
	if frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} already exists. Link it in Style Item instead.").format(item_code))
	group = (
		frappe.db.get_value("Product Type", tp.product_type, "item_group")
		if tp.product_type
		else None
	) or settings.style_item_group
	if not group:
		frappe.throw(_("Set an Item Group on Product Type {0} or a Style Item Group in Apparel Settings.").format(tp.product_type))
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": tp.style_name or item_code,
			"item_group": group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_sales_item": 1,
			"has_variants": 1,
			"variant_based_on": "Item Attribute",
			"attributes": [{"attribute": colour_attr}, {"attribute": size_attr}],
			"image": tp.front_image,
			"description": f"{tp.style_no} {tp.style_name or ''} ({tp.customer_name or tp.customer})",
		}
	).insert()
	tp.db_set("style_item", item.name)
	return item.name


def ensure_attribute_values(attribute, values):
	if not frappe.db.exists("Item Attribute", attribute):
		frappe.get_doc({"doctype": "Item Attribute", "attribute_name": attribute, "item_attribute_values": []}).insert(
			ignore_permissions=True
		)
	doc = frappe.get_doc("Item Attribute", attribute)
	existing = {v.attribute_value.strip().upper() for v in doc.item_attribute_values}
	abbrs = {v.abbr.upper() for v in doc.item_attribute_values}
	added = False
	for value in values:
		value = (value or "").strip()
		if not value or value.upper() in existing:
			continue
		abbr = "".join(ch for ch in value.upper() if ch.isalnum())[:10] or value[:10]
		base, n = abbr, 1
		while abbr in abbrs:
			n += 1
			abbr = f"{base[:8]}{n}"
		doc.append("item_attribute_values", {"attribute_value": value, "abbr": abbr})
		existing.add(value.upper())
		abbrs.add(abbr)
		added = True
	if added:
		doc.flags.ignore_permissions = True
		doc.save()
