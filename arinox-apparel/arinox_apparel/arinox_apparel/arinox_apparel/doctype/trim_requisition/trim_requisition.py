# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Trim Requisition (TR): labels, thread, fusing, buttons, tags, packaging for an order. Quantities depend on the
basis: per garment, per size, per colour, per carton, by length or a fixed quantity. Submit = approved."""

import json
import math
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime

from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import colour_level, get_order_lines
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import get_style_dates
from arinox_apparel.materials import common as mc

LENGTH_BASES = ("By Length",)


def row_key(r):
	return "|".join([
		r.sales_order or "", r.style_item or "", (r.colour or "").strip().upper(), (r.size or "").strip().upper(),
		r.trim_category or "", r.trim_item or r.description or "", (r.trim_colour or "").strip().upper(),
	])


def material_type_for(category):
	c = (category or "").lower()
	if "label" in c:
		return "Label"
	if "packaging" in c:
		return "Packaging"
	return "Trim"


def guess_category(material_type, description):
	"""Trim Category for a Tech Pack material row, from its type and words in the description."""
	d = (description or "").lower()
	for words, cat in (
		(("size label", "size tab", "size tag"), "Size Label"), (("care", "wash care"), "Care Label"), (("thread",), "Thread"),
		(("fusing", "interlining", "keo"), "Fusing / Interlining"), (("security",), "Security Tag"),
		(("hang tag", "hangtag", "price ticket"), "Hang Tag"), (("button",), "Button"), (("zip", "hook", "fastener", "velcro"), "Zipper / Hooks / Fasteners"),
		(("elastic", "tape", "drawcord", "cord"), "Elastic / Tape"), (("label",), "Woven Label"),
		(("carton", "poly", "bag", "tissue", "silica", "sticker", "hanger"), "Packaging"),
	):
		if any(w in d for w in words):
			return cat
	return "Packaging" if material_type == "Packaging" else "Others"


class TrimRequisition(Document):
	def autoname(self):
		prefix = frappe.db.get_value("Company", self.company, "apparel_tr_prefix") or "TR"
		self.name = mc.next_number(prefix, self.tr_date)

	def validate(self):
		if not self.ordered_by:
			self.ordered_by = frappe.session.user
		if not self.items:
			frappe.throw(_("Add at least one trim line."))
		if cint(self.revision_no) > 0 and not (self.revision_reason or "").strip():
			frappe.throw(_("Enter the reason for this revision."))
		self.check_duplicates()
		flags = []
		for r in self.items:
			self.fill_row(r, flags)
			self.compute_row(r, flags)
		self.check_revision(flags)
		self.red_flags = "\n".join(dict.fromkeys(flags))
		self.set_status()

	def before_submit(self):
		for r in self.items:
			if not r.trim_item:
				frappe.throw(_("Row {0}: choose or create the trim item before approving.").format(r.idx))
			if not r.supplier and not cint(r.customer_provided):
				frappe.throw(_("Row {0}: choose a supplier, or mark the trim as buyer supplied.").format(r.idx))

	def on_submit(self):
		self.db_set({"approved_by": frappe.session.user, "approved_on": now_datetime()})
		self.create_requests()
		if self.previous_tr:
			frappe.db.set_value("Trim Requisition", self.previous_tr, "status", "Superseded")
		mc.stamp_safe_requisition(self, "TR_RAISED")
		self.set_status(save=True)

	def before_cancel(self):
		for parent, name in frappe.db.sql(
			"""select i.parent, i.name from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.apparel_requisition_type = 'TR' and i.apparel_requisition = %s and m.docstatus = 1""", self.name):
			po = frappe.db.sql("select distinct p.parent from `tabPurchase Order Item` p where p.material_request_item = %s and p.docstatus < 2", name)
			if po:
				frappe.throw(_("Material Request {0} is already on Purchase Order {1}. Cancel the order first, or revise this requisition.").format(parent, po[0][0]))

	def on_cancel(self):
		for mr in {m[0] for m in frappe.db.sql(
			"""select distinct i.parent from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.apparel_requisition_type = 'TR' and i.apparel_requisition = %s and m.docstatus = 1""", self.name)}:
			doc = frappe.get_doc("Material Request", mr)
			doc.flags.ignore_permissions = True
			doc.cancel()
		if self.previous_tr:
			prev = frappe.get_doc("Trim Requisition", self.previous_tr)
			prev.db_set("status", "Approved")
			prev.set_status(save=True)
		mc.unstamp_safe("Trim Requisition", self.name)
		self.db_set("status", "Cancelled")

	# ---- rows -----------------------------------------------------------------------------------------------------
	def check_duplicates(self):
		seen = {}
		for r in self.items:
			if not (r.trim_item or r.description):
				continue
			k = row_key(r)
			if k in seen:
				frappe.throw(_("Row {0} repeats row {1}: same order, style, colour, size, category and trim.").format(r.idx, seen[k]))
			seen[k] = r.idx

	def fill_row(self, r, flags):
		so = frappe.db.get_value("Sales Order", r.sales_order, ["docstatus", "customer", "company"], as_dict=True)
		if not so:
			frappe.throw(_("Row {0}: Sales Order {1} does not exist.").format(r.idx, r.sales_order))
		if so.docstatus != 1:
			frappe.throw(_("Row {0}: Sales Order {1} is not submitted.").format(r.idx, r.sales_order))
		if so.customer != self.customer or so.company != self.company:
			frappe.throw(_("Row {0}: Sales Order {1} belongs to another buyer or company.").format(r.idx, r.sales_order))
		if frappe.db.get_value("Item", r.style_item, "variant_of"):
			frappe.throw(_("Row {0}: pick the style (template item), not a variant.").format(r.idx))
		r.style_no = r.style_no or frappe.db.get_value("Tech Pack", {"style_item": r.style_item}, "style_no") or r.style_item
		# DTM resolves to the garment colour
		if (r.trim_colour or "").strip().upper() in ("DTM", "DTM GROUND COLOR", "DYED TO MATCH") and r.colour:
			r.trim_colour = r.colour
		if not cint(r.garment_qty) and r.calc_basis != "Fixed Qty":
			r.garment_qty = self.order_qty_for(r)
		if r.customer_provided and not r.trim_item:
			pass
		# approval hold
		status, ok = mc.approval_info(r.sales_order, r.style_item, "Bulk Trim", None, self.customer)
		r.approval_status = status
		hold_mode = (mc.settings().get("hold_po_until_approval") or "Warn")
		r.hold = 1 if (not ok and hold_mode != "Off" and not cint(r.customer_provided)) else 0
		if r.hold:
			flags.append(_("Row {0}: bulk trim approval is {1}; the purchase order will be held.").format(r.idx, status))
		pcd = get_style_dates(r.sales_order, r.style_item, r.colour or None)[0]
		due_days = cint(mc.settings().get("trim_due_days_before_pcd") or 7)
		if pcd and not r.required_by:
			r.required_by = add_days(pcd, -due_days)
		if pcd and r.required_by and getdate(r.required_by) > add_days(getdate(pcd), -due_days):
			flags.append(_("Row {0}: required by {1} is later than PCD {2} minus {3} days.").format(r.idx, r.required_by, pcd, due_days))
		if not pcd:
			flags.append(_("Row {0}: no planned cut date yet; set the Factory Allocation.").format(r.idx))

	def order_qty_for(self, r):
		"""Garment qty for the row's scope: a size, a colour, or the whole style."""
		total = 0
		for it in frappe.get_all("Sales Order Item", {"parent": r.sales_order}, ["item_code", "qty", "apparel_colour", "apparel_size"]):
			if mc.style_of(it.item_code) != r.style_item:
				continue
			if r.colour and (it.apparel_colour or "").strip().upper() != r.colour.strip().upper():
				continue
			if r.size and (it.apparel_size or "").strip().upper() != r.size.strip().upper():
				continue
			total += cint(it.qty)
		return total

	def compute_row(self, r, flags):
		basis = r.calc_basis or "Per Garment"
		rule = mc.get_allowance(material_type_for(r.trim_category), r.trim_category, self.customer)
		default_pct = flt(rule.allowance_pct)
		if r.allowance_pct is None:
			r.allowance_pct = default_pct
		elif flt(r.allowance_pct) != default_pct and not (r.allowance_reason or "").strip():
			frappe.throw(_("Row {0}: the allowance {1}% differs from the rule ({2}%). Enter the reason.").format(r.idx, r.allowance_pct, default_pct))
		if not flt(r.pack_size):
			r.pack_size = flt(rule.pack_size)
		a = 1 + flt(r.allowance_pct) / 100
		gq, qpg, spare = cint(r.garment_qty), flt(r.qty_per_garment), flt(r.spare_per_garment)
		if basis == "Per Garment" or basis in ("Per Size", "Per Colour"):
			if basis == "Per Size" and not (r.size or "").strip():
				frappe.throw(_("Row {0}: a per-size line needs the size.").format(r.idx))
			if basis == "Per Colour" and not (r.colour or "").strip():
				frappe.throw(_("Row {0}: a per-colour line needs the colour.").format(r.idx))
			gross = gq * (qpg + spare) * a
		elif basis == "Per Carton":
			if cint(r.pcs_per_carton) <= 0:
				frappe.throw(_("Row {0}: enter the pieces per carton.").format(r.idx))
			gross = math.ceil(gq / cint(r.pcs_per_carton)) * qpg * a
		elif basis == "By Length":
			if flt(r.consumption) <= 0 or not r.consumption_uom:
				frappe.throw(_("Row {0}: enter the length per garment and its unit.").format(r.idx))
			gross = gq * flt(r.consumption) * a
		else:  # Fixed Qty
			gross = qpg
		if qpg <= 0 and basis != "By Length":
			frappe.throw(_("Row {0}: enter the quantity per garment (or carton).").format(r.idx))
		r.gross_qty = flt(gross, 4)
		if flt(r.stock_used) > 0:
			if not r.stock_warehouse or not r.trim_item:
				frappe.throw(_("Row {0}: choose the trim item and warehouse to use leftover stock.").format(r.idx))
			free = mc.free_stock(r.trim_item, r.stock_warehouse, "Trim Requisition", "Trim Requisition Item", self.name)
			if flt(r.stock_used) > free + 0.0001:
				frappe.throw(_("Row {0}: only {1} of {2} is free in {3} (the rest is claimed by other requisitions).").format(
					r.idx, flt(free, 2), r.trim_item, r.stock_warehouse))
		r.net_qty = flt(max(flt(r.gross_qty) - flt(r.stock_used), 0), 4)
		base_uom = r.consumption_uom if basis == "By Length" else (frappe.db.get_value("Item", r.trim_item, "stock_uom") if r.trim_item else None) or "Nos"
		r.order_uom = r.order_uom or base_uom
		qty = r.net_qty
		if r.order_uom != base_uom:
			if mc.uom_kind(r.order_uom) and mc.uom_kind(base_uom) in ("m", "yd"):
				qty = mc.from_metres(mc.to_metres(qty, base_uom), r.order_uom)
			else:
				frappe.throw(_("Row {0}: cannot convert {1} to {2}. Use the same unit or a length unit.").format(r.idx, base_uom, r.order_uom))
		if basis == "By Length":
			r.order_qty = mc.round_up_to_pack(flt(qty, 2), r.pack_size) if r.net_qty > 0 else 0
		else:
			r.order_qty = mc.round_up_to_pack(math.ceil(round(qty, 4)), r.pack_size) if r.net_qty > 0 else 0

	def check_revision(self, flags):
		if not self.previous_tr:
			return
		chain = mc.revision_chain("Trim Requisition", "previous_tr", self.previous_tr)
		for r in self.items:
			before = mc.requested_so_far("TR", chain, row_key(r))
			if before and flt(r.net_qty) + 0.0005 < before:
				flags.append(_("Row {0}: reduced from {1} to {2}. Reduce the order with the supplier.").format(r.idx, flt(before, 2), flt(r.net_qty, 2)))

	# ---- status and requests ----------------------------------------------------------------------------------------
	def set_status(self, save=False):
		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 2:
			status = "Cancelled"
		elif self.status == "Superseded":
			status = "Superseded"
		else:
			need = [r for r in self.items if flt(r.net_qty) > 0]
			if not need or all(flt(r.received_qty) + 0.0005 >= flt(r.net_qty) for r in need):
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

	def create_requests(self):
		chain = mc.revision_chain("Trim Requisition", "previous_tr", self.name)[1:]
		lines = []
		for r in self.items:
			if flt(r.net_qty) <= 0:
				continue
			key = row_key(r)
			delta = flt(r.net_qty) - mc.requested_so_far("TR", chain, key)
			if delta <= 0.0005:
				continue
			stock_uom = frappe.db.get_value("Item", r.trim_item, "stock_uom")
			order_qty = delta if r.order_uom == stock_uom else mc.round_up_to_pack(delta, r.pack_size)
			qty, uom, cf = mc.mr_line(r.trim_item, delta, r.order_uom, order_qty)
			if cf == 1 and uom == stock_uom:
				qty = math.ceil(round(delta, 4)) if r.calc_basis != "By Length" else flt(delta, 2)
			lines.append({
				"item_code": r.trim_item, "qty": qty, "uom": uom, "conversion_factor": cf, "supplier": r.supplier,
				"required_by": r.required_by, "key": key, "style_no": r.style_no, "colour": r.colour, "sales_order": r.sales_order,
				"description": r.description, "customer_provided": cint(r.customer_provided),
				"hold_reason": _("Trim approval {0}").format(r.approval_status) if r.hold else None,
			})
		mc.create_material_requests(self, lines, "TR", "Trim")
		for r in self.items:
			mri = frappe.db.sql(
				"""select i.name, i.parent from `tabMaterial Request Item` i where i.apparel_requisition_type = 'TR' and i.apparel_requisition = %s
				and i.apparel_requisition_item = %s limit 1""", (self.name, row_key(r)))
			if mri:
				r.db_set({"material_request": mri[0][1], "material_request_item": mri[0][0]})

	# ---- buttons ------------------------------------------------------------------------------------------------
	@frappe.whitelist()
	def get_lines_from_sales_orders(self, sales_orders):
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
	def create_trim_items(self):
		from arinox_apparel.materials.items import ensure_trim_item

		self.check_permission("write")
		made = []
		for r in self.items:
			if r.trim_item:
				continue
			code = re.sub(r"[^A-Za-z0-9]+", "-", (r.buyer_item_code or r.description or "").strip()).strip("-").upper()[:60]
			if not code:
				frappe.throw(_("Row {0}: enter a buyer item code or a description first.").format(r.idx))
			uom = r.consumption_uom if r.calc_basis == "By Length" and r.consumption_uom else "Nos"
			r.trim_item = ensure_trim_item(f"TRIM-{code}", r.description, r.trim_category, uom, self.customer, r.buyer_item_code, cint(r.customer_provided))
			made.append(r.trim_item)
		return made


