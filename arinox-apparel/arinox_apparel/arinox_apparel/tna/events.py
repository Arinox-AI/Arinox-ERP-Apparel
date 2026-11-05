"""Auto-stamping of milestone actuals from the documents that prove them. One place, never raises into the caller:
a T&A problem must not block a purchase, a receipt or an approval."""

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

from arinox_apparel.tna.status import refresh_order_tna

SAMPLE_CODES = {
	"Lab Dip": "LAB_DIP", "Fit": "FIT", "Bulk Trim": "TRIMS_APPROVED", "Bulk Fabric": "BULK_FABRIC_APPROVED", "Fabric Test (FPT)": "FPT_PASSED",
	"TOP": "TOP", "Size Set": "TOP",
}
PP_TYPES = ("PP", "Garment Test (GPT)")


def norm(c):
	return (c or "").strip().upper()


def tnas_for(sales_order, style_item, colour=None):
	filters = {"style_item": style_item, "status": ["!=", "Cancelled"]}
	if sales_order:
		filters["sales_order"] = sales_order
	rows = frappe.get_all("Order TNA", filters, ["name", "colour", "sales_order", "style_item"])
	return [r for r in rows if not colour or not norm(r.colour) or norm(r.colour) == norm(colour)]


def _milestone(tna, code):
	name = frappe.db.get_value("TNA Milestone", {"order_tna": tna, "milestone_type": code}, "name")
	return frappe.get_doc("TNA Milestone", name) if name else None


def stamp(sales_order, style_item, colour, code, date, source_doctype, source_name, partial=False, planned=False):
	"""Record that `code` happened on `date` for every Order TNA of this style x colour. An existing actual from another
	document is never overwritten. `planned=True` moves the revised date instead (for a supplier's planned ETD)."""
	for t in tnas_for(sales_order, style_item, colour):
		ms = _milestone(t.name, code)
		if not ms or cint(ms.not_applicable):
			continue
		changed = False
		if planned:
			if not ms.actual_date and date and getdate(date) != getdate(ms.planned_date):
				ms.revised_date = getdate(date)
				ms.revision_reason = ms.revision_reason or _("Supplier plan ({0})").format(source_name)
				changed = True
		elif partial:
			if not ms.actual_date and not cint(ms.partial):
				ms.partial, ms.source_doctype, ms.source_name = 1, source_doctype, source_name
				changed = True
		else:
			same = ms.source_doctype == source_doctype and ms.source_name == source_name
			if not ms.actual_date or same:
				ms.actual_date, ms.partial = getdate(date or nowdate()), 0
				ms.source_doctype, ms.source_name = source_doctype, source_name
				changed = True
		if changed:
			ms.flags.ignore_permissions = True
			ms.save()


def unstamp(source_doctype, source_name):
	"""A source document was cancelled: clear what it stamped, then look for another document that proves the same thing."""
	for name in frappe.get_all("TNA Milestone", {"source_doctype": source_doctype, "source_name": source_name}, pluck="name"):
		ms = frappe.get_doc("TNA Milestone", name)
		ms.actual_date, ms.partial, ms.source_doctype, ms.source_name = None, 0, None, None
		ms.flags.ignore_permissions = True
		ms.save()
		refind(ms)


