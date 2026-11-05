# Copyright (c) 2026, Arinox AI and contributors
"""Phase E: subcontract round trip, finishing, packing, final inspection, shipment and delivery, invoicing, payment follow-up and
claims. Pure functions first (with the golden numbers from the company's documents), then the document rules, then one chain."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from arinox_apparel.arinox_apparel.report.receivables_follow_up.receivables_follow_up import bucket
from arinox_apparel.arinox_apparel.tests import utils as u
from arinox_apparel.arinox_apparel.tests.production_base import ProductionBase
from arinox_apparel.production import ledger, maths, packing
from arinox_apparel.shipping import common, followup


# ---- pure functions --------------------------------------------------------------------------------------------------
class TestPureMaths(IntegrationTestCase):
	def test_solid_cartons_and_tail(self):
		rows = packing.plan_cartons({("W", "XS"): 276, ("W", "S"): 456}, "Solid Colour Solid Size", 24)
		self.assertEqual([(r["carton_from"], r["carton_to"], r["tail"]) for r in rows], [(1, 11, 0), (12, 30, 0), (31, 31, 1)])
		self.assertEqual(rows[-1]["contents"], [("W", "XS", 12)])
		total = sum((r["carton_to"] - r["carton_from"] + 1) * r["pieces_per_carton"] for r in rows)
		self.assertEqual(total, 276 + 456)

	def test_ratio_packs_golden_16(self):
		# ratio 1:2:2:1 with quantities XS 276, S 456, M 438, L 231 -> 219 full packs (company sheet)
		self.assertEqual(maths.full_packs({"XS": 276, "S": 456, "M": 438, "L": 231}, {"XS": 1, "S": 2, "M": 2, "L": 1}), 219)
		rows = packing.plan_cartons({("W", "XS"): 276, ("W", "S"): 456, ("W", "M"): 438, ("W", "L"): 231}, "Solid Colour Assorted Size", 6, {"XS": 1, "S": 2, "M": 2, "L": 1})
		self.assertEqual(rows[0]["contents"], [("W", "XS", 1), ("W", "S", 2), ("W", "M", 2), ("W", "L", 1)])
		self.assertEqual(rows[0]["carton_to"], 219)
		self.assertEqual(sum((r["carton_to"] - r["carton_from"] + 1) * r["pieces_per_carton"] for r in rows), 276 + 456 + 438 + 231)

	def test_tail_rules(self):
		pool = {("A", "S"): 5, ("B", "M"): 7}
		mixed = packing.plan_cartons(pool, "Solid Colour Solid Size", 24, tail_rule="Mixed Colour and Size")
		self.assertEqual(len(mixed), 1)
		self.assertEqual(len(packing.plan_cartons(pool, "Solid Colour Solid Size", 24, tail_rule="Own Carton")), 2)
		self.assertEqual(len(packing.plan_cartons(pool, "Solid Colour Solid Size", 24, tail_rule="Mixed Size Only")), 2)

	def test_carton_ranges_golden_12(self):
		problems = packing.check_ranges([(1, 27), (28, 67), (68, 102), (103, 124), (124, 127)])
		self.assertEqual(len(problems), 1)
		self.assertIn("124", problems[0])
		self.assertEqual(packing.check_ranges([(1, 5), (6, 9)]), [])
		self.assertTrue(packing.check_ranges([(1, 5), (8, 9)]))  # a gap

	def test_sscc_has_a_valid_check_digit(self):
		code = packing.sscc_number("0360002914", 1)
		self.assertEqual(len(code), 18)
		self.assertTrue(maths.valid_gs1(code))
		with self.assertRaises(ValueError):
			packing.sscc_number("12", 1)

	def test_carton_draw_is_repeatable_and_includes_a_tail(self):
		pool = [("PL", n, 1 if n == 40 else 0) for n in range(1, 41)]
		a = packing.draw_cartons(pool, 7, 1234)
		self.assertEqual(a, packing.draw_cartons(pool, 7, 1234))
		self.assertEqual(len(set(a)), 7)
		self.assertTrue(any(c[2] for c in a))

	def test_over_short_golden_9(self):
		text, total = packing.size_summary({("W", "XS"): 276, ("W", "S"): 456, ("W", "M"): 438, ("W", "L"): 231, ("W", "XL"): 119},
										  {("W", "XS"): 270, ("W", "S"): 436, ("W", "M"): 421, ("W", "L"): 223, ("W", "XL"): 112})
		self.assertAlmostEqual(total, 3.97, 2)
		self.assertIn("+6.25 %", text)

	def test_expected_due_dates_golden(self):
		# ship-date basis: on board 2026-03-26 + 30 days -> 2026-04-25; overdue 131 days on 2026-09-03
		_d, src, due = followup.expected_due(followup.BL, 30, "2026-03-25", on_board="2026-03-26")
		self.assertEqual((str(due), src), ("2026-04-25", "B/L"))
		self.assertEqual((getdate("2026-09-03") - due).days, 131)
		# ROG: ETA 2026-04-08 + 5 days buffer + 15 days = 2026-04-28; delivery recorded 04-14 -> 04-29
		self.assertEqual(str(followup.expected_due(followup.ROG, 15, "2026-03-25", eta="2026-04-08", buffer_days=5)[2]), "2026-04-28")
		self.assertEqual(str(followup.expected_due(followup.ROG, 15, "2026-03-25", eta="2026-04-08", delivery="2026-04-14")[2]), "2026-04-29")
		self.assertEqual(str(followup.expected_due(followup.INVOICE, 30, "2026-03-25")[2]), "2026-04-24")

	def test_follow_up_status(self):
		s = followup.status_for
		self.assertEqual(s(0, 100, "2026-01-01", "2026-09-03")[0], "Paid")
		self.assertEqual(s(100, 100, "2026-09-10", "2026-09-03", soon_days=7)[0], "Due Soon")
		self.assertEqual(s(100, 100, "2026-12-10", "2026-09-03")[0], "Not Due")
		self.assertEqual(s(100, 100, "2026-04-25", "2026-09-03"), ("Overdue", 131))
		self.assertEqual(s(100, 100, "2026-04-25", "2026-09-03", promise="2026-09-10")[0], "Promised")
		self.assertEqual(s(100, 100, "2026-04-25", "2026-09-03", disputed=True)[0], "Disputed")
		self.assertEqual(s(60, 100, "2026-12-01", "2026-09-03")[0], "Partly Paid")
		# golden 10: 37,436.90 + 46.80 invoiced, 5,768.90 received -> 31,714.80 outstanding
		self.assertAlmostEqual(37436.9 + 46.8 - 5768.9, 31714.8, 2)

	def test_ageing_buckets(self):
		self.assertEqual([bucket(d) for d in (-3, 0, 1, 30, 31, 60, 61, 90, 91, 400)],
						 ["not_due", "not_due", "d1_30", "d1_30", "d31_60", "d31_60", "d61_90", "d61_90", "d90_plus", "d90_plus"])

	def test_claim_window_golden_16(self):
		from arinox_apparel.arinox_apparel.doctype.buyer_claim.buyer_claim import window_check

		self.assertTrue(window_check("Quality", "2026-01-30", "2026-03-31", 60, 30)[2])
		self.assertFalse(window_check("Quality", "2026-01-30", "2026-04-01", 60, 30)[2])
		self.assertFalse(window_check("Quantity Short", "2026-01-30", "2026-03-02", 60, 30)[2])
		self.assertTrue(window_check("Chargeback", "2026-01-30", "2027-01-01", 60, 30)[2])

	def test_penalty_golden_12(self):
		rate, qty, amount = maths.penalty(2000, 30, 1, 10, "All Damaged")
		self.assertEqual((rate, qty, amount), (1.5, 30, 300))
		self.assertEqual(maths.penalty(2000, 30, 1, 10, "Excess Only")[1], 10)
		self.assertEqual(maths.penalty(2000, 20, 1, 10)[1], 0)  # exactly at the limit: no penalty

	def test_serial_root_uses_the_contract(self):
		so, _style, sc = u.make_order("_AT-E-SER1")
		self.assertEqual(common.serial_root(so.name), sc.name)
		a, b = common.next_serial(sc.name, "XX"), common.next_serial(sc.name, "XX")
		self.assertEqual((a, b), (f"{sc.name}-XX-01", f"{sc.name}-XX-02"))


# ---- document rules -----------------------------------------------------------------------------------------------------
class ShipBase(ProductionBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		abbr = frappe.db.get_value("Company", cls.company, "abbr")
		cls._saved = {}
		fg = f"_AT Finished Goods - {abbr}"
		if not frappe.db.exists("Warehouse", fg):
			frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "_AT Finished Goods", "company": cls.company}).insert(ignore_permissions=True)
		cls._saved["fg_warehouse"] = frappe.db.get_single_value("Apparel Settings", "fg_warehouse")
		frappe.db.set_single_value("Apparel Settings", "fg_warehouse", fg)
		cls._saved["post_fg_receipt"] = frappe.db.get_single_value("Apparel Settings", "post_fg_receipt")
		frappe.db.set_single_value("Apparel Settings", "post_fg_receipt", 0)  # stock is not under test here
		cls._neg = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		cls.fg = fg
		cls.plan = make_test_plan()
		make_usd_debtors(cls.company)

	@classmethod
	def tearDownClass(cls):
		cls.purge_all()
		for field, val in cls._saved.items():
			frappe.db.set_single_value("Apparel Settings", field, val)
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", cls._neg)
		super().tearDownClass()

	@classmethod
	def purge(cls, doctype, filters):
		for n in frappe.get_all(doctype, filters, pluck="name"):
			d = frappe.get_doc(doctype, n)
			d.flags.ignore_permissions = True
			if d.docstatus == 1:
				try:
					d.cancel()
				except Exception:
					frappe.db.set_value(doctype, n, "docstatus", 2)
			frappe.delete_doc(doctype, n, force=1, ignore_permissions=True)

	@classmethod
	def purge_all(cls):
		cards = frappe.get_all("Production Card", {"sales_order": cls.so.name}, pluck="name")
		contract = cls.sc.name
		cls.purge("Buyer Claim", {"sales_contract": contract})
		cls.purge("Sales Invoice", {"apparel_sales_contract": contract})
		cls.purge("Delivery Note", {"apparel_sales_contract": contract})
		cls.purge("Shipment", {"apparel_contracts": ["like", f"%{contract}%"]})
		if cards:
			cls.purge("Final Inspection", {"production_card": ["in", cards]})
			frappe.db.delete("Stock Entry", {"apparel_production_card": ["in", cards]})

	def setUp(self):
		self.purge_all()
		self.clean()
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)
		self.card = self.issue_card()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 1)

	def route(self, *processes):
		self.clean()
		self.card = self.issue_card(processes=[{"subcontract_process": p, "position": pos, "sequence": (i + 1) * 10, "item_state": "Garments"} for i, (p, pos) in enumerate(processes)])
		return self.card

	def post(self, stage, colour="Navy", size="S", qty=100, **kw):
		ledger.post(self.card.name, [dict(stage=stage, colour=colour, size=size, qty=qty, **kw)], "Production Adjustment", f"_E-{stage}-{colour}{size}", check=False)

	def finish_all(self):
		"""Pieces sewn, finished and graded A for every colour and size on the card, as if the line had run."""
		for l in self.card.lines:
			for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A"):
				self.post(stage, l.colour, l.size, l.order_qty)

	def packing_doc(self, **kw):
		data = {"doctype": "Packing List", "production_card": self.card.name, "pcs_per_carton": 24, "pack_type": "Solid Colour Solid Size", "buyer_po": "PO-" + self.card.style_no if self.card.style_no else "PO"}
		data.update(kw)
		return frappe.get_doc(data)

	def make_packed(self, weights=True):
		pl = self.packing_doc()
		pl.insert()
		pl.generate_cartons()
		for c in pl.cartons:
			c.length_cm, c.width_cm, c.height_cm = 54, 33, 20
			if weights:
				c.net_weight_kg, c.gross_weight_kg = 4.5, 5.5
		pl.save()
		pl.submit()
		return pl

	def shipment(self, pl):
		sh = frappe.get_doc({"doctype": "Shipment", "pickup_from_type": "Company", "pickup_company": self.company, "delivery_to_type": "Customer", "delivery_customer": u.CUSTOMER,
							 "apparel_mode": "Sea LCL", "apparel_booking_no": "BK-" + frappe.generate_hash(length=5), "apparel_packing_lists": [{"packing_list": pl.name}]})
		sh.insert()
		return sh

	def ready(self):
		self.finish_all()
		pl = self.make_packed()
		sh = self.shipment(pl)
		return pl, sh

	def inspect(self, pl, result="Accepted", **kw):
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "inspection_type": "Final", "aql_plan": self.plan,
							 "lots": [{"packing_list": pl.name}], "result": result, **kw})
		fi.insert()
		fi.pick_cartons()
		fi.save()
		fi.submit()
		return fi


def make_usd_debtors(company):
	"""The test company keeps its receivables in another currency; ERPNext wants a debtors account in the invoice currency."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"_AT Debtors USD - {abbr}"
	if not frappe.db.exists("Account", name):
		parent = frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "parent_account")
		frappe.get_doc({"doctype": "Account", "account_name": "_AT Debtors USD", "company": company, "parent_account": parent, "account_type": "Receivable",
						"account_currency": "USD"}).insert(ignore_permissions=True)
	cust = frappe.get_doc("Customer", u.CUSTOMER)
	if not any(a.company == company and a.account == name for a in cust.accounts):
		cust.append("accounts", {"company": company, "account": name})
		cust.save(ignore_permissions=True)


