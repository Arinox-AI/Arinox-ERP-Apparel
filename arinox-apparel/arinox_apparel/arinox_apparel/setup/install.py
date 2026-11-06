"""Idempotent setup, run after install and after every migrate.

Custom fields are prefixed `apparel_` so they cannot collide with fields a site created by hand.
Seeds are only inserted when missing; edits made on the site are never overwritten.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = (
	"Apparel Merchandiser", "Apparel Costing Manager", "Apparel Merchandising Manager",
	"Apparel Production Manager", "Apparel Production User", "Apparel QA",
)

# name, group, calc type, material scope, sequence, mandatory
# From "APPAREL_COSTING_DETAILED_REVISED.xlsx": raw materials, process charges, other expenses as % of
# product cost, then profit as a markup on the cost so far.
COST_HEADS = [
	("Fabric", "Material", "From Materials", "Fabric", 10, 1),
	("Trims", "Material", "From Materials", "Non-Fabric", 20, 1),
	("Fabric Export Cost", "Material", "Per Metre of Fabric", None, 25, 1),
	("Fabric Import Cost", "Material", "Per Metre of Fabric", None, 26, 1),
	("Stitching (CMT)", "Conversion", "Per Piece", None, 30, 1),
	("Washing", "Conversion", "Per Piece", None, 40, 1),
	("Printing", "Conversion", "Per Piece", None, 45, 1),
	("Embellishment", "Conversion", "Per Piece", None, 50, 1),
	("Testing", "Conversion", "Per Piece", None, 60, 1),
	("Rejection Allowance", "Allowance", "Percent of Product Cost", None, 70, 1),
	("Finance", "Financial", "Percent of Product Cost", None, 80, 1),
	("Bank Charges", "Financial", "Percent of Product Cost", None, 90, 1),
	("Freight", "Logistics", "Percent of Product Cost", None, 100, 1),
	("Overhead", "Overhead", "Percent of Product Cost", None, 110, 1),
	("Depreciation", "Overhead", "Percent of Product Cost", None, 115, 0),
	("Buying Agent Commission", "Financial", "Percent of Product Cost", None, 120, 0),
	("Profit", "Profit", "Percent of Subtotal", None, 130, 1),
]

PRODUCT_TYPES = ["Knit Top", "Woven Top", "Bottom", "Dress", "Outerwear", "Sleepwear"]


def after_install():
	after_migrate()


def after_migrate():
	make_roles()
	make_custom_fields()
	seed_cost_heads()
	seed_product_types()
	seed_sample_rules()
	setup_variant_attributes()
	set_settings_defaults()
	from arinox_apparel.setup import materials

	materials.run()
	from arinox_apparel.setup import production

	production.run()
	from arinox_apparel.setup import shipping

	shipping.run()
	from arinox_apparel.tna import seed as tna_seed

	tna_seed.seed()
	frappe.db.commit()


def set_settings_defaults():
	"""A Single stores nothing until saved, so its JSON defaults would never reach
	get_single_value. Write each default once, only where the field is still empty."""
	meta = frappe.get_meta("Apparel Settings")
	for df in meta.fields:
		if not df.default or df.fieldtype in ("Link", "Table"):
			continue
		if df.fieldtype == "Check":  # 0 is a real choice for a check; only fill one that was never saved
			unsaved = not frappe.db.sql("select 1 from `tabSingles` where doctype=%s and field=%s", ("Apparel Settings", df.fieldname))
		else:
			unsaved = frappe.db.get_single_value("Apparel Settings", df.fieldname) in (None, "", 0)
		if unsaved:
			frappe.db.set_single_value("Apparel Settings", df.fieldname, df.default)


def setup_variant_attributes():
	"""Style variants need a colour and a size attribute. ERPNext's setup wizard normally makes
	them; create empty ones if it has not run, and point Apparel Settings at them."""
	for attr in ("Colour", "Size"):
		if not frappe.db.exists("Item Attribute", attr):
			frappe.get_doc({"doctype": "Item Attribute", "attribute_name": attr}).insert(ignore_permissions=True)
	for field, attr in (("colour_attribute", "Colour"), ("size_attribute", "Size")):
		if not frappe.db.get_single_value("Apparel Settings", field):
			frappe.db.set_single_value("Apparel Settings", field, attr)


def make_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def make_custom_fields():
	create_custom_fields(get_custom_fields(), ignore_validate=True, update=True)


def get_custom_fields():
	return {
		"Company": [
			dict(fieldname="apparel_contract_prefix", fieldtype="Data", label="Apparel Contract Prefix",
				 insert_after="abbr", description="Prefix of Sales Contract numbers issued by this company, e.g. SC. "
				 "Number format: PREFIX + YY.MM.### (counter restarts each month)."),
			dict(fieldname="apparel_pc_prefix", fieldtype="Data", label="Production Card Prefix", default="PC",
				 insert_after="apparel_contract_prefix", description="Number format: PREFIX + YY.MM.### (counter restarts each month)."),
		],
		"Workstation": [
			dict(fieldname="apparel_line_section", fieldtype="Section Break", label="Apparel Line", collapsible=1),
			dict(fieldname="apparel_line_type", fieldtype="Select", label="Line Type", options="\nCutting\nSewing\nFinishing\nPacking",
				 insert_after="apparel_line_section"),
			dict(fieldname="apparel_default_operators", fieldtype="Int", label="Default Operators", insert_after="apparel_line_type"),
			dict(fieldname="apparel_default_helpers", fieldtype="Int", label="Default Helpers", insert_after="apparel_default_operators"),
		],
		"Stock Entry": [
			dict(fieldname="apparel_production_card", fieldtype="Link", options="Production Card", label="Production Card",
				 insert_after="purpose", read_only=1, no_copy=1, search_index=1),
			dict(fieldname="apparel_issue_kind", fieldtype="Select", label="Production Issue Kind",
				 options="\nFabric Issue\nRemnant Return\nTrim Issue\nFinished Goods Receipt", insert_after="apparel_production_card", read_only=1, no_copy=1),
		],
		"Opportunity": [
			dict(fieldname="apparel_section", fieldtype="Section Break", label="Apparel Inquiry",
				 insert_after="probability", collapsible=0),
			dict(fieldname="apparel_product_type", fieldtype="Link", options="Product Type", label="Product Type",
				 insert_after="apparel_section"),
			dict(fieldname="apparel_season", fieldtype="Data", label="Season", insert_after="apparel_product_type"),
			dict(fieldname="apparel_target_qty", fieldtype="Int", label="Target Order Qty", insert_after="apparel_season"),
			dict(fieldname="apparel_col_1", fieldtype="Column Break", insert_after="apparel_target_qty"),
			dict(fieldname="apparel_target_fob", fieldtype="Currency", options="currency", label="Buyer Target FOB / pc",
				 insert_after="apparel_col_1"),
			dict(fieldname="apparel_delivery_from", fieldtype="Date", label="Delivery Window From",
				 insert_after="apparel_target_fob"),
			dict(fieldname="apparel_delivery_to", fieldtype="Date", label="Delivery Window To",
				 insert_after="apparel_delivery_from"),
			dict(fieldname="apparel_source_email", fieldtype="Data", label="Source Email Reference",
				 insert_after="apparel_delivery_to", description="Message id or subject of the buyer's email"),
		],
		"Quotation": [
			dict(fieldname="apparel_price_negotiation", fieldtype="Link", options="Price Negotiation",
				 label="Price Negotiation", insert_after="valid_till", no_copy=0),
		],
		"Quotation Item": [
			dict(fieldname="apparel_cost_sheet", fieldtype="Link", options="Cost Sheet", label="Cost Sheet",
				 insert_after="item_name", in_list_view=0, search_index=1),
			dict(fieldname="apparel_style_no", fieldtype="Data", label="Style No", insert_after="apparel_cost_sheet",
				 read_only=1),
			dict(fieldname="apparel_style_item", fieldtype="Link", options="Item", label="Style Item",
				 insert_after="apparel_style_no", read_only=1),
		],
		"Sales Order": [
			dict(fieldname="apparel_sales_contract", fieldtype="Link", options="Sales Contract", label="Sales Contract",
				 insert_after="po_date", read_only=1, no_copy=1, search_index=1, in_standard_filter=1),
		],
		"Work Order": [
			dict(fieldname="apparel_gate_section", fieldtype="Section Break", label="Apparel Bulk Gate", insert_after="sales_order",
				 collapsible=1),
			dict(fieldname="apparel_gate_override", fieldtype="Check", label="Override Bulk Gate", insert_after="apparel_gate_section",
				 no_copy=1, description="Apparel Merchandising Manager only"),
			dict(fieldname="apparel_gate_override_reason", fieldtype="Small Text", label="Override Reason",
				 insert_after="apparel_gate_override", depends_on="apparel_gate_override", no_copy=1),
		],
		"Sales Order Item": [
			dict(fieldname="apparel_colour", fieldtype="Data", label="Colour", insert_after="delivery_date", read_only=1),
			dict(fieldname="apparel_size", fieldtype="Data", label="Size", insert_after="apparel_colour", read_only=1),
			dict(fieldname="apparel_ship_to", fieldtype="Data", label="Ship To", insert_after="apparel_size", read_only=1),
			dict(fieldname="apparel_buyer_po", fieldtype="Data", label="Buyer PO", insert_after="apparel_ship_to", read_only=1),
			dict(fieldname="apparel_etd", fieldtype="Date", label="ETD", insert_after="apparel_buyer_po"),
			dict(fieldname="apparel_in_warehouse_date", fieldtype="Date", label="In-Warehouse Date",
				 insert_after="apparel_etd"),
			dict(fieldname="apparel_qty_tolerance_pct", fieldtype="Percent", label="Qty Tolerance ± %",
				 insert_after="apparel_in_warehouse_date", read_only=1),
			dict(fieldname="apparel_cost_sheet", fieldtype="Link", options="Cost Sheet", label="Cost Sheet",
				 insert_after="apparel_qty_tolerance_pct", read_only=1),
		],
	}


def seed_cost_heads(update=False):
	"""Insert missing heads. `update=True` (used by a patch) also brings existing seeded heads in line."""
	for name, group, calc, scope, seq, mandatory in COST_HEADS:
		if frappe.db.exists("Cost Head", name):
			if update:
				frappe.db.set_value(
					"Cost Head", name,
					{"head_group": group, "calc_type": calc, "material_scope": scope, "sequence": seq, "is_mandatory": mandatory},
					update_modified=False,
				)
				frappe.db.sql(
					"update `tabCosting Parameter Rate` set calc_type = %s where cost_head = %s", (calc, name)
				)
			continue
		frappe.get_doc(
			{
				"doctype": "Cost Head",
				"head_name": name,
				"head_group": group,
				"calc_type": calc,
				"material_scope": scope,
				"sequence": seq,
				"is_mandatory": mandatory,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)


def seed_product_types():
	for pt in PRODUCT_TYPES:
		if not frappe.db.exists("Product Type", pt):
			frappe.get_doc({"doctype": "Product Type", "product_type": pt}).insert(ignore_permissions=True)


def seed_sample_rules():
	"""Insert the default rule for every sample type that has none yet. Edits made on the site are never overwritten."""
	from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import DEFAULT_RULES

	have = set(frappe.get_all("Apparel Sample Rule", {"parent": "Apparel Settings"}, pluck="sample_type"))
	idx = frappe.db.count("Apparel Sample Rule", {"parent": "Apparel Settings"})
	for stype, (gate, per_colour, basis, days) in DEFAULT_RULES.items():
		if stype in have:
			continue
		idx += 1
		frappe.get_doc({
			"doctype": "Apparel Sample Rule", "parenttype": "Apparel Settings", "parent": "Apparel Settings",
			"parentfield": "sample_rules", "idx": idx, "sample_type": stype, "gate": gate, "per_colour": per_colour,
			"due_basis": basis, "days_before": days,
		}).db_insert()