def refind(ms):
	"""Best-effort: set `ms` from another live document of the right kind."""
	tna = frappe.db.get_value("Order TNA", ms.order_tna, ["sales_order", "style_item", "colour"], as_dict=True)
	found = None
	code = ms.milestone_type
	if code in ("FR_RAISED", "TR_RAISED"):
		dt, child = ("Fabric Requisition", "Fabric Requisition Item") if code == "FR_RAISED" else ("Trim Requisition", "Trim Requisition Item")
		r = frappe.db.sql(
			f"""select p.name, date(p.approved_on) from `tab{dt}` p join `tab{child}` c on c.parent = p.name where p.docstatus = 1 and p.status != 'Cancelled'
			and c.sales_order = %s and c.style_item = %s and (c.colour is null or c.colour = '' or upper(c.colour) = upper(%s)) order by p.approved_on limit 1""",
			(tna.sales_order, tna.style_item, tna.colour or ""))
		found = (dt, r[0][0], r[0][1]) if r else None
	elif code == "FABRIC_BOOKED":
		r = frappe.db.sql(
			"""select o.name, o.transaction_date from `tabPurchase Order` o join `tabPurchase Order Item` i on i.parent = o.name where o.docstatus = 1
			and i.apparel_requisition_type = 'FR' and i.sales_order = %s and upper(i.apparel_colour) = upper(%s) order by o.creation limit 1""", (tna.sales_order, tna.colour or ""))
		found = ("Purchase Order", r[0][0], r[0][1]) if r else None
	if found:
		ms.reload()
		ms.actual_date, ms.source_doctype, ms.source_name = getdate(found[2]), found[0], found[1]
		ms.flags.ignore_permissions = True
		ms.save()


# ---- sample approvals ---------------------------------------------------------------------------------------------------

def sync_samples(tna):
	"""Set the approval milestones of one Order TNA from the Sample Approvals that apply to it."""
	from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import APPROVED, scope_filters
	from arinox_apparel.materials.common import approval_info

	so = frappe.db.get_value("Order TNA", tna.name, ["sales_order", "style_item", "colour", "customer"], as_dict=True)

	def dates_for(types):
		rows = frappe.get_all("Sample Approval", scope_filters(so.sales_order, so.style_item) | {"sample_type": ["in", list(types)], "status": ["in", list(APPROVED)]},
			["name", "colour", "approved_on", "sample_type"])
		return [(r.name, r.approved_on) for r in rows if r.approved_on and (not norm(r.colour) or norm(r.colour) == norm(so.colour))]

	for code in set(SAMPLE_CODES.values()) | {"PP_GPT"}:
		ms = _milestone(tna.name, code)
		if not ms or cint(ms.not_applicable):
			continue
		types = [t for t, c in SAMPLE_CODES.items() if c == code] if code != "PP_GPT" else list(PP_TYPES)
		ok = all(approval_info(so.sales_order, so.style_item, t, so.colour, so.customer)[1] for t in types)
		done = dates_for(types) if ok else []
		if code == "PP_GPT":
			# needs the PP approved (GPT only when the rules ask for it)
			ok = bool(dates_for(["PP"])) and approval_info(so.sales_order, so.style_item, "Garment Test (GPT)", so.colour, so.customer)[1]
			done = dates_for(PP_TYPES) if ok else []
		elif code == "TOP":
			ok = bool(done)
		if done and (ok or code != "PP_GPT"):
			name, date = max(done, key=lambda d: d[1])
			if not ms.actual_date or (ms.source_doctype == "Sample Approval"):
				ms.actual_date, ms.partial, ms.source_doctype, ms.source_name = getdate(date), 0, "Sample Approval", name
				ms.flags.ignore_permissions = True
				ms.save()
		elif ms.source_doctype == "Sample Approval" and ms.actual_date:
			ms.actual_date, ms.source_doctype, ms.source_name = None, None, None
			ms.flags.ignore_permissions = True
			ms.save()


