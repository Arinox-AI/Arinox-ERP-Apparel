# Copyright (c) 2026, Arinox AI and contributors
"""Finishing Receipt: pieces that arrived in finishing from sewing or from a vendor process. Posts FIN_IN, which the
flow rules cap at what the previous route step released (a washed style cannot receive more than came back)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from arinox_apparel.production import ledger
from arinox_apparel.shipping import common


class FinishingReceipt(Document):
	def autoname(self):
		self.name = common.next_serial(common.card_root(self.production_card), "FIN")

	def validate(self):
		card = common.require_open_card(self.production_card)
		self.sales_contract, self.sales_order = card.sales_contract, card.sales_order
		if not self.rows:
			frappe.throw(_("Add the pieces received."))
		on_card = {(l.colour, l.size) for l in frappe.get_all("Production Card Line", {"parent": self.production_card}, ["colour", "size"])}
		total = 0
		for r in self.rows:
			r.qty = cint(r.qty)
			if r.qty <= 0:
				frappe.throw(_("Row {0}: enter a quantity above zero.").format(r.idx))
			if (r.colour, r.size) not in on_card:
				frappe.throw(_("Row {0}: {1} {2} is not on production card {3}.").format(r.idx, r.colour, r.size, self.production_card))
			total += r.qty
		self.total_qty = total
		if self.source == "Subcontract Return" and not self.supplier:
			frappe.throw(_("Name the vendor the pieces came from."))

	def on_submit(self):
		self.post_movements(check=True)

	def post_movements(self, check=False):
		rows = [{"stage": "FIN_IN", "colour": r.colour, "size": r.size, "qty": r.qty, "line": self.line, "supplier": self.supplier,
				 "shade_band": r.shade_band, "source_row": r.name} for r in self.rows]
		ledger.post(self.production_card, rows, "Finishing Receipt", self.name, self.receipt_date, check=check)

	def on_cancel(self):
		ledger.unpost("Finishing Receipt", self.name)