def make_test_plan():
	name = "_AT Plan"
	if not frappe.db.exists("AQL Plan", name):
		frappe.get_doc({"doctype": "AQL Plan", "plan_name": name, "inspection_level": "General II", "aql_critical": "0", "aql_major": "2.5", "aql_minor": "4.0",
						"rows": [{"lot_from": 1, "lot_to": 99999999, "code_letter": "X", "sample_size": 80, "critical_ac": 0, "critical_re": 1, "major_ac": 3, "major_re": 4,
								  "minor_ac": 5, "minor_re": 6, "confirmed": 1}]}).insert(ignore_permissions=True)
	return name


class TestSubcontractAndFinishing(ShipBase):
	def seed_sewn(self, qty=100):
		for stage in ("CUT", "SEW_IN", "SEW_OUT"):
			self.post(stage, qty=qty)

	def challan(self, qty=100, **kw):
		d = frappe.get_doc({"doctype": "Subcontract Challan", "production_card": self.card.name, "supplier": self.supplier(), "subcontract_process": "Wash",
							"rows": [{"colour": "Navy", "size": "S", "qty": qty, "unit_value": 10}], **kw})
		d.insert()
		d.submit()
		return d

	def supplier(self):
		if not frappe.db.exists("Supplier", "_AT Wash House"):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": "_AT Wash House", "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert(ignore_permissions=True)
		return "_AT Wash House"

	def back(self, challan, good=90, vendor=4, factory=2, repair=0, **kw):
		d = frappe.get_doc({"doctype": "Subcontract Return", "challan": challan.name,
							"rows": [{"colour": "Navy", "size": "S", "good_qty": good, "reject_vendor_qty": vendor, "reject_factory_qty": factory, "accepted_for_repair": repair}], **kw})
		d.insert()
		d.submit()
		return d

	def test_names_carry_the_contract(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		self.assertTrue(ch.name.startswith(f"{self.sc.name}-SC-"), ch.name)
		self.assertEqual(ch.sales_contract, self.sc.name)

	def test_round_trip_posts_the_ledger_and_status(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		self.assertEqual(ledger.stage_total(self.card.name, "SC_OUT", "Navy", "S"), 100)
		self.assertIsNotNone(ch.expected_return_date)
		self.back(ch, good=60, vendor=0, factory=0)
		ch.reload()
		self.assertEqual((ch.status, ch.returned_qty), ("Partly Returned", 60))
		self.back(ch, good=30, vendor=4, factory=6)
		ch.reload()
		self.assertEqual((ch.status, ch.returned_qty), ("Returned", 100))
		self.assertEqual(ledger.stage_total(self.card.name, "SC_BACK_GOOD", "Navy", "S"), 90)
		self.assertEqual(ledger.stage_total(self.card.name, "SC_BACK_REJECT_VENDOR", "Navy", "S"), 4)

	def test_vendor_cannot_return_more_than_sent(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		with self.assertRaises(frappe.ValidationError):
			self.back(ch, good=100, vendor=1, factory=0)

	def test_cannot_send_more_than_sewn(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn(50)
		with self.assertRaises(frappe.ValidationError):
			self.challan(qty=60)

	def test_repair_only_for_factory_fault(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		with self.assertRaises(frappe.ValidationError):
			self.back(ch, good=90, vendor=4, factory=2, repair=3)

	def test_cannot_cancel_a_challan_with_returns(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		ret = self.back(ch)
		with self.assertRaises(frappe.ValidationError):
			ch.cancel()
		ret.cancel()
		ch.reload()
		self.assertEqual(ch.status, "Open")
		ch.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "SC_OUT"), 0)

	def test_short_close_needs_a_manager_and_a_reason(self):
		from arinox_apparel.arinox_apparel.doctype.subcontract_challan.subcontract_challan import short_close

		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		with self.assertRaises(frappe.ValidationError):
			short_close(ch.name, "  ")
		short_close(ch.name, "Vendor lost 10 pieces")
		ch.reload()
		self.assertEqual(ch.status, "Short Closed")
		with self.assertRaises(frappe.ValidationError):
			self.back(ch)

	def test_settlement_penalty_and_payable(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		self.back(ch, good=90, vendor=4, factory=2)
		st = frappe.get_doc({"doctype": "Subcontract Settlement", "challan": ch.name, "rate": 2, "invoiced_qty": 100})
		st.insert()
		# 4 of 100 (4 %) vendor-damaged is above the 1 % limit: all four are penalised at the 10 unit value; 92 pieces are payable
		self.assertEqual((st.short_qty, st.penalty_qty, st.penalty_amount, st.payable_qty), (4, 4, 40, 92))
		self.assertEqual((st.gross_amount, st.net_amount), (184, 144))
		self.assertTrue(st.variance_note)  # the vendor invoices 100, we owe 92
		st.submit()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Subcontract Settlement", "challan": ch.name, "rate": 2}).insert()  # one settlement per challan

	def test_finishing_takes_only_what_came_back_from_the_wash(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		self.back(ch, good=90, vendor=4, factory=2)
		fr = lambda q: frappe.get_doc({"doctype": "Finishing Receipt", "production_card": self.card.name, "source": "Subcontract Return", "supplier": self.supplier(),
									   "rows": [{"colour": "Navy", "size": "S", "qty": q}]})
		bad = fr(91)
		bad.insert()
		with self.assertRaises(frappe.ValidationError):
			bad.submit()
		ok = fr(90)
		ok.insert()
		ok.submit()
		self.assertTrue(ok.name.startswith(f"{self.sc.name}-FIN-"))
		self.assertEqual(ledger.stage_total(self.card.name, "FIN_IN", "Navy", "S"), 90)
		ok.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "FIN_IN"), 0)

	def test_ledger_rebuild_reproduces_the_new_documents(self):
		self.route(("Wash", "After Sewing"))
		self.seed_sewn()
		ch = self.challan()
		self.back(ch, good=90, vendor=4, factory=2)
		before = {s: ledger.stage_total(self.card.name, s) for s in ("SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY")}
		frappe.db.delete("Production Movement", {"production_card": self.card.name, "source_doctype": ["in", ["Subcontract Challan", "Subcontract Return"]]})
		ledger.rebuild_movements(self.card.name)
		after = {s: ledger.stage_total(self.card.name, s) for s in before}
		# the manually seeded adjustment rows are not documents, so only the document stages must match
		self.assertEqual(before, after)

	def test_needle_log_gate(self):
		from arinox_apparel.arinox_apparel.doctype.needle_detector_log.needle_detector_log import needle_problems

		line = "_AT Needle Line"
		if not frappe.db.exists("Workstation", line):
			frappe.get_doc({"doctype": "Workstation", "workstation_name": line, "production_capacity": 1}).insert(ignore_permissions=True)
		frappe.db.delete("Needle Detector Log", {"line": line})
		prev = frappe.db.get_single_value("Apparel Settings", "needle_check_required")
		frappe.db.set_single_value("Apparel Settings", "needle_check_required", "Block")
		try:
			problems, mode = needle_problems(line, nowdate())
			self.assertEqual(mode, "Block")
			self.assertEqual(len(problems), 1)
			frappe.get_doc({"doctype": "Needle Detector Log", "line": line, "result": "Pass"}).insert()
			self.assertEqual(needle_problems(line, nowdate())[0], [])
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": "Needle Detector Log", "line": line, "result": "Fail"}).insert()  # a failure needs the action
			frappe.get_doc({"doctype": "Needle Detector Log", "line": line, "result": "Fail", "action": "Re-scan since 10:00", "rescan_done": 0}).insert()
			self.assertEqual(len(needle_problems(line, nowdate())[0]), 1)  # no re-scan logged: still blocked
		finally:
			frappe.db.set_single_value("Apparel Settings", "needle_check_required", prev)
			frappe.db.delete("Needle Detector Log", {"line": line})


class TestPacking(ShipBase):
	def test_generate_submit_and_cancel(self):
		self.finish_all()
		pl = self.make_packed()
		total = sum(l.order_qty for l in self.card.lines)
		self.assertTrue(pl.name.startswith(f"{self.sc.name}-PL-"), pl.name)
		self.assertEqual(pl.total_pieces, total)
		self.assertEqual(ledger.stage_total(self.card.name, "PACKED"), total)
		# cartons run on without a gap and CBM is L x W x H
		self.assertEqual(pl.cartons[0].carton_from, 1)
		self.assertEqual([c.carton_from for c in pl.cartons[1:]], [c.carton_to + 1 for c in pl.cartons[:-1]])
		self.assertAlmostEqual(pl.cartons[0].cbm_per_carton, 0.03564, 6)
		self.assertEqual(pl.total_cartons, sum(c.carton_count for c in pl.cartons))
		pl.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "PACKED"), 0)

	def test_cannot_pack_more_than_finished(self):
		self.finish_all()
		pl = self.packing_doc()
		pl.insert()
		pl.generate_cartons()
		pl.contents[0].qty_per_carton += 30
		pl.save()
		for c in pl.cartons:
			c.gross_weight_kg = 5.5
		pl.save()
		with self.assertRaises(frappe.ValidationError):
			pl.submit()

	def test_nothing_to_pack_before_finishing(self):
		pl = self.packing_doc()
		pl.insert()
		with self.assertRaises(frappe.ValidationError):
			pl.generate_cartons()

	def test_overlapping_carton_numbers_are_refused(self):
		self.finish_all()
		pl = self.packing_doc()
		pl.insert()
		pl.generate_cartons()
		pl.cartons[1].carton_from = pl.cartons[0].carton_to  # one carton in two rows
		with self.assertRaises(frappe.ValidationError):
			pl.save()

	def test_gross_weight_is_required_to_submit(self):
		self.finish_all()
		pl = self.packing_doc()
		pl.insert()
		pl.generate_cartons()
		pl.save()
		with self.assertRaises(frappe.ValidationError):
			pl.submit()

	def test_second_list_only_gets_what_is_left(self):
		self.finish_all()
		self.make_packed()
		second = self.packing_doc()
		second.insert()
		with self.assertRaises(frappe.ValidationError):
			second.generate_cartons()  # everything is already packed

	def test_sscc_numbers_are_never_reused(self):
		prev = frappe.db.get_single_value("Apparel Settings", "gs1_company_prefix")
		frappe.db.set_single_value("Apparel Settings", "gs1_company_prefix", "0360002914")
		try:
			self.finish_all()
			pl = self.make_packed()
			pl.reload()
			codes = [r.sscc for r in pl.sscc]
			self.assertEqual(len(codes), pl.total_cartons)
			self.assertEqual(len(set(codes)), len(codes))
			self.assertTrue(all(maths.valid_gs1(c) for c in codes))
			pl.cancel()
			pl2 = self.make_packed()
			pl2.reload()
			self.assertFalse(set(codes) & {r.sscc for r in pl2.sscc})
		finally:
			frappe.db.set_single_value("Apparel Settings", "gs1_company_prefix", prev)

	def test_needle_block_stops_packing(self):
		self.finish_all()
		prev = frappe.db.get_single_value("Apparel Settings", "needle_check_required")
		frappe.db.set_single_value("Apparel Settings", "needle_check_required", "Block")
		frappe.db.delete("Needle Detector Log", {"check_date": nowdate()})
		try:
			with self.assertRaises(frappe.ValidationError):
				self.make_packed()
		finally:
			frappe.db.set_single_value("Apparel Settings", "needle_check_required", prev)


class TestFinalInspection(ShipBase):
	def test_unconfirmed_aql_row_is_refused(self):
		self.finish_all()
		pl = self.make_packed()
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "lots": [{"packing_list": pl.name}], "aql_plan": "Garment AQL 2.5 / 4.0 Level II"})
		with self.assertRaises(frappe.ValidationError):  # 1,200 pieces falls in code J, which QA has not confirmed
			fi.insert()

	def test_accept_with_no_defects(self):
		self.finish_all()
		pl = self.make_packed()
		fi = self.inspect(pl)
		self.assertTrue(fi.name.startswith(f"{self.sc.name}-FI-"), fi.name)
		self.assertEqual((fi.sample_size, fi.major_re, fi.minor_re), (80, 4, 6))
		self.assertEqual(len(fi.cartons_picked), fi.inspected_cartons)
		pl.reload()
		self.assertEqual(pl.final_inspection, fi.name)

	def test_defects_fail_the_lot_and_block_accept(self):
		self.finish_all()
		pl = self.make_packed()
		major = frappe.db.get_value("Apparel Defect Code", {"severity": "Major"}, "name")
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "aql_plan": self.plan, "lots": [{"packing_list": pl.name}],
							 "defects": [{"defect_code": major, "qty": 4}], "result": "Accepted"})
		with self.assertRaises(frappe.ValidationError):
			fi.insert()  # 4 majors reach the reject number
		fi.result = "Rejected"
		fi.insert()
		self.assertEqual(fi.computed_result, "Rejected")

	def test_any_critical_defect_fails(self):
		self.finish_all()
		pl = self.make_packed()
		critical = frappe.db.get_value("Apparel Defect Code", {"severity": "Critical"}, "name")
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "aql_plan": self.plan, "lots": [{"packing_list": pl.name}], "defects": [{"defect_code": critical, "qty": 1}]})
		fi.insert()
		self.assertEqual(fi.computed_result, "Rejected")

	def test_failed_check_cannot_be_accepted_and_concession_needs_approval(self):
		self.finish_all()
		pl = self.make_packed()
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "aql_plan": self.plan, "lots": [{"packing_list": pl.name}], "metal_detection_ok": "No", "result": "Accepted"})
		with self.assertRaises(frappe.ValidationError):
			fi.insert()
		fi.result = "Accepted with Concession"
		with self.assertRaises(frappe.ValidationError):
			fi.insert()  # no buyer approval reference
		fi.concession_ref, fi.approved_by = "Buyer email 12 Nov", "Jennifer"
		fi.insert()

	def test_must_pick_cartons_before_submit(self):
		self.finish_all()
		pl = self.make_packed()
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "aql_plan": self.plan, "lots": [{"packing_list": pl.name}], "result": "Accepted"})
		fi.insert()
		with self.assertRaises(frappe.ValidationError):
			fi.submit()

	def test_gate_follows_the_latest_inspection(self):
		from arinox_apparel.arinox_apparel.doctype.final_inspection.final_inspection import gate_problems

		self.finish_all()
		pl = self.make_packed()
		self.assertTrue(gate_problems([pl.name]))  # no inspection yet
		self.inspect(pl, result="Rejected")
		self.assertTrue(gate_problems([pl.name]))
		fi = self.inspect(pl, result="Accepted", inspection_type="Re-inspection", previous_inspection=frappe.get_all("Final Inspection", {"production_card": self.card.name}, pluck="name")[0])
		self.assertEqual(gate_problems([pl.name]), [])
		fi.cancel()
		self.assertTrue(gate_problems([pl.name]))

	def test_pre_final_never_opens_the_gate(self):
		from arinox_apparel.arinox_apparel.doctype.final_inspection.final_inspection import gate_problems

		self.finish_all()
		pl = self.make_packed()
		self.inspect(pl, inspection_type="Pre-Final")
		self.assertTrue(gate_problems([pl.name]))

	def test_small_share_packed_is_refused_for_a_final(self):
		for l in self.card.lines:
			if l.colour == "Navy" and l.size == "S":
				for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A"):
					self.post(stage, "Navy", "S", 50)
		pl = self.packing_doc()
		pl.insert()
		pl.generate_cartons()
		for c in pl.cartons:
			c.gross_weight_kg = 5.5
		pl.save()
		pl.submit()
		fi = frappe.get_doc({"doctype": "Final Inspection", "production_card": self.card.name, "aql_plan": self.plan, "lots": [{"packing_list": pl.name}]})
		with self.assertRaises(frappe.ValidationError):
			fi.insert()  # 50 of 1,200 is far below the share a final inspection needs


