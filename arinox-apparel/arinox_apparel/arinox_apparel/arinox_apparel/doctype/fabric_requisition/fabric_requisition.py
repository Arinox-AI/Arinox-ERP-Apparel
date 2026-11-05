# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Fabric Requisition (FR): the merchandiser's request to buy fabric, one line per style x colour x fabric.
Submit = approved. Submitting creates Material Requests (grouped by supplier). Totals are always computed here,
never trusted from the client."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import colour_level, get_order_lines
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import get_style_dates
from arinox_apparel.materials import common as mc


def row_key(r):
	return "|".join([r.sales_order or "", r.style_item or "", (r.colour or "").strip().upper(), r.material_role or "", r.fabric_item or ""])


class FabricRequisition(Document):
	def autoname(self):
		prefix = frappe.db.get_value("Company", self.company, "apparel_fr_prefix") or "FR"
		self.name = mc.next_number(prefix, self.fr_date)

	# ---- lifecycle ----------------------------------------------------------------------------------------------
	def validate(self):
		if not self.ordered_by:
			self.ordered_by = frappe.session.user
		if not self.terms:
			self.terms = default_terms()
		if not self.items:
			frappe.throw(_("Add at least one fabric line."))
		if cint(self.revision_no) > 0 and not (self.revision_reason or "").strip():
			frappe.throw(_("Enter the reason for this revision."))
		self.check_duplicates()
		flags = []
		for r in self.items:
			self.fill_row(r, flags)
			self.compute_row(r, flags)
		self.check_revision(flags)
		self.build_summary()
		self.total_order_m = sum(flt(r.net_qty) for r in self.items)
		self.red_flags = "\n".join(dict.fromkeys(flags))
		self.set_status()

	def before_submit(self):
		for r in self.items:
			if not r.fabric_item:
				frappe.throw(_("Row {0}: choose or create the fabric item before approving.").format(r.idx))

	def on_submit(self):
		self.db_set({"approved_by": frappe.session.user, "approved_on": now_datetime()})
		self.create_requests()
		if self.previous_fr:
			frappe.db.set_value("Fabric Requisition", self.previous_fr, "status", "Superseded")
		mc.stamp_safe_requisition(self, "FR_RAISED")
		self.set_status(save=True)

	def before_cancel(self):
		for mri in frappe.db.sql(
			"""select i.parent, i.name from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.apparel_requisition_type = 'FR' and i.apparel_requisition = %s and m.docstatus = 1""", self.name):
			po = frappe.db.sql(
				"""select distinct p.name from `tabPurchase Order Item` p where p.material_request_item = %s and p.docstatus < 2""", mri[1])
			if po:
				frappe.throw(_("Material Request {0} is already on Purchase Order {1}. Cancel the order first, or revise this requisition.").format(mri[0], po[0][0]))

	def on_cancel(self):
		for mr in {m[0] for m in frappe.db.sql(
			"""select distinct i.parent from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.apparel_requisition_type = 'FR' and i.apparel_requisition = %s and m.docstatus = 1""", self.name)}:
			doc = frappe.get_doc("Material Request", mr)
			doc.flags.ignore_permissions = True
			doc.cancel()
		if self.previous_fr:
			prev = frappe.get_doc("Fabric Requisition", self.previous_fr)
			prev.db_set("status", "Approved")
			prev.set_status(save=True)
		mc.unstamp_safe("Fabric Requisition", self.name)
		self.db_set("status", "Cancelled")

	# ---- rows -----------------------------------------------------------------------------------------------------
	def check_duplicates(self):
		seen = {}
		for r in self.items:
			if not r.fabric_item:
				continue
			k = row_key(r)
			if k in seen:
				frappe.throw(_("Row {0} repeats row {1}: same order, style, colour, role and fabric.").format(r.idx, seen[k]))
			seen[k] = r.idx

	def fill_row(self, r, flags):
		so = frappe.db.get_value("Sales Order", r.sales_order, ["docstatus", "customer", "company", "apparel_sales_contract"], as_dict=True)
		if not so:
			frappe.throw(_("Row {0}: Sales Order {1} does not exist.").format(r.idx, r.sales_order))
		if so.docstatus != 1:
			frappe.throw(_("Row {0}: Sales Order {1} is not submitted.").format(r.idx, r.sales_order))
		if so.customer != self.customer or so.company != self.company:
			frappe.throw(_("Row {0}: Sales Order {1} belongs to another buyer or company.").format(r.idx, r.sales_order))
		r.sales_contract = so.apparel_sales_contract
		if frappe.db.get_value("Item", r.style_item, "variant_of"):
			frappe.throw(_("Row {0}: pick the style (template item), not a variant.").format(r.idx))
		r.style_no = r.style_no or frappe.db.get_value("Tech Pack", {"style_item": r.style_item}, "style_no") or r.style_item
		order_qty = order_colour_qty(r.sales_order, r.style_item, r.colour)
		if not cint(r.garment_qty):
			r.garment_qty = order_qty
		elif order_qty and cint(r.garment_qty) != order_qty:
			flags.append(_("Row {0}: garment qty {1} differs from the Sales Order ({2}).").format(r.idx, r.garment_qty, order_qty))
		if flt(r.consumption) <= 0:
			frappe.throw(_("Row {0}: consumption must be more than zero.").format(r.idx))
		if flt(r.cuttable_width_cm) <= 0:
			frappe.throw(_("Row {0}: enter the cuttable width.").format(r.idx))
		if not r.consumption_source:
			frappe.throw(_("Row {0}: say where the consumption comes from (marker, cost sheet, tech pack or manual).").format(r.idx))
		if mc.uom_kind(r.consumption_uom) == "kg" and not flt(r.gsm):
			frappe.throw(_("Row {0}: a kg line needs the GSM.").format(r.idx))
		if r.fabric_item and not flt(r.gsm):
			r.gsm = flt(frappe.db.get_value("Item", r.fabric_item, "apparel_fabric_gsm"))
		# approval status
		status, ok = mc.approval_info(r.sales_order, r.style_item, "Lab Dip", r.colour, self.customer)
		r.lab_dip_status = status
		hold_mode = (mc.settings().get("hold_po_until_approval") or "Warn")
		r.hold = 1 if (not ok and hold_mode != "Off") else 0
		if not ok:
			flags.append(_("Row {0}: lab dip is {1}; the purchase order will be held.").format(r.idx, status))
		# description width vs field
		import re

		m = re.search(r"CW\s*(\d+(?:\.\d+)?)", r.fabric_description or "", re.I)
		if m and abs(flt(m.group(1)) - flt(r.cuttable_width_cm)) > 0.5:
			flags.append(_("Row {0}: the description says CW {1} but the cuttable width is {2}.").format(r.idx, m.group(1), r.cuttable_width_cm))
		# dates
		pcd = get_style_dates(r.sales_order, r.style_item, r.colour)[0]
		due_days = cint(mc.settings().get("fabric_due_days_before_pcd") or 10)
		if pcd and not r.required_by:
			r.required_by = add_days(pcd, -due_days)
		if pcd and r.required_by and getdate(r.required_by) > add_days(getdate(pcd), -due_days):
			flags.append(_("Row {0}: required by {1} is later than PCD {2} minus {3} days.").format(r.idx, r.required_by, pcd, due_days))
		if not pcd:
			flags.append(_("Row {0}: no planned cut date yet; set the Factory Allocation.").format(r.idx))
		if not r.supplier:
			flags.append(_("Row {0}: no supplier chosen.").format(r.idx))

	def compute_row(self, r, flags):
		cons_m = mc.to_metres(r.consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
		rule = mc.get_allowance(
			r.material_role == "Lining" and "Lining" or ("Contrast Fabric" if r.material_role == "Contrast" else "Fabric"),
			customer=self.customer, item_group=frappe.db.get_value("Item", r.fabric_item, "item_group") if r.fabric_item else None)
		default_pct = flt(rule.allowance_pct)
		if r.allowance_pct is None:
			r.allowance_pct = default_pct
		elif flt(r.allowance_pct) != default_pct and not (r.allowance_reason or "").strip():
			frappe.throw(_("Row {0}: the allowance {1}% differs from the rule ({2}%). Enter the reason.").format(r.idx, r.allowance_pct, default_pct))
		r.pack_size = flt(rule.pack_size)
		r.gross_qty = flt(cint(r.garment_qty) * cons_m * (1 + flt(r.allowance_pct) / 100), 4)
		if flt(r.stock_used) > 0:
			if not r.stock_warehouse or not r.fabric_item:
				frappe.throw(_("Row {0}: choose the fabric item and warehouse to use leftover stock.").format(r.idx))
			free = mc.free_stock(r.fabric_item, r.stock_warehouse, "Fabric Requisition", "Fabric Requisition Item", self.name)
			if flt(r.stock_used) > free + 0.0001:
				frappe.throw(_("Row {0}: only {1} m of {2} is free in {3} (the rest is claimed by other requisitions).").format(
					r.idx, flt(free, 2), r.fabric_item, r.stock_warehouse))
		r.net_qty = flt(max(flt(r.gross_qty) - flt(r.stock_used), 0), 4)
		r.order_uom = r.order_uom or (frappe.db.get_value("Item", r.fabric_item, "stock_uom") if r.fabric_item else None) or "Meter"
		r.order_qty = mc.round_up_to_pack(mc.from_metres(r.net_qty, r.order_uom, r.gsm, r.cuttable_width_cm), r.pack_size) if r.net_qty > 0 else 0
		if r.net_qty > 0 and flt(rule.min_order_qty) and flt(r.order_qty) < flt(rule.min_order_qty):
			r.order_qty = flt(rule.min_order_qty)
			flags.append(_("Row {0}: raised to the minimum order of {1}.").format(r.idx, rule.min_order_qty))
		self.compare_costing(r, flags)

	def compare_costing(self, r, flags):
		if not r.costed_consumption or not r.consumption:
			return
		try:
			costed_m = mc.to_metres(r.costed_consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
			now_m = mc.to_metres(r.consumption, r.consumption_uom, r.gsm, r.cuttable_width_cm)
		except frappe.ValidationError:
			return
		if costed_m and abs(now_m - costed_m) / costed_m > 0.05:
			word = "less" if now_m < costed_m else "more"
			flags.append(_("Row {0}: consumption {1} is more than 5% {2} than costed ({3}).").format(r.idx, r.consumption, word, r.costed_consumption))

	def check_revision(self, flags):
		if not self.previous_fr:
			return
		chain = mc.revision_chain("Fabric Requisition", "previous_fr", self.previous_fr)
		mine = {row_key(r): r for r in self.items if r.fabric_item}
		for r in mine.values():
			before = mc.requested_so_far("FR", chain, row_key(r))
			if before and flt(r.net_qty) + 0.0005 < before:
				flags.append(_("Row {0}: reduced from {1} m to {2} m. Reduce the order with the supplier.").format(r.idx, flt(before, 2), flt(r.net_qty, 2)))
		for (k, before) in self.previous_totals(chain).items():
			if k not in mine and before > 0:
				flags.append(_("Line removed ({0}): {1} m was already requested. Cancel or reduce the order with the supplier.").format(k.replace("|", " / "), flt(before, 2)))

	def previous_totals(self, chain):
		rows = frappe.db.sql(
			"""select i.apparel_requisition_item, sum(i.stock_qty) from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.apparel_requisition_type = 'FR' and i.apparel_requisition in %s and m.docstatus < 2 group by i.apparel_requisition_item""",
			(tuple(chain),))
		return {k: flt(q) for k, q in rows}

	def build_summary(self):
		self.set("summary", [])
		groups = {}
		for r in self.items:
			if flt(r.net_qty) <= 0:
				continue
			g = groups.setdefault((r.fabric_item or r.fabric_description, r.supplier or ""), {"fabric_item": r.fabric_item, "fabric_description": r.fabric_description,
				"supplier": r.supplier, "total": 0, "uom": r.order_uom, "date": None, "n": 0})
			g["total"] += flt(r.order_qty)
			g["n"] += 1
			if r.required_by and (not g["date"] or getdate(r.required_by) < getdate(g["date"])):
				g["date"] = r.required_by
		for g in groups.values():
			self.append("summary", {"fabric_item": g["fabric_item"], "fabric_description": g["fabric_description"], "supplier": g["supplier"],
				"total_order_qty": flt(g["total"], 2), "uom": g["uom"], "earliest_required_by": g["date"], "line_count": g["n"]})

	# ---- status ---------------------------------------------------------------------------------------------------
	def set_status(self, save=False):
		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 2:
			status = "Cancelled"
		elif self.status == "Superseded":
			status = "Superseded"
		else:
			need = [r for r in self.items if flt(r.net_qty) > 0]
			if not need:
				status = "Received"
			elif all(flt(r.received_qty) + 0.0005 >= flt(r.net_qty) for r in need):
				status = "Received"
			elif any(flt(r.received_qty) > 0 for r in need):
				status = "Partly Received"
			elif all(flt(r.ordered_qty) + 0.0005 >= flt(r.net_qty) for r in need):
				status = "Ordered"
			elif any(flt(r.ordered_qty) > 0 for r in need):
				status = "Partly Ordered"
			else:
				status = "Approved"
		self.status = status
		if save:
			self.db_set("status", status, update_modified=False)

	# ---- Material Requests ----------------------------------------------------------------------------------------------
	def create_requests(self):
		chain = mc.revision_chain("Fabric Requisition", "previous_fr", self.name)[1:]
		lines = []
		for r in self.items:
			if flt(r.net_qty) <= 0:
				continue
			key = row_key(r)
			delta = flt(r.net_qty) - mc.requested_so_far("FR", chain, key)
			if delta <= 0.0005:
				continue
			order_qty = mc.round_up_to_pack(mc.from_metres(delta, r.order_uom, r.gsm, r.cuttable_width_cm), r.pack_size)
			qty, uom, cf = mc.mr_line(r.fabric_item, delta, r.order_uom, order_qty)
			lines.append({
				"item_code": r.fabric_item, "qty": qty, "uom": uom, "conversion_factor": cf, "supplier": r.supplier,
				"required_by": r.required_by, "key": key, "style_no": r.style_no, "colour": r.colour, "sales_order": r.sales_order,
				"description": r.fabric_description, "hold_reason": _("Lab dip {0}").format(r.lab_dip_status) if r.hold else None,
			})
		mc.create_material_requests(self, lines, "FR", "Fabric")
		for r in self.items:
			mri = frappe.db.sql(
				"""select i.name, i.parent from `tabMaterial Request Item` i where i.apparel_requisition_type = 'FR' and i.apparel_requisition = %s
				and i.apparel_requisition_item = %s limit 1""", (self.name, row_key(r)))
			if mri:
				r.db_set({"material_request": mri[0][1], "material_request_item": mri[0][0]})

	# ---- buttons ------------------------------------------------------------------------------------------------
	@frappe.whitelist()
	def get_lines_from_sales_orders(self, sales_orders):
		"""One row per style x colour x fabric of the Tech Pack, quantities from the Sales Order."""
		self.check_permission("write")
		added = 0
		have = {row_key(r) for r in self.items}
		for so in json.loads(sales_orders) if isinstance(sales_orders, str) else sales_orders:
			for line in lines_for_sales_order(so, self.customer, self.company):
				k = row_key(frappe._dict(line))
				if k in have:
					continue
				have.add(k)
				self.append("items", line)
				added += 1
		return added

	@frappe.whitelist()
	def create_fabric_items(self):
		"""Create the template and colour variant for every row that has none."""
		from arinox_apparel.materials.items import ensure_fabric_item

		self.check_permission("write")
		made = []
		for r in self.items:
			if r.fabric_item:
				continue
			code = (r.fabric_description or "").split(",")[0].strip()
			if not code:
				frappe.throw(_("Row {0}: the description must start with the fabric quality code.").format(r.idx))
			r.fabric_item = ensure_fabric_item(code, r.fabric_colour or r.colour, r.fabric_description, r.gsm, r.cuttable_width_cm)
			made.append(r.fabric_item)
		return made


def default_terms():
	return (
		"<ol><li>Delivery: as per the schedule above.</li><li>Partial shipments: not allowed.</li><li>Quality: as per the buyer's quality standards.</li>"
		"<li>Quantity: as per our internal buying standards. Over and above the allowance, uncut fabric will be returned to the supplier.</li>"
		"<li>Quantity is in metres.</li><li>Bulk shrinkage should be as per the approved fabric data sheet.</li>"
		"<li>Cuttable width and GSM must match the approved fabric data sheet.</li></ol>"
	)


def order_colour_qty(sales_order, style_item, colour):
	cl = colour_level(get_order_lines(sales_order))
	row = cl.get((style_item, (colour or "").strip().upper()))
	return cint(row.qty) if row else 0


def lines_for_sales_order(sales_order, customer, company):
	"""FR line dicts for one Sales Order from the Tech Pack materials (FR types only)."""
	so = frappe.db.get_value("Sales Order", sales_order, ["docstatus", "customer", "company"], as_dict=True)
	if not so or so.docstatus != 1 or so.customer != customer or so.company != company:
		frappe.throw(_("Sales Order {0} must be submitted and belong to this buyer and company.").format(sales_order))
	fr_types = mc.fr_material_types()
	out = []
	for (style, colour_key), o in colour_level(get_order_lines(sales_order)).items():
		tp = mc.tech_pack_for(style)
		if not tp:
			frappe.msgprint(_("Style {0} has no submitted Tech Pack; no fabric lines were made for it.").format(style))
			continue
		cs = mc.cost_sheet_for(sales_order, style)
		all_colours = [c.colour for c in tp.colours]
		for m in tp.materials:
			if m.material_type not in fr_types or not mc.colour_matches(m.colour, o.colour, all_colours):
				continue
			cons, uom, source, costed = flt(m.consumption), m.uom or "Meter", "Tech Pack", None
			if cs:
				for cm in cs.materials:
					if cm.material_type == m.material_type and (cm.is_selected or cm.is_selected is None) and (
						(cm.item and cm.item == m.item) or (cm.description or "").strip().lower() == (m.description or "").strip().lower()):
						costed = flt(cm.consumption)
						if not cons:
							cons, uom, source = costed, cm.uom or uom, "Cost Sheet"
						break
			width = mc.parse_width_cm(m.width) or 0
			role = {"Lining": "Lining", "Contrast Fabric": "Contrast"}.get(m.material_type, "Shell")
			gsm = mc.parse_width_cm(m.gsm) if m.gsm else 0
			out.append({
				"sales_order": sales_order, "style_item": style, "style_no": tp.style_no, "style_name": tp.style_name, "colour": o.colour,
				"material_role": role, "tech_pack_material": m.name, "fabric_item": m.item, "fabric_description": m.description,
				"fabric_colour": m.colour or o.colour, "supplier": m.nominated_supplier, "nominated_by_buyer": 1 if m.nominated_supplier else 0,
				"cuttable_width_cm": width, "gsm": gsm, "garment_qty": cint(o.qty), "consumption": cons, "consumption_uom": uom,
				"consumption_source": source, "costed_consumption": costed,
			})
	return out


# ---- agent API --------------------------------------------------------------------------------------------------

@frappe.whitelist()
def get_requisition_context(sales_order):
	"""Everything an agent needs to draft the FR and TR for an order."""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	so = frappe.get_doc("Sales Order", sales_order)
	styles = {}
	for (style, colour_key), o in colour_level(get_order_lines(sales_order)).items():
		tp = mc.tech_pack_for(style)
		cs = mc.cost_sheet_for(sales_order, style)
		pcd, ex_factory, in_wh = get_style_dates(sales_order, style, o.colour)
		st = styles.setdefault(style, {"style_item": style, "tech_pack": tp.name if tp else None, "cost_sheet": cs.name if cs else None, "colours": []})
		st["colours"].append({
			"colour": o.colour, "qty": cint(o.qty), "pcd": str(pcd) if pcd else None, "ex_factory": str(ex_factory) if ex_factory else None,
			"lab_dip": mc.approval_info(sales_order, style, "Lab Dip", o.colour, so.customer)[0],
			"bulk_trim": mc.approval_info(sales_order, style, "Bulk Trim", None, so.customer)[0],
		})
		if tp and "materials" not in st:
			st["materials"] = [m.as_dict() for m in tp.materials]
	return {"sales_order": sales_order, "customer": so.customer, "company": so.company, "styles": list(styles.values()),
		"allowance_rules": frappe.get_all("Material Allowance Rule", {"enabled": 1}, ["material_type", "trim_category", "customer", "allowance_pct", "pack_size"]),
		"fr_material_types": mc.fr_material_types()}


@frappe.whitelist()
def save_fabric_requisition(data):
	"""Create or update a DRAFT fabric requisition. Validation runs. Never submits."""
	data = json.loads(data) if isinstance(data, str) else data
	if data.get("name") and frappe.db.exists("Fabric Requisition", data["name"]):
		doc = frappe.get_doc("Fabric Requisition", data["name"])
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft can be changed. Use Revise on an approved requisition."))
		doc.check_permission("write")
		doc.update({k: v for k, v in data.items() if k not in ("name", "items", "doctype")})
		if "items" in data:
			doc.set("items", data["items"])
		doc.save()
	else:
		doc = frappe.get_doc({**{k: v for k, v in data.items() if k != "name"}, "doctype": "Fabric Requisition"})
		doc.check_permission("create")
		doc.insert()
	return doc.name


@frappe.whitelist()
def revise_fabric_requisition(source_name):
	"""A new draft revision of an approved FR. Quantities are refreshed from the order on save; only the increase is
	requested again when it is submitted."""
	src = frappe.get_doc("Fabric Requisition", source_name)
	src.check_permission("read")
	if src.docstatus != 1 or src.status in ("Superseded", "Cancelled"):
		frappe.throw(_("Only an approved, current requisition can be revised."))
	new = frappe.copy_doc(src)
	new.docstatus = 0  # copy_doc keeps the source's docstatus; a revision starts as a draft
	for child in new.get_all_children():
		child.docstatus = 0
	new.previous_fr = src.name
	new.revision_no = cint(src.revision_no) + 1
	new.status = "Draft"
	new.set("summary", [])
	new.revision_reason = None
	new.approved_by = new.approved_on = None
	for r in new.items:
		for f in ("material_request", "material_request_item", "ordered_qty", "received_qty", "accepted_qty", "rejected_qty"):
			r.set(f, None if f in ("material_request", "material_request_item") else 0)
		r.garment_qty = order_colour_qty(r.sales_order, r.style_item, r.colour) or r.garment_qty
	return new
