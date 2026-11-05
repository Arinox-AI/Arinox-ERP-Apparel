"""Availability rules for the Production Movement ledger (plan section 3.2).

A document that posts quantities asks `Flow` whether each row fits. The rule for each stage is the output of the
stage before it on the card's route, less what was already posted. A Production Manager can override with a
reason; counting mistakes are corrected with a Production Adjustment, never by editing history."""

import frappe
from frappe import _
from frappe.utils import cint

from arinox_apparel.production.maths import planned_cut  # noqa: F401  (re-exported for callers)

CUT_PURPOSES = ("Bulk", "Pilot", "Sample")
REJECT_STAGES = ("CUT_REJECT", "SEW_REJECT", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_REJECT")


def settings_value(field, default=None):
	v = frappe.db.get_single_value("Apparel Settings", field)
	return default if v in (None, "") else v


def repair_accepted(card, colour, size):
	"""Factory-fault rejects the factory decided to repair and take back into finishing (plan 9.4).
	Filled in by the subcontracting slice; zero until that doctype exists."""
	if not frappe.db.exists("DocType", "Subcontract Return Row"):
		return 0
	return frappe.db.sql(
		"""select ifnull(sum(r.accepted_for_repair), 0) from `tabSubcontract Return Row` r
		join `tabSubcontract Return` p on p.name = r.parent
		where p.docstatus = 1 and r.production_card = %s and r.colour = %s and r.size = %s""",
		(card, colour, size),
	)[0][0] or 0


class Flow:
	"""Loads the ledger totals of one production card once, then answers `limit()` and absorbs `apply()` so several
	rows of one document are checked cumulatively."""

	def __init__(self, card):
		self.card = card
		self.doc = frappe.get_doc("Production Card", card)
		self.T = {}
		for colour, size, stage, purpose, process, qty in frappe.db.sql(
			"""select colour, size, stage, ifnull(purpose, ''), ifnull(subcontract_process, ''), sum(qty) from `tabProduction Movement`
			where production_card = %s group by colour, size, stage, purpose, subcontract_process""", card):
			self.T[(colour, size, stage, purpose, process)] = qty or 0
		self.lines = {(l.colour, l.size): l for l in self.doc.lines}
		self.route = sorted(self.doc.processes, key=lambda p: (0 if p.position == "Before Sewing" else 1, cint(p.sequence), p.idx))

	# ---- totals --------------------------------------------------------------------------------------------------
	def t(self, colour, size, stage, purpose=None, process=None):
		total = 0
		for (c, s, st, pu, pr), qty in self.T.items():
			if c == colour and s == size and st == stage and (purpose is None or pu == purpose) and (process is None or pr == process):
				total += qty
		return total

	def apply(self, row):
		key = (row["colour"], row["size"], row["stage"], row.get("purpose") or "Bulk", row.get("process") or "")
		self.T[key] = self.T.get(key, 0) + row["qty"]

	def good_cut(self, colour, size):
		return self.t(colour, size, "CUT") - self.t(colour, size, "CUT_REJECT")

	def route_for(self, colour, position):
		return [p for p in self.route if p.position == position and (not (p.colour or "").strip() or (p.colour or "").strip().upper() == colour.strip().upper())]

	def back_good(self, colour, size, process):
		return self.t(colour, size, "SC_BACK_GOOD", process=process)

	def after_output(self, colour, size):
		"""Pieces that have finished every garment process and sewing: what finishing may receive."""
		after = self.route_for(colour, "After Sewing")
		if after:
			return self.back_good(colour, size, after[-1].subcontract_process)
		return self.t(colour, size, "SEW_OUT")

	# ---- the rules -----------------------------------------------------------------------------------------------
	def limit(self, row):
		"""(max qty this row may add, 'block' or 'warn'), or (None, None) when no rule applies."""
		stage, colour, size = row["stage"], row["colour"], row["size"]
		purpose, process = row.get("purpose") or "Bulk", row.get("process") or ""
		t = self.t
		if stage == "CUT":
			line = self.lines.get((colour, size))
			if purpose == "Re-cut":
				lost = sum(t(colour, size, s) for s in REJECT_STAGES)
				return lost - t(colour, size, "CUT", purpose="Re-cut"), "block"
			if not line:
				frappe.throw(_("{0} {1} is not on production card {2}.").format(colour, size, self.card))
			cap = line.planned_cut_qty + cint(settings_value("cut_cap_extra_pcs", 3))
			done = sum(t(colour, size, "CUT", purpose=p) for p in CUT_PURPOSES)
			mode = settings_value("cut_cap_mode", "Block")
			if mode == "Off":
				return None, None
			return cap - done, ("warn" if mode == "Warn" else "block")
		if stage == "SEW_IN":
			avail = self.good_cut(colour, size)
			for p in self.route_for(colour, "Before Sewing"):
				avail = min(avail, self.back_good(colour, size, p.subcontract_process))
			return avail - t(colour, size, "SEW_IN"), "block"
		if stage in ("SEW_OUT", "SEW_REJECT"):
			return t(colour, size, "SEW_IN") - t(colour, size, "SEW_OUT") - t(colour, size, "SEW_REJECT"), "block"
		if stage == "SC_OUT":
			route = self.route_for(colour, "Before Sewing") + self.route_for(colour, "After Sewing")
			names = [p.subcontract_process for p in route]
			if process not in names:
				frappe.throw(_("{0} is not on the route of production card {1} for colour {2}.").format(process, self.card, colour))
			i = names.index(process)
			before = route[i].position == "Before Sewing"
			if i == 0 or route[i - 1].position != route[i].position:
				prior = self.good_cut(colour, size) if before else t(colour, size, "SEW_OUT")
			else:
				prior = self.back_good(colour, size, route[i - 1].subcontract_process)
			return prior - t(colour, size, "SC_OUT", process=process), "block"
		if stage == "FIN_IN":
			return self.after_output(colour, size) + repair_accepted(self.card, colour, size) - t(colour, size, "FIN_IN"), "block"
		if stage in ("FIN_A", "FIN_B", "FIN_REJECT"):
			return t(colour, size, "FIN_IN") - t(colour, size, "FIN_A") - t(colour, size, "FIN_B") - t(colour, size, "FIN_REJECT"), "block"
		if stage in ("SAMPLE_OUT", "PACKED"):
			return t(colour, size, "FIN_A") - t(colour, size, "SAMPLE_OUT") - t(colour, size, "PACKED"), "block"
		if stage == "SHIPPED":
			return t(colour, size, "PACKED") - t(colour, size, "SHIPPED"), "block"
		return None, None  # SC_BACK_* are limited per challan row by the Subcontract Return itself

	def check(self, rows, override=False):
		"""Raise if any row exceeds its limit. Rows of the same document accumulate."""
		problems = []
		for row in rows:
			if row["qty"] > 0 and not override:
				limit, severity = self.limit(row)
				if limit is not None and row["qty"] > limit + 1e-9:
					msg = _("{0}: {1} {2} {3} — {4} entered, {5} available.").format(
						row["stage"], row["colour"], row["size"], row.get("process") or "", _fmt(row["qty"]), _fmt(max(limit, 0)))
					if severity == "warn":
						frappe.msgprint(msg, indicator="orange", title=_("Production Flow"))
					else:
						problems.append(msg)
			self.apply(row)
		if problems:
			frappe.throw("<br>".join(problems), title=_("Production Flow"))


def _fmt(n):
	return int(n) if float(n) == int(n) else round(n, 2)