class TestShipmentAndInvoice(ShipBase):
	def test_shipment_fills_itself_from_the_packing_list(self):
		pl, sh = self.ready()
		self.assertEqual(sh.apparel_contracts, self.sc.name)
		self.assertAlmostEqual(sh.apparel_declared_cbm, pl.total_cbm, 6)
		self.assertAlmostEqual(sh.apparel_declared_gross_kg, pl.total_gross_kg, 3)
		self.assertEqual(sum(p.count for p in sh.shipment_parcel), pl.total_cartons)
		self.assertGreater(sh.value_of_goods, 0)
		pl.reload()
		self.assertEqual((pl.shipment, pl.status), (sh.name, "On Shipment"))

	def test_removing_a_list_frees_it(self):
		pl, sh = self.ready()
		sh.set("apparel_packing_lists", [])
		sh.save()
		pl.reload()
		self.assertEqual((pl.shipment, pl.status), (None, "Open"))

	def test_a_list_cannot_be_on_two_shipments_or_be_cancelled_while_on_one(self):
		pl, sh = self.ready()
		with self.assertRaises(frappe.ValidationError):
			self.shipment(pl)
		pl.reload()
		with self.assertRaises(frappe.ValidationError):
			pl.cancel()

	def test_differing_measures_are_reported_not_overwritten(self):
		pl, sh = self.ready()
		sh.apparel_carrier_cbm = round(sh.apparel_declared_cbm * 1.2, 6)
		sh.apparel_carrier_gross_kg = sh.apparel_declared_gross_kg
		sh.save()
		self.assertIn("Carrier CBM", sh.apparel_measure_note)
		self.assertNotIn("weight", sh.apparel_measure_note.lower())
		self.assertAlmostEqual(sh.apparel_declared_cbm, pl.total_cbm, 6)

	def test_air_on_a_sea_contract_needs_a_reason(self):
		frappe.db.set_value("Sales Contract", self.sc.name, "shipment_mode", "Sea", update_modified=False)
		pl, sh = self.ready()
		sh.apparel_mode = "Air"
		with self.assertRaises(frappe.ValidationError):
			sh.save()
		sh.reload()
		sh.apparel_mode, sh.apparel_reason_for_air, sh.apparel_air_cost_borne_by = "Air", "Late fabric", "Factory"
		sh.save()

	def make_dns(self, sh):
		from arinox_apparel.shipping import shipment as sm

		return sm.make_delivery_notes(sh.name)

	def test_delivery_note_is_blocked_until_the_lot_passes(self):
		pl, sh = self.ready()
		dns = self.make_dns(sh)
		self.assertEqual(len(dns), 1)
		dn = frappe.get_doc("Delivery Note", dns[0])
		self.assertEqual(sum(i.qty for i in dn.items), pl.total_pieces)
		self.assertTrue(all(i.apparel_packing_list == pl.name for i in dn.items))
		self.assertEqual(dn.apparel_sales_contract, self.sc.name)
		with self.assertRaises(frappe.ValidationError) as cm:
			dn.submit()
		self.assertIn("final inspection", str(cm.exception).lower())
		self.inspect(pl)
		dn.reload()
		dn.submit()
		self.assertEqual(ledger.stage_total(self.card.name, "SHIPPED"), pl.total_pieces)
		pl.reload()
		self.assertEqual(pl.status, "Shipped")
		dn.cancel()
		self.assertEqual(ledger.stage_total(self.card.name, "SHIPPED"), 0)
		pl.reload()
		self.assertEqual(pl.status, "On Shipment")

	def test_gate_override_needs_a_manager_and_a_reason(self):
		pl, sh = self.ready()
		dn = frappe.get_doc("Delivery Note", self.make_dns(sh)[0])
		dn.apparel_gate_override = 1
		with self.assertRaises(frappe.ValidationError):
			dn.submit()  # no reason
		dn.reload()
		dn.apparel_gate_override = 1
		dn.apparel_gate_override_reason = "Buyer released the lot by email"
		dn.save()
		dn.submit()
		self.assertEqual(dn.docstatus, 1)

	def test_delivery_note_over_the_allowance_is_blocked(self):
		pl, sh = self.ready()
		self.inspect(pl)
		dn = frappe.get_doc("Delivery Note", self.make_dns(sh)[0])
		dn.items[0].qty += 500  # far above the contract band
		dn.items[0].stock_qty = dn.items[0].qty
		dn.save()
		with self.assertRaises(frappe.ValidationError):
			dn.submit()

	def test_invoice_chain_and_follow_up(self):
		from arinox_apparel.shipping import invoicing

		pl, sh = self.ready()
		self.inspect(pl)
		dn = frappe.get_doc("Delivery Note", self.make_dns(sh)[0])
		dn.submit()
		sh.reload()
		self.assertEqual(sh.apparel_ship_status, "Cargo Handed Over")
		made = invoicing.prepare_invoices(sh.name)
		self.assertEqual(len(made), 1)
		si = frappe.get_doc("Sales Invoice", made[0])
		number = si.apparel_commercial_invoice_no
		self.assertTrue(number.startswith(f"{self.sc.name}-INV-"), number)
		self.assertEqual((si.apparel_sales_contract, si.apparel_shipment), (self.sc.name, sh.name))
		self.assertEqual(si.total_qty, pl.total_pieces)
		self.assertIsNotNone(si.apparel_expected_due_date)
		# running it again keeps the number and replaces the draft
		again = invoicing.prepare_invoices(sh.name)
		self.assertEqual(frappe.db.get_value("Sales Invoice", again[0], "apparel_commercial_invoice_no"), number)
		self.assertEqual(frappe.db.count("Sales Invoice", {"apparel_shipment": sh.name, "docstatus": 0}), 1)
		# a counted-from-B/L contract cannot be submitted before the on-board date
		frappe.db.set_value("Sales Contract", self.sc.name, {"payment_basis": followup.BL, "payment_days": 30}, update_modified=False)
		invoicing.prepare_invoices(sh.name)
		with self.assertRaises(frappe.ValidationError):
			invoicing.submit_invoices(sh.name)
		sh.apparel_on_board_date = nowdate()
		sh.save()
		done = invoicing.submit_invoices(sh.name)
		si = frappe.get_doc("Sales Invoice", done[0])
		self.assertEqual(si.docstatus, 1)
		self.assertEqual(str(si.apparel_expected_due_date), str(add_days(nowdate(), 30)))
		self.assertEqual(si.apparel_due_basis, followup.BL)
		self.assertEqual(str(si.due_date), str(si.apparel_expected_due_date))  # ERPNext's own due date follows the contract basis too
		# the delivery date later moves nothing for a B/L basis, but ETA and ROG would; the daily job keeps the status current
		followup.daily()
		si.reload()
		self.assertIn(si.apparel_followup_status, ("Not Due", "Due Soon"))
		followup.log_follow_up(si.name, "Called AP: payment run on the 20th", promise_date=add_days(nowdate(), 20), promise_amount=1000, next_action_date=add_days(nowdate(), 10))
		si.reload()
		self.assertEqual(str(si.apparel_promise_date), str(add_days(nowdate(), 20)))
		self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "Sales Invoice", "reference_name": si.name, "content": ["like", "%payment run%"]}))
		# the contract trail lists the whole chain under the one number
		from arinox_apparel.arinox_apparel.report.contract_trail.contract_trail import execute

		kinds = {r["doctype"] for r in execute({"contract": self.sc.name})[1]}
		self.assertTrue({"Sales Order", "Production Card", "Packing List", "Final Inspection", "Delivery Note", "Sales Invoice", "Shipment"} <= kinds, kinds)

	def test_closed_status_is_not_reopened(self):
		from arinox_apparel.shipping import shipment as sm

		pl, sh = self.ready()
		frappe.db.set_value("Shipment", sh.name, "apparel_ship_status", "Closed", update_modified=False)
		sm.refresh_status(sh.name)
		self.assertEqual(frappe.db.get_value("Shipment", sh.name, "apparel_ship_status"), "Closed")

	def test_a_shipped_list_cannot_be_taken_off(self):
		pl, sh = self.ready()
		dn = frappe.get_doc("Delivery Note", self.make_dns(sh)[0])
		dn.apparel_gate_override, dn.apparel_gate_override_reason = 1, "Buyer released the lot"
		dn.save()
		dn.submit()
		sh.reload()
		sh.set("apparel_packing_lists", [])
		with self.assertRaises(frappe.ValidationError):
			sh.save()
		pl.reload()
		self.assertEqual((pl.shipment, pl.status), (sh.name, "Shipped"))

	def test_transfer_price_by_percent(self):
		from arinox_apparel.shipping import invoicing

		frappe.db.set_value("Customer", u.CUSTOMER, {"apparel_transfer_basis": "Percent of Customer Price", "apparel_transfer_pct": 40}, update_modified=False)
		try:
			self.assertEqual(invoicing.transfer_rate(u.CUSTOMER, frappe._dict(rate=20, item_code="x")), 8)
			frappe.db.set_value("Customer", u.CUSTOMER, "apparel_transfer_pct", 0, update_modified=False)
			with self.assertRaises(frappe.ValidationError):
				invoicing.transfer_rate(u.CUSTOMER, frappe._dict(rate=20, item_code="x"))
		finally:
			frappe.db.set_value("Customer", u.CUSTOMER, {"apparel_transfer_basis": "", "apparel_transfer_pct": 0}, update_modified=False)

	def test_freight_variance_and_allocation(self):
		from arinox_apparel.shipping import freight

		pl, sh = self.ready()
		frappe.db.set_value("Shipment", sh.name, "apparel_estimate_total", 2000, update_modified=False)
		rows, basis, cost = freight.allocated_costs(sh.name)
		self.assertEqual((basis, cost), ("cbm", 2000))
		self.assertEqual(rows, [(self.sc.name, 1.0, 2000.0)])