def lines_for_sales_order(sales_order, customer, company):
	"""TR line dicts for one Sales Order from the Tech Pack materials that are not fabric."""
	so = frappe.db.get_value("Sales Order", sales_order, ["docstatus", "customer", "company"], as_dict=True)
	if not so or so.docstatus != 1 or so.customer != customer or so.company != company:
		frappe.throw(_("Sales Order {0} must be submitted and belong to this buyer and company.").format(sales_order))
	fr_types = mc.fr_material_types()
	order = get_order_lines(sales_order)
	by_colour = colour_level(order)
	size_qty = {}
	for it in frappe.get_all("Sales Order Item", {"parent": sales_order}, ["item_code", "qty", "apparel_colour", "apparel_size"]):
		key = (mc.style_of(it.item_code), (it.apparel_size or "").strip())
		size_qty[key] = size_qty.get(key, 0) + cint(it.qty)
	styles = {}
	for (style, _c), o in by_colour.items():
		styles.setdefault(style, []).append(o)
	out = []
	for style, colours in styles.items():
		tp = mc.tech_pack_for(style)
		if not tp:
			frappe.msgprint(_("Style {0} has no submitted Tech Pack; no trim lines were made for it.").format(style))
			continue
		cs = mc.cost_sheet_for(sales_order, style)
		pcs = cint(cs.pcs_per_carton) if cs else 0
		total = sum(cint(c.qty) for c in colours)
		all_colours = [c.colour for c in tp.colours]
		for m in tp.materials:
			if m.material_type in fr_types:
				continue
			cat = guess_category(m.material_type, m.description)
			base = {
				"sales_order": sales_order, "style_item": style, "style_no": tp.style_no, "trim_category": cat, "trim_item": m.item,
				"buyer_item_code": m.buyer_item_code, "description": m.description, "supplier": m.nominated_supplier,
				"nominated_by_buyer": 1 if m.nominated_supplier else 0, "customer_provided": 1 if m.buyer_supplied else 0,
			}
			is_length = mc.uom_kind(m.uom) in ("m", "yd")
			cons = flt(m.consumption) or 1
			dtm = "dtm" in (m.description or "").lower() or (m.colour or "").strip().upper() == "DTM"
			if cat == "Size Label":
				for (st, size), q in sorted(size_qty.items()):
					if st == style and size:
						out.append({**base, "size": size, "calc_basis": "Per Size", "garment_qty": q, "qty_per_garment": cons if not is_length else 1})
			elif cat == "Packaging" and "carton" in (m.description or "").lower():
				if not pcs:
					frappe.msgprint(_("Style {0}: set the pieces per carton on the Cost Sheet to get the carton line.").format(style))
					continue
				out.append({**base, "calc_basis": "Per Carton", "garment_qty": total, "qty_per_garment": cons, "pcs_per_carton": pcs})
			elif dtm or ((m.colour or "").strip() and mc.colour_matches(m.colour, "", all_colours) is False):
				for c in colours:
					if not dtm and (m.colour or "").strip().upper() != (c.colour or "").strip().upper():
						continue
					row = {**base, "colour": c.colour, "trim_colour": c.colour, "garment_qty": cint(c.qty)}
					row.update({"calc_basis": "By Length", "consumption": cons, "consumption_uom": m.uom or "Meter"} if is_length else
						{"calc_basis": "Per Garment", "qty_per_garment": cons})
					out.append(row)
			elif is_length:
				out.append({**base, "calc_basis": "By Length", "garment_qty": total, "consumption": cons, "consumption_uom": m.uom})
			else:
				out.append({**base, "calc_basis": "Per Garment", "garment_qty": total, "qty_per_garment": cons})
	return out


