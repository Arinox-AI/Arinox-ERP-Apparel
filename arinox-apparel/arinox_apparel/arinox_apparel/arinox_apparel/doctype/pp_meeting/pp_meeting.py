# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Pre-production meeting, held after the production card is issued. Planning, purchasing, cutting, sewing,
(washing) and QC attend, and every open buyer comment is turned into an action with an owner and a date.
Submitting the meeting issues the minutes; action rows stay editable so they can be closed later."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

from arinox_apparel.arinox_apparel.doctype.sample_approval.sample_approval import APPROVED, get_rules, scope_filters



def required_departments(meeting_type, is_washed=0):
	"""Departments that must attend, from Apparel Settings (one per line). Washing joins when the garment is washed."""
	field = "pilot_required_departments" if meeting_type == "Pilot Run" else "pp_required_departments"
	default = "Cutting\nSewing\nQC\nCAD" if meeting_type == "Pilot Run" else "Planning\nPurchasing\nCutting\nSewing\nQC"
	names = [d.strip() for d in (frappe.db.get_single_value("Apparel Settings", field) or default).splitlines() if d.strip()]
	if cint(is_washed) and meeting_type != "Pilot Run" and "Washing" not in names:
		names.append("Washing")
	return names


def open_buyer_comments(sales_order, style_item):
	"""Open comments on every sample of this style that applies to the order."""
	rows = []
	for s in frappe.get_all("Sample Approval", scope_filters(sales_order, style_item), ["name", "sample_type", "colour"]):
		for c in frappe.get_all(
			"Sample Approval Comment", {"parent": s.name, "parenttype": "Sample Approval", "status": "Open"},
			["name", "category", "comment", "relevant_to_cutting"],
		):
			c.update(sample_approval=s.name, sample_type=s.sample_type, colour=s.colour)
			rows.append(c)
	return rows


