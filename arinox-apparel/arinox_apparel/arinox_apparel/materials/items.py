"""Fabric and trim item set-up: a template per fabric quality with the Colour attribute, a variant per colour."""

import frappe
from frappe import _
from frappe.utils import flt

from arinox_apparel.materials.common import YARD_M


def ensure_uom(name):
	if not frappe.db.exists("UOM", name):
		frappe.get_doc({"doctype": "UOM", "uom_name": name}).insert(ignore_permissions=True)


def material_item_group():
	for g in ("Raw Material", "Raw Materials"):
		if frappe.db.exists("Item Group", g):
			return g
	return frappe.db.get_single_value("Apparel Settings", "style_item_group") or frappe.db.get_value("Item Group", {"is_group": 0}, "name")


def add_uom_rows(item_doc, gsm=None, width_cm=None):
	"""Yard always (1 yd = 0.9144 m); Kg when GSM and width are known (1 kg = 1000 / (gsm x width_m) m)."""
	have = {u.uom for u in item_doc.get("uoms") or []}
	if "Yard" not in have:
		ensure_uom("Yard")
		item_doc.append("uoms", {"uom": "Yard", "conversion_factor": YARD_M})
	if flt(gsm) and flt(width_cm) and "Kg" not in have:
		ensure_uom("Kg")
		item_doc.append("uoms", {"uom": "Kg", "conversion_factor": round(1000 / (flt(gsm) * flt(width_cm) / 100), 6)})


def ensure_fabric_item(quality_code, colour, description=None, gsm=None, width_cm=None, content=None, construction=None,
                       material_type="Fabric"):
	"""Template `quality_code` (stock UOM Meter, batch tracked, Colour attribute) and its colour variant. Returns the
	variant item code. Safe to call again."""
	from erpnext.controllers.item_variant import create_variant, get_variant

	from arinox_apparel.arinox_apparel.doctype.tech_pack.tech_pack import ensure_attribute_values

	quality_code = (quality_code or "").strip()
	if not quality_code:
		frappe.throw(_("Enter the fabric quality code."))
	attr = frappe.db.get_single_value("Apparel Settings", "colour_attribute") or "Colour"
	ensure_attribute_values(attr, [colour])
	ensure_uom("Meter")
	if not frappe.db.exists("Item", quality_code):
		tpl = frappe.get_doc({
			"doctype": "Item", "item_code": quality_code, "item_name": quality_code, "item_group": material_item_group(),
			"stock_uom": "Meter", "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0, "has_batch_no": 1,
			"has_variants": 1, "variant_based_on": "Item Attribute", "attributes": [{"attribute": attr}],
			"description": description or quality_code,
			"apparel_material_type": material_type, "apparel_fabric_gsm": gsm, "apparel_fabric_width_cm": width_cm,
			"apparel_fabric_content": content, "apparel_construction": construction,
		})
		add_uom_rows(tpl, gsm, width_cm)
		tpl.flags.ignore_permissions = True
		tpl.insert()
	elif not frappe.db.get_value("Item", quality_code, "has_variants"):
		return quality_code  # a plain (non-variant) fabric item is used as it is
	args = {attr: colour}
	code = get_variant(quality_code, args=args)
	if not code:
		variant = create_variant(quality_code, args)
		variant.update({"has_batch_no": 1, "apparel_material_type": material_type, "apparel_fabric_gsm": gsm,
			"apparel_fabric_width_cm": width_cm, "apparel_fabric_content": content, "apparel_construction": construction})
		add_uom_rows(variant, gsm, width_cm)
		variant.flags.ignore_permissions = True
		variant.insert()
		code = variant.name
	return code


def ensure_trim_item(item_code, description=None, trim_category=None, uom="Nos", customer=None, buyer_code=None, customer_provided=0):
	"""A plain stock item per trim code. Buyer code goes on Item Customer Detail."""
	ensure_uom(uom)
	if frappe.db.exists("Item", item_code):
		return item_code
	item = frappe.get_doc({
		"doctype": "Item", "item_code": item_code, "item_name": description or item_code, "item_group": material_item_group(),
		"stock_uom": uom, "is_stock_item": 1, "is_purchase_item": 0 if customer_provided else 1, "is_sales_item": 0,
		"is_customer_provided_item": 1 if customer_provided else 0, "customer": customer if customer_provided else None,
		"description": description or item_code, "apparel_material_type": "Trim", "apparel_trim_category": trim_category,
	})
	if customer and buyer_code:
		item.append("customer_items", {"customer_name": customer, "ref_code": buyer_code})
	item.flags.ignore_permissions = True
	item.insert()
	return item.name
