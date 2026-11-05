"""Planning dates for an Order TNA. `plan_dates` is pure (dates in, dates out) so each rule is easy to test;
`make_order_tnas` builds the documents from a Sales Order."""

import math
from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate


def holiday_dates(company):
	"""Set of non-working dates from the Company's default Holiday List; None when the company has no list."""
	hl = frappe.db.get_value("Company", company, "default_holiday_list") if company else None
	if not hl:
		return None
	return {getdate(d) for d in frappe.get_all("Holiday", {"parent": hl}, pluck="holiday_date")}


def working_day(d, holidays, direction=1):
	"""Move `d` to the next (direction 1) or previous (-1) working day. With no Holiday List only Sundays are off."""
	d = getdate(d)
	for _i in range(60):
		off = (d in holidays) if holidays is not None else d.weekday() == 6
		if not off:
			return d
		d = getdate(add_days(d, direction))
	return d


def plan_dates(rows, order_received, ex_factory, qty, holidays=None, pcd=None, overrides=None, na=()):
	"""rows: dicts with code, basis, after, offset_days, duration_rule, daily_output (in template order).
	Returns OrderedDict code -> {planned, start}. A not-applicable milestone passes its predecessor's date through
	(offset 0) so a skipped step adds no days. `pcd` and `overrides` pin dates (a Factory Allocation decides PCD and
	the end of sewing); everything after them follows."""
	overrides = {k: getdate(v) for k, v in (overrides or {}).items() if v}
	if pcd:
		overrides.setdefault("PCD", getdate(pcd))
	dates, pending = {}, list(rows)
	for _pass in range(len(rows) + 2):
		moved = False
		for r in list(pending):
			if r["basis"] == "Order Received":
				base = order_received
			elif r["basis"] == "Ex-Factory":
				base = ex_factory
			elif r["basis"] == "PCD":
				base = dates.get("PCD", {}).get("planned") or pcd
			else:
				base = dates.get(r.get("after"), {}).get("planned")
			if base is None:
				continue
			offset = cint(r.get("offset_days"))
			if r.get("duration_rule") == "Qty / Daily Output" and cint(r.get("daily_output")):
				offset = max(1, math.ceil(flt(qty) / cint(r["daily_output"])))
			if r["code"] in na:
				offset = 0
			if r["code"] in overrides:
				planned = overrides[r["code"]]
			else:
				planned = working_day(add_days(getdate(base), offset), holidays, -1 if offset < 0 else 1)
			start = getdate(base) if r["basis"] == "After Milestone" else planned
			dates[r["code"]] = {"planned": planned, "start": min(start, planned)}
			pending.remove(r)
			moved = True
		if not pending or not moved:
			break
	out = OrderedDict()
	for r in rows:
		if r["code"] in dates:
			out[r["code"]] = dates[r["code"]]
	return out, [r["code"] for r in pending]


def feasibility(dates, ex_factory):
	"""(feasible, note): the last milestone before Ex-Factory must not land after the ex-factory date."""
	if not dates or not ex_factory:
		return True, None
	body = {c: (v["planned"] if isinstance(v, dict) else v) for c, v in dates.items() if c != "EX_FACTORY"}
	if not body:
		return True, None
	code = max(body, key=lambda c: body[c])
	late = date_diff(body[code], ex_factory)
	if late > 0:
		return False, _("Plan is {0} days late against ex-factory ({1} lands on {2}).").format(late, code, body[code])
	return True, None


# ---- applicability -----------------------------------------------------------------------------------------------

def applies(mtype, sales_order, style_item, customer):
	"""Whether a milestone type applies to this style on this order."""
	from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import effective_gate, get_rules
	from arinox_apparel.materials import common as mc

	when = mtype.applies_when or "Always"
	if when == "Always":
		return True
	if when == "Washed Only":
		tp = mc.tech_pack_for(style_item)
		text = f"{(tp.wash_description or '') if tp else ''} {(tp.wash_code or '') if tp else ''}".strip().lower()
		if text and "no wash" not in text:
			return True
		return bool(frappe.db.exists("Sample Approval", {"style_item": style_item, "is_washed": 1}))
	if when == "Printed Only":
		cs = mc.cost_sheet_for(sales_order, style_item)
		if not cs:
			return False
		for ch in cs.charges:
			if (ch.cost_head or "").lower() == "printing" and not ch.not_applicable and flt(ch.rate):
				return True
		return False
	rule = get_rules(customer, sales_order, style_item).get(mtype.sample_type)
	return bool(rule) and effective_gate(rule, sales_order) != "No"