def backfill(order_tna):
	"""A T&A made after the fact picks up what already happened."""
	tna = frappe.get_doc("Order TNA", order_tna)
	stamp(tna.sales_order, tna.style_item, tna.colour, "ORDER_RECEIVED", tna.order_received_date, "Sales Order", tna.sales_order)
	tp = frappe.db.get_value("Tech Pack", {"style_item": tna.style_item, "docstatus": 1}, ["name", "received_on", "buyer_bom_file"], as_dict=True, order_by="creation")
	if tp:
		stamp(tna.sales_order, tna.style_item, tna.colour, "TECH_PACK_RECEIVED", tp.received_on or nowdate(), "Tech Pack", tp.name)
		if tp.buyer_bom_file:
			stamp(tna.sales_order, tna.style_item, tna.colour, "BOM_RECEIVED", tp.received_on or nowdate(), "Tech Pack", tp.name)
	sync_samples(tna)
	for code in ("FR_RAISED", "TR_RAISED", "FABRIC_BOOKED"):
		ms = _milestone(tna.name, code)
		if ms and not ms.actual_date and not cint(ms.not_applicable):
			refind(ms)
	for m in frappe.get_all("PP Meeting", {"sales_order": tna.sales_order, "style_item": tna.style_item, "docstatus": 1}, ["name", "meeting_date", "meeting_type"]):
		stamp(tna.sales_order, tna.style_item, tna.colour, "PILOT_RUN" if m.meeting_type == "Pilot Run" else "PP_MEETING", m.meeting_date, "PP Meeting", m.name)
	refresh_order_tna(tna.name)


# ---- document hooks (wired in hooks.py) -------------------------------------------------------------------------------

def _safe(fn):
	def wrapper(doc, method=None):
		try:
			fn(doc, method)
		except Exception:
			frappe.log_error(title=f"T&A hook {fn.__name__} failed", message=frappe.get_traceback())
	wrapper.__name__ = fn.__name__
	return wrapper


@_safe
def on_tech_pack(doc, method=None):
	if doc.docstatus != 1 or not doc.style_item:
		return
	for t in tnas_for(None, doc.style_item):
		stamp(t.sales_order, doc.style_item, t.colour, "TECH_PACK_RECEIVED", doc.received_on or nowdate(), "Tech Pack", doc.name)
		if doc.buyer_bom_file:
			stamp(t.sales_order, doc.style_item, t.colour, "BOM_RECEIVED", doc.received_on or nowdate(), "Tech Pack", doc.name)


@_safe
def on_sample_approval(doc, method=None):
	for t in tnas_for(doc.sales_order, doc.style_item, doc.colour):
		sync_samples(frappe._dict(name=t.name))
		refresh_order_tna(t.name)


@_safe
def on_pp_meeting(doc, method=None):
	if method == "on_cancel":
		unstamp("PP Meeting", doc.name)
		return
	code = "PILOT_RUN" if doc.meeting_type == "Pilot Run" else "PP_MEETING"
	stamp(doc.sales_order, doc.style_item, None, code, doc.meeting_date, "PP Meeting", doc.name)


@_safe
def on_factory_allocation(doc, method=None):
	from arinox_apparel.tna.planner import replan

	for name in frappe.get_all("Order TNA", {"sales_order": doc.sales_order, "status": ["!=", "Cancelled"]}, pluck="name"):
		replan(name)


@_safe
def on_work_order(doc, method=None):
	if not doc.get("sales_order") or not doc.get("actual_start_date"):
		return
	style = frappe.db.get_value("Item", doc.production_item, "variant_of")
	if style:
		from arinox_apparel.overrides.work_order import style_and_colour

		_s, colour = style_and_colour(doc.production_item)
		stamp(doc.sales_order, style, colour, "PCD", getdate(doc.actual_start_date), "Work Order", doc.name)


@_safe
def on_sales_order_submit(doc, method=None):
	from arinox_apparel.tna.planner import make_order_tnas

	if frappe.db.get_single_value("Apparel Settings", "default_tna_template") and doc.get("apparel_sales_contract"):
		make_order_tnas(doc.name)


@_safe
def on_sales_order_cancel(doc, method=None):
	for name in frappe.get_all("Order TNA", {"sales_order": doc.name, "status": ["!=", "Cancelled"]}, pluck="name"):
		frappe.db.set_value("Order TNA", name, "status", "Cancelled", update_modified=False)
		for m in frappe.get_all("TNA Milestone", {"order_tna": name}, pluck="name"):
			frappe.db.set_value("TNA Milestone", m, {"status": "Not Applicable", "color": "#cbd5e0"}, update_modified=False)
