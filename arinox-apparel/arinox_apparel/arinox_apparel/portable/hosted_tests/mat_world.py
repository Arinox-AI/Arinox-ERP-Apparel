"""Fixtures for the materials tests: an order on a style with a submitted Tech Pack, suppliers, fabric and trim items, lab dips approved, and the warehouses."""
import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.test_gate import gate_order
from arinox_apparel.portable.hosted_tests.test_samples import sample


def supplier(name):
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert()
	return name


def warehouses():
	"""The five warehouses Apparel Settings names (created once), set in the settings."""
	out = {}
	for field, label in (("inspection_warehouse_fabric", "HT Inspect Fabric"), ("inspection_warehouse_trim", "HT Inspect Trim"), ("store_warehouse_fabric", "HT Store Fabric"),
						 ("store_warehouse_trim", "HT Store Trim"), ("rejected_warehouse", "HT Rejected")):
		name = frappe.db.get_value("Warehouse", {"warehouse_name": label, "company": fx.company()}, "name")
		if not name:
			name = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": label, "company": fx.company()}).insert().name
		frappe.db.set_single_value("Apparel Settings", field, name)
		out[field] = name
	return out


def call(script, **kw):
	return fx.engine_call(script, **kw)["arinox_result"]


def fabric_items():
	"""[Navy, Black] variants of the test fabric quality (created through the Create Fabric Items button)."""
	rows = [{"idx": i + 1, "fabric_description": "_ATQ-1, 100% Cotton, CW 132CM", "colour": c, "gsm": 145, "cuttable_width_cm": 132} for i, c in enumerate(("Navy", "Black"))]
	made = call("arinox_fabric_requisition_create_fabric_items", doc=json.dumps({"items": rows}))["arinox_doc"]["items"]
	return [m["fabric_item"] for m in made]


def world():
	"""Returns a dict: so, template, navy, black (variants), mill_a, mill_b, navy_fabric, black_fabric, wh."""
	so, template, navy, black = gate_order()
	tp = frappe.get_doc("Tech Pack", {"style_item": template})
	if tp.docstatus == 0:
		tp.submit()
	wh = warehouses()
	frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Warn")
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)     # site setup: roll bundles need it
	mill_a, mill_b = supplier("HT Mill A"), supplier("HT Mill B")
	nf, bf = fabric_items()
	for colour in ("Navy", "Black"):
		if not frappe.db.exists("Sample Approval", {"sample_type": "Lab Dip", "style_item": template, "colour": colour, "sales_order": so.name}):
			sample(so, "Lab Dip", colour=colour, style_item=template).insert()
	return {"so": so, "template": template, "navy": navy, "black": black, "mill_a": mill_a, "mill_b": mill_b, "navy_fabric": nf, "black_fabric": bf, "wh": wh}


def fr(w, colours=("Navy", "Black"), **kw):
	"""A draft Fabric Requisition with a fully filled line per colour (built through the Get Lines button)."""
	res = call("arinox_fabric_requisition_get_lines_from_sales_orders", doc=json.dumps({"customer": fx.customer(), "company": fx.company(), "items": []}),
			   sales_orders=json.dumps([w["so"].name]))
	rows = res["arinox_doc"]["items"]
	for r in rows:
		r.update(cuttable_width_cm=132, gsm=145, consumption_source="Cost Sheet", fabric_item=w["navy_fabric"] if r["colour"] == "Navy" else w["black_fabric"],
				 fabric_description="_ATQ-1, 100% Cotton, CW 132CM", supplier=w["mill_a"])
	rows = [r for r in rows if r["colour"] in colours]
	rows.sort(key=lambda r: r["colour"], reverse=True)               # Navy first, then Black
	d = {"doctype": "Fabric Requisition", "company": fx.company(), "customer": fx.customer(), "items": rows}
	d.update(kw)
	return frappe.get_doc(d)


def trim_item(code, description, category, uom="Nos", customer=None, provided=0):
	return call("arinox_trim_requisition_create_trim_items", doc=json.dumps({"customer": customer or fx.customer(), "items": [
		{"idx": 1, "buyer_item_code": code, "description": description, "trim_category": category, "consumption_uom": uom,
		 "calc_basis": "By Length" if uom == "Meter" else "Per Garment", "customer_provided": provided}]}))["arinox_doc"]["items"][0]["trim_item"]


def tr(w, rows, **kw):
	base = {"sales_order": w["so"].name, "style_item": w["template"], "calc_basis": "Per Garment", "supplier": w["mill_a"]}
	d = {"doctype": "Trim Requisition", "company": fx.company(), "customer": fx.customer(), "items": [dict(base, **r) for r in rows]}
	d.update(kw)
	return frappe.get_doc(d)


def make_pos(kind, name):
	return call("arinox_purchase_order_make_purchase_orders", requisition_type=kind, name=name)


def receive(po, qty=None):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	pr = make_purchase_receipt(po.name)
	if qty is not None:
		pr.items[0].qty = qty
	pr.insert()
	return pr


def received_fabric(w, rolls=10, each=88.2, late_days=1):
	"""FR (Navy, 882 m) -> PO -> receipt with a roll list, submitted."""
	f = fr(w, colours=("Navy",))
	f.insert()
	f.submit()
	po = frappe.get_doc("Purchase Order", make_pos("FR", f.name)[0])
	po.transaction_date = add_days(nowdate(), -20)
	po.schedule_date = add_days(nowdate(), -late_days)
	for i in po.items:
		i.rate = 3
		i.schedule_date = add_days(nowdate(), -late_days)
	po.save()
	po.submit()
	pr = receive(po)
	call("arinox_rolls_import_roll_list", pr_name=pr.name, row_name=pr.items[0].name, rolls=json.dumps(
		[{"roll_no": "R%02d" % (i + 1), "dye_lot": "L1", "length": each} for i in range(rolls)]), length_uom="Meter", update_row_qty=0)
	pr.reload()
	pr.submit()
	return f, po, pr


def bin_qty(item, wh):
	return frappe.utils.flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))
