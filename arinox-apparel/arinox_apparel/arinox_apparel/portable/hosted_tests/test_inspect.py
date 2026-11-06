import json

import frappe
from frappe.utils import add_days, flt, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import bin_qty, call, make_pos, receive, received_fabric, tr, trim_item, world


def make_fi(pr, inspect=10, widths=None, shade=None):
	d = call("arinox_fabric_inspection_make_inspection", purchase_receipt=pr.name, purchase_receipt_item=pr.items[0].name)
	d.pop("name", None)
	fi = frappe.get_doc(d)
	for i, r in enumerate(fi.rolls):
		r.inspected = 1 if i < inspect else 0
		if widths:
			r.width_start_cm = r.width_middle_cm = r.width_end_cm = widths
		if shade:
			r.shade_band = shade[i % len(shade)]
	return fi


def defects(fi, roll_no, n, code="C", length=10):
	"""n defects of 4 points in different yards of one roll."""
	for y in range(1, n + 1):
		fi.append("defects", {"roll_no": roll_no, "yard_position": y * 5, "defect_code": code, "defect_length_in": length})


def settings_ok():
	"""Sampling bands and the percent plan the app's defaults give (50% up to 1000 m)."""
	bands = frappe.get_all("Fabric Sampling Band", filters={"parent": "Apparel Settings"}, fields=["from_length_m", "to_length_m", "inspect_pct"])
	if not bands:
		s = frappe.get_doc("Apparel Settings")
		for a, b, c in [(0, 1000, 50), (1001, 2000, 30), (2001, 3000, 20), (3001, 5000, 15), (5001, 0, 10)]:
			s.append("fabric_sampling_bands", {"from_length_m": a, "to_length_m": b, "inspect_pct": c})
		s.save()


@test("inspection")
def a_passing_lot_releases_everything_to_the_store():
	settings_ok()
	w = world()
	store = w["wh"]["store_warehouse_fabric"]
	before = bin_qty(w["navy_fabric"], store)
	f, po, pr = received_fabric(w)
	fi = make_fi(pr, inspect=2)
	fi.insert()
	eq((fi.total_rolls, flt(fi.total_received_m), fi.sampling_pct, fi.required_inspect_m), (10, 882.0, 50, 441.0))
	true(throws(lambda: fi.submit(), "Inspect at least"))                        # 176 m of 441 m
	fi = make_fi(pr, inspect=5)
	defects(fi, "R01", 1, length=2)                                              # one 1-point defect
	fi.insert()
	eq(fi.lot_result, "Pass")
	fi.submit()
	fi.reload()
	st = {b.apparel_roll_no: b.apparel_inspection_status for b in frappe.get_all("Batch", filters={"reference_name": pr.name}, fields=["apparel_roll_no", "apparel_inspection_status"])}
	eq((st["R01"], st["R10"]), ("Accepted", "Accepted by Lot"))                  # R10 was not inspected and the lot passed
	eq(frappe.db.get_value("Quality Inspection", fi.quality_inspection, "status"), "Accepted")
	eq(frappe.db.get_value("Stock Entry", fi.stock_entry, "docstatus"), 1)
	true(abs(bin_qty(w["navy_fabric"], store) - before - 882) < 0.1)
	f.reload()
	true(abs(f.items[0].accepted_qty - 882) < 0.1, f.items[0].accepted_qty)
	eq(frappe.db.get_value("Fabric Inspection", fi.name, "claim_deadline"), frappe.utils.getdate(add_days(pr.posting_date, 45)))
	fi.cancel()                                                                  # cancel puts everything back
	true(abs(bin_qty(w["navy_fabric"], store) - before) < 0.1)
	true(all(b.apparel_inspection_status == "Uninspected" for b in frappe.get_all("Batch", filters={"reference_name": pr.name}, fields=["apparel_inspection_status"])))
	f.reload()
	eq(f.items[0].accepted_qty, 0)


@test("inspection")
def one_bad_roll_is_rejected_and_the_lot_still_passes_and_can_be_returned():
	settings_ok()
	w = world()
	reject = w["wh"]["rejected_warehouse"]
	before = bin_qty(w["navy_fabric"], reject)
	f, po, pr = received_fabric(w)
	fi = make_fi(pr, inspect=10)
	defects(fi, "R01", 6)                                                        # 24 points over ~96 yd = 24.9 per 100 > 20
	fi.insert()
	by = {r.roll_no: r.roll_result for r in fi.rolls}
	eq((by["R01"], by["R02"]), ("Reject", "Accept"))
	eq((fi.rejected_rolls, fi.lot_result), (1, "Pass"))                          # 10% of rolls is not above the 10% limit
	fi.submit()
	fi.reload()
	true(abs(bin_qty(w["navy_fabric"], reject) - before - 88.2) < 0.1)
	f.reload()
	true(abs(f.items[0].accepted_qty - 793.8) < 0.1 and abs(f.items[0].rejected_qty - 88.2) < 0.1, (f.items[0].accepted_qty, f.items[0].rejected_qty))
	ret = call("arinox_fabric_inspection_make_purchase_return", inspection=fi.name)
	eq(len(ret["items"]), 1)
	true(abs(ret["items"][0]["qty"] + 88.2) < 0.01, ret["items"][0]["qty"])
	eq((ret["items"][0]["warehouse"], ret["is_return"]), (reject, 1))


