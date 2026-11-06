# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""One approval item: a sample type for a style (and colour, and material) with every submission round,
the buyer's decision and comments. Status follows the last round. The bulk gate reads these records."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

APPROVED = ("Approved", "Approved with Comments")
DECIDED_NEEDS_COMMENT = ("Approved with Comments", "Rejected", "Resubmit")
GATE_OK = ("Approved", "Approved with Comments", "Not Required")
MANAGER_ROLES = ("Apparel Merchandising Manager", "System Manager")

# Used until Apparel Settings has its own rule rows. Same values as the seeded table.
# type: (gate, per_colour, due_basis, days_offset)
DEFAULT_RULES = {
	"Proto": ("No", 0, "PCD", 90),
	"Fit": ("Required", 0, "PCD", 45),
	"Size Set": ("If Raised", 0, "PCD", 30),
	"Lab Dip": ("Required", 1, "PCD", 60),
	"Strike Off": ("If Raised", 1, "PCD", 60),
	"Desk Loom": ("If Raised", 1, "PCD", 60),
	"Bulk Fabric": ("Required", 1, "PCD", 25),
	"Bulk Trim": ("Required", 0, "PCD", 25),
	"PP": ("Required", 0, "PCD", 14),
	"Garment Test (GPT)": ("If Raised", 0, "PCD", 14),
	"TOP": ("No", 1, "Ex-Factory", 10),
	"Salesman": ("No", 0, "PCD", 30),
	"Photo Sample": ("No", 0, "PCD", 30),
	"Customer Sample": ("No", 0, "After Fit Approval", 10),
	"Fabric Test (FPT)": ("If Raised", 1, "PCD", 21),
}


def _rule(gate="No", per_colour=0, due_basis="PCD", days_before=0, qty=0, sample_size=None, split_po_exempt=0, chargeback_amount=0):
	return frappe._dict(
		gate=gate or "No", per_colour=cint(per_colour), due_basis=due_basis or "PCD", days_before=cint(days_before),
		qty=cint(qty), sample_size=sample_size, split_po_exempt=cint(split_po_exempt), chargeback_amount=flt(chargeback_amount),
	)


def get_rules(customer=None, sales_order=None, style_item=None):
	"""sample type -> rule. Defaults, then Apparel Settings rows, then Sample Requirement overrides.
	Overrides are scoped to a customer, an order and/or a style; the most specific one wins field by field.
	A blank field in an override keeps the value below it."""
	rules = {t: _rule(*d) for t, d in DEFAULT_RULES.items()}
	for r in frappe.get_single("Apparel Settings").get("sample_rules") or []:
		rules[r.sample_type] = _rule(
			r.gate, r.per_colour, r.due_basis, r.days_before, r.qty, r.sample_size, r.split_po_exempt, r.chargeback_amount
		)
	if sales_order and not customer:
		customer = frappe.db.get_value("Sales Order", sales_order, "customer")
	scored = []
	for q in frappe.get_all("Sample Requirement", {"enabled": 1}, ["*"]):
		score = 0
		for field, value, weight in (("sales_order", sales_order, 4), ("style_item", style_item, 2), ("customer", customer, 1)):
			if q.get(field):
				if q.get(field) != value:
					score = None
					break
				score += weight
		if score:
			scored.append((score, q))
	for _score, q in sorted(scored, key=lambda x: x[0]):
		rule = rules.setdefault(q.sample_type, _rule())
		if q.gate:
			rule.gate = q.gate
		if q.per_colour:
			rule.per_colour = 1 if q.per_colour == "Yes" else 0
		if q.due_basis:  # basis and offset travel together
			rule.due_basis, rule.days_before = q.due_basis, cint(q.days_before)
		if cint(q.qty):
			rule.qty = cint(q.qty)
		if q.sample_size:
			rule.sample_size = q.sample_size
		if cint(q.split_po_exempt):
			rule.split_po_exempt = 1
		if flt(q.chargeback_amount):
			rule.chargeback_amount = flt(q.chargeback_amount)
	return rules


def is_split_po(sales_order):
	"""An order that ships to more than one destination."""
	dests = {
		(d or "").strip().upper()
		for d in frappe.get_all("Sales Order Item", {"parent": sales_order}, pluck="apparel_ship_to")
		if (d or "").strip()
	}
	return len(dests) > 1


def effective_gate(rule, sales_order):
	"""The gate after the split-PO exemption."""
	if rule.gate != "No" and rule.split_po_exempt and sales_order and is_split_po(sales_order):
		return "No"
	return rule.gate


def norm(colour):
	return (colour or "").strip().upper()


