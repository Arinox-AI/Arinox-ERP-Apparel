"""Material status of every approved FR / TR line, and the material gate that holds bulk production."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from arinox_apparel.materials import common as mc


def line_status(r, min_pct=100, today=None):
	"""Status of one requisition line. `r` carries net, ordered, received, accepted, rejected, hold, eta/etd flags."""
	need = flt(r.net) * flt(min_pct) / 100
	if flt(r.net) <= 0 or flt(r.accepted) + 0.0005 >= need:
		return "Accepted"
	if flt(r.received) - flt(r.accepted) - flt(r.rejected) > 0.0005:
		return "In House - QC Pending"
	if flt(r.rejected) > 0 and flt(r.received) + 0.0005 >= flt(r.net):
		return "Rejected"
	if flt(r.received) > 0:
		return "Short"
	if flt(r.ordered) > 0:
		return "In Transit" if (r.get("etd_actual") or r.get("eta")) else "Ordered"
	if cint(r.get("hold")):
		return "On Hold"
	return "Requested"


def material_rows(filters=None):
	"""One dict per approved, current FR / TR line, with purchase order, receipt and inspection facts."""
	filters = frappe._dict(filters or {})
	min_pct = flt(mc.settings().get("material_gate_min_pct") or 100)
	out = []
	for typ, dt, child, item_f in (("FR", "Fabric Requisition", "Fabric Requisition Item", "fabric_item"), ("TR", "Trim Requisition", "Trim Requisition Item", "trim_item")):
		if filters.get("material_type") and filters.material_type != ("Fabric" if typ == "FR" else "Trim"):
			continue
		cond, args = ["p.docstatus = 1", "p.status not in ('Superseded', 'Cancelled')"], {}
		for f, col in (("customer", "p.customer"), ("company", "p.company")):
			if filters.get(f):
				cond.append(f"{col} = %({f})s"); args[f] = filters[f]
		if filters.get("sales_order"):
			cond.append("c.sales_order = %(sales_order)s"); args["sales_order"] = filters.sales_order
		if filters.get("supplier"):
			cond.append("c.supplier = %(supplier)s"); args["supplier"] = filters.supplier
		rows = frappe.db.sql(
			f"""select c.name, c.parent, c.sales_order, c.style_no, c.colour, c.{item_f} as item, c.supplier, c.required_by, c.net_qty, c.ordered_qty,
			c.received_qty, c.accepted_qty, c.rejected_qty, c.hold, c.material_request_item, p.customer, p.company
			from `tab{child}` c join `tab{dt}` p on p.name = c.parent where {' and '.join(cond)} order by c.sales_order, c.style_no, c.colour""",
			args, as_dict=True)
		for r in rows:
			po = frappe.db.sql(
				"""select o.name, o.transaction_date, o.apparel_etd_planned, o.apparel_etd_revised, o.apparel_etd_actual, o.apparel_eta, o.apparel_supplier_contract_no
				from `tabPurchase Order Item` i join `tabPurchase Order` o on o.name = i.parent where i.material_request_item = %s and o.docstatus = 1 order by o.creation""",
				r.material_request_item or "", as_dict=True) if r.material_request_item else []
			last = po[-1] if po else frappe._dict()
			claim = frappe.db.sql(
				"""select min(claim_deadline) from `tabFabric Inspection` where docstatus = 1 and purchase_receipt_item in (
				select name from `tabPurchase Receipt Item` where purchase_order_item in (select name from `tabPurchase Order Item` where material_request_item = %s))""",
				r.material_request_item or "")[0][0] if typ == "FR" and r.material_request_item else None
			d = frappe._dict(
				type=typ, requisition=r.parent, sales_order=r.sales_order, customer=r.customer, style_no=r.style_no, colour=r.colour, item=r.item,
				supplier=r.supplier, required_by=r.required_by, net=flt(r.net_qty), ordered=flt(r.ordered_qty), received=flt(r.received_qty),
				accepted=flt(r.accepted_qty), rejected=flt(r.rejected_qty), hold=cint(r.hold), po=", ".join(p.name for p in po),
				po_date=last.get("transaction_date"), etd_planned=last.get("apparel_etd_planned"), etd_revised=last.get("apparel_etd_revised"),
				etd_actual=last.get("apparel_etd_actual"), eta=last.get("apparel_eta"), claim_deadline=claim,
			)
			d.in_inspection = max(d.received - d.accepted - d.rejected, 0)
			d.balance = max(d.net - d.received, 0)
			d.status = line_status(d, min_pct)
			d.days_late = max(date_diff(nowdate(), r.required_by), 0) if r.required_by and d.status != "Accepted" else 0
			if filters.get("status") and filters.status != d.status:
				continue
			if cint(filters.get("only_late")) and not d.days_late:
				continue
			out.append(d)
	return out


# ---- the material gate -------------------------------------------------------------------------------------------

def material_gate(sales_order, style_item, colour):
	"""(blockers, warnings) for bulk production of a style x colour: every requisition line must have its accepted
	quantity in. Trims that only matter later (finishing, packing) never hold cutting."""
	s = mc.settings()
	fab, trim = s.get("material_gate_fabric") or "Block", s.get("material_gate_trims") or "Warn"
	min_pct = flt(s.get("material_gate_min_pct") or 100)
	blockers, warnings = [], []
	if fab != "Off":
		for r in frappe.db.sql(
			"""select c.parent, c.fabric_item, c.net_qty, c.accepted_qty from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent
			where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s
			and upper(c.colour) = upper(%s) and c.net_qty > 0""", (sales_order, style_item, colour or ""), as_dict=True):
			need = flt(r.net_qty) * min_pct / 100
			if flt(r.accepted_qty) + 0.0005 < need:
				msg = _("Fabric {0}: {1} m of {2} m accepted ({3}).").format(r.fabric_item, flt(r.accepted_qty, 1), flt(r.net_qty, 1), r.parent)
				(blockers if fab == "Block" else warnings).append(msg)
	if trim != "Off":
		for r in frappe.db.sql(
			"""select c.parent, c.trim_item, c.net_qty, c.accepted_qty, c.trim_category from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent
			left join `tabTrim Category` k on k.name = c.trim_category
			where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s
			and (c.colour is null or c.colour = '' or upper(c.colour) = upper(%s)) and c.net_qty > 0 and coalesce(k.needed_for, 'Sewing') in ('Cutting', 'Sewing')""",
			(sales_order, style_item, colour or ""), as_dict=True):
			need = flt(r.net_qty) * min_pct / 100
			if flt(r.accepted_qty) + 0.0005 < need:
				msg = _("Trim {0}: {1} of {2} accepted ({3}).").format(r.trim_item, flt(r.accepted_qty, 1), flt(r.net_qty, 1), r.parent)
				(blockers if trim == "Block" else warnings).append(msg)
	return blockers, warnings


def trim_readiness(sales_order, style_item, needed_for):
	"""Available / Partial / Not Available for the trims of one need (Sewing or Packing)."""
	rows = frappe.db.sql(
		"""select c.net_qty, c.received_qty, c.accepted_qty from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent
		left join `tabTrim Category` k on k.name = c.trim_category where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled')
		and c.sales_order = %s and c.style_item = %s and c.net_qty > 0 and coalesce(k.needed_for, 'Sewing') = %s""", (sales_order, style_item, needed_for), as_dict=True)
	if not rows:
		return None
	min_pct = flt(mc.settings().get("material_gate_min_pct") or 100)
	if all(flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * min_pct / 100 for r in rows):
		return "Available"
	if any(flt(r.received_qty) > 0 or flt(r.accepted_qty) > 0 for r in rows):
		return "Partial"
	return "Not Available"