class TestInvoicedChain(TestShipmentAndInvoice):
	"""Claims, close and prints all start from an order that has shipped and been invoiced."""

	def invoiced(self):
		from arinox_apparel.shipping import invoicing

		pl, sh = self.ready()
		self.inspect(pl)
		frappe.get_doc("Delivery Note", self.make_dns(sh)[0]).submit()
		sh.reload()
		sh.apparel_on_board_date = nowdate()
		sh.apparel_hbl_no = "HBL-TEST"
		sh.save()
		invoicing.prepare_invoices(sh.name)
		done = invoicing.submit_invoices(sh.name)
		return pl, sh, frappe.get_doc("Sales Invoice", done[0])

	def test_prints_render(self):
		pl, sh, si = self.invoiced()
		html = frappe.get_print("Packing List", pl.name, "Packing List Form")
		self.assertIn("PACKING LIST", html)
		self.assertIn(self.sc.name, html)
		html = frappe.get_print("Sales Invoice", si.name, "Commercial Invoice")
		self.assertIn("COMMERCIAL INVOICE", html)
		self.assertIn(si.apparel_commercial_invoice_no, html)
		fi = frappe.get_doc("Final Inspection", frappe.get_all("Final Inspection", {"production_card": self.card.name}, pluck="name")[0])
		self.assertIn("FINAL INSPECTION REPORT", frappe.get_print("Final Inspection", fi.name, "Final Inspection Report"))

	def test_claim_cap_window_and_credit_note(self):
		from arinox_apparel.arinox_apparel.doctype.buyer_claim.buyer_claim import make_credit_note

		pl, sh, si = self.invoiced()
		claim = frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Quality", "claimed_amount": 5000, "rows": [{"colour": "Navy", "size": "S", "pieces": 10}]})
		claim.insert()
		self.assertTrue(claim.name.startswith(f"{self.sc.name}-CL-"), claim.name)
		self.assertEqual(claim.sales_contract, self.sc.name)
		self.assertAlmostEqual(claim.cap_amount, round(si.net_total / si.total_qty * 10, 2), 2)
		self.assertIn("Open claim", frappe.db.get_value("Sales Invoice", si.name, "apparel_dispute_reason") or "")  # no reminders while it is open
		claim.status, claim.accepted_amount, claim.settlement = "Accepted", claim.cap_amount + 100, "Credit Note"
		with self.assertRaises(frappe.ValidationError):
			claim.submit()  # above the cap needs a written reason
		claim.reload()
		claim.status, claim.accepted_amount, claim.settlement, claim.override_reason = "Accepted", claim.cap_amount + 100, "Credit Note", "Buyer holds the full value; agreed by sales director"
		claim.save()
		claim.submit()
		self.assertFalse(frappe.db.get_value("Sales Invoice", si.name, "apparel_dispute_reason"))
		cn = frappe.get_doc("Sales Invoice", make_credit_note(claim.name))
		self.assertEqual((cn.docstatus, cn.is_return), (0, 1))
		self.assertAlmostEqual(abs(cn.net_total), claim.accepted_amount, 2)  # the claim is a net value; any tax on the invoice is repeated on the credit
		self.assertEqual(make_credit_note(claim.name), cn.name)  # asking again does not draft a second one

	def test_undecided_claim_cannot_be_submitted(self):
		pl, sh, si = self.invoiced()
		claim = frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Chargeback", "claimed_amount": 200})
		claim.insert()
		with self.assertRaises(frappe.ValidationError):
			claim.submit()

	def test_commercial_close_waits_for_payment(self):
		from arinox_apparel.shipping import close

		pl, sh, si = self.invoiced()
		rows = {label: (ok, detail) for label, ok, detail in close.checklist(self.so.name)}
		self.assertTrue(rows["Everything shipped is invoiced"][0])
		paid = rows["Customer invoices paid"]
		self.assertFalse(paid[0])
		self.assertIn(si.name, paid[1])
		with self.assertRaises(frappe.ValidationError):
			close.commercial_close(self.so.name)


