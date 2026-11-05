"""Inspection rules as small pure functions (4-point fabric system, sampling, lot decision, trim AQL), plus the shared
steps both inspections use: the receipt context, the Quality Inspection record and the Stock Entry."""

import math

import frappe
from frappe import _
from frappe.utils import cint, flt

from arinox_apparel.materials import common as mc

YARD_IN = 36.0


# ---- fabric: 4-point system ----------------------------------------------------------------------------------------

def defect_points(length_in, always_four=False):
	"""Points for one defect by its length in inches: up to 3 = 1, over 3 to 6 = 2, over 6 to 9 = 3, over 9 = 4.
	Holes (and any code marked 'always 4') take 4 points."""
	if always_four:
		return 4
	n = flt(length_in)
	if n <= 3:
		return 1
	if n <= 6:
		return 2
	if n <= 9:
		return 3
	return 4


def roll_points(defects):
	"""Total points of one roll. `defects` = list of (yard_position, points). No more than 4 points count in one yard;
	a defect with no yard number counts on its own."""
	by_yard, loose = {}, 0
	for yard, pts in defects:
		if yard in (None, "", 0):
			loose += pts
		else:
			by_yard[yard] = by_yard.get(yard, 0) + pts
	return loose + sum(min(p, 4) for p in by_yard.values())


def points_per_100_linear(total_points, inspected_m):
	yards = flt(inspected_m) / mc.YARD_M
	return flt(total_points) * 100 / yards if yards else 0.0


def points_per_100_square(total_points, inspected_m, width_cm):
	"""points x 3600 / (inspected yards x width in inches)."""
	yards = flt(inspected_m) / mc.YARD_M
	width_in = flt(width_cm) / 2.54
	return flt(total_points) * 3600 / (yards * width_in) if yards and width_in else 0.0


def sampling_pct(bands, total_m):
	"""Inspect % for a lot of `total_m` metres. Band to_length 0 = no upper limit. 100 when no band matches."""
	for b in sorted(bands, key=lambda b: flt(b.from_length_m)):
		if flt(b.from_length_m) <= flt(total_m) and (not flt(b.to_length_m) or flt(total_m) <= flt(b.to_length_m)):
			return flt(b.inspect_pct)
	return 100.0


def lot_decision(avg_points, threshold, rejected_rolls, inspected_rolls, total_rolls, max_rejected_pct, on_hold=False):
	"""Pass / Fail / Re-inspect 100% / Hold. A sample that fails sends the lot to 100% inspection; once every roll has
	been inspected a failing lot is Fail."""
	if on_hold:
		return "Hold"
	rejected_pct = rejected_rolls * 100 / inspected_rolls if inspected_rolls else 0
	failing = flt(avg_points) > flt(threshold) or rejected_pct > flt(max_rejected_pct)
	if not failing:
		return "Pass"
	return "Re-inspect 100%" if inspected_rolls < total_rolls else "Fail"


def roll_disposition(inspected, roll_result, lot_result):
	"""What happens to a roll's stock: Accepted, Accepted by Lot, Rejected or Hold."""
	if inspected:
		return {"Accept": "Accepted", "Reject": "Rejected"}.get(roll_result, "Hold")
	return "Accepted by Lot" if lot_result == "Pass" else "Hold"


def width_impact(avg_actual_cm, required_cm, net_qty_m):
	"""Extra metres needed when the fabric is narrower than the cuttable width the consumption was based on."""
	if not flt(avg_actual_cm) or not flt(required_cm) or flt(avg_actual_cm) >= flt(required_cm):
		return 0.0
	return flt(net_qty_m) * (flt(required_cm) / flt(avg_actual_cm) - 1)


# ---- trims ---------------------------------------------------------------------------------------------------------

def trim_sample(plan, received_qty):
	"""(sample size, accept max, reject min) of a Trim Sampling Plan for a lot. Percent plans have no accept numbers.
	An AQL plan inspects the whole lot up to `full_inspect_up_to`."""
	received_qty = flt(received_qty)
	if plan.method == "Percent":
		return max(1, math.ceil(received_qty * flt(plan.inspect_pct) / 100)) if received_qty else 0, None, None
	if received_qty <= cint(plan.full_inspect_up_to):
		return received_qty, None, None
	rows = sorted(plan.rows, key=lambda r: cint(r.lot_from))
	pick = next((r for r in rows if cint(r.lot_from) <= received_qty <= cint(r.lot_to)), rows[-1] if rows else None)
	if not pick:
		return received_qty, None, None
	return min(flt(pick.sample_size), received_qty), cint(pick.accept_max), cint(pick.reject_min)


def trim_result(plan, defective, inspected, reject_min, size_mixup):
	"""Pass or Fail. A size mix-up always fails. AQL: fail at the reject number. Percent: fail above the plan's limit."""
	if size_mixup:
		return "Fail"
	if plan.method == "AQL Table" and reject_min is not None:
		return "Fail" if cint(defective) >= cint(reject_min) else "Pass"
	pct = flt(defective) * 100 / flt(inspected) if flt(inspected) else 0
	limit = getattr(plan, "max_defective_pct", None)
	return "Fail" if pct > flt(5 if limit is None else limit) else "Pass"


# ---- shared steps ----------------------------------------------------------------------------------------------

