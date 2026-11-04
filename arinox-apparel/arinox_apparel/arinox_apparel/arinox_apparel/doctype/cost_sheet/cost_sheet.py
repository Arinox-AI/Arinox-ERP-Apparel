# Copyright (c) 2026, Arinox AI and contributors
# For license information, please see license.txt
"""Garment cost build-up.

Materials -> cost heads in sequence -> computed FOB (grossed up for price-based charges) -> margin
at the quoted price. Margin below the floor needs a Costing Manager's approval; a price move after
approval resets it. All of this runs on the server, so an API write cannot skip it.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

COSTING_MANAGER = "Apparel Costing Manager"
PRICE_CALC = "Percent of Price"
MATERIAL_CALC = "From Materials"
PRODUCT_COST_CALC = "Percent of Product Cost"
SUBTOTAL_CALC = "Percent of Subtotal"
# Heads whose amount does not depend on another head. Product cost = materials + these.
DIRECT_CALCS = ("Per Piece", "Per SAM Minute", "Per Metre of Fabric", "Percent of Material")
FABRIC_TYPES = ("Fabric", "Lining", "Contrast Fabric")
MAX_OPTIONS = 4
SIGNOFF_STEPS = (
	"Fabric Cost Checked",
	"First Costing Done",
	"Second Round Checked",
	"Final Checked & Approved",
)
METRES_PER = {"meter": 1, "metre": 1, "mtr": 1, "m": 1, "yard": 0.9144, "yd": 0.9144, "yds": 0.9144,
			  "cm": 0.01, "inch": 0.0254, "in": 0.0254}


class CostSheet(Document):
	def validate(self):
		self.set_revision_no()
		if not self.company:
			from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import get_default_company

			self.company = get_default_company()
		self.ensure_signoff_rows()
		if not self.costing_parameter:
			self.costing_parameter = find_costing_parameter(
				self.customer, self.product_type, self.costing_date, self.currency
			)
		if not self.charges:
			self.set_charges_from_parameter()
		self.validate_materials()
		self.validate_charges()
		self.calculate()
		self.update_approval_status()

	def before_submit(self):
		self.check_cost_heads_complete()
		self.check_signoffs()
		if self.below_floor and self.approval_status != "Approved":
			if COSTING_MANAGER in frappe.get_roles():
				self.stamp_approval(_("Approved at submit by Costing Manager"))
			else:
				frappe.throw(
					_(
						"Margin {0}% is below the floor of {1}%. A Costing Manager must approve this Cost Sheet before it can be submitted."
					).format(flt(self.margin_pct, 2), flt(self.margin_floor_pct, 2)),
					title=_("Below Margin Floor"),
				)

	# ------------------------------------------------------------------ sign-off
	def ensure_signoff_rows(self):
		have = {r.step for r in self.signoffs}
		for step in SIGNOFF_STEPS:
			if step not in have:
				self.append("signoffs", {"step": step})
		order = {step: i for i, step in enumerate(SIGNOFF_STEPS)}
		self.signoffs.sort(key=lambda r: order.get(r.step, 99))
		for i, r in enumerate(self.signoffs, 1):
			r.idx = i

	def check_signoffs(self):
		if not frappe.db.get_single_value("Apparel Settings", "require_costing_signoff"):
			return
		missing = [r.step for r in self.signoffs if not r.signed_by]
		if missing:
			frappe.throw(
				_("Costing sign-off incomplete. Still to sign: {0}").format(", ".join(missing)), title=_("Sign-off Required")
			)

	# ------------------------------------------------------------------ setup
	def set_revision_no(self):
		if self.amended_from:
			prev = frappe.db.get_value("Cost Sheet", self.amended_from, "revision_no") or 1
			self.revision_no = prev + 1
		elif not self.revision_no:
			self.revision_no = 1

	@frappe.whitelist()
	def set_charges_from_parameter(self):
		"""Fill one charge row per enabled, non-material cost head, with rates from the parameter."""
		rates = {}
		if self.costing_parameter:
			for r in frappe.get_all(
				"Costing Parameter Rate",
				filters={"parent": self.costing_parameter, "parenttype": "Costing Parameter"},
				fields=["cost_head", "rate", "not_applicable"],
			):
				rates[r.cost_head] = r
		self.set("charges", [])
		for head in get_cost_heads():
			if head.calc_type == MATERIAL_CALC:
				continue
			r = rates.get(head.name)
			self.append(
				"charges",
				{
					"cost_head": head.name,
					"calc_type": head.calc_type,
					"sequence": head.sequence,
					"head_group": head.head_group,
					"rate": flt(r.rate) if r else 0,
					"not_applicable": r.not_applicable if r else 0,
					"source": "Parameter" if r else "Manual",
				},
			)

	# ------------------------------------------------------------------ validation
	def validate_materials(self):
		groups = defaultdict(list)
		for m in self.materials:
			if m.per_carton and not cint(self.pcs_per_carton):
				frappe.throw(_("Row {0}: set Pcs per Carton to cost a carton per piece.").format(m.idx))
			if flt(m.conversion_factor) < 0 or flt(m.exchange_rate) < 0:
				frappe.throw(_("Row {0}: conversion factor and exchange rate cannot be negative.").format(m.idx))
			if flt(m.wastage_pct) < 0 or flt(m.wastage_pct) >= 100:
				frappe.throw(_("Row {0}: wastage % must be between 0 and 100.").format(m.idx))
			if flt(m.wastage_pct) and not (m.wastage_reason or "").strip():
				frappe.throw(
					_("Row {0} ({1}): wastage {2}% needs a reason. Wastage is set per order, never by default.").format(
						m.idx, m.description, flt(m.wastage_pct)
					)
				)
			if m.option_group:
				groups[m.option_group.strip().lower()].append(m)
			else:
				m.is_selected = 1

		for rows in groups.values():
			label = rows[0].option_group
			if len(rows) > MAX_OPTIONS:
				frappe.throw(_("Option group {0} has {1} options. The maximum is {2}.").format(label, len(rows), MAX_OPTIONS))
			selected = [r for r in rows if r.is_selected]
			if len(rows) > 1 and len(selected) != 1:
				frappe.throw(
					_("Option group {0}: select exactly one option to price the garment (now {1}).").format(label, len(selected))
				)
			if len(rows) == 1:
				rows[0].is_selected = 1

	def validate_charges(self):
		seen = set()
		for c in self.charges:
			if c.cost_head in seen:
				frappe.throw(_("Cost head {0} appears twice.").format(c.cost_head))
			seen.add(c.cost_head)
			head = frappe.get_cached_value(
				"Cost Head", c.cost_head, ["calc_type", "sequence", "head_group"], as_dict=True
			)
			c.calc_type, c.sequence, c.head_group = head.calc_type, head.sequence, head.head_group
			if c.calc_type == MATERIAL_CALC:
				frappe.throw(
					_("{0} is calculated from the materials table and cannot be a charge row.").format(c.cost_head)
				)
			if c.not_applicable:
				c.rate = 0

	def check_cost_heads_complete(self):
		"""G1: a cost left out comes straight out of margin."""
		present = {c.cost_head: c for c in self.charges}
		missing, zero = [], []
		for head in get_cost_heads():
			if not head.is_mandatory:
				continue
			if head.calc_type == MATERIAL_CALC:
				if not any(_in_scope(m.material_type, head.material_scope) for m in self.materials):
					missing.append(head.name)
				continue
			row = present.get(head.name)
			if not row:
				missing.append(head.name)
			elif not flt(row.rate) and not row.not_applicable:
				zero.append(head.name)
		if missing or zero:
			msg = []
			if missing:
				msg.append(_("Missing: {0}").format(", ".join(missing)))
			if zero:
				msg.append(_("Zero rate without N/A: {0}").format(", ".join(zero)))
			frappe.throw("<br>".join(msg), title=_("Cost Sheet Incomplete"))

	# ------------------------------------------------------------------ maths
	def calculate(self):
		fabric = other = fabric_m = 0.0
		for m in self.materials:
			m.flags.unknown_length_uom = False
			cons = (1 / cint(self.pcs_per_carton)) if m.per_carton else flt(m.consumption)
			qty = cons * (1 + flt(m.wastage_pct) / 100)
			factor = flt(m.conversion_factor) or 1
			fx = (flt(m.exchange_rate) or 1) if m.price_currency and m.price_currency != self.currency else 1
			m.amount = flt(qty * factor * flt(m.rate) * fx, 6)
			if not m.is_selected:
				continue
			if m.material_type in FABRIC_TYPES:
				fabric += m.amount
				per_unit = to_metres(m.uom)
				fabric_m += qty * per_unit if per_unit else 0
				if per_unit is None:
					m.flags.unknown_length_uom = True
			else:
				other += m.amount
		self.fabric_cost, self.trim_cost = flt(fabric, 6), flt(other, 6)
		self.material_cost = flt(fabric + other, 6)
		self.fabric_metres = flt(fabric_m, 6)

		charges = sorted(self.charges, key=lambda r: (r.sequence or 0, r.idx))
		# pass 1: amounts that depend on nothing but the materials and the sheet header
		direct = 0.0
		for c in charges:
			rate = 0 if c.not_applicable else flt(c.rate)
			if c.calc_type == "Per Piece":
				c.amount = rate
			elif c.calc_type == "Per SAM Minute":
				c.amount = rate * flt(self.sam)
			elif c.calc_type == "Per Metre of Fabric":
				if any(m.flags.unknown_length_uom for m in self.materials):
					frappe.throw(_("A selected fabric row has a UOM that is not a length. Use Meter, Yard, cm or inch."))
				c.amount = rate * flt(self.fabric_metres)
			elif c.calc_type == "Percent of Material":
				c.amount = self.material_cost * rate / 100
			else:
				continue
			c.amount = flt(c.amount, 6)
			if c.head_group != "Profit":
				direct += c.amount
		self.product_cost = flt(self.material_cost + direct, 6)

		# pass 2, in sequence: percentage heads. Profit is kept out of cost.
		running = self.material_cost
		profit_amount = price_pct = profit_pct = 0.0
		price_rows = []
		for c in charges:
			rate = 0 if c.not_applicable else flt(c.rate)
			if c.calc_type in DIRECT_CALCS:
				pass
			elif c.calc_type == PRODUCT_COST_CALC:
				c.amount = flt(self.product_cost * rate / 100, 6)
			elif c.calc_type == SUBTOTAL_CALC:
				c.amount = flt(running * rate / 100, 6)
			elif c.calc_type == PRICE_CALC:
				price_rows.append(c)
				if c.head_group == "Profit":
					profit_pct += rate
				else:
					price_pct += rate
				continue
			if c.head_group == "Profit":
				profit_amount += c.amount
			else:
				running += c.amount

		self.subtotal = flt(running, 6)
		self.conversion_cost = flt(running - self.material_cost, 6)
		self.profit_amount = flt(profit_amount, 6)
		self.price_cost_pct, self.profit_pct = price_pct, profit_pct
		total_pct = price_pct + profit_pct
		if total_pct >= 100:
			frappe.throw(_("Price-based charges add up to {0}%. They must be below 100%.").format(total_pct))
		self.computed_price = flt((self.subtotal + self.profit_amount) / (1 - total_pct / 100), 6)
		if not flt(self.quoted_price):
			self.quoted_price = flt(self.computed_price, 2)
		for c in price_rows:
			c.amount = flt(flt(self.quoted_price) * (0 if c.not_applicable else flt(c.rate)) / 100, 6)

		m = self.margin_at_price(self.quoted_price)
		self.total_cost_at_quote = m["cost"]
		self.margin_amount = m["margin"]
		self.margin_pct = m["margin_pct"]
		self.markup_pct = m["markup_pct"]
		self.margin_floor_pct = self.get_margin_floor()
		self.below_floor = 1 if self.margin_pct < flt(self.margin_floor_pct) else 0
		self.order_value = flt(self.quoted_price) * (self.order_qty or 0)
		self.quoted_price_local = (
			flt(flt(self.quoted_price) * flt(self.local_exchange_rate), 2)
			if self.local_currency and flt(self.local_exchange_rate)
			else 0
		)

	def margin_at_price(self, price):
		"""Margin if the garment sells at `price`. Price-based charges other than profit scale with it."""
		price = flt(price)
		cost = flt(self.subtotal) + price * flt(self.price_cost_pct) / 100
		margin = price - cost
		return {
			"cost": flt(cost, 6),
			"margin": flt(margin, 6),
			"margin_pct": flt(margin / price * 100, 2) if price else 0,
			"markup_pct": flt(margin / cost * 100, 2) if cost else 0,
		}

	def get_margin_floor(self):
		floor = None
		if self.costing_parameter:
			floor = frappe.db.get_value("Costing Parameter", self.costing_parameter, "margin_floor_pct")
		if floor is None or floor == 0:
			floor = frappe.db.get_single_value("Apparel Settings", "default_margin_floor_pct")
		return flt(floor)

	# ------------------------------------------------------------------ approval
	def update_approval_status(self):
		if not self.below_floor:
			if self.approval_status in ("Pending", "Rejected"):
				self.approval_status = "Not Required"
			elif self.approval_status == "Not Required":
				pass
			return
		if self.approval_status == "Approved" and price_moved(self.approved_price, self.quoted_price):
			self.approval_status = "Pending"
			self.approved_by = self.approved_on = self.approved_price = None
			frappe.msgprint(
				_("Quoted price changed after approval. Margin approval reset to Pending."), indicator="orange", alert=True
			)
		elif self.approval_status == "Not Required":
			self.approval_status = "Pending"

	def stamp_approval(self, remarks=None):
		self.approval_status = "Approved"
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.approved_price = self.quoted_price
		if remarks and not self.approval_remarks:
			self.approval_remarks = remarks


def price_moved(old, new):
	tol = flt(frappe.db.get_single_value("Apparel Settings", "approval_tolerance_pct"))
	if not flt(old):
		return True
	return abs(flt(new) - flt(old)) / flt(old) * 100 > tol


def _in_scope(material_type, scope):
	if scope == "Fabric":
		return material_type in FABRIC_TYPES
	if scope == "Non-Fabric":
		return material_type not in FABRIC_TYPES
	return True


def to_metres(uom):
	"""Metres in one unit of `uom`. A fabric row with no UOM is taken to be in metres."""
	return METRES_PER.get((uom or "Meter").strip().lower())


def get_cost_heads():
	return frappe.get_all(
		"Cost Head",
		filters={"enabled": 1},
		fields=["name", "head_group", "calc_type", "material_scope", "sequence", "is_mandatory"],
		order_by="sequence asc",
	)


def find_costing_parameter(customer, product_type, on_date=None, currency=None):
	"""Most specific enabled parameter valid on the date: customer+type > customer > type > generic."""
	on_date = getdate(on_date or nowdate())
	filters = {"enabled": 1, "effective_from": ("<=", on_date)}
	if currency:
		filters["currency"] = currency
	rows = frappe.get_all(
		"Costing Parameter",
		filters=filters,
		fields=["name", "customer", "product_type", "effective_from", "effective_to"],
		order_by="effective_from desc",
	)
	best, best_score = None, -1
	for r in rows:
		if r.effective_to and getdate(r.effective_to) < on_date:
			continue
		if r.customer and r.customer != customer:
			continue
		if r.product_type and r.product_type != product_type:
			continue
		score = (2 if r.customer else 0) + (1 if r.product_type else 0)
		if score > best_score:
			best, best_score = r.name, score
	return best


# ---------------------------------------------------------------------- whitelisted API


@frappe.whitelist()
def sign_off(name, step, remarks=None):
	"""Record the current user against one costing sign-off step. Steps are signed in order."""
	doc = frappe.get_doc("Cost Sheet", name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Cost Sheet can be signed off."))
	if step not in SIGNOFF_STEPS:
		frappe.throw(_("Unknown sign-off step {0}.").format(step))
	doc.ensure_signoff_rows()
	rows = {r.step: r for r in doc.signoffs}
	if rows[step].signed_by:
		frappe.throw(_("{0} is already signed by {1}.").format(step, rows[step].signed_by))
	for earlier in SIGNOFF_STEPS[: SIGNOFF_STEPS.index(step)]:
		if not rows[earlier].signed_by:
			frappe.throw(_("Sign {0} first.").format(earlier))
	if step == SIGNOFF_STEPS[-1] and COSTING_MANAGER not in frappe.get_roles():
		frappe.throw(_("Final approval needs the {0} role.").format(COSTING_MANAGER), frappe.PermissionError)
	rows[step].signed_by = frappe.session.user
	rows[step].signed_on = now_datetime()
	if remarks:
		rows[step].remarks = remarks
	doc.save()
	return step


@frappe.whitelist()
def approve(name, remarks=None):
	frappe.only_for(COSTING_MANAGER)
	doc = frappe.get_doc("Cost Sheet", name)
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Cost Sheet can be approved."))
	if not doc.below_floor:
		frappe.throw(_("This Cost Sheet is above the margin floor; no approval is needed."))
	doc.approval_remarks = remarks
	doc.stamp_approval()
	doc.save()
	return doc.approval_status


@frappe.whitelist()
def reject(name, remarks=None):
	frappe.only_for(COSTING_MANAGER)
	doc = frappe.get_doc("Cost Sheet", name)
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft Cost Sheet can be rejected."))
	doc.approval_status = "Rejected"
	doc.approval_remarks = remarks
	doc.flags.keep_rejected = True
	doc.db_update()
	return doc.approval_status


@frappe.whitelist()
def get_margin_at_price(cost_sheet, price):
	doc = frappe.get_doc("Cost Sheet", cost_sheet)
	doc.check_permission("read")
	out = doc.margin_at_price(price)
	out["floor"] = doc.margin_floor_pct
	out["below_floor"] = out["margin_pct"] < flt(doc.margin_floor_pct)
	return out


@frappe.whitelist()
def get_costing_context(customer, product_type=None, style_no=None, tech_pack=None, currency=None):
	"""One call for the AI costing agent: the parameter that applies, its rates, the cost head
	library, and the most similar submitted costings with their outcomes."""
	frappe.has_permission("Cost Sheet", "read", throw=True)
	if tech_pack:
		tp = frappe.get_doc("Tech Pack", tech_pack)
		tp.check_permission("read")
		product_type = product_type or tp.product_type
		style_no = style_no or tp.style_no
	param_name = find_costing_parameter(customer, product_type, nowdate(), currency)
	param = frappe.get_doc("Costing Parameter", param_name).as_dict() if param_name else None

	prev = frappe.get_all(
		"Cost Sheet",
		filters={"docstatus": 1, "customer": customer, **({"product_type": product_type} if product_type else {})},
		fields=[
			"name", "style_no", "style_name", "costing_date", "currency", "material_cost", "subtotal",
			"quoted_price", "margin_pct", "order_qty", "revision_no",
		],
		order_by="costing_date desc",
		limit=20,
	)
	for p in prev:
		p.agreed_price = frappe.db.get_value(
			"Price Negotiation Style", {"cost_sheet": p.name, "style_status": "Agreed"}, "agreed_price"
		)
		p.same_style = bool(style_no and p.style_no == style_no)
	prev.sort(key=lambda p: not p.same_style)

	return {
		"costing_parameter": param,
		"margin_floor_pct": (param or {}).get("margin_floor_pct")
		or frappe.db.get_single_value("Apparel Settings", "default_margin_floor_pct"),
		"cost_heads": get_cost_heads(),
		"previous_costings": prev,
	}


@frappe.whitelist()
def get_previous_costing(cost_sheet):
	"""Materials and charges of an earlier Cost Sheet, for copying into a new one."""
	doc = frappe.get_doc("Cost Sheet", cost_sheet)
	doc.check_permission("read")
	skip = {"name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "owner", "modified_by", "docstatus"}
	return {
		"materials": [{k: v for k, v in m.as_dict().items() if k not in skip} for m in doc.materials],
		"charges": [
			{**{k: v for k, v in c.as_dict().items() if k not in skip}, "source": "Previous Costing"} for c in doc.charges
		],
		"sam": doc.sam,
	}


@frappe.whitelist()
def make_price_negotiation(source_name):
	"""Add this costing to the customer's open negotiation for the inquiry, or start one."""
	cs = frappe.get_doc("Cost Sheet", source_name)
	if cs.docstatus != 1:
		frappe.throw(_("Submit the Cost Sheet before negotiating on it."))
	filters = {"customer": cs.customer, "status": ("in", ["Open", "Partly Agreed", "On Hold"])}
	filters["opportunity"] = cs.opportunity or ("is", "not set")
	name = frappe.db.get_value("Price Negotiation", filters, "name", order_by="creation desc")
	pn = frappe.get_doc("Price Negotiation", name) if name else frappe.new_doc("Price Negotiation")
	if not name:
		pn.update({"customer": cs.customer, "opportunity": cs.opportunity, "currency": cs.currency})
	if pn.currency != cs.currency:
		frappe.throw(_("Negotiation {0} is in {1}; this Cost Sheet is in {2}.").format(pn.name, pn.currency, cs.currency))
	if not any(s.cost_sheet == cs.name for s in pn.styles):
		pn.append("styles", {"cost_sheet": cs.name, "qty": cs.order_qty})
		pn.append(
			"rounds",
			{"cost_sheet": cs.name, "direction": "Our Offer", "price": cs.quoted_price, "qty": cs.order_qty,
			 "remarks": _("Opening offer from costing rev {0}").format(cs.revision_no)},
		)
	pn.save()
	return pn.name


@frappe.whitelist()
def make_quotation(source_name):
	from arinox_apparel.arinox_apparel.doctype.price_negotiation.price_negotiation import build_quotation

	cs = frappe.get_doc("Cost Sheet", source_name)
	if cs.docstatus != 1:
		frappe.throw(_("Submit the Cost Sheet before quoting it."))
	return build_quotation(
		customer=cs.customer,
		currency=cs.currency,
		opportunity=cs.opportunity,
		lines=[{"cost_sheet": cs.name, "qty": cs.order_qty or 1, "rate": cs.quoted_price}],
	)