def get_style_dates(sales_order, style_item, colour=None):
	"""(PCD, ex-factory, in-warehouse) for a style x colour. PCD from the Factory Allocation, then the contract
	line; ex-factory and in-warehouse from the Sales Order lines."""
	pcd = ex_factory = in_warehouse = None
	if not sales_order:
		return pcd, ex_factory, in_warehouse
	fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
	if fa:
		for r in frappe.get_all(
			"Factory Allocation Line", {"parent": fa, "style_item": style_item}, ["colour", "pcd"], order_by="pcd"
		):
			if r.pcd and (not colour or norm(r.colour) == norm(colour)):
				pcd = r.pcd
				break
	contract = frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract")
	if not pcd and contract:
		for r in frappe.get_all(
			"Sales Contract Item", {"parent": contract, "style_item": style_item}, ["colour", "pcd"], order_by="pcd"
		):
			if r.pcd and (not colour or norm(r.colour) == norm(colour)):
				pcd = r.pcd
				break
	for it in frappe.get_all(
		"Sales Order Item", {"parent": sales_order},
		["item_code", "apparel_colour", "delivery_date", "apparel_in_warehouse_date"], order_by="delivery_date",
	):
		if frappe.db.get_value("Item", it.item_code, "variant_of") == style_item or it.item_code == style_item:
			if colour and norm(it.apparel_colour) != norm(colour):
				continue
			ex_factory = ex_factory or it.delivery_date
			in_warehouse = in_warehouse or it.apparel_in_warehouse_date
			if ex_factory and in_warehouse:
				break
	return pcd, ex_factory, in_warehouse


def fit_approved_on(sales_order, style_item):
	"""Latest approval date of the Fit samples of this style that apply to the order."""
	rows = frappe.get_all(
		"Sample Approval", {**scope_filters(sales_order, style_item), "sample_type": "Fit", "status": ["in", list(APPROVED)]},
		pluck="approved_on",
	)
	rows = [r for r in rows if r]
	return max(rows) if rows else None