def receipt_context(pr_name, row_name, kind):
	"""Everything an inspection needs about one Purchase Receipt row of an FR (fabric) or TR (trim)."""
	pr = frappe.db.get_value("Purchase Receipt", pr_name, ["name", "docstatus", "company", "supplier", "posting_date", "currency"], as_dict=True)
	if not pr:
		frappe.throw(_("Purchase Receipt {0} does not exist.").format(pr_name))
	if pr.docstatus != 1:
		frappe.throw(_("Purchase Receipt {0} is not submitted. Inspect goods that have been received.").format(pr_name))
	row = frappe.db.get_value("Purchase Receipt Item", {"name": row_name, "parent": pr_name},
		["name", "item_code", "warehouse", "stock_qty", "qty", "uom", "conversion_factor", "purchase_order", "purchase_order_item", "serial_and_batch_bundle", "net_amount"], as_dict=True)
	if not row:
		frappe.throw(_("Row {0} is not on {1}.").format(row_name, pr_name))
	ctx = frappe._dict(pr=pr, row=row, requisition=None, requisition_type=None, mri=None, so_list=[], styles=[], customer=None, terms=None)
	if row.purchase_order_item:
		poi = frappe.db.get_value("Purchase Order Item", row.purchase_order_item,
			["parent", "material_request_item", "apparel_requisition_type", "apparel_requisition"], as_dict=True)
		ctx.mri = poi.material_request_item
		ctx.requisition_type, ctx.requisition = poi.apparel_requisition_type, poi.apparel_requisition
		ctx.purchase_order = poi.parent
		po = frappe.db.get_value("Purchase Order", poi.parent, ["apparel_purchase_terms", "supplier"], as_dict=True)
		from arinox_apparel.materials.purchasing import terms_for

		ctx.terms = terms_for(po.apparel_purchase_terms, po.supplier)
	want = "FR" if kind == "Fabric" else "TR"
	if ctx.requisition_type and ctx.requisition_type != want:
		frappe.throw(_("This receipt row came from a {0}; use the {1} inspection.").format(ctx.requisition_type, "trim" if want == "FR" else "fabric"))
	if ctx.requisition:
		dt = "Fabric Requisition" if want == "FR" else "Trim Requisition"
		child = dt + " Item"
		req_rows = frappe.get_all(child, {"parent": ctx.requisition, "material_request_item": ctx.mri}, ["sales_order", "style_no", "colour", "style_item"] + (["cuttable_width_cm"] if want == "FR" else []))
		ctx.so_list = sorted({r.sales_order for r in req_rows})
		ctx.styles = sorted({r.style_no for r in req_rows if r.style_no})
		ctx.colour = req_rows[0].colour if req_rows else None
		ctx.required_width = req_rows[0].get("cuttable_width_cm") if req_rows else None
		ctx.customer = frappe.db.get_value(dt, ctx.requisition, "customer")
	return ctx


def append_red_flag(requisition_type, name, text):
	dt = "Fabric Requisition" if requisition_type == "FR" else "Trim Requisition"
	if not name or not frappe.db.exists(dt, name):
		return
	cur = frappe.db.get_value(dt, name, "red_flags") or ""
	if text not in cur:
		frappe.db.set_value(dt, name, "red_flags", (cur + "\n" + text).strip(), update_modified=False)


QI_PARAMETERS = ("Average Points per 100 Linear Yards", "Worst Roll Points per 100", "Average Width (cm)", "Shrinkage Warp %",
	"Shrinkage Weft %", "Trim Defective %", "Trim Size Mix-up")


def ensure_qi_parameters():
	for p in QI_PARAMETERS:
		if not frappe.db.exists("Quality Inspection Parameter", p):
			frappe.get_doc({"doctype": "Quality Inspection Parameter", "parameter": p}).insert(ignore_permissions=True)


def make_quality_inspection(ctx, item_code, accepted, readings, sample_size, remarks=None):
	"""Incoming Quality Inspection against the receipt: manual statuses, submitted. `readings` = (parameter, value, status)."""
	ensure_qi_parameters()
	qi = frappe.new_doc("Quality Inspection")
	qi.update({
		"inspection_type": "Incoming", "reference_type": "Purchase Receipt", "reference_name": ctx.pr.name, "item_code": item_code,
		"report_date": frappe.utils.nowdate(), "sample_size": sample_size, "inspected_by": frappe.session.user,
		"manual_inspection": 1, "status": "Accepted" if accepted else "Rejected", "remarks": remarks, "child_row_reference": ctx.row.name,
	})
	for spec, value, status in readings:
		qi.append("readings", {"specification": spec, "value": "", "reading_value": str(value), "manual_inspection": 1, "numeric": 0, "status": status})
	qi.flags.ignore_permissions = True
	qi.insert()
	qi.submit()
	return qi.name


def make_stock_entry(ctx, rows, kind, submit):
	"""Move stock out of the inspection warehouse. `rows` = list of dict(item_code, qty, target, batch_no=None).
	Returns the Stock Entry name, or None when nothing moves."""
	rows = [r for r in rows if flt(r["qty"]) > 0 and r["target"]]
	if not rows:
		return None
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = ctx.pr.company
	for r in rows:
		line = {"item_code": r["item_code"], "qty": r["qty"], "s_warehouse": ctx.row.warehouse, "t_warehouse": r["target"]}
		if r.get("batch_no"):
			line.update({"batch_no": r["batch_no"], "use_serial_batch_fields": 1})
		se.append("items", line)
	se.remarks = _("Inspection release for {0}").format(ctx.pr.name)
	se.flags.ignore_permissions = True
	se.insert()
	if submit:
		se.submit()
	return se.name


def cancel_linked(doctype, name):
	if name and frappe.db.exists(doctype, name):
		d = frappe.get_doc(doctype, name)
		d.flags.ignore_permissions = True
		if d.docstatus == 1:
			d.cancel()
		elif d.docstatus == 0:
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