def pick_template(customer, product_type, shipment_mode=None):
	"""Most specific template: customer + product type, customer, product type, then the default."""
	best, score = None, -1
	for t in frappe.get_all("TNA Template", fields=["name", "customer", "product_type", "shipment_mode", "is_default"]):
		s = 0
		for f, v, w in (("customer", customer, 4), ("product_type", product_type, 2), ("shipment_mode", shipment_mode, 1)):
			if t.get(f):
				if t.get(f) != v:
					s = None
					break
				s += w
		if s is None:
			continue
		if not (t.customer or t.product_type or t.shipment_mode) and not cint(t.is_default):
			continue
		if s > score:
			best, score = t.name, s
	return best or frappe.db.get_single_value("Apparel Settings", "default_tna_template")


# ---- building ------------------------------------------------------------------------------------------------------

def order_groups(sales_order):
	"""Sales Order lines grouped to style x colour x ex-factory date."""
	from arinox_apparel.materials.common import style_of

	groups = OrderedDict()
	for it in frappe.get_all("Sales Order Item", {"parent": sales_order}, ["item_code", "qty", "apparel_colour", "apparel_ship_to", "delivery_date"], order_by="idx"):
		key = (style_of(it.item_code), (it.apparel_colour or "").strip(), str(getdate(it.delivery_date)) if it.delivery_date else "")
		g = groups.setdefault(key, frappe._dict(style_item=key[0], colour=key[1], ex_factory=it.delivery_date, qty=0, ship_tos=set()))
		g.qty += cint(it.qty)
		if (it.apparel_ship_to or "").strip():
			g.ship_tos.add(it.apparel_ship_to.strip())
	return list(groups.values())


def allocation_for(sales_order, style_item, colour):
	"""(factory, pcd, sewing_end) from the Factory Allocation for a style x colour."""
	fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
	if not fa:
		return None, None, None
	for r in frappe.get_all("Factory Allocation Line", {"parent": fa, "style_item": style_item}, ["colour", "factory", "pcd", "sewing_end"], order_by="pcd"):
		if not colour or not (r.colour or "").strip() or r.colour.strip().upper() == colour.strip().upper():
			return r.factory, r.pcd, r.sewing_end
	return None, None, None


def template_rows(template):
	t = frappe.get_cached_doc("TNA Template", template)
	rows = []
	for r in t.milestones:
		rows.append({"code": r.milestone_type, "basis": r.basis, "after": r.after_milestone, "offset_days": r.offset_days,
			"duration_rule": r.duration_rule, "daily_output": r.daily_output, "owner_role": r.owner_role})
	return rows


def compute_plan(tna):
	"""Planned dates for an Order TNA document (or dict) from its template. Returns (dates, na_codes, unresolved)."""
	rows = template_rows(tna.template)
	so = frappe.db.get_value("Sales Order", tna.sales_order, ["customer", "company"], as_dict=True)
	na = set()
	for r in rows:
		mt = frappe.get_cached_doc("TNA Milestone Type", r["code"])
		if not applies(mt, tna.sales_order, tna.style_item, so.customer):
			na.add(r["code"])
	_f, pcd, sewing_end = allocation_for(tna.sales_order, tna.style_item, tna.colour)
	overrides = {}
	if sewing_end:
		overrides["BULK_FINISH"] = sewing_end
	dates, unresolved = plan_dates(rows, tna.order_received_date, tna.ex_factory_date, tna.order_qty, holiday_dates(so.company),
		pcd=tna.pcd or pcd, overrides=overrides, na=na)
	return dates, na, unresolved, rows