@frappe.whitelist()
def save_trim_requisition(data):
	"""Create or update a DRAFT trim requisition. Validation runs. Never submits."""
	data = json.loads(data) if isinstance(data, str) else data
	if data.get("name") and frappe.db.exists("Trim Requisition", data["name"]):
		doc = frappe.get_doc("Trim Requisition", data["name"])
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft can be changed. Use Revise on an approved requisition."))
		doc.check_permission("write")
		doc.update({k: v for k, v in data.items() if k not in ("name", "items", "doctype")})
		if "items" in data:
			doc.set("items", data["items"])
		doc.save()
	else:
		doc = frappe.get_doc({**{k: v for k, v in data.items() if k != "name"}, "doctype": "Trim Requisition"})
		doc.check_permission("create")
		doc.insert()
	return doc.name


@frappe.whitelist()
def revise_trim_requisition(source_name):
	src = frappe.get_doc("Trim Requisition", source_name)
	src.check_permission("read")
	if src.docstatus != 1 or src.status in ("Superseded", "Cancelled"):
		frappe.throw(_("Only an approved, current requisition can be revised."))
	new = frappe.copy_doc(src)
	new.docstatus = 0
	for child in new.get_all_children():
		child.docstatus = 0
	new.previous_tr = src.name
	new.revision_no = cint(src.revision_no) + 1
	new.status = "Draft"
	new.revision_reason = None
	new.approved_by = new.approved_on = None
	for r in new.items:
		r.material_request = r.material_request_item = None
		for f in ("ordered_qty", "received_qty", "accepted_qty", "rejected_qty"):
			r.set(f, 0)
		r.garment_qty = new.order_qty_for(r) or r.garment_qty
	return new
