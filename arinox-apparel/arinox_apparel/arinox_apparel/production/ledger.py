"""The Production Movement ledger: every stage document writes its quantities here, and reports sum them.

post() is called from a document's on_submit, unpost() from its on_cancel. The source document stays the truth:
`rebuild_movements` recomputes the whole ledger of a card from the submitted documents."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from arinox_apparel.production.flow import Flow

STAGES = (
	"CUT", "CUT_REJECT", "SEW_IN", "SEW_OUT", "SEW_REJECT", "SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR",
	"SC_BACK_REJECT_FACTORY", "FIN_IN", "FIN_A", "FIN_B", "FIN_REJECT", "SAMPLE_OUT", "PACKED", "SHIPPED",
)

# Doctypes that write to the ledger: (doctype, name of the production card field). A doctype whose card sits in
# its rows rather than its header lists the child doctype instead. Filled in as each slice is built.
LEDGER_SOURCES = [
	("Production Adjustment", "production_card", None),
	("Lay Report", "production_card", None),
	("Line Input", "production_card", None),
	("Daily Line Report", "production_card", "Daily Line Report Output"),
	("Line QC Report", "production_card", None),
	("Subcontract Challan", "production_card", None),
	("Subcontract Return", None, "Subcontract Return Row"),
	("Finishing Receipt", "production_card", None),
	("Packing List", "production_card", None),
]


def post(card, rows, source_doctype, source_name, posting_date=None, override=False, check=True):
	"""Write `rows` (dicts: stage, colour, size, qty, purpose, process, line, supplier, shade_band, fault_source,
	source_row) to the ledger for production card `card`. Raises if a row exceeds the flow rules unless `override`."""
	rows = [dict(r) for r in rows if r.get("qty")]
	if not rows:
		return
	for r in rows:
		if r["stage"] not in STAGES:
			frappe.throw(_("Unknown production stage {0}.").format(r["stage"]))
		r["colour"] = (r.get("colour") or "").strip()
		r["size"] = (r.get("size") or "").strip()
		r["qty"] = float(r["qty"])
		r.setdefault("purpose", "Bulk")
	if check:
		Flow(card).check(rows, override=override)
	card_doc = frappe.db.get_value("Production Card", card, ["sales_order", "style_item"], as_dict=True)
	for r in rows:
		mv = frappe.get_doc({
			"doctype": "Production Movement", "production_card": card, "sales_order": card_doc.sales_order,
			"style_item": card_doc.style_item, "colour": r["colour"], "size": r["size"], "stage": r["stage"],
			"purpose": r["purpose"], "subcontract_process": r.get("process") or None, "qty": r["qty"],
			"posting_date": getdate(posting_date or nowdate()), "line": r.get("line") or None,
			"supplier": r.get("supplier") or None, "shade_band": r.get("shade_band") or None,
			"fault_source": r.get("fault_source") or None, "source_doctype": source_doctype, "source_name": source_name,
			"source_row": r.get("source_row"),
		})
		mv.flags.ignore_links = True  # the source document is mid-submit; the ledger never blocks on it
		mv.insert(ignore_permissions=True)
	refresh_card_status(card)


def unpost(source_doctype, source_name):
	"""A source document was cancelled: remove what it wrote."""
	cards = frappe.db.sql_list("select distinct production_card from `tabProduction Movement` where source_doctype = %s and source_name = %s", (source_doctype, source_name))
	frappe.db.delete("Production Movement", {"source_doctype": source_doctype, "source_name": source_name})
	for c in cards:
		refresh_card_status(c)


STATUS_BY_STAGE = [("SHIPPED", "Shipped"), ("PACKED", "Packed"), ("FIN_IN", "In Finishing"), ("SC_OUT", "At Subcontractor"), ("SEW_IN", "In Sewing"), ("CUT", "In Cutting")]


def refresh_card_status(card):
	"""Card status follows the furthest stage that has quantities. Closed, Superseded and Cancelled cards are left alone."""
	row = frappe.db.get_value("Production Card", card, ["docstatus", "status"], as_dict=True)
	if not row or row.docstatus != 1 or row.status in ("Superseded", "Cancelled", "Closed"):
		return
	present = set(frappe.db.sql_list("select distinct stage from `tabProduction Movement` where production_card = %s", card))
	status = next((label for stage, label in STATUS_BY_STAGE if stage in present), "Issued")
	if status != row.status:
		frappe.db.set_value("Production Card", card, "status", status, update_modified=False)


def totals(card, purpose=None):
	"""{(colour, size): {stage: qty}} for one card."""
	cond, args = "", [card]
	if purpose:
		cond, args = " and purpose = %s", [card, purpose]
	out = {}
	for colour, size, stage, qty in frappe.db.sql(
		f"select colour, size, stage, sum(qty) from `tabProduction Movement` where production_card = %s{cond} group by colour, size, stage", args):
		out.setdefault((colour, size), {})[stage] = qty or 0
	return out


def stage_total(card, stage, colour=None, size=None, purpose=None):
	cond, args = "", [card, stage]
	for field, val in (("colour", colour), ("size", size), ("purpose", purpose)):
		if val is not None:
			cond += f" and {field} = %s"
			args.append(val)
	return frappe.db.sql(f"select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card = %s and stage = %s{cond}", args)[0][0]


def rebuild_movements(card):
	"""Recompute the ledger of one card from its submitted source documents (a repair tool). Returns the number of
	rows written. Each source document implements `post_movements(check=False)`."""
	frappe.db.delete("Production Movement", {"production_card": card})
	written = 0
	for doctype, field, child in LEDGER_SOURCES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if child:
			cf = field or "production_card"
			names = frappe.db.sql_list(f"select distinct parent from `tab{child}` where {cf} = %s", card)
		elif field and frappe.get_meta(doctype).has_field(field):
			names = frappe.get_all(doctype, {field: card}, pluck="name")
		else:
			continue
		for name in names:
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus != 1 or not hasattr(doc, "post_movements"):
				continue
			before = frappe.db.count("Production Movement", {"production_card": card})
			doc.post_movements(check=False)
			written += frappe.db.count("Production Movement", {"production_card": card}) - before
	# Delivery Notes are ERPNext documents: their rows carry the card, and our poster reads them
	if frappe.get_meta("Delivery Note Item").has_field("apparel_production_card"):
		from arinox_apparel.shipping import delivery

		for name in frappe.db.sql_list("select distinct parent from `tabDelivery Note Item` where apparel_production_card = %s and docstatus = 1", card):
			before = frappe.db.count("Production Movement", {"production_card": card})
			delivery.post_movements(frappe.get_doc("Delivery Note", name), check=False, only_card=card)
			written += frappe.db.count("Production Movement", {"production_card": card}) - before
	return written


def transfer_card(old, new):
	"""A revision of a production card keeps the history: every ledger row and stage document that points at the old
	card is pointed at the new one (the old card is Superseded and shows nothing). Done in SQL on purpose: submitted
	documents are not edited, only their link to the live card moves."""
	if not old or old == new:
		return 0
	moved = 0
	seen = set()
	for dt in frappe.get_all("DocField", {"fieldname": "production_card", "fieldtype": "Link", "options": "Production Card"}, pluck="parent"):
		if dt in ("Production Card", "Production Card Line") or dt in seen or not frappe.db.table_exists(dt):
			continue
		seen.add(dt)
		frappe.db.sql(f"update `tab{dt}` set production_card = %s where production_card = %s", (new, old))
		moved += frappe.db.sql("select row_count()")[0][0]
	return moved
