import json

import frappe
from frappe.utils import nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def plan(quantities, pack_type="Solid Colour Solid Size", pcs=24, ratios=None, tail="Mixed Colour and Size", start=1):
	"""The generator API with explicit quantities: the pure carton planning, no card needed."""
	form = {"pack_type": pack_type, "pcs_per_carton": pcs, "tail_carton_rule": tail, "carton_start": start,
			"ratios": [{"size": s, "pieces_per_pack": r} for s, r in (ratios or {}).items()]}
	out = fx.engine_call("arinox_packing_list_api_generate", doc=frappe.as_json(form), quantities=json.dumps(quantities))
	return out["arinox_result"]["plan"]


def total(rows):
	return sum((r["carton_to"] - r["carton_from"] + 1) * r["pieces_per_carton"] for r in rows)


def gs1_ok(code):
	digits = [int(c) for c in code[:-1]][::-1]
	return (10 - sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits)) % 10) % 10 == int(code[-1])


@test("packing")
def solid_cartons_and_a_tail_carton():
	rows = plan({"W|XS": 276, "W|S": 456})
	eq([(r["carton_from"], r["carton_to"], r["tail"]) for r in rows], [(1, 11, 0), (12, 30, 0), (31, 31, 1)])
	eq(rows[-1]["contents"], [["W", "XS", 12]])
	eq(total(rows), 276 + 456)


@test("packing")
def ratio_packs_give_219_full_cartons():
	"""Ratio 1:2:2:1 on XS 276, S 456, M 438, L 231 is 219 full packs (the company's sheet)."""
	rows = plan({"W|XS": 276, "W|S": 456, "W|M": 438, "W|L": 231}, "Solid Colour Assorted Size", 6, {"XS": 1, "S": 2, "M": 2, "L": 1})
	eq(rows[0]["contents"], [["W", "XS", 1], ["W", "S", 2], ["W", "M", 2], ["W", "L", 1]])
	eq(rows[0]["carton_to"], 219)
	eq(total(rows), 276 + 456 + 438 + 231)


@test("packing")
def the_tail_rule_decides_how_leftovers_are_boxed():
	pool = {"A|S": 5, "B|M": 7}
	eq(len(plan(pool, tail="Mixed Colour and Size")), 1)
	eq(len(plan(pool, tail="Own Carton")), 2)
	eq(len(plan(pool, tail="Mixed Size Only")), 2)


@test("packing")
def a_pack_that_does_not_divide_the_carton_is_refused():
	true(throws(lambda: plan({"W|XS": 10}, "Solid Colour Assorted Size", 7, {"XS": 2, "S": 2}), "multiple of the pack size"))


@test("packing")
def generate_submit_and_cancel_move_the_ledger():
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24)
	eq(frappe.db.get_value("Packing List", pl.name, "total_pieces"), 100)
	eq(frappe.db.get_value("Packing List", pl.name, "total_cartons"), 5)       # 4 full + 1 tail
	packed = frappe.db.sql("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and stage='PACKED'", card.name)[0][0]
	eq(packed, 100)
	true("100 / 100" in pl.size_summary or "100 / 100" in frappe.db.get_value("Packing List", pl.name, "size_summary"), pl.size_summary)
	pl.cancel()
	eq(frappe.db.sql("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and stage='PACKED'", card.name)[0][0], 0)


@test("packing")
def nothing_to_pack_before_finishing_and_never_more_than_finished():
	so = fx.colour_so({("Navy", "S"): 100})
	card = frappe.get_doc({"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": so.name, "style_item": fx.item(),
						   "lines": [{"colour": "Navy", "size": "S"}]}).insert()
	card.submit()
	true(throws(lambda: fx.packing_list(card, 24), "Nothing is available to pack"))
	done = fx.finished_card(50)
	true(throws(lambda: fx.packing_list(done, 24, quantities={"Navy|S": 60}), "available"))