class SampleApproval(Document):
	def rule(self):
		return get_rules(self.customer, self.sales_order, self.style_item).get(self.sample_type) or _rule()

	def validate(self):
		self.fetch_links()
		self.validate_scope()
		self.validate_waiver()
		self.number_rounds()
		self.validate_rounds()
		self.validate_process_rules()
		self.compute_measurements()
		self.compute_shrinkage()
		self.set_status()
		self.apply_rule_defaults()
		self.set_due_date()
		self.set_chargeback()

	# -- links and scope
	def fetch_links(self):
		if self.sales_order:
			so = frappe.db.get_value("Sales Order", self.sales_order, ["customer", "apparel_sales_contract", "docstatus"], as_dict=True)
			if not so:
				frappe.throw(_("Sales Order {0} does not exist.").format(self.sales_order))
			self.customer = so.customer
			self.sales_contract = so.apparel_sales_contract
		if not self.customer and self.tech_pack:
			self.customer = frappe.db.get_value("Tech Pack", self.tech_pack, "customer")
		if not self.style_no:
			self.style_no = frappe.db.get_value("Tech Pack", self.tech_pack, "style_no") if self.tech_pack else self.style_item
		if self.style_item and frappe.db.get_value("Item", self.style_item, "variant_of"):
			frappe.throw(_("Pick the style (template item), not a size or colour variant."))

	def validate_scope(self):
		rule = self.rule()
		if rule.per_colour and not (self.colour or "").strip():
			frappe.throw(_("{0} is approved per colour. Enter the colour.").format(self.sample_type))
		if self.sample_type in ("Bulk Fabric", "Bulk Trim") and not (self.material_item or self.material_description):
			frappe.throw(_("Enter the material (item or description) being approved."))

	def validate_waiver(self):
		changed = self.is_new() and self.waived or (not self.is_new() and self.has_value_changed("waived"))
		if self.waived:
			if changed and not set(frappe.get_roles()) & set(MANAGER_ROLES):
				frappe.throw(_("Only an Apparel Merchandising Manager can mark a sample as not required."))
			if not (self.waiver_reason or "").strip():
				frappe.throw(_("Enter the reason this approval is not required."))
			if changed:
				self.waived_by = frappe.session.user
		else:
			self.waived_by = None

	# -- rounds
	def number_rounds(self):
		for i, r in enumerate(self.rounds, 1):
			r.round_no = i

	def validate_rounds(self):
		today = getdate(nowdate())
		by_round = {}
		for c in self.comments:
			by_round.setdefault(cint(c.round_no), []).append(c)
		for r in self.rounds:
			if r.sent_on and r.decision_on and getdate(r.decision_on) < getdate(r.sent_on):
				frappe.throw(_("Round {0}: decision date is before the sent date.").format(r.round_no))
			if r.decision_on and getdate(r.decision_on) > today:
				frappe.throw(_("Round {0}: decision date cannot be in the future.").format(r.round_no))
			if r.decision != "Pending" and not r.decision_on:
				frappe.throw(_("Round {0}: enter the decision date.").format(r.round_no))
			if r.decision in DECIDED_NEEDS_COMMENT and not by_round.get(cint(r.round_no)):
				frappe.throw(_("Round {0} is '{1}': add the buyer's comment for that round.").format(r.round_no, r.decision))

	def last_round(self):
		return self.rounds[-1] if self.rounds else None

	def validate_process_rules(self):
		last = self.last_round()
		if not last or last.decision not in APPROVED or self.waived:
			return
		if self.sample_type in ("Bulk Fabric", "Bulk Trim") and cint(self.is_washed) and not cint(last.tested_after_wash):
			frappe.throw(_("This material is washed. The approval must come from a submission tested after wash."))
		if self.sample_type == "PP" and not cint(self.in_bulk_fabric):
			frappe.throw(_("A PP sample can only be approved when it is made in bulk fabric."))
		if self.sample_type in ("Garment Test (GPT)", "Fabric Test (FPT)"):
			failed = [t.test_property for t in self.tests if t.result == "Fail"]
			if failed:
				frappe.throw(_("The lab test cannot be approved while these tests fail: {0}").format(", ".join(failed)))
		off = [m.point_of_measure for m in self.measurements if m.actual not in (None, "") and not cint(m.in_tolerance)]
		if off:
			frappe.msgprint(_("Approved with measurements out of tolerance: {0}").format(", ".join(off)), indicator="orange")

	def compute_measurements(self):
		"""Up to five sample readings per point; in tolerance only when every reading is."""
		for m in self.measurements:
			readings = [flt(v) for v in (m.actual, m.reading_2, m.reading_3, m.reading_4, m.reading_5) if v not in (None, "")]
			if not readings or m.spec is None:
				m.deviation, m.in_tolerance = 0, 0
				continue
			devs = [round(r - flt(m.spec), 3) for r in readings]
			m.deviation = max(devs, key=abs)
			lo, hi = -abs(flt(m.tol_minus)), abs(flt(m.tol_plus))
			m.in_tolerance = 1 if all(lo <= d <= hi for d in devs) else 0

	def compute_shrinkage(self):
		limit = flt(frappe.db.get_single_value("Apparel Settings", "max_shrinkage_pct"))
		over = []
		for r in self.shrinkage:
			for d in ("warp", "weft", "bias"):
				before, after = flt(r.get(f"before_{d}")), flt(r.get(f"after_{d}"))
				r.set(f"shrink_{d}_pct", round((after - before) / before * 100, 2) if before else 0)
			if limit and any(abs(flt(r.get(f"shrink_{d}_pct"))) > limit for d in ("warp", "weft")):
				over.append(r.roll_no or r.idx)
		if over:
			frappe.msgprint(_("Shrinkage above {0}% on: {1}").format(limit, ", ".join(map(str, over))), indicator="orange")

	def set_status(self):
		last = self.last_round()
		if self.waived:
			self.status = "Not Required"
		elif not last:
			self.status = "Open"
		elif last.decision == "Pending":
			self.status = "Submitted" if last.sent_on else "Open"
		else:
			self.status = last.decision
		sent = [r.sent_on for r in self.rounds if r.sent_on]
		self.submitted_on = max(sent) if sent else None
		self.approved_on = last.decision_on if last and last.decision in APPROVED and not self.waived else None

	def apply_rule_defaults(self):
		rule = self.rule()
		self.chargeback_amount = rule.chargeback_amount or 0
		if not self.sample_qty and rule.qty:
			self.sample_qty = rule.qty
		if not self.sample_size and rule.sample_size:
			self.sample_size = rule.sample_size

	def basis_date(self, rule):
		pcd, ex_factory, in_warehouse = get_style_dates(self.sales_order, self.style_item, self.colour)
		self.pcd = self.pcd or pcd
		self.ex_factory_date = self.ex_factory_date or ex_factory
		self.in_warehouse_date = self.in_warehouse_date or in_warehouse
		if rule.due_basis == "Ex-Factory":
			return self.ex_factory_date, -1
		if rule.due_basis == "In-Warehouse":
			return self.in_warehouse_date, -1
		if rule.due_basis == "After Fit Approval":
			return fit_approved_on(self.sales_order, self.style_item), 1
		return self.pcd, -1

	def set_due_date(self):
		if self.due_date:
			return
		rule = self.rule()
		if not rule.days_before and rule.due_basis != "After Fit Approval":
			return
		basis, direction = self.basis_date(rule)
		if basis:
			self.due_date = add_days(basis, direction * rule.days_before)

	def set_chargeback(self):
		"""Exposure = the rule's chargeback when the sample went out late, or is overdue and still not sent."""
		self.late_chargeback = 0
		if not flt(self.chargeback_amount) or not self.due_date or self.waived:
			return
		due = getdate(self.due_date)
		sent = [getdate(r.sent_on) for r in self.rounds if r.sent_on]
		if (sent and min(sent) > due) or (not sent and getdate(nowdate()) > due):
			self.late_chargeback = self.chargeback_amount

	def on_update(self):
		"""An approved Fit starts the clock on samples due 'after fit approval'."""
		if self.sample_type != "Fit" or self.status not in APPROVED:
			return
		for s in frappe.get_all(
			"Sample Approval", {**scope_filters(self.sales_order, self.style_item), "due_date": ["is", "not set"], "name": ["!=", self.name]},
			["name", "sample_type", "customer"],
		):
			rule = get_rules(s.customer, self.sales_order, self.style_item).get(s.sample_type)
			if rule and rule.due_basis == "After Fit Approval" and self.approved_on:
				frappe.db.set_value("Sample Approval", s.name, "due_date", add_days(self.approved_on, rule.days_before))

	# -- tools used from the form
	@frappe.whitelist()
	def load_spec_from_tech_pack(self):
		"""Fill the measurement table with the tech pack spec for the sample size."""
		if not self.tech_pack:
			frappe.throw(_("Select the Tech Pack first."))
		if not self.sample_size:
			frappe.throw(_("Enter the sample size first."))
		tp = frappe.get_doc("Tech Pack", self.tech_pack)
		self.set("measurements", [])
		col = self.sample_size.strip().lower()
		if col not in ("xxs", "xs", "s", "m", "l", "xl", "xxl"):
			frappe.throw(_("Sample size {0} is not a standard size on the Tech Pack.").format(self.sample_size))
		for m in tp.measurements:
			if flt(m.get(col)):
				self.append("measurements", {
					"pom_code": m.pom_code, "point_of_measure": m.point_of_measure, "size": self.sample_size.strip().upper(),
					"spec": m.get(col), "tol_plus": m.tolerance, "tol_minus": m.tolerance,
				})
		if not self.measurements:
			frappe.throw(_("The Tech Pack has no measurements for size {0}.").format(self.sample_size))
		return len(self.measurements)

	@frappe.whitelist()
	def load_standard_tests(self):
		"""Add the standard test list from Apparel Settings (one test per line)."""
		names = (frappe.db.get_single_value("Apparel Settings", "gpt_test_list") or "").splitlines()
		have = {t.test_property for t in self.tests}
		for name in (n.strip() for n in names):
			if name and name not in have:
				self.append("tests", {"test_property": name})
		return len(self.tests)