class PPMeeting(Document):
	def validate(self):
		self.fetch_links()
		self.default_from_allocation()
		self.stamp_actions()
		self.set_status()

	def fetch_links(self):
		so = frappe.db.get_value("Sales Order", self.sales_order, ["docstatus", "customer", "apparel_sales_contract"], as_dict=True)
		if not so or so.docstatus != 1:
			frappe.throw(_("Sales Order {0} must be submitted.").format(self.sales_order))
		self.customer, self.sales_contract = so.customer, so.apparel_sales_contract
		self.meeting_type = self.meeting_type or "PP Meeting"
		if frappe.db.get_value("Item", self.style_item, "variant_of"):
			frappe.throw(_("Pick the style (template item), not a variant."))
		from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import get_order_lines

		lines = [o for o in get_order_lines(self.sales_order).values() if o.style_item == self.style_item]
		if not lines:
			frappe.throw(_("Style {0} is not on Sales Order {1}.").format(self.style_item, self.sales_order))
		self.order_qty = sum(o.qty for o in lines)
		if not self.style_no:
			self.style_no = (frappe.db.get_value("Tech Pack", self.tech_pack, "style_no") if self.tech_pack else None) or self.style_item
		if self.pp_sample:
			pp = frappe.db.get_value("Sample Approval", self.pp_sample, ["sample_type", "style_item"], as_dict=True)
			if pp.sample_type != "PP" or pp.style_item != self.style_item:
				frappe.throw(_("{0} is not a PP sample of style {1}.").format(self.pp_sample, self.style_item))

	def default_from_allocation(self):
		if self.factory and self.line and self.pcd:
			return
		fa = frappe.db.get_value("Factory Allocation", {"sales_order": self.sales_order}, "name")
		if not fa:
			return
		row = frappe.db.get_value(
			"Factory Allocation Line", {"parent": fa, "style_item": self.style_item}, ["factory", "line", "pcd"], as_dict=True, order_by="pcd"
		)
		if row:
			self.factory = self.factory or row.factory
			self.line = self.line or row.line
			self.pcd = self.pcd or row.pcd

	def stamp_actions(self):
		for a in self.actions:
			if a.status == "Closed" and not a.closed_on:
				a.closed_on = nowdate()
			elif a.status == "Open":
				a.closed_on = None

	def set_status(self):
		if self.docstatus == 0:
			self.status = "Draft"
		else:
			self.status = "Open Actions" if any(a.status == "Open" for a in self.actions) else "Closed"

	# -- submit checks
	def before_submit(self):
		if not self.production_card_issued_on:
			frappe.throw(_("Enter the date the production card was issued. The meeting is held after it."))
		if getdate(self.meeting_date) < getdate(self.production_card_issued_on):
			frappe.throw(_("The meeting date is before the production card was issued."))
		self.check_attendance()
		self.check_actions_complete()
		if self.meeting_type == "PP Meeting":  # the pilot run follows the PP meeting; it has no buyer comments of its own
			self.check_pp_sample()
			self.check_comments_listed()

	def check_pp_sample(self):
		"""A PP sample is needed when the rules require one (or one was named). Buyers that waive PP skip it."""
		rule = get_rules(self.customer, self.sales_order, self.style_item).get("PP")
		if not self.pp_sample and (not rule or rule.gate != "Required"):
			return
		status = frappe.db.get_value("Sample Approval", self.pp_sample, "status") if self.pp_sample else None
		if status not in APPROVED:
			frappe.throw(_("The PP sample must be buyer approved before the PP meeting is issued."))

	def check_attendance(self):
		need = set(required_departments(self.meeting_type, self.is_washed))
		present = {(p.department or "").strip() for p in self.participants if cint(p.attended)}
		if need - present:
			frappe.throw(_("These departments must attend: {0}").format(", ".join(sorted(need - present))))

	def check_comments_listed(self):
		listed = {a.comment_ref for a in self.actions if a.comment_ref}
		missing = [c for c in open_buyer_comments(self.sales_order, self.style_item) if c.name not in listed]
		if missing:
			frappe.throw(
				_("Every buyer comment must be reviewed. {0} open comment(s) are not in the action list, for example: {1}. "
				  "Use Get Buyer Comments.").format(len(missing), missing[0].comment[:80])
			)

	def check_actions_complete(self):
		for a in self.actions:
			if not (a.action_taken and a.action_owner and a.target_date):
				frappe.throw(_("Action row {0} needs the action, an owner and a target date.").format(a.idx))

	# -- after submit
	def before_update_after_submit(self):
		self.stamp_actions()
		self.set_status()
		self.check_actions_complete()

	def on_submit(self):
		self.sync_comments()

	def on_update_after_submit(self):
		self.sync_comments()

	def on_cancel(self):
		for a in self.actions:
			if a.comment_ref:
				frappe.db.set_value("Sample Approval Comment", a.comment_ref, {"status": "Open", "closed_in": None})

	def sync_comments(self):
		for a in self.actions:
			if a.comment_ref and frappe.db.exists("Sample Approval Comment", a.comment_ref):
				closed = a.status == "Closed"
				frappe.db.set_value(
					"Sample Approval Comment", a.comment_ref,
					{"status": "Closed" if closed else "Open", "closed_in": self.name if closed else None},
				)

	# -- tools used from the form
	@frappe.whitelist()
	def load_from_requisitions(self):
		"""Fabric required and received, shade count and trim readiness from the requisitions of this order and style."""
		from arinox_apparel.materials.status import trim_readiness

		self.check_permission("write")
		rows = frappe.db.sql(
			"""select c.colour, sum(c.net_qty) net, sum(c.accepted_qty) accepted, group_concat(distinct i.shade_bands_found) shades
			from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent
			left join `tabFabric Inspection` i on i.fabric_requisition = p.name and i.docstatus = 1 and i.colour = c.colour
			where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s group by c.colour""",
			(self.sales_order, self.style_item), as_dict=True)
		have = {(r.colour or "").strip().upper(): r for r in self.colours}
		for r in rows:
			row = have.get((r.colour or "").strip().upper())
			if not row:
				row = self.append("colours", {"colour": r.colour})
			row.fabric_required_m = flt(r.net, 2)
			row.fabric_received_m = flt(r.accepted, 2)
			bands = {b.strip() for b in (r.shades or "").replace(";", ",").split(",") if b.strip()}
			row.no_of_shades = len(bands) or row.no_of_shades
		for field, need in (("sewing_trims", "Sewing"), ("packing_trims", "Packing")):
			status = trim_readiness(self.sales_order, self.style_item, need)
			if status:
				self.set(field, status)
		return len(rows)

	@frappe.whitelist()
	def get_buyer_comments(self):
		listed = {a.comment_ref for a in self.actions if a.comment_ref}
		added = 0
		for c in open_buyer_comments(self.sales_order, self.style_item):
			if c.name in listed:
				continue
			label = c.sample_type + (f" / {c.colour}" if c.colour else "")
			self.append("actions", {
				"sample_approval": c.sample_approval, "comment_ref": c.name, "source": "Buyer Comment",
				"category": c.category, "comment": f"[{label}] {c.comment}", "relevant_to_cutting": c.relevant_to_cutting,
			})
			added += 1
		return added

	@frappe.whitelist()
	def add_standard_participants(self):
		have = {p.department for p in self.participants}
		for d in required_departments(self.meeting_type, self.is_washed):
			if d not in have:
				self.append("participants", {"department": d, "attended": 0})
		return len(self.participants)


def cutting_actions_open(sales_order, style_item):
	"""(PP meetings held, open cutting-related actions). Actions of pilot runs count too; only a PP Meeting
	counts as the meeting being held."""
	open_rows, all_meetings = [], frappe.get_all(
		"PP Meeting", {"sales_order": sales_order, "style_item": style_item, "docstatus": 1}, ["name", "meeting_type"]
	)
	meetings = [m for m in all_meetings if m.meeting_type == "PP Meeting"]
	for m in all_meetings:
		open_rows += frappe.get_all(
			"PP Meeting Action", {"parent": m.name, "relevant_to_cutting": 1, "status": "Open"}, ["comment"]
		)
	return meetings, open_rows