@test("packing")
def overlapping_or_missing_carton_numbers_are_refused():
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24, submit=False)
	pl.cartons[1].carton_from = pl.cartons[0].carton_to          # row 2 starts inside row 1
	true(throws(lambda: pl.save(), "is in two rows"))
	pl = fx.packing_list(fx.finished_card(100), 24, submit=False)
	pl.cartons[1].carton_from = pl.cartons[0].carton_to + 3
	pl.cartons[1].carton_to = pl.cartons[1].carton_from + 1
	true(throws(lambda: pl.save(), "missing"))


@test("packing")
def gross_weight_is_required_to_submit():
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24, submit=False)
	pl.cartons[0].gross_weight_kg = 0
	pl.save()
	true(throws(lambda: pl.submit(), "gross weight"))


@test("packing")
def a_second_list_only_gets_what_is_left():
	card = fx.finished_card(100)
	fx.packing_list(card, 24, quantities={"Navy|S": 60})
	rows = fx.engine_call("arinox_packing_list_api_generate", doc=frappe.as_json({"production_card": card.name, "pack_type": "Solid Colour Solid Size", "pcs_per_carton": 24, "carton_start": 1}))["arinox_result"]["plan"]
	eq(total(rows), 40)


@test("packing")
def two_styles_sharing_a_colour_and_size_are_tied_to_their_own_order_lines():
	"""A packing list of style B must point at B's Sales Order line, not at style A's line with the same colour and size (the delivery over-ship check reads that line)."""
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	a, b = fx.item("HT-STYLE-1"), fx.item("HT-STYLE-2")
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	rows = [{"item_code": it, "qty": q, "rate": 10, "delivery_date": frappe.utils.add_days(nowdate(), 60), "warehouse": wh, "apparel_colour": "Navy", "apparel_size": "S",
			 "apparel_qty_tolerance_pct": 10} for it, q in ((a, 50), (b, 70))]
	so = frappe.get_doc({"doctype": "Sales Order", "customer": fx.customer(), "company": fx.company(), "delivery_date": frappe.utils.add_days(nowdate(), 60), "items": rows}).insert()
	so.submit()
	card = frappe.get_doc({"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": so.name, "style_item": b, "lines": [{"colour": "Navy", "size": "S"}]})
	card.insert()
	card.submit()
	for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A"):
		fx.engine(action="post", card=card.name, rows=json.dumps([{"stage": stage, "colour": "Navy", "size": "S", "qty": 70}]), source_doctype="Setup", source_name="S-" + stage, posting_date=nowdate(), check="0")
	pl = fx.packing_list(card, 24)
	lines = frappe.get_all("Packing List Content", {"parent": pl.name}, pluck="sales_order_item")
	true(lines and all(frappe.db.get_value("Sales Order Item", n, "item_code") == b for n in lines), "carton contents of style B are tied to B's line")


@test("packing")
def sscc_numbers_have_a_valid_check_digit_and_are_never_reused():
	frappe.db.set_single_value("Apparel Settings", "gs1_company_prefix", "0360002914")
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24)
	codes = frappe.get_all("Packing List SSCC", {"parent": pl.name}, pluck="sscc")
	eq(len(codes), 5)
	true(all(len(c) == 18 and gs1_ok(c) for c in codes), codes)
	pl.cancel()
	second = fx.packing_list(fx.finished_card(100), 24)
	again = frappe.get_all("Packing List SSCC", {"parent": second.name}, pluck="sscc")
	true(not (set(codes) & set(again)), "an SSCC was reused after a cancel")


@test("packing")
def a_failed_needle_check_blocks_packing():
	frappe.db.set_single_value("Apparel Settings", "needle_check_required", "Block")
	card = fx.finished_card(100)
	pl = fx.packing_list(card, 24, submit=False)
	true(throws(lambda: pl.submit(), "needle detector"))
	if not frappe.db.exists("Workstation", "HT Line 1"):
		frappe.get_doc({"doctype": "Workstation", "workstation_name": "HT Line 1"}).insert()
	frappe.get_doc({"doctype": "Needle Detector Log", "check_date": nowdate(), "line": "HT Line 1", "result": "Pass"}).insert()
	pl = frappe.get_doc("Packing List", pl.name)
	pl.submit()
	eq(pl.docstatus, 1)
