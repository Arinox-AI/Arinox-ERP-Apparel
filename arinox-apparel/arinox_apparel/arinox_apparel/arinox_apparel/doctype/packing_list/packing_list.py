# Copyright (c) 2026, Arinox AI and contributors
"""Packing List: cartons of a Sales Order's pieces for one buyer PO and ship-to. Replaces ERPNext's Packing Slip, which
needs a draft Delivery Note and has no carton range, ratio, CBM or SSCC. Posts PACKED to the production ledger and
drafts the finished-goods receipt. Cartons are numbered as a run of identical cartons (`1~11`) like the company's sheet."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from arinox_apparel.arinox_apparel.doctype.needle_detector_log.needle_detector_log import needle_problems
from arinox_apparel.production import ledger, maths, packing, stock
from arinox_apparel.production.flow import Flow
from arinox_apparel.shipping import common

OPEN_STATES = ("Open", "On Shipment")


class PackingList(Document):
	def autoname(self):
		self.name = common.next_serial(common.card_root(self.production_card), "PL")

	# ---- validation ----------------------------------------------------------------------------------------------
	def validate(self):
		card = common.require_open_card(self.production_card)
		self.sales_contract, self.sales_order, self.customer, self.style_item = card.sales_contract, card.sales_order, card.customer, card.style_item
		if not cint(self.pcs_per_carton) or cint(self.pcs_per_carton) <= 0:
			frappe.throw(_("Enter the pieces per carton."))
		self.fill_carton_dimensions()
		if self.cartons or self.docstatus == 1:
			self.check_cartons()
			self.check_contents()
		self.compute_totals()
		self.set_size_summary()

	def fill_carton_dimensions(self):
		default = frappe.db.get_value("Shipment Parcel Template", self.carton_type, ["length", "width", "height"], as_dict=True) if self.carton_type else None
		for c in self.cartons:
			if default and not (flt(c.length_cm) and flt(c.width_cm) and flt(c.height_cm)):
				c.length_cm, c.width_cm, c.height_cm = default.length, default.width, default.height
			if not c.carton_type:
				c.carton_type = self.carton_type

	def check_cartons(self):
		if not self.cartons:
			frappe.throw(_("Add the cartons, or use Generate Cartons."))
		problems = packing.check_ranges([(c.carton_from, c.carton_to) for c in self.cartons])
		first = min(cint(c.carton_from) for c in self.cartons)
		if first != cint(self.carton_start or 1):
			problems.append(_("Cartons must start at {0}.").format(cint(self.carton_start or 1)))
		if problems:
			frappe.throw("<br>".join(problems), title=_("Carton numbers"))
		for c in self.cartons:
			c.carton_count = cint(c.carton_to) - cint(c.carton_from) + 1
			c.cbm_per_carton = round(maths.carton_cbm(c.length_cm or 0, c.width_cm or 0, c.height_cm or 0), 6)
			c.total_cbm = round(c.cbm_per_carton * c.carton_count, 6)

	def check_contents(self):
		items = frappe.get_all("Sales Order Item", {"parent": self.sales_order}, ["name", "apparel_colour", "apparel_size", "apparel_ship_to", "apparel_buyer_po"])
		on_card = {(l.colour, l.size) for l in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["colour", "size"])}
		by_row = {}
		for ct in self.contents:
			ct.qty_per_carton = cint(ct.qty_per_carton)
			if ct.qty_per_carton <= 0:
				frappe.throw(_("Carton content row {0}: enter a quantity above zero.").format(ct.idx))
			if (ct.colour, ct.size) not in on_card:
				frappe.throw(_("Carton content row {0}: {1} {2} is not on production card {3}.").format(ct.idx, ct.colour, ct.size, self.production_card))
			ct.sales_order_item = self.match_order_item(items, ct)
			by_row[cint(ct.carton_from)] = by_row.get(cint(ct.carton_from), 0) + ct.qty_per_carton
		for c in self.cartons:
			got = by_row.get(cint(c.carton_from), 0)
			if not got:
				frappe.throw(_("Cartons {0}~{1} have no contents.").format(c.carton_from, c.carton_to))
			c.pieces_per_carton = got
			c.total_pieces = got * c.carton_count
		known = {cint(c.carton_from) for c in self.cartons}
		for k in by_row:
			if k not in known:
				frappe.throw(_("Contents point at carton row {0}, which does not exist.").format(k))
		for ct in self.contents:
			count = next(c.carton_count for c in self.cartons if cint(c.carton_from) == cint(ct.carton_from))
			ct.pieces_total = ct.qty_per_carton * count

	def match_order_item(self, items, ct):
		cands = [i for i in items if i.apparel_colour == ct.colour and i.apparel_size == ct.size]
		if self.ship_to and any(i.apparel_ship_to for i in cands):
			cands = [i for i in cands if (i.apparel_ship_to or "") == self.ship_to]
		if self.buyer_po and any(i.apparel_buyer_po for i in cands):
			cands = [i for i in cands if (i.apparel_buyer_po or "") == self.buyer_po]
		if not cands:
			frappe.throw(_("{0} {1} (ship to {2}) is not on Sales Order {3}.").format(ct.colour, ct.size, self.ship_to or "-", self.sales_order))
		return cands[0].name

	def compute_totals(self):
		self.total_cartons = sum(c.carton_count for c in self.cartons)
		self.total_pieces = sum(c.total_pieces for c in self.cartons)
		self.total_net_kg = round(sum(flt(c.net_weight_kg) * c.carton_count for c in self.cartons), 3)
		self.total_gross_kg = round(sum(flt(c.gross_weight_kg) * c.carton_count for c in self.cartons), 3)
		self.total_cbm = round(sum(c.total_cbm for c in self.cartons), 6)

	def pieces_by_key(self):
		out = {}
		for ct in self.contents:
			out[(ct.colour, ct.size)] = out.get((ct.colour, ct.size), 0) + cint(ct.pieces_total)
		return out

	def set_size_summary(self):
		packed = packed_by_key(self.production_card, exclude=self.name, states=(0, 1))
		for k, v in self.pieces_by_key().items():
			packed[k] = packed.get(k, 0) + v
		ordered = {}
		for i in frappe.get_all("Sales Order Item", {"parent": self.sales_order}, ["apparel_colour", "apparel_size", "qty"]):
			if (i.apparel_colour, i.apparel_size) in {(l.colour, l.size) for l in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["colour", "size"])}:
				ordered[(i.apparel_colour, i.apparel_size)] = ordered.get((i.apparel_colour, i.apparel_size), 0) + flt(i.qty)
		self.size_summary, total = packing.size_summary(packed, ordered)
		self.total_vs_order_pct = total

	# ---- generate ------------------------------------------------------------------------------------------------
	@frappe.whitelist()
	def generate_cartons(self, quantities=None):
		"""Build the carton rows from `quantities` ({'colour|size': pieces}); default is everything packable for this
		ship-to. Replaces the current rows."""
		if self.docstatus != 0:
			frappe.throw(_("Only a draft can be regenerated."))
		qty = {}
		if quantities:
			import json as _json

			for k, v in (_json.loads(quantities) if isinstance(quantities, str) else quantities).items():
				c, s = k.split("|", 1)
				qty[(c, s)] = cint(v)
		else:
			qty = self.packable()
		if not qty:
			frappe.throw(_("Nothing is available to pack: finish pieces into A-grade first."))
		ratio = {r.size: cint(r.pieces_per_pack) for r in self.ratios}
		try:
			plan = packing.plan_cartons(qty, self.pack_type, cint(self.pcs_per_carton), ratio, self.tail_carton_rule, cint(self.carton_start or 1))
		except ValueError as e:
			frappe.throw(str(e))
		self.set("cartons", [])
		self.set("contents", [])
		for row in plan:
			self.append("cartons", {"carton_from": row["carton_from"], "carton_to": row["carton_to"], "tail": row["tail"], "carton_type": self.carton_type})
			for colour, size, q in row["contents"]:
				self.append("contents", {"carton_from": row["carton_from"], "colour": colour, "size": size, "qty_per_carton": q})
		self.fill_carton_dimensions()
		return len(plan)

	def packable(self):
		"""Pieces that can still go into cartons: A-grade not sampled or packed, less pieces on other draft lists, kept inside
		what the order (plus its tolerance) still allows for this ship-to."""
		flow = Flow(self.production_card)
		drafts = packed_by_key(self.production_card, exclude=self.name, states=(0,))
		others = packed_by_key(self.production_card, exclude=self.name, states=(0, 1), ship_to=self.ship_to)
		items = frappe.get_all("Sales Order Item", {"parent": self.sales_order}, ["apparel_colour", "apparel_size", "apparel_ship_to", "qty", "apparel_qty_tolerance_pct"])
		out = {}
		for l in flow.doc.lines:
			key = (l.colour, l.size)
			avail = flow.t(*key, "FIN_A") - flow.t(*key, "SAMPLE_OUT") - flow.t(*key, "PACKED") - drafts.get(key, 0)
			rows = [i for i in items if i.apparel_colour == l.colour and i.apparel_size == l.size and (not self.ship_to or not i.apparel_ship_to or i.apparel_ship_to == self.ship_to)]
			if rows:
				cap = sum(maths.max_ship_qty(i.qty, i.apparel_qty_tolerance_pct or 0) for i in rows)
				avail = min(avail, cap - others.get(key, 0))
			if avail > 0:
				out[key] = int(avail)
		return out

	# ---- submit ----------------------------------------------------------------------------------------------------
	def before_submit(self):
		if not self.cartons:
			frappe.throw(_("Add the cartons, or use Generate Cartons."))
		bad = [c for c in self.cartons if flt(c.gross_weight_kg) <= 0]
		if bad:
			frappe.throw(_("Enter the gross weight of every carton row (row {0}).").format(bad[0].idx))
		maxkg = flt(common.settings_value("carton_max_gross_kg", 0))
		for c in self.cartons:
			if flt(c.net_weight_kg) > flt(c.gross_weight_kg):
				frappe.throw(_("Carton row {0}: net weight is more than gross.").format(c.idx))
			if maxkg and flt(c.gross_weight_kg) > maxkg:
				frappe.msgprint(_("Carton row {0}: {1} kg gross is above the {2} kg limit.").format(c.idx, c.gross_weight_kg, maxkg), indicator="orange")
		line = frappe.db.get_value("Production Card", self.production_card, "line")
		problems, mode = needle_problems(line, self.packing_date)
		if problems:
			if mode == "Block":
				frappe.throw("<br>".join(problems), title=_("Needle detector"))
			frappe.msgprint("<br>".join(problems), indicator="orange", title=_("Needle detector"))

	def post_movements(self, check=False):
		rows = [{"stage": "PACKED", "colour": c, "size": s, "qty": q} for (c, s), q in self.pieces_by_key().items()]
		ledger.post(self.production_card, rows, "Packing List", self.name, self.packing_date, check=check)

	def on_submit(self):
		self.post_movements(check=True)
		self.make_sscc()
		self.make_fg_receipt()
		common.stamp_card(self.production_card, "PACK_FINISHED", self.packing_date, "Packing List", self.name, partial=True)
		self.check_pack_finished()

	def check_pack_finished(self):
		"""PACK_FINISHED is complete when every colour and size with A-grade pieces has them all packed (less samples)."""
		flow = Flow(self.production_card)
		lines = [l for l in flow.doc.lines if flow.t(l.colour, l.size, "FIN_A")]
		if lines and all(flow.t(l.colour, l.size, "PACKED") >= flow.t(l.colour, l.size, "FIN_A") - flow.t(l.colour, l.size, "SAMPLE_OUT") for l in lines):
			common.stamp_card(self.production_card, "PACK_FINISHED", self.packing_date, "Packing List", self.name)

	def make_sscc(self):
		"""One SSCC per carton number from a counter that never goes back, so a cancelled list keeps its numbers retired."""
		prefix = common.settings_value("gs1_company_prefix")
		if not prefix:
			return
		idx = 0
		for c in self.cartons:
			for n in range(cint(c.carton_from), cint(c.carton_to) + 1):
				serial = frappe.model.naming.getseries(f"SSCC-{prefix}-", 1)
				try:
					code = packing.sscc_number(prefix, serial)
				except ValueError as e:
					frappe.throw(str(e))
				idx += 1
				frappe.get_doc({"doctype": "Packing List SSCC", "parent": self.name, "parenttype": "Packing List", "parentfield": "sscc",
								"idx": idx, "carton_no": n, "sscc": code}).insert(ignore_permissions=True)

	def make_fg_receipt(self):
		"""Draft Material Receipt of the packed pieces into Finished Goods, so the Delivery Note has stock. The accountant
		submits it (set `auto_submit_stock_entries` to do it here)."""
		if not cint(common.settings_value("post_fg_receipt", 1)):
			return
		wh = common.settings_value("fg_warehouse")
		if not wh:
			frappe.msgprint(_("Set the Finished Goods warehouse in Apparel Settings to receive packed pieces into stock."), indicator="orange")
			return
		items = frappe.get_all("Sales Order Item", {"parent": self.sales_order}, ["name", "item_code", "rate", "apparel_cost_sheet"])
		by_name = {i.name: i for i in items}
		qty, rate = {}, {}
		for ct in self.contents:
			i = by_name.get(ct.sales_order_item)
			if not i:
				continue
			qty[i.item_code] = qty.get(i.item_code, 0) + cint(ct.pieces_total)
			cost = frappe.db.get_value("Cost Sheet", i.apparel_cost_sheet, "product_cost") if i.apparel_cost_sheet else None
			rate[i.item_code] = flt(cost) or flt(frappe.db.get_value("Item", i.item_code, "valuation_rate")) or flt(i.rate)
		if not qty:
			return
		company = frappe.db.get_value("Production Card", self.production_card, "company")
		try:
			se = frappe.new_doc("Stock Entry")
			se.stock_entry_type = se.purpose = "Material Receipt"
			se.company = company
			se.apparel_production_card, se.apparel_issue_kind = self.production_card, "Finished Goods Receipt"
			for code, q in qty.items():
				se.append("items", {"item_code": code, "qty": q, "t_warehouse": wh, "basic_rate": rate[code], "allow_zero_valuation_rate": 0 if rate[code] else 1})
			se.remarks = _("Packed on {0}. Rate from the Cost Sheet cost (or the order rate when none): check before submitting.").format(self.name)
			se.flags.ignore_permissions = True
			se.insert()
			if cint(common.settings_value("auto_submit_stock_entries", 0)):
				se.submit()
			self.db_set("fg_stock_entry", se.name)
		except Exception:
			frappe.log_error(title="Finished goods receipt failed", message=frappe.get_traceback())
			frappe.msgprint(_("The finished-goods receipt could not be drafted; see the error log. Packing itself is saved."), indicator="orange")

	# ---- cancel ----------------------------------------------------------------------------------------------------
	def before_cancel(self):
		if self.shipment:
			frappe.throw(_("{0} is on shipment {1}. Remove it from the shipment first.").format(self.name, self.shipment))
		inspections = frappe.get_all("Final Inspection Lot", {"packing_list": self.name}, pluck="parent")
		if inspections and frappe.db.exists("Final Inspection", {"name": ["in", inspections], "docstatus": 1, "result": ["in", ["Accepted", "Accepted with Concession"]]}):
			frappe.msgprint(_("An accepted final inspection covers this list; a new inspection is needed after repacking."), indicator="orange")
		dn = frappe.db.exists("Delivery Note Item", {"apparel_packing_list": self.name, "docstatus": 1})
		if dn:
			frappe.throw(_("A submitted Delivery Note uses this packing list."))

	def on_cancel(self):
		ledger.unpost("Packing List", self.name)
		common.unstamp_doc("Packing List", self.name)
		if self.fg_stock_entry:
			stock.cancel_entry(self.fg_stock_entry)
			self.db_set("fg_stock_entry", None)
		# SSCC numbers already drawn stay retired: the counter never goes back


def packed_by_key(card, exclude=None, states=(1,), ship_to=None):
	"""Pieces on other packing lists of the card by (colour, size). `states` are the docstatus values to count: (1,) is
	what the ledger already holds, (0,) the drafts, (0, 1) everything not cancelled."""
	cond = " and p.ship_to = %(ship_to)s" if ship_to else ""
	rows = frappe.db.sql(
		f"""select c.colour, c.size, sum(c.pieces_total) from `tabPacking List Content` c join `tabPacking List` p on p.name = c.parent
		where p.production_card = %(card)s and p.docstatus in %(states)s and p.name != %(exclude)s{cond} group by c.colour, c.size""",
		{"card": card, "states": tuple(states), "exclude": exclude or "", "ship_to": ship_to})
	return {(c, s): q or 0 for c, s, q in rows}
