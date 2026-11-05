"""Shared helpers for the Phase C requisitions: unit conversion, allowance rules, numbering, approvals lookup,
stock claims, Material Request creation, roll-ups. No company or buyer is named here; rules are data."""

import math

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import cint, flt, getdate, nowdate

YARD_M = 0.9144
ALIASES = {
	"m": "m", "meter": "m", "metre": "m", "mtr": "m", "mtrs": "m", "meters": "m", "metres": "m",
	"yd": "yd", "yds": "yd", "yard": "yd", "yards": "yd",
	"kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
}
FABRIC_ROLES = ("Shell", "Lining", "Pocketing", "Contrast", "Other")


def uom_kind(uom):
	return ALIASES.get((uom or "").strip().lower())


def to_metres(qty, uom, gsm=None, width_cm=None):
	"""Quantity of fabric in `uom` to metres. kg needs GSM and cuttable width: m = kg*1000 / (gsm * width_m)."""
	kind = uom_kind(uom)
	if kind == "m":
		return flt(qty)
	if kind == "yd":
		return flt(qty) * YARD_M
	if kind == "kg":
		if not flt(gsm) or not flt(width_cm):
			frappe.throw(_("GSM and cuttable width are needed to convert kg to metres."))
		return flt(qty) * 1000 / (flt(gsm) * flt(width_cm) / 100)
	frappe.throw(_("Cannot convert UOM {0} to metres. Use Meter, Yard or Kg for fabric.").format(uom))


def from_metres(metres, uom, gsm=None, width_cm=None):
	kind = uom_kind(uom)
	if kind == "m":
		return flt(metres)
	if kind == "yd":
		return flt(metres) / YARD_M
	if kind == "kg":
		if not flt(gsm) or not flt(width_cm):
			frappe.throw(_("GSM and cuttable width are needed to convert metres to kg."))
		return flt(metres) * (flt(gsm) * flt(width_cm) / 100) / 1000
	frappe.throw(_("Cannot convert metres to UOM {0}.").format(uom))


def parse_width_cm(text):
	"""'132CM', 'CW 152 cm', '57"', '56in' -> cm. None when no width is found."""
	import re

	if not text:
		return None
	t = str(text).strip().lower()
	m = re.search(r"(\d+(?:\.\d+)?)\s*(cm|\"|in\b|inch)", t)
	if not m:
		m = re.search(r"(\d+(?:\.\d+)?)", t)
		return flt(m.group(1)) if m else None
	v = flt(m.group(1))
	return round(v * 2.54, 1) if m.group(2) in ('"', "in", "inch") else v


def round_up_to_pack(qty, pack_size):
	qty = flt(qty)
	if flt(pack_size) > 0 and qty > 0:
		return math.ceil(round(qty / flt(pack_size), 9)) * flt(pack_size)
	return qty


def next_number(prefix, on_date=None):
	"""PREFIX + YY.MM.### with a counter that restarts each month (the same pattern as the contract number)."""
	on = getdate(on_date or nowdate())
	key = f"{prefix}{on.strftime('%y')}.{on.strftime('%m')}."
	return key + getseries(key, 3)


def settings():
	return frappe.get_cached_doc("Apparel Settings")


def fr_material_types():
	raw = settings().get("fr_material_types") or "Fabric\nLining\nContrast Fabric"
	return [t.strip() for t in raw.splitlines() if t.strip()]


# ---- allowance -----------------------------------------------------------------------------------------------

def get_allowance(material_type=None, trim_category=None, customer=None, item_group=None):
	"""Most specific enabled Material Allowance Rule: customer 4, trim category 2, material type 1, item group 1.
	Returns allowance %, pack size and minimum order qty (0 when nothing matches)."""
	best, best_score = None, 0
	for r in frappe.get_all("Material Allowance Rule", {"enabled": 1}, ["*"]):
		score = 0
		for field, value, weight in (
			("customer", customer, 4), ("trim_category", trim_category, 2), ("material_type", material_type, 1), ("item_group", item_group, 1),
		):
			if r.get(field):
				if r.get(field) != value:
					score = None
					break
				score += weight
		if score and score > best_score:
			best, best_score = r, score
	if not best:
		return frappe._dict(allowance_pct=0, pack_size=0, min_order_qty=0)
	return frappe._dict(allowance_pct=flt(best.allowance_pct), pack_size=flt(best.pack_size), min_order_qty=flt(best.min_order_qty))