@frappe.whitelist()
def make_order_tnas(sales_order, template=None):
	"""One Order TNA per style x colour x ex-factory date of a submitted Sales Order. Existing ones are left alone.
	Returns the names created."""
	from arinox_apparel.materials import common as mc
	from arinox_apparel.tna.events import backfill

	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("read")
	frappe.has_permission("Order TNA", "create", throw=True)
	if so.docstatus != 1:
		frappe.throw(_("Submit the Sales Order first."))
	made = []
	for g in order_groups(sales_order):
		if not g.ex_factory:
			frappe.msgprint(_("Style {0} {1} has no delivery date on the Sales Order; no T&A was made for it.").format(g.style_item, g.colour))
			continue
		exists = frappe.db.exists("Order TNA", {"sales_order": sales_order, "style_item": g.style_item, "colour": g.colour,
			"ex_factory_date": getdate(g.ex_factory), "status": ["!=", "Cancelled"]})
		if exists:
			continue
		tp = mc.tech_pack_for(g.style_item)
		tpl = template or pick_template(so.customer, tp.product_type if tp else None)
		if not tpl:
			frappe.throw(_("No T&A template. Set a default in Apparel Settings."))
		received = so.po_date or so.transaction_date
		factory, pcd, _se = allocation_for(sales_order, g.style_item, g.colour)
		doc = frappe.get_doc({
			"doctype": "Order TNA", "sales_order": sales_order, "style_item": g.style_item, "style_no": tp.style_no if tp else g.style_item,
			"colour": g.colour, "order_qty": g.qty, "ship_tos": ", ".join(sorted(g.ship_tos)), "merchant": frappe.session.user,
			"factory": factory, "order_received_date": received, "order_date_missing": 0 if so.po_date else 1, "pcd": pcd,
			"ex_factory_date": getdate(g.ex_factory), "template": tpl,
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		build_milestones(doc)
		backfill(doc.name)
		made.append(doc.name)
	return made


def build_milestones(tna):
	dates, na, unresolved, rows = compute_plan(tna)
	if unresolved:
		frappe.msgprint(_("These milestones could not be dated (missing base): {0}").format(", ".join(unresolved)), indicator="orange")
	meta = {r["code"]: r for r in rows}
	names = {}
	seq = 0
	for r in rows:
		code = r["code"]
		if code not in dates:
			continue
		seq += 10
		mt = frappe.get_cached_doc("TNA Milestone Type", code)
		ms = frappe.get_doc({
			"doctype": "TNA Milestone", "order_tna": tna.name, "milestone_type": code, "sequence": seq, "label": mt.label, "department": mt.department,
			"is_critical": mt.is_critical, "planned_start": dates[code]["start"], "planned_date": dates[code]["planned"], "not_applicable": 1 if code in na else 0,
		})
		ms.flags.ignore_permissions = True
		ms.insert()
		names[code] = ms.name
	for code, name in names.items():
		after = meta[code]["after"] if meta[code]["basis"] == "After Milestone" else None
		if after and after in names:
			frappe.db.set_value("TNA Milestone", name, "depends_on_tasks", names[after], update_modified=False)
	feasible, note = feasibility({c: v for c, v in dates.items() if c not in na}, tna.ex_factory_date)
	tna.db_set({"plan_feasible": 1 if feasible else 0, "feasibility_note": note})
	from arinox_apparel.tna.status import refresh_order_tna

	refresh_order_tna(tna.name)


def replan(order_tna):
	"""Recompute planned dates after the PCD or the sewing window changed. Before the baseline is locked the planned
	dates move; after it, only the revised dates do (the baseline stays as agreed)."""
	tna = frappe.get_doc("Order TNA", order_tna)
	if tna.status == "Cancelled":
		return
	factory, pcd, _se = allocation_for(tna.sales_order, tna.style_item, tna.colour)
	if factory and tna.factory != factory:
		tna.db_set("factory", factory)
		tna.factory = factory
		frappe.db.sql("update `tabTNA Milestone` set factory = %s where order_tna = %s", (factory, order_tna))
	if pcd and (not tna.pcd or getdate(tna.pcd) != getdate(pcd)):
		tna.db_set("pcd", pcd)
		tna.pcd = pcd
	dates, na, _u, _r = compute_plan(tna)
	locked = cint(tna.baseline_locked)
	for ms in frappe.get_all("TNA Milestone", {"order_tna": order_tna}, ["name", "milestone_type", "actual_date", "planned_date", "revised_date", "not_applicable"]):
		d = dates.get(ms.milestone_type)
		if not d or ms.actual_date:
			continue
		if locked:
			if getdate(d["planned"]) != getdate(ms.planned_date):
				frappe.db.set_value("TNA Milestone", ms.name, {"revised_date": d["planned"], "revision_reason": _("Factory allocation / plan change")}, update_modified=False)
			elif ms.revised_date:
				frappe.db.set_value("TNA Milestone", ms.name, {"revised_date": None}, update_modified=False)
		else:
			frappe.db.set_value("TNA Milestone", ms.name, {"planned_date": d["planned"], "planned_start": d["start"], "revised_date": None}, update_modified=False)
	feasible, note = feasibility({c: v for c, v in dates.items() if c not in na}, tna.ex_factory_date)
	tna.db_set({"plan_feasible": 1 if feasible else 0, "feasibility_note": note})
	from arinox_apparel.tna.status import refresh_order_tna

	refresh_order_tna(order_tna)
