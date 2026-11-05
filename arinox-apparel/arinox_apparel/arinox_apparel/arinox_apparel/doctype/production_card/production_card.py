# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Production Card: the order sheet issued to cutting. One per Sales Order x style x ex-factory date, one line per
colour x size. Submit = issue. Issuing needs no bulk gate (the PP meeting asks for an issued card, so the gate cannot
come first); the gate is checked at the first bulk lay. The card never creates purchase requests: fabric and trims are
requested by the Fabric and Trim Requisitions (Phase C)."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import get_order_lines
from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import get_style_dates
from arinox_apparel.materials import common as mc
from arinox_apparel.production import maths
from arinox_apparel.production.gate import active_card

LIVE_STATUSES = ("Superseded", "Cancelled")


def settings_value(field, default=None):
	v = frappe.db.get_single_value("Apparel Settings", field)
	return default if v in (None, "") else v


def order_matrix(sales_order, style_item):
	"""{(colour, size): {order_qty, tolerance_pct}} plus the earliest ex-factory date and the buyer POs of a style on an
	order. Sizes and colours come from the Sales Order items (they carry `apparel_size` and `apparel_colour`)."""
	cells, ex_factory, pos = {}, None, []
	for it in frappe.get_all(
		"Sales Order Item", {"parent": sales_order},
		["item_code", "qty", "apparel_colour", "apparel_size", "apparel_buyer_po", "apparel_qty_tolerance_pct", "delivery_date"]):
		style = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
		if style != style_item:
			continue
		key = ((it.apparel_colour or "").strip(), (it.apparel_size or "").strip())
		cell = cells.setdefault(key, frappe._dict(order_qty=0, tolerance_pct=0))
		cell.order_qty += cint(it.qty)
		cell.tolerance_pct = max(flt(cell.tolerance_pct), flt(it.apparel_qty_tolerance_pct))
		if it.delivery_date and (not ex_factory or getdate(it.delivery_date) < getdate(ex_factory)):
			ex_factory = getdate(it.delivery_date)
		if it.apparel_buyer_po and it.apparel_buyer_po not in pos:
			pos.append(it.apparel_buyer_po)
	return cells, ex_factory, pos