# ---- order, tech pack, cost sheet, approvals ---------------------------------------------------------------------

def tech_pack_for(style_item):
	name = frappe.db.get_value("Tech Pack", {"style_item": style_item, "docstatus": 1}, "name", order_by="creation desc")
	return frappe.get_doc("Tech Pack", name) if name else None


def style_of(item_code):
	return frappe.db.get_value("Item", item_code, "variant_of") or item_code


def cost_sheet_for(sales_order, style_item):
	for it in frappe.get_all("Sales Order Item", {"parent": sales_order}, ["item_code", "apparel_cost_sheet"]):
		if it.apparel_cost_sheet and style_of(it.item_code) == style_item:
			return frappe.get_doc("Cost Sheet", it.apparel_cost_sheet)
	return None


def colour_matches(material_colour, garment_colour, all_colours):
	"""A Tech Pack material row with a colour belongs to that garment colour only; blank belongs to all."""
	mc = (material_colour or "").strip().upper()
	if not mc:
		return True
	if mc == (garment_colour or "").strip().upper():
		return True
	return mc not in {(c or "").strip().upper() for c in all_colours}


def approval_info(sales_order, style_item, sample_type, colour=None, customer=None):
	"""(status text, ok) for one sample type of a style x colour on an order. ok = the gate would let it pass."""
	from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import (
		GATE_OK, effective_gate, get_rules, norm, scope_filters,
	)

	rule = get_rules(customer, sales_order, style_item).get(sample_type)
	gate = effective_gate(rule, sales_order) if rule else "No"
	rows = frappe.get_all(
		"Sample Approval", scope_filters(sales_order, style_item) | {"sample_type": sample_type}, ["name", "status", "colour"]
	)
	if rule and rule.per_colour:
		rows = [r for r in rows if not (r.colour or "").strip() or norm(r.colour) == norm(colour)]
	if not rows:
		return ("Not Required", True) if gate == "No" else ("Not Raised", gate != "Required")
	bad = [r for r in rows if r.status not in GATE_OK]
	if bad:
		return bad[0].status, False
	return "Approved", True


# ---- stock claims ------------------------------------------------------------------------------------------------

def free_stock(item_code, warehouse, parent_dt, child_dt, exclude=None):
	"""Actual stock minus the stock already claimed by other approved requisitions (not superseded, not cancelled)."""
	if not item_code or not warehouse:
		return 0.0
	actual = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
	item_field = "fabric_item" if parent_dt == "Fabric Requisition" else "trim_item"
	claimed = frappe.db.sql(
		f"""select coalesce(sum(c.stock_used), 0) from `tab{child_dt}` c join `tab{parent_dt}` p on p.name = c.parent
		where c.{item_field} = %s and c.stock_warehouse = %s and p.docstatus = 1 and p.status != 'Superseded'
		and p.name != %s""",
		(item_code, warehouse, exclude or ""),
	)[0][0]
	return actual - flt(claimed)


# ---- Material Request creation -----------------------------------------------------------------------------------

def item_has_uom(item_code, uom):
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	return uom == stock_uom or bool(frappe.db.exists("UOM Conversion Detail", {"parent": item_code, "uom": uom}))


