"""Fabric roll list import: one Batch per roll, one Serial and Batch Bundle per Purchase Receipt row."""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt

from arinox_apparel.materials import common as mc


def parse_roll_text(text):
	"""Lines of 'roll no, dye lot, length[, width]' (tab, comma or semicolon separated) -> list of dicts. A header line,
	a blank line or a line without a numeric length is skipped."""
	rolls = []
	for line in (text or "").splitlines():
		parts = [p.strip() for p in re.split(r"[\t,;]+|\s{2,}", line.strip()) if p.strip()]
		if len(parts) < 3:
			continue
		try:
			length = float(parts[2])
		except ValueError:
			continue
		rolls.append({"roll_no": parts[0], "dye_lot": parts[1], "length": length, "width_cm": float(parts[3]) if len(parts) > 3 and re.match(r"^\d+(\.\d+)?$", parts[3]) else None})
	return rolls


def clean_rolls(rolls):
	out, seen = [], set()
	for r in rolls:
		roll_no = str(r.get("roll_no") or "").strip()
		if not roll_no:
			frappe.throw(_("Every roll needs a roll number."))
		if roll_no.upper() in seen:
			frappe.throw(_("Roll number {0} appears twice in the list.").format(roll_no))
		seen.add(roll_no.upper())
		length = flt(r.get("length"))
		if length <= 0:
			frappe.throw(_("Roll {0}: the length must be more than zero.").format(roll_no))
		out.append({"roll_no": roll_no, "dye_lot": (r.get("dye_lot") or "").strip(), "length": length, "width_cm": flt(r.get("width_cm")) or None})
	if not out:
		frappe.throw(_("The roll list is empty."))
	return out


def forget_previous_import(pr, row):
	"""A re-import replaces the draft bundle and the batches this receipt made."""
	bundle = row.get("serial_and_batch_bundle")
	if not bundle:
		return
	old = frappe.get_doc("Serial and Batch Bundle", bundle)
	if old.docstatus != 0:
		frappe.throw(_("Row {0} already has a submitted roll bundle.").format(row.idx))
	batches = [e.batch_no for e in old.entries if e.batch_no]
	row.db_set({"serial_and_batch_bundle": None, "use_serial_batch_fields": 0})
	frappe.delete_doc("Serial and Batch Bundle", bundle, ignore_permissions=True, force=True)
	for b in set(batches):
		if frappe.db.get_value("Batch", b, "reference_name") == pr.name:
			frappe.delete_doc("Batch", b, ignore_permissions=True, force=True)


@frappe.whitelist()
def import_roll_list(pr_name, row_name, rolls, length_uom="Meter", update_row_qty=0):
	"""Make a Batch per roll and the bundle for one row of a draft Purchase Receipt. `rolls` is a JSON list or pasted text.
	The roll total must equal the row quantity unless `update_row_qty` is set."""
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation

	pr = frappe.get_doc("Purchase Receipt", pr_name)
	pr.check_permission("write")
	if pr.docstatus != 0:
		frappe.throw(_("Roll lists can only be imported into a draft receipt."))
	row = next((r for r in pr.items if r.name == row_name), None)
	if not row:
		frappe.throw(_("Row not found on {0}.").format(pr_name))
	if not frappe.db.get_value("Item", row.item_code, "has_batch_no"):
		frappe.throw(_("{0} is not batch tracked, so it has no rolls.").format(row.item_code))
	if isinstance(rolls, str):
		try:
			rolls = json.loads(rolls)
		except ValueError:
			rolls = parse_roll_text(rolls)
	rolls = clean_rolls(rolls)
	stock_uom = frappe.db.get_value("Item", row.item_code, "stock_uom")
	gsm = frappe.db.get_value("Item", row.item_code, "apparel_fabric_gsm")
	for r in rolls:
		r["metres"] = mc.to_metres(r["length"], length_uom, gsm, r["width_cm"] or frappe.db.get_value("Item", row.item_code, "apparel_fabric_width_cm"))
	total = sum(r["metres"] for r in rolls)
	stock_qty = flt(row.stock_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1)
	if abs(total - stock_qty) > max(0.005 * stock_qty, 0.01):
		if not cint(update_row_qty):
			frappe.throw(_("The roll list adds up to {0} {1} but the receipt row says {2}. Fix the list, or change the row quantity.").format(
				flt(total, 2), stock_uom, flt(stock_qty, 2)))
		row.qty = total / (flt(row.conversion_factor) or 1)
		row.received_qty = row.qty + flt(row.rejected_qty)
		pr.save()
		row = next(r for r in pr.items if r.name == row_name)
	forget_previous_import(pr, row)
	supplier = pr.supplier
	made = {}
	for r in rolls:
		bid = f"{pr.name}-{r['roll_no']}"[:140]
		if frappe.db.exists("Batch", bid):
			frappe.throw(_("Batch {0} already exists. Roll numbers must be unique within a receipt.").format(bid))
		b = frappe.get_doc({
			"doctype": "Batch", "batch_id": bid, "item": row.item_code, "supplier": supplier, "reference_doctype": "Purchase Receipt",
			"reference_name": pr.name, "apparel_roll_no": r["roll_no"], "apparel_dye_lot": r["dye_lot"], "apparel_ticket_length": r["metres"],
			"apparel_width_cm": r["width_cm"], "apparel_inspection_status": "Uninspected",
		})
		b.flags.ignore_permissions = True
		b.insert()
		made[b.name] = flt(r["metres"], 6)
	bundle = SerialBatchCreation({
		"item_code": row.item_code, "warehouse": row.warehouse, "type_of_transaction": "Inward", "voucher_type": "Purchase Receipt",
		"voucher_no": pr.name, "voucher_detail_no": row.name, "company": pr.company, "posting_date": pr.posting_date,
		"posting_time": pr.posting_time, "do_not_submit": True, "qty": total,
	}).make_serial_and_batch_bundle(batch_nos=made)
	row.db_set({"serial_and_batch_bundle": bundle.name, "use_serial_batch_fields": 0, "batch_no": None})
	return {"rolls": len(made), "total": flt(total, 2), "bundle": bundle.name}


def check_rolls_before_submit(doc):
	"""A fabric row from an FR needs its roll list before the receipt can be submitted."""
	for pri in doc.items:
		if not pri.get("purchase_order_item"):
			continue
		kind = frappe.db.get_value("Purchase Order Item", pri.purchase_order_item, "apparel_requisition_type")
		if kind == "FR" and frappe.db.get_value("Item", pri.item_code, "has_batch_no") and not (pri.get("serial_and_batch_bundle") or pri.get("batch_no")):
			frappe.throw(_("Row {0} ({1}): import the roll list before submitting. Each fabric roll is tracked.").format(pri.idx, pri.item_code))