class ProductionCard(Document):
	def autoname(self):
		prefix = frappe.db.get_value("Company", self.company, "apparel_pc_prefix") or "PC"
		self.name = mc.next_number(prefix, self.issue_date or nowdate())

	# ---- lifecycle -----------------------------------------------------------------------------------------------
	def validate(self):
		self.check_order()
		self.fill_header()
		if cint(self.revision_no) > 0 and not (self.revision_reason or "").strip():
			frappe.throw(_("Enter the reason for this revision."))
		self.check_unique()
		flags = []
		self.compute_lines(flags)
		self.compute_fabrics(flags)
		self.check_route()
		self.set_pilot_required()
		self.red_flags = "\n".join(dict.fromkeys(flags))

	def before_submit(self):
		if not self.lines:
			frappe.throw(_("Add the colour x size breakup before issuing."))
		missing = self.missing_prerequisites()
		if missing:
			frappe.msgprint("<br>• ".join([_("Issued with these still open:")] + missing), indicator="orange", title=_("Production Card"))

	def on_submit(self):
		self.db_set({"issue_date": nowdate(), "status": "Issued"})
		if self.previous_card:
			from arinox_apparel.production import ledger

			frappe.db.set_value("Production Card", self.previous_card, "status", "Superseded")
			ledger.transfer_card(self.previous_card, self.name)
			self.refresh_status()
		self.link_pp_meeting()

	def on_cancel(self):
		if frappe.db.exists("Production Movement", {"production_card": self.name}):
			frappe.throw(_("Production card {0} already has cutting, sewing or packing quantities and cannot be cancelled. "
						   "Use Revise, or a Production Adjustment to correct a count.").format(self.name))
		self.db_set("status", "Cancelled")

	# ---- checks and fill ------------------------------------------------------------------------------------------
	def refresh_status(self):
		"""Status follows the furthest stage that has quantities (never moves backwards past Issued)."""
		if self.docstatus != 1 or self.status in ("Superseded", "Cancelled", "Closed"):
			return
		order = [("SHIPPED", "Shipped"), ("PACKED", "Packed"), ("FIN_IN", "In Finishing"), ("SC_OUT", "At Subcontractor"), ("SEW_IN", "In Sewing"), ("CUT", "In Cutting")]
		present = {r[0] for r in frappe.db.sql("select distinct stage from `tabProduction Movement` where production_card = %s", self.name)}
		status = "Issued"
		for stage, label in order:
			if stage in present:
				status = label
				break
		if status != self.status:
			self.db_set("status", status, update_modified=False)

	def check_order(self):
		so = frappe.db.get_value("Sales Order", self.sales_order, ["docstatus", "customer", "company"], as_dict=True)
		if not so or so.docstatus != 1:
			frappe.throw(_("Sales Order {0} must be submitted.").format(self.sales_order))
		if so.customer != self.customer:
			frappe.throw(_("Sales Order {0} belongs to {1}, not {2}.").format(self.sales_order, so.customer, self.customer))
		if so.company != self.company:
			frappe.throw(_("Sales Order {0} belongs to company {1}.").format(self.sales_order, so.company))

	def fill_header(self):
		item = frappe.db.get_value("Item", self.style_item, ["item_name"], as_dict=True)
		if not item:
			frappe.throw(_("Style item {0} not found.").format(self.style_item))
		tp = frappe.db.get_value("Tech Pack", {"style_item": self.style_item}, ["style_no", "style_name", "season"], as_dict=True)
		self.style_name = self.style_name or (tp.style_name if tp else None) or item.item_name
		self.style_no = self.style_no or (tp.style_no if tp else None) or self.style_item
		contract = frappe.db.get_value("Sales Order", self.sales_order, "apparel_sales_contract")
		self.sales_contract = contract
		self.season = self.season or (frappe.db.get_value("Sales Contract", contract, "season") if contract else None) or (tp.season if tp else None)
		cells, ex_factory, pos = order_matrix(self.sales_order, self.style_item)
		self.buyer_pos = "\n".join(pos)
		self.ex_factory_date = self.ex_factory_date or ex_factory
		pcd, _ex, _wh = get_style_dates(self.sales_order, self.style_item)
		self.pcd = self.pcd or pcd
		self.default_extra_cut_pct = self.default_extra_cut_pct if self.default_extra_cut_pct not in (None, "") else flt(settings_value("default_extra_cut_pct", 5))
		self.trim_allowance_pct = self.trim_allowance_pct if self.trim_allowance_pct not in (None, "") else flt(settings_value("trim_allowance_pct", 2))
		self.bundle_size = cint(self.bundle_size) or cint(settings_value("bundle_size", 20))
		if not self.factory or not self.line:
			fa = frappe.db.get_value("Factory Allocation", {"sales_order": self.sales_order}, "name")
			if fa:
				row = frappe.get_all("Factory Allocation Line", {"parent": fa, "style_item": self.style_item}, ["factory", "line"], limit=1)
				if row:
					self.factory = self.factory or row[0].factory
					self.line = self.line or row[0].line
		self.made_by = self.made_by or frappe.session.user

	def check_unique(self):
		"""One live card per order x style x ex-factory date. A revision chain shares the key."""
		others = frappe.get_all("Production Card", {
			"sales_order": self.sales_order, "style_item": self.style_item, "ex_factory_date": self.ex_factory_date,
			"docstatus": 1, "status": ["not in", LIVE_STATUSES], "name": ["!=", self.name or ""]}, pluck="name")
		others = [n for n in others if n != self.previous_card]
		if others:
			frappe.throw(_("Production card {0} already covers this order, style and ex-factory date. Use Revise on it.").format(others[0]))

	def compute_lines(self, flags):
		cells, _ex, _pos = order_matrix(self.sales_order, self.style_item)
		if not cells:
			frappe.throw(_("Style {0} has no lines on Sales Order {1}.").format(self.style_item, self.sales_order))
		seen = set()
		max_extra = flt(settings_value("max_extra_cut_pct", 8))
		is_manager = bool({"Apparel Production Manager", "Apparel Merchandising Manager", "System Manager"} & set(frappe.get_roles()))
		for r in self.lines:
			key = ((r.colour or "").strip(), (r.size or "").strip())
			if key in seen:
				frappe.throw(_("Row {0}: {1} {2} appears twice.").format(r.idx, *key))
			seen.add(key)
			cell = cells.get(key)
			if not cell:
				frappe.throw(_("Row {0}: {1} {2} is not on Sales Order {3}. Check the colour and size spelling.").format(r.idx, key[0], key[1], self.sales_order))
			r.colour, r.size = key
			r.order_qty = cell.order_qty
			r.max_qty = maths.max_ship_qty(cell.order_qty, cell.tolerance_pct)
			if r.extra_cut_pct in (None, ""):
				r.extra_cut_pct = self.default_extra_cut_pct
			if flt(r.extra_cut_pct) < 0:
				frappe.throw(_("Row {0}: extra cut cannot be negative.").format(r.idx))
			if flt(r.extra_cut_pct) > max_extra:
				if not is_manager:
					frappe.throw(_("Row {0}: extra cut {1}% is above the limit of {2}%. A production manager can allow it.").format(r.idx, r.extra_cut_pct, max_extra))
				flags.append(_("Extra cut above {0}% on {1} {2}.").format(max_extra, r.colour, r.size))
			r.planned_cut_qty = maths.planned_cut(r.order_qty, r.extra_cut_pct)
		for key in cells:
			if key not in seen:
				flags.append(_("{0} {1} is on the Sales Order but not on this card.").format(*key))
		source = self.name if (self.name and not self.is_new()) else self.previous_card
		if source:
			cut_over = []
			for r in self.lines:
				done = frappe.db.sql("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and colour=%s and size=%s and stage='CUT' and purpose != 'Re-cut'",
									 (source, r.colour, r.size))[0][0]
				if done > r.planned_cut_qty:
					cut_over.append(f"{r.colour} {r.size}: cut {int(done)} > plan {r.planned_cut_qty}")
			if cut_over:
				flags.append(_("Cut exceeds the revised plan: {0}").format("; ".join(cut_over)))

	def colour_cut(self, colour):
		return sum(cint(r.planned_cut_qty) for r in self.lines if (r.colour or "").strip().upper() == (colour or "").strip().upper())

	def compute_fabrics(self, flags):
		for r in self.fabrics:
			if flt(r.consumption) <= 0:
				frappe.throw(_("Fabric row {0}: consumption must be above zero.").format(r.idx))
			if not any((l.colour or "").strip().upper() == (r.colour or "").strip().upper() for l in self.lines):
				frappe.throw(_("Fabric row {0}: colour {1} is not on the size breakup.").format(r.idx, r.colour))
			gsm = width = None
			if r.fabric_item:
				gsm, width = frappe.db.get_value("Item", r.fabric_item, ["apparel_fabric_gsm", "apparel_fabric_width_cm"]) or (None, None)
			per_garment_m = mc.to_metres(flt(r.consumption), r.consumption_uom or "Meter", gsm, width)
			r.required_m = round(self.colour_cut(r.colour) * per_garment_m, 3)
			if r.fabric_requisition_item:
				fr = frappe.db.get_value("Fabric Requisition Item", r.fabric_requisition_item, ["net_qty", "accepted_qty"], as_dict=True)
				if fr:
					r.fr_net_m, r.accepted_m = flt(fr.net_qty), flt(fr.accepted_qty)
					if r.fr_net_m and r.required_m > r.fr_net_m * 1.01:
						flags.append(_("{0} {1}: card needs {2} m but the requisition covers {3} m.").format(r.colour, r.fabric_item or "", round(r.required_m, 1), round(r.fr_net_m, 1)))
			if r.fabric_item and self.name and not self.is_new():
				from arinox_apparel.production.stock import moved

				r.issued_m = moved(self.name, "Fabric Issue", r.fabric_item)
			r.shortage_m = round(max(flt(r.required_m) - flt(r.accepted_m), 0), 3) if r.accepted_m else flt(r.required_m)
			if r.shortage_m > 0 and self.docstatus == 1:
				flags.append(_("{0}: {1} m of fabric still to be accepted.").format(r.colour, round(r.shortage_m, 1)))

	def check_route(self):
		seen = set()
		for p in self.processes:
			key = (p.subcontract_process, (p.colour or "").strip().upper())
			if key in seen:
				frappe.throw(_("Process {0} appears twice on the route.").format(p.subcontract_process))
			seen.add(key)
			info = frappe.db.get_value("Subcontract Process", p.subcontract_process, ["default_position", "item_state"], as_dict=True)
			if not p.item_state and info:
				p.item_state = info.item_state
			if p.position == "Before Sewing" and p.item_state == "Garments":
				frappe.throw(_("{0}: garments cannot go out before sewing; choose Cut Panels or After Sewing.").format(p.subcontract_process))
			if p.position == "After Sewing" and p.item_state == "Cut Panels":
				frappe.throw(_("{0}: cut panels cannot be sent after sewing; choose Garments or Before Sewing.").format(p.subcontract_process))

	def set_pilot_required(self):
		total = sum(cint(r.order_qty) for r in self.lines)
		by_qty = total >= cint(settings_value("pilot_min_order_qty", 1000))
		by_rule = False
		if frappe.db.exists("DocType", "Pilot Run"):
			rule = frappe.db.get_value("Apparel Sample Rule", {"parent": "Apparel Settings", "sample_type": "Pilot Run"}, "gate")
			by_rule = rule == "Required"  # "If Raised" means the buyer must ask; only an explicit Required rule forces a pilot
		self.pilot_required = 1 if (by_qty or by_rule) else 0
		if cint(self.pilot_waiver):
			if not ({"Apparel Production Manager", "System Manager"} & set(frappe.get_roles())) and self.has_value_changed("pilot_waiver"):
				frappe.throw(_("Only a production manager can waive the pilot run."))
			if not (self.pilot_waiver_reason or "").strip():
				frappe.throw(_("Enter the reason for waiving the pilot run."))

	def missing_prerequisites(self):
		out = []
		if not frappe.db.exists("Factory Allocation", {"sales_order": self.sales_order}):
			out.append(_("No Factory Allocation for this order."))
		if not frappe.db.exists("Tech Pack", {"style_item": self.style_item, "docstatus": ["<", 2]}):
			out.append(_("No Tech Pack for this style."))
		if not frappe.db.exists("Fabric Requisition Item", {"sales_order": self.sales_order, "style_item": self.style_item, "docstatus": 1}):
			out.append(_("No approved Fabric Requisition."))
		if not frappe.db.exists("Trim Requisition Item", {"sales_order": self.sales_order, "style_item": self.style_item, "docstatus": 1}):
			out.append(_("No approved Trim Requisition."))
		if not self.packing_instruction:
			out.append(_("No Packing Instruction."))
		return out

	def link_pp_meeting(self):
		"""The PP meeting asks for an issued production card; hand it the reference on any draft meeting."""
		for name in frappe.get_all("PP Meeting", {"sales_order": self.sales_order, "style_item": self.style_item, "docstatus": 0}, pluck="name"):
			frappe.db.set_value("PP Meeting", name, {"production_card_ref": self.name, "production_card_issued_on": nowdate()}, update_modified=False)

	# ---- reads for the form and the agent --------------------------------------------------------------------------
	@frappe.whitelist()
	def get_summary(self):
		return production_summary(self.name)