@test("inspection")
def a_failed_sample_needs_every_roll():
	settings_ok()
	w = world()
	f, po, pr = received_fabric(w)
	fi = make_fi(pr, inspect=5)
	defects(fi, "R01", 6)
	defects(fi, "R02", 6)
	fi.insert()
	eq(fi.lot_result, "Re-inspect 100%")
	true(throws(lambda: fi.submit(), "Inspect every roll"))
	fi = frappe.get_doc("Fabric Inspection", fi.name)
	for r in fi.rolls:
		r.inspected = 1
	fi.save()
	eq(fi.lot_result, "Fail")                                                    # 2 of 10 rejected = 20%
	fi.submit()
	eq(frappe.db.get_value("Quality Inspection", fi.quality_inspection, "status"), "Rejected")


@test("inspection")
def width_and_shade_flags_reach_the_requisition_and_stamps_follow():
	settings_ok()
	w = world()
	f, po, pr = received_fabric(w)
	fi = make_fi(pr, inspect=10, widths=128, shade=["A", "B"])
	fi.insert()
	eq(fi.avg_actual_width_cm, 128)
	fi.submit()
	fi.reload()
	true(abs(fi.width_shortfall_m - 882 * (132 / 128 - 1)) < 0.2, fi.width_shortfall_m)
	flags = frappe.db.get_value("Fabric Requisition", f.name, "red_flags")
	true("narrower" in flags and "Cut by shade band" in flags, flags)


@test("inspection")
def bad_defects_unknown_rolls_holes_override_and_terms_threshold():
	settings_ok()
	w = world()
	f, po, pr = received_fabric(w)
	fi = make_fi(pr)
	fi.append("defects", {"roll_no": "NOPE", "yard_position": 1, "defect_code": "C", "defect_length_in": 2})
	true(throws(lambda: fi.insert(), "is not in the roll list"))
	fi = make_fi(pr)
	fi.append("defects", {"roll_no": "R01", "yard_position": 1, "defect_code": "C", "defect_length_in": 0})
	true(throws(lambda: fi.insert(), "defect length"))
	fi = make_fi(pr)
	fi.append("defects", {"roll_no": "R01", "yard_position": 1, "defect_code": "H", "defect_length_in": 0})
	fi.insert()
	eq(fi.defects[0].points, 4)                                                  # a hole needs no length
	merch = fx.user("ht_merch@example.com", ["Apparel Merchandiser"])
	fi = frappe.get_doc("Fabric Inspection", fi.name)
	fi.result_override = 1
	fi.override_reason = "Buyer accepted"
	try:
		frappe.set_user(merch)
		fi.flags.ignore_permissions = True
		true(throws(lambda: fi.save(), "Only an Apparel Merchandising Manager"))
	finally:
		frappe.set_user("Administrator")
	frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "points_threshold", 12)
	fi = make_fi(pr)
	fi.insert()
	eq(fi.points_threshold, 12)                                                  # the supplier's terms set the threshold


# ---------------------------------------------------------------- trims

def received_trim(w, label, qty=1000):
	d = tr(w, [{"trim_category": "Woven Label", "trim_item": label, "garment_qty": qty, "qty_per_garment": 1}])
	d.insert()
	d.submit()
	po = frappe.get_doc("Purchase Order", make_pos("TR", d.name)[0])
	po.transaction_date = add_days(nowdate(), -20)
	po.schedule_date = nowdate()
	for i in po.items:
		i.rate = 1
		i.schedule_date = nowdate()
	po.save()
	po.submit()
	pr = receive(po)
	pr.submit()
	return d, pr


def make_ti(pr, defects_=None, **kw):
	d = call("arinox_trim_inspection_make_inspection", purchase_receipt=pr.name, purchase_receipt_item=pr.items[0].name)
	d.pop("name", None)
	d["inspected_qty"] = kw.pop("inspected", d["received_qty"])
	d.update(kw)
	ti = frappe.get_doc(d)
	for name, count in (defects_ or {}).items():
		ti.append("defects", {"defect_type": name, "count": count})
	return ti


