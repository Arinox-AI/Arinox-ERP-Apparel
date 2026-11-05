"""The few ERPNext Stock Entries Phase D makes (plan section 3.3): fabric issue to the cutting floor, remnant return,
trim issue. Production tracking itself is quantity based; stock only moves where a physical store hands goods over."""

import frappe
from frappe import _
from frappe.utils import cint, flt

KINDS = ("Fabric Issue", "Remnant Return", "Trim Issue")


def setting(field):
	return frappe.db.get_single_value("Apparel Settings", field)


def roll_available(batch, warehouse=None, item_code=None):
	"""Metres of a roll (Batch) in a warehouse. 0 when the warehouse is unknown."""
	if not warehouse:
		return 0
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	return flt(get_batch_qty(batch_no=batch, warehouse=warehouse, item_code=item_code))


def make_transfer(company, rows, kind, card, remarks, submit=True):
	"""Material Transfer for `rows` = dicts(item_code, qty, s_warehouse, t_warehouse, batch_no=None). Returns the name,
	or None when nothing moves. The entry is tagged with the production card and the kind so reports can sum it."""
	rows = [r for r in rows if flt(r.get("qty")) > 0]
	if not rows:
		return None
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = company
	se.apparel_production_card = card
	se.apparel_issue_kind = kind
	for r in rows:
		line = {"item_code": r["item_code"], "qty": r["qty"], "s_warehouse": r["s_warehouse"], "t_warehouse": r["t_warehouse"]}
		if r.get("batch_no"):
			line.update({"batch_no": r["batch_no"], "use_serial_batch_fields": 1})
		se.append("items", line)
	se.remarks = remarks
	se.flags.ignore_permissions = True
	se.insert()
	if submit:
		se.submit()
	return se.name


def cancel_entry(name):
	if name and frappe.db.exists("Stock Entry", name):
		d = frappe.get_doc("Stock Entry", name)
		d.flags.ignore_permissions = True
		if d.docstatus == 1:
			d.cancel()
		elif d.docstatus == 0:
			frappe.delete_doc("Stock Entry", name, ignore_permissions=True, force=True)


def moved(card, kind, item_code=None):
	"""Quantity moved by submitted entries of this kind for a production card (optionally one item)."""
	cond, args = "", [card, kind]
	if item_code:
		cond, args = " and d.item_code = %s", [card, kind, item_code]
	return flt(frappe.db.sql(
		f"""select ifnull(sum(d.qty), 0) from `tabStock Entry Detail` d join `tabStock Entry` s on s.name = d.parent
		where s.docstatus = 1 and s.apparel_production_card = %s and s.apparel_issue_kind = %s{cond}""", args)[0][0])


def issue_fabric_entry(card_name, rolls, submit=None):
	"""Issue rolls from the fabric store to Cutting WIP. rolls = [{batch_no, qty}]. Only accepted rolls leave the store."""
	card = frappe.get_doc("Production Card", card_name)
	if card.docstatus != 1:
		frappe.throw(_("Issue the production card first."))
	src, dst = setting("store_warehouse_fabric"), setting("cutting_wip_warehouse")
	if not src or not dst:
		frappe.throw(_("Set the fabric store and Cutting WIP warehouses in Apparel Settings."))
	items = []
	for r in rolls:
		b = frappe.db.get_value("Batch", r["batch_no"], ["item", "apparel_inspection_status", "apparel_roll_no"], as_dict=True)
		if not b:
			frappe.throw(_("Roll {0} not found.").format(r["batch_no"]))
		if b.apparel_inspection_status not in ("Accepted", "Accepted by Lot"):
			frappe.throw(_("Roll {0} is {1}. Only accepted rolls can be issued to cutting.").format(b.apparel_roll_no or r["batch_no"], b.apparel_inspection_status or _("not inspected")))
		if b.item not in {f.fabric_item for f in card.fabrics}:
			frappe.throw(_("Roll {0} is {1}, which is not a fabric of production card {2}.").format(b.apparel_roll_no or r["batch_no"], b.item, card.name))
		items.append({"item_code": b.item, "qty": flt(r["qty"]), "s_warehouse": src, "t_warehouse": dst, "batch_no": r["batch_no"]})
	name = make_transfer(card.company, items, "Fabric Issue", card.name, _("Fabric issued to cutting for {0}").format(card.name), submit=True if submit is None else submit)
	refresh_issued(card.name)
	return name


def refresh_issued(card):
	"""Write the issued metres onto the fabric rows of an issued card (an issued card is not re-validated, so this is
	set here). A fabric item used for two colours is split by what each colour's lays have used; until then it is shown
	on the first row."""
	done = set()
	for row in frappe.get_all("Production Card Fabric", {"parent": card}, ["name", "fabric_item"], order_by="idx"):
		if not row.fabric_item or row.fabric_item in done:
			continue
		done.add(row.fabric_item)
		frappe.db.set_value("Production Card Fabric", row.name, "issued_m", moved(card, "Fabric Issue", row.fabric_item), update_modified=False)