def mr_line(item_code, qty_stock, order_uom=None, order_qty=None):
	"""(qty, uom, conversion_factor) for a Material Request row: the order UOM when the item has it, else stock UOM."""
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if order_uom and order_uom != stock_uom and flt(order_qty) > 0 and item_has_uom(item_code, order_uom):
		cf = flt(frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": order_uom}, "conversion_factor")) or 1
		return flt(order_qty), order_uom, cf
	return flt(qty_stock), stock_uom, 1


def company_warehouse(field, company):
	"""The warehouse named in Apparel Settings `field`, or its equivalent in `company` (created when missing). Settings hold
	one warehouse per role; a group with several Companies needs the same role in each."""
	wh = settings().get(field)
	if not wh or not company:
		return wh
	wc, base = frappe.db.get_value("Warehouse", wh, ["company", "warehouse_name"])
	if wc == company:
		return wh
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{base} - {abbr}"
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc({"doctype": "Warehouse", "warehouse_name": base, "company": company}).insert(ignore_permissions=True)
	return name


def create_material_requests(doc, lines, requisition_type, kind):
	"""Group `lines` by (supplier, customer-provided) and make one Material Request per group.
	Each line: item_code, qty, uom, conversion_factor, supplier, required_by, key, style_no, colour, hold_reason,
	customer_provided, sales_order, description. Returns the Material Request names."""
	if not lines:
		return []
	s = settings()
	warehouse = company_warehouse("inspection_warehouse_fabric" if kind == "Fabric" else "inspection_warehouse_trim", doc.company)
	groups = {}
	for ln in lines:
		groups.setdefault((ln.get("supplier") or "", cint(ln.get("customer_provided"))), []).append(ln)
	names = []
	for (supplier, provided), rows in groups.items():
		mr = frappe.new_doc("Material Request")
		mr.material_request_type = "Customer Provided" if provided else "Purchase"
		mr.company = doc.company
		mr.transaction_date = nowdate()
		mr.schedule_date = min(getdate(r["required_by"]) for r in rows if r.get("required_by")) if any(r.get("required_by") for r in rows) else nowdate()
		if provided:
			mr.customer = doc.customer
		mr.title = f"{doc.name} {supplier or 'no supplier'}"[:140]
		for r in rows:
			mr.append("items", {
				"item_code": r["item_code"], "qty": r["qty"], "uom": r["uom"], "conversion_factor": r.get("conversion_factor") or 1,
				"schedule_date": r.get("required_by") or mr.schedule_date, "warehouse": warehouse,
				"sales_order": r.get("sales_order"), "description": (r.get("description") or "")[:500] or None,
				"apparel_requisition_type": requisition_type, "apparel_requisition": doc.name, "apparel_requisition_item": r["key"],
				"apparel_style_no": r.get("style_no"), "apparel_colour": r.get("colour"), "apparel_hold_reason": r.get("hold_reason"),
			})
		mr.flags.ignore_permissions = True
		mr.insert()
		if cint(s.get("auto_submit_material_request")):
			mr.submit()
		names.append(mr.name)
	return names


def requested_so_far(requisition_type, chain_names, key):
	"""Stock qty already requested for this line key by every document in the revision chain."""
	if not chain_names:
		return 0.0
	rows = frappe.db.sql(
		"""select coalesce(sum(i.stock_qty), 0) from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
		where i.apparel_requisition_type = %s and i.apparel_requisition in %s and i.apparel_requisition_item = %s and m.docstatus < 2""",
		(requisition_type, tuple(chain_names), key),
	)
	return flt(rows[0][0])


def revision_chain(doctype, previous_field, name):
	"""Names of this document and every earlier revision."""
	chain, cur = [], name
	while cur and cur not in chain:
		chain.append(cur)
		cur = frappe.db.get_value(doctype, cur, previous_field)
	return chain


def stamp_safe(*args, **kwargs):
	"""Stamp a T&A milestone. Never raises: a T&A problem must not block a purchase, a receipt or a requisition."""
	try:
		from arinox_apparel.tna.events import stamp

		stamp(*args, **kwargs)
	except ImportError:
		pass
	except Exception:
		frappe.log_error(title="T&A stamp failed", message=frappe.get_traceback())


def stamp_safe_requisition(doc, code):
	"""Stamp `code` for every style x colour on a requisition."""
	seen = set()
	for r in doc.items:
		k = (r.sales_order, r.style_item, (r.colour or "").strip().upper())
		if k in seen:
			continue
		seen.add(k)
		stamp_safe(r.sales_order, r.style_item, r.colour, code, nowdate(), doc.doctype, doc.name)


def unstamp_safe(doctype, name):
	try:
		from arinox_apparel.tna.events import unstamp

		unstamp(doctype, name)
	except ImportError:
		pass
	except Exception:
		frappe.log_error(title="T&A unstamp failed", message=frappe.get_traceback())