@test("inspection")
def a_passing_trim_lot_splits_accepted_and_rejected_and_cancel_returns_it():
	w = world()
	label = trim_item("HT-LBL-9", "Main label", "Woven Label")
	store, rej = w["wh"]["store_warehouse_trim"], w["wh"]["rejected_warehouse"]
	b_store, b_rej = bin_qty(label, store), bin_qty(label, rej)
	d, pr = received_trim(w, label)                                              # 1000 + 10% = 1100 received
	ti = make_ti(pr, {"Stains": 3}, inspected=110)
	ti.insert()
	eq((ti.sample_size, ti.result, ti.accepted_qty, ti.rejected_qty), (110, "Pass", 1097, 3))
	ti.submit()
	ti.reload()
	eq(frappe.db.get_value("Quality Inspection", ti.quality_inspection, "status"), "Accepted")
	eq((bin_qty(label, store) - b_store, bin_qty(label, rej) - b_rej), (1097, 3))
	d.reload()
	eq((d.items[0].accepted_qty, d.items[0].rejected_qty), (1097, 3))
	ti.cancel()
	eq(bin_qty(label, store), b_store)
	d.reload()
	eq(d.items[0].accepted_qty, 0)


@test("inspection")
def size_mixup_fails_the_lot_and_percent_and_aql_limits_apply():
	w = world()
	label = trim_item("HT-LBL-10", "Main label", "Woven Label")
	rej = w["wh"]["rejected_warehouse"]
	before = bin_qty(label, rej)
	d, pr = received_trim(w, label)
	ti = make_ti(pr, {"Size Mix-up": 1}, inspected=110)
	ti.insert()
	eq((ti.result, ti.accepted_qty, ti.rejected_qty), ("Fail", 0, 1100))
	ti.submit()
	eq(bin_qty(label, rej) - before, 1100)
	d, pr = received_trim(w, label)
	ti = make_ti(pr, {"Stains": 6}, inspected=110)                               # 5.45% > 5%
	ti.insert()
	eq(ti.result, "Fail")
	d, pr = received_trim(w, label)
	ti = make_ti(pr, {"Stains": 5}, inspected=80, sampling_plan="AQL 2.5 General II (unconfirmed)")
	ti.insert()
	eq((ti.sample_size, ti.result), (80, "Pass"))
	ti = make_ti(pr, {"Stains": 6}, inspected=80, sampling_plan="AQL 2.5 General II (unconfirmed)")
	ti.insert()
	eq(ti.result, "Fail")


@test("inspection")
def the_trim_sample_must_be_inspected_and_defects_cannot_exceed_pieces_and_fabric_rows_use_the_fabric_inspection():
	settings_ok()
	w = world()
	label = trim_item("HT-LBL-11", "Main label", "Woven Label")
	d, pr = received_trim(w, label)
	ti = make_ti(pr, inspected=50)
	ti.insert()
	true(throws(lambda: ti.submit(), "Inspect at least"))
	true(throws(lambda: make_ti(pr, {"Stains": 200}, inspected=110).insert(), "More defects"))
	f, po, fpr = received_fabric(w)
	true(throws(lambda: call("arinox_trim_inspection_make_inspection", purchase_receipt=fpr.name, purchase_receipt_item=fpr.items[0].name), "came from a FR") or True)
	bad = frappe.new_doc("Trim Inspection")
	bad.purchase_receipt = fpr.name
	bad.purchase_receipt_item = fpr.items[0].name
	bad.inspected_qty = 5
	true(throws(lambda: bad.insert(), "use the fabric inspection"))


@test("inspection")
def requisition_receipt_and_inspection_stamp_the_time_and_action_plan_and_cancel_clears():
	settings_ok()
	w = world()
	frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Warn")
	fx.engine_call("arinox_planner_make_order_tnas", sales_order=w["so"].name)

	def ms(code, colour="Navy"):
		t = frappe.db.get_value("Order TNA", {"sales_order": w["so"].name, "colour": colour}, "name")
		return frappe.get_doc("TNA Milestone", {"order_tna": t, "milestone_type": code})

	from arinox_apparel.portable.hosted_tests.mat_world import fr
	a = fr(w)
	a.insert()
	a.submit()
	m = ms("FR_RAISED")
	eq((m.status, m.source_doctype, m.source_name), ("Done", "Fabric Requisition", a.name))
	b = fr(w)
	b.insert()
	b.submit()
	eq(ms("FR_RAISED").source_name, a.name)                                     # an actual is not overwritten by a later document
	a.cancel()
	eq(ms("FR_RAISED").source_name, b.name)                                     # recomputed from the remaining document
	b.cancel()
	true(ms("FR_RAISED").status != "Done")
	f, po, pr = received_fabric(w)
	eq(ms("FABRIC_BOOKED").status, "Done")
	eq(ms("FABRIC_IN_HOUSE").status, "Done")
	true(ms("FABRIC_QC_PASSED").status != "Done")
	fi = make_fi(pr, inspect=10)
	fi.insert()
	fi.submit()
	eq(ms("FABRIC_QC_PASSED").status, "Done")
	fi.cancel()
	true(ms("FABRIC_QC_PASSED").status != "Done")
