"""Shared fixtures for the Phase D tests. Everything is prefixed _AT so it never touches real data."""

import frappe
from frappe.tests import IntegrationTestCase

from arinox_apparel.arinox_apparel.doctype.production_card.production_card import get_card_lines
from arinox_apparel.arinox_apparel.tests import utils as u

_counter = {"n": 0}


class ProductionBase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = u.setup_masters()
		_counter["n"] += 1
		cls.so, cls.style, cls.sc = u.make_order(f"_AT-P{_counter['n']}{frappe.generate_hash(length=3).upper()}")

	def tearDown(self):
		frappe.set_user("Administrator")

	def card_doc(self, **kw):
		ctx = get_card_lines(self.so.name, self.style)
		data = {
			"doctype": "Production Card", "company": self.company, "customer": u.CUSTOMER, "sales_order": self.so.name,
			"style_item": self.style, "lines": [{"colour": r["colour"], "size": r["size"]} for r in ctx["lines"]],
		}
		data.update(kw)
		return frappe.get_doc(data)

	def issue_card(self, **kw):
		card = self.card_doc(**kw)
		card.insert()
		card.submit()
		return card

	# documents that hang off a production card, in the order they must be removed (children of the flow first)
	DEPENDENTS = ["Line QC Report", "Daily Line Report", "Line Input", "Packing List", "Finishing Receipt", "Subcontract Return",
				  "Subcontract Challan", "Lay Report", "Recut Request", "Cut Plan", "Pilot Run", "Production Adjustment"]

	def clean(self):
		"""Remove this test order's production records only (the dev site also holds real demo data)."""
		cards = frappe.get_all("Production Card", {"sales_order": self.so.name}, pluck="name")
		if not cards:
			return
		for dt in self.DEPENDENTS:
			if not frappe.db.exists("DocType", dt):
				continue
			meta = frappe.get_meta(dt)
			if not meta.has_field("production_card"):
				continue
			for n in frappe.get_all(dt, {"production_card": ["in", cards]}, pluck="name"):
				d = frappe.get_doc(dt, n)
				d.flags.ignore_permissions = True
				if d.docstatus == 1:
					try:
						d.cancel()
					except Exception:
						frappe.db.set_value(dt, n, "docstatus", 2)
				frappe.delete_doc(dt, n, force=1, ignore_permissions=True)
		frappe.db.delete("Cut Bundle", {"production_card": ["in", cards]})
		frappe.db.delete("Production Movement", {"production_card": ["in", cards]})
		for n in cards:
			d = frappe.get_doc("Production Card", n)
			if d.docstatus == 1:
				d.flags.ignore_permissions = True
				try:
					d.cancel()
				except Exception:
					frappe.db.set_value("Production Card", n, "docstatus", 2)
			frappe.delete_doc("Production Card", n, force=1, ignore_permissions=True)