# ---- the Server Script pieces: they run in Frappe's sandbox, as they would on a site that cannot install an app -------------
def run_script(name, **doc_locals):
	from frappe.utils.safe_exec import safe_exec

	from arinox_apparel.portable import loader

	entry = next(e for e in loader.manifest() if e["name"] == name)
	return safe_exec(loader.source(entry), _locals=doc_locals)


class TestPortableScripts(ShipBase):
	def messages(self):
		return " | ".join(m if isinstance(m, str) else str(m) for m in (frappe.local.message_log or []))

	def test_every_script_compiles_in_the_sandbox_and_is_installed(self):
		from arinox_apparel.portable import loader

		for e in loader.manifest():
			self.assertIsNone(loader.compile_problem(e), e["name"])
			self.assertTrue(frappe.db.exists("Server Script", e["name"]), e["name"])

	def test_container_check_digit_and_chargeable_weight_golden_7(self):
		frappe.local.message_log = []
		d = frappe.get_doc({"doctype": "Shipment", "apparel_mode": "Air", "apparel_containers": [
			{"container_no": "CSQU3054383", "container_type": "40HC"}, {"container_no": "ABCD1234567", "container_type": "40HC"}],
			"shipment_parcel": [{"length": 54, "width": 34, "height": 25, "weight": 8.28, "count": 75}]})
		run_script("arinox_shipment_checks", doc=d)
		msg = self.messages()
		self.assertIn("ABCD1234567", msg)       # fails the ISO 6346 check digit
		self.assertNotIn("CSQU3054383", msg)    # a valid example number
		# 75 cartons of 54 x 34 x 25 cm: volumetric 573.75 kg, actual 621 kg -> the greater is charged
		self.assertEqual(d.apparel_chargeable_kg, 621.0)
		d.shipment_parcel[0].weight = 5
		run_script("arinox_shipment_checks", doc=d)
		self.assertEqual(d.apparel_chargeable_kg, 573.75)
		d.apparel_mode = "Sea LCL"
		run_script("arinox_shipment_checks", doc=d)
		self.assertAlmostEqual(d.apparel_chargeable_cbm, 3.4425, 2)  # 3.4425 m3 against 0.375 t

	def test_destination_filing_rows_come_from_the_enabled_rules(self):
		rule = "Importer Security Filing (US)"
		frappe.db.set_value("Destination Filing Rule", rule, "enabled", 1)
		try:
			pl, sh = self.ready()
			sh.apparel_destination_country, sh.incoterm, sh.apparel_cutoff = "United States", "DDP", "2026-12-22 16:00:00"
			sh.save()
			self.assertEqual([(r.rule, str(r.due_by)[:19]) for r in sh.apparel_filings], [(rule, "2026-12-21 16:00:00")])
			sh.save()
			self.assertEqual(len(sh.apparel_filings), 1)   # saving again adds nothing
			sh.apparel_mode, sh.apparel_reason_for_air, sh.apparel_air_cost_borne_by = "Air", "Late fabric", "Factory"
			sh.apparel_filings = []
			sh.save()
			self.assertEqual(len(sh.apparel_filings), 0)   # the rule is for sea cargo only
		finally:
			frappe.db.set_value("Destination Filing Rule", rule, "enabled", 0)

	def test_freight_quote_lines(self):
		pl, sh = self.ready()
		doc = frappe.get_doc({"doctype": "Supplier Quotation", "apparel_shipment": sh.name, "items": [
			{"item_code": "x", "qty": 2, "rate": 10, "apparel_charge_unit": "Per Shipment", "apparel_min_amount": 50},
			{"item_code": "y", "qty": 10, "rate": 10, "apparel_charge_unit": "Per Pallet", "apparel_max_amount": 60},
			{"item_code": "z", "qty": 1, "rate": 99, "apparel_charge_unit": "At Cost"},
			{"item_code": "w", "qty": round(sh.apparel_declared_cbm * 2, 3), "rate": 5, "apparel_charge_unit": "Per CBM"}]})
		frappe.local.message_log = []
		run_script("arinox_quote_checks", doc=doc)
		self.assertEqual([i.rate for i in doc.items][:3], [25, 6, 0])   # minimum charge lifts the rate, maximum caps it, at-cost is not priced
		self.assertIn("(at cost", doc.items[2].description)
		self.assertIn("Per CBM", self.messages())                      # quoted on twice the cubic metres the shipment has
		self.assertIn("Per Shipment", self.messages())                  # 2 against 1 shipment

	def test_sample_invoice_joins_the_follow_up(self):
		si = frappe.get_doc({"doctype": "Sales Invoice", "apparel_is_sample_invoice": 1, "posting_date": "2026-03-25", "due_date": "2026-04-24"})
		run_script("arinox_sample_invoice", doc=si)
		self.assertEqual((si.po_no, str(si.apparel_expected_due_date), si.apparel_due_basis), ("SAMPLE", "2026-04-24", "Days after Invoice Date"))
		other = frappe.get_doc({"doctype": "Sales Invoice", "posting_date": "2026-03-25", "due_date": "2026-04-24"})
		run_script("arinox_sample_invoice", doc=other)
		self.assertFalse(other.get("apparel_expected_due_date"))

	def test_letter_of_credit_deadlines(self):
		pl, sh = self.ready()
		sh.apparel_on_board_date = "2026-10-20"
		sh.save()
		lc = frappe.get_doc({"doctype": "Letter of Credit", "lc_no": "LC-TEST-1", "customer": u.CUSTOMER, "currency": "USD", "amount": 10000, "tolerance_pct": 5,
							 "latest_shipment_date": "2026-10-15", "expiry_date": "2026-11-08", "shipment": sh.name})
		lc.insert()
		try:
			self.assertEqual(str(lc.presentation_deadline), "2026-11-08")   # 20 Oct + 21 days is 10 Nov, but the credit expires on the 8th
			self.assertIn("after the latest shipment date", lc.check_note)
			lc.expiry_date = "2027-03-01"
			lc.save()
			self.assertEqual(str(lc.presentation_deadline), "2026-11-10")
			old = frappe.get_doc({"doctype": "Letter of Credit", "lc_no": "LC-TEST-2", "customer": u.CUSTOMER, "currency": "USD", "amount": 1, "expiry_date": add_days(nowdate(), -3)})
			old.insert()
			self.assertEqual(old.status, "Expired")
			old.delete()
		finally:
			lc.delete()

	def test_letter_of_credit_reminder_is_raised_once(self):
		lc = frappe.get_doc({"doctype": "Letter of Credit", "lc_no": "LC-TEST-3", "customer": u.CUSTOMER, "currency": "USD", "amount": 1, "expiry_date": add_days(nowdate(), 5)})
		lc.insert()
		try:
			run_script("arinox_lc_watch")
			run_script("arinox_lc_watch")
			self.assertEqual(frappe.db.count("ToDo", {"reference_type": "Letter of Credit", "reference_name": lc.name}), 1)
		finally:
			frappe.db.delete("ToDo", {"reference_type": "Letter of Credit", "reference_name": lc.name})
			lc.delete()

	def test_on_board_and_in_warehouse_are_stamped_on_the_t_and_a(self):
		pl, sh = self.ready()
		tnas = frappe.get_all("Order TNA", {"sales_order": self.so.name}, pluck="name")
		for t in tnas:   # the default template does not carry these two, so give this order's T&A the milestones
			for code in ("ON_BOARD", "IN_WAREHOUSE"):
				if not frappe.db.exists("TNA Milestone", {"order_tna": t, "milestone_type": code}):
					src = frappe.get_all("TNA Milestone", {"order_tna": t}, ["name"], limit=1)[0].name
					m = frappe.copy_doc(frappe.get_doc("TNA Milestone", src))
					m.milestone_type, m.actual_date, m.source_doctype, m.source_name = code, None, None, None
					m.insert(ignore_permissions=True)
		sh.apparel_on_board_date, sh.apparel_delivery_date = "2026-10-28", "2026-11-02"
		sh.save()
		sh.apparel_delivery_date = "2027-03-01"   # planned, not yet happened: must not block the save or stamp anything
		sh.save()
		got = {m.milestone_type: str(m.actual_date) for m in frappe.get_all("TNA Milestone", {"order_tna": ["in", tnas], "milestone_type": ["in", ["ON_BOARD", "IN_WAREHOUSE"]]}, ["milestone_type", "actual_date"])}
		self.assertEqual(got, {"ON_BOARD": "2026-10-28", "IN_WAREHOUSE": "2026-11-02"})

	def test_close_production_rules(self):
		self.finish_all()
		frappe.local.form_dict.update({"production_card": self.card.name, "reason": ""})
		draft = self.packing_doc()
		draft.insert()
		with self.assertRaises(frappe.ValidationError) as cm:
			frappe.get_doc("Server Script", "arinox_close_production").execute_method()
		self.assertIn("draft Packing List", str(cm.exception))
		draft.delete()
		with self.assertRaises(frappe.ValidationError) as cm:
			frappe.get_doc("Server Script", "arinox_close_production").execute_method()   # nothing has shipped
		self.assertIn("lower limit", str(cm.exception))
		frappe.local.form_dict.update({"reason": "Buyer cancelled the balance"})
		out = frappe.get_doc("Server Script", "arinox_close_production").execute_method()
		self.assertEqual(frappe.db.get_value("Production Card", self.card.name, "status"), "Closed")
		self.assertEqual(out["status"], "Closed")   # an API script hands back frappe.flags

	def test_production_summary_query_report(self):
		from frappe.desk.query_report import run

		self.finish_all()
		pl = self.make_packed()
		res = run("Production Summary", filters={"production_card": self.card.name})
		rows = [r for r in res["result"] if isinstance(r, dict) and r.get("colour") in ("Navy", "Black")]   # a totals row follows
		self.assertEqual(len(rows), 6)                        # Navy and Black in S, M and L
		navy_s = next(r for r in rows if r["colour"] == "Navy" and r["size"] == "S")
		self.assertEqual((navy_s["order_qty"], navy_s["cut"], navy_s["packed"], navy_s["shipped"], navy_s["a_grade_not_packed"], navy_s["packed_not_shipped"]), (200, 200, 200, 0, 0, 200))

	def test_carton_label_prints_one_label_per_carton_with_the_sscc(self):
		prev = frappe.db.get_single_value("Apparel Settings", "gs1_company_prefix")
		frappe.db.set_single_value("Apparel Settings", "gs1_company_prefix", "0360002914")
		try:
			self.finish_all()
			pl = self.make_packed()
			html = frappe.get_print("Packing List", pl.name, "Carton Label")
			self.assertEqual(html.count('class="cl"'), pl.total_cartons)
			self.assertIn(f"CARTON 1 OF {pl.total_cartons}", html)
			pl.reload()
			self.assertIn(f"(00){pl.sscc[0].sscc}", html)
			self.assertEqual(html.count("<svg data-barcode-value"), pl.total_cartons)
		finally:
			frappe.db.set_single_value("Apparel Settings", "gs1_company_prefix", prev)