def line_defaults(sales_order, style_item):
	cells, ex_factory, pos = order_matrix(sales_order, style_item)
	return cells, ex_factory, pos


@frappe.whitelist()
def get_card_lines(sales_order, style_item):
	"""Colour x size rows for a new card, straight from the Sales Order."""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	cells, ex_factory, pos = order_matrix(sales_order, style_item)
	order = sorted(cells, key=lambda k: (k[0], k[1]))
	return {
		"lines": [{"colour": c, "size": s, "order_qty": cells[(c, s)].order_qty} for c, s in order],
		"ex_factory_date": str(ex_factory) if ex_factory else None,
		"buyer_pos": pos,
	}


@frappe.whitelist()
def revise_production_card(source_name):
	"""New draft from an issued card, quantities refreshed from the current Sales Order. Cancel-and-amend is not used:
	cutting may already have started."""
	if not frappe.has_permission("Production Card", "create"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	src = frappe.get_doc("Production Card", source_name)
	if src.docstatus != 1 or src.status in LIVE_STATUSES:
		frappe.throw(_("Only an issued, current production card can be revised."))
	new = frappe.copy_doc(src)
	new.previous_card = src.name
	new.revision_no = cint(src.revision_no) + 1
	new.revision_reason = None
	new.status = "Draft"
	new.issue_date = None
	for r in new.lines:
		r.planned_cut_qty = None
	return new.as_dict()


# ---- summary and agent API --------------------------------------------------------------------------------------------

def production_summary(card):
	"""Stage totals per colour x size for one card, with the plan next to them."""
	from arinox_apparel.production import ledger

	doc = frappe.get_doc("Production Card", card)
	tot = ledger.totals(card)
	rows = []
	for l in doc.lines:
		t = tot.get((l.colour, l.size), {})
		rows.append({"colour": l.colour, "size": l.size, "order_qty": l.order_qty, "planned_cut_qty": l.planned_cut_qty, **t})
	return {"card": card, "status": doc.status, "rows": rows}


@frappe.whitelist()
def get_production_context(sales_order):
	"""Everything an agent needs to draft production cards for an order."""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	styles = {}
	for it in frappe.get_all("Sales Order Item", {"parent": sales_order}, ["item_code"]):
		styles[frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code] = 1
	out = []
	for style in styles:
		cells, ex_factory, pos = order_matrix(sales_order, style)
		card = active_card(sales_order, style)
		out.append({
			"style_item": style, "ex_factory_date": str(ex_factory) if ex_factory else None, "buyer_pos": pos,
			"lines": [{"colour": c, "size": s, "order_qty": v.order_qty, "tolerance_pct": v.tolerance_pct} for (c, s), v in sorted(cells.items())],
			"card": card.name if card else None,
			"fabric_requisitions": frappe.get_all("Fabric Requisition Item", {"sales_order": sales_order, "style_item": style, "docstatus": 1}, ["parent", "colour", "net_qty", "accepted_qty"]),
			"trim_requisitions": frappe.get_all("Trim Requisition Item", {"sales_order": sales_order, "style_item": style, "docstatus": 1}, ["parent", "trim_category", "colour", "net_qty"]),
			"allocation": frappe.get_all("Factory Allocation Line", {"parent": frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name") or "", "style_item": style}, ["colour", "factory", "line", "pcd", "sewing_start", "sewing_end"]),
		})
	return {"sales_order": sales_order, "styles": out,
			"defaults": {"extra_cut_pct": flt(settings_value("default_extra_cut_pct", 5)), "bundle_size": cint(settings_value("bundle_size", 20))}}


@frappe.whitelist()
def save_production_card(data):
	"""Create or update a DRAFT production card (validation runs). Never submits."""
	data = json.loads(data) if isinstance(data, str) else data
	if data.get("name") and frappe.db.exists("Production Card", data["name"]):
		doc = frappe.get_doc("Production Card", data["name"])
		if doc.docstatus != 0:
			frappe.throw(_("Only a draft production card can be changed here."))
		if not frappe.has_permission("Production Card", "write", doc):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc.update({k: v for k, v in data.items() if k not in ("name", "doctype", "docstatus")})
	else:
		if not frappe.has_permission("Production Card", "create"):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		doc = frappe.get_doc({**data, "doctype": "Production Card"})
	doc.save()
	return {"name": doc.name, "red_flags": doc.red_flags, "planned_cut_total": sum(cint(r.planned_cut_qty) for r in doc.lines)}


@frappe.whitelist()
def get_production_status(sales_order):
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	cards = frappe.get_all("Production Card", {"sales_order": sales_order, "docstatus": 1, "status": ["not in", LIVE_STATUSES]}, pluck="name")
	return [production_summary(c) for c in cards]


@frappe.whitelist()
def get_order_styles(sales_order):
	"""Style templates on a Sales Order, for the style picker."""
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	styles = []
	for it in frappe.get_all("Sales Order Item", {"parent": sales_order}, ["item_code"]):
		s = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
		if s not in styles:
			styles.append(s)
	return styles