@frappe.whitelist()
def get_sample_rules(customer=None, sales_order=None, style_item=None):
	return {k: dict(v) for k, v in get_rules(customer, sales_order, style_item).items()}


def scope_filters(sales_order, style_item):
	"""Samples that apply to this order: this Sales Order's, or ones raised before any order existed."""
	return {"style_item": style_item, "sales_order": ["in", [sales_order, "", None]]}


@frappe.whitelist()
def get_sampling_milestones(sales_order):
	"""Sampling dates and status per style x colour, for the T&A / WIP sheet or the planning agent:
	for each sample type its due date, first sent date, last decision date and status, plus the round-by-round
	history of fit samples (1st fit, 2nd fit, ...) and the PP approval and TOP submission dates."""
	from arinox_apparel.arinox_apparel.doctype.factory_allocation.factory_allocation import get_order_lines

	out = []
	for o in get_order_lines(sales_order).values():
		style, key = o.style_item, (o.style_item, norm(o.colour))
		if any(r["style_item"] == style and norm(r["colour"]) == key[1] for r in out):
			continue
		row = {"style_item": style, "colour": o.colour, "samples": {}}
		for smp in frappe.get_all(
			"Sample Approval", scope_filters(sales_order, style),
			["name", "sample_type", "colour", "status", "due_date", "submitted_on", "approved_on", "late_chargeback"],
		):
			if smp.colour and norm(smp.colour) != key[1]:
				continue
			rounds = frappe.get_all(
				"Sample Approval Round", {"parent": smp.name}, ["round_no", "sent_on", "decision", "decision_on"], order_by="round_no"
			)
			row["samples"].setdefault(smp.sample_type, []).append({**smp, "rounds": rounds})
		out.append(row)
	return out
