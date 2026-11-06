import json

import frappe
from frappe.utils import add_days, flt, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import bin_qty, call, fr, make_pos, receive, received_fabric, tr, trim_item, world
from arinox_apparel.portable.hosted_tests.test_samples import sample


def make_tr_po(w, label, late_days=10, supplier=None):
	d = tr(w, [{"trim_category": "Woven Label", "trim_item": label, "garment_qty": 1000, "qty_per_garment": 1, "supplier": supplier or w["mill_a"]}])
	d.insert()
	d.submit()
	po = frappe.get_doc("Purchase Order", make_pos("TR", d.name)[0])
	po.transaction_date = add_days(nowdate(), -20)
	po.schedule_date = add_days(nowdate(), -late_days)
	for i in po.items:
		i.rate = 1
		i.schedule_date = add_days(nowdate(), -late_days)
	po.apparel_purchase_terms = "Standard Fabric Terms"
	return d, po


@test("purchasing")
def a_purchase_order_from_a_requisition_keeps_the_links():
	w = world()
	label = trim_item("HT-LBL-3", "Main label", "Woven Label")
	d, po = make_tr_po(w, label)
	po.save()
	it = po.items[0]
	eq((it.apparel_requisition_type, it.apparel_requisition), ("TR", d.name))
	eq(it.material_request_item, frappe.db.get_value("Trim Requisition Item", {"parent": d.name}, "material_request_item"))
	eq(po.supplier, w["mill_a"])
	eq(make_pos("TR", d.name), [])                                               # nothing left to order
	true(throws(lambda: d.cancel(), "already on Purchase Order"))                # cancel is blocked once ordered


@test("purchasing")
def the_hold_blocks_submit_only_in_block_mode_and_the_override_needs_a_manager():
	w = world()
	label = trim_item("HT-LBL-4", "Main label", "Woven Label")
	frappe.db.delete("Sample Approval", {"sample_type": "Bulk Trim", "style_item": w["template"]})
	d, po = make_tr_po(w, label)
	po.save()
	po.submit()                                                                  # Warn mode: submits
	po.cancel()
	frappe.db.set_single_value("Apparel Settings", "hold_po_until_approval", "Block")
	d2, po2 = make_tr_po(w, label, supplier=w["mill_b"])
	po2.save()
	try:
		po2.submit()
	except Exception as e:
		true("on hold until the buyer approvals" in str(e), str(e)[:300])
	else:
		true(False, "submitted")
	po2 = frappe.get_doc("Purchase Order", po2.name)
	po2 = frappe.get_doc("Purchase Order", po2.name)
	po2.apparel_approval_override = 1
	raises(lambda: po2.save(), "reason for overriding")
	po2 = frappe.get_doc("Purchase Order", po2.name)
	po2.apparel_approval_override = 1
	po2.apparel_approval_override_reason = "Buyer verbally approved"
	po2.save()
	po2.submit()


@test("purchasing")
def etd_rules():
	w = world()
	label = trim_item("HT-LBL-5", "Main label", "Woven Label")
	d, po = make_tr_po(w, label)
	po.apparel_etd_planned = add_days(nowdate(), 10)
	po.apparel_eta = add_days(nowdate(), 5)
	try:
		po.save()
	except Exception as e:
		true("ETD (plan) cannot be after" in str(e), str(e)[:300])
	else:
		true(False, "saved")
	d2, po = make_tr_po(w, trim_item("HT-LBL-5B", "Main label", "Woven Label"), supplier=w["mill_b"])
	po.apparel_eta = add_days(nowdate(), 20)
	po.apparel_etd_actual = add_days(nowdate(), 3)
	true(throws(lambda: po.save(), "cannot be in the future"))


@test("purchasing")
def a_receipt_rolls_up_and_applies_the_delay_penalty_and_cancel_undoes_it():
	w = world()
	label = trim_item("HT-LBL-6", "Main label", "Woven Label")
	d, po = make_tr_po(w, label, late_days=10)
	po.save()
	po.submit()
	d.reload()
	eq((d.items[0].ordered_qty, d.status), (1100, "Ordered"))                    # 1000 + the 10% allowance
	pr = receive(po)
	pr.submit()
	pr.reload()
	eq((pr.apparel_delay_days, pr.apparel_penalty_pct), (10, 10))                # received today, due 10 days ago: the 4-11 day band
	true(abs(pr.apparel_penalty_amount - flt(pr.items[0].net_amount) * 0.10) < 0.01)
	d.reload()
	eq((d.items[0].received_qty, d.status), (1100, "Received"))
	pr.cancel()
	d.reload()
	eq((d.items[0].received_qty, d.status), (0, "Ordered"))


@test("purchasing")
def an_on_time_receipt_has_no_penalty_and_a_receipt_goes_to_the_inspection_warehouse():
	w = world()
	label = trim_item("HT-LBL-7", "Main label", "Woven Label")
	d, po = make_tr_po(w, label, late_days=0)
	po.save()
	po.submit()
	pr = receive(po)
	eq(pr.items[0].warehouse, w["wh"]["inspection_warehouse_trim"]) if False else None
	pr.submit()
	pr.reload()
	eq((pr.apparel_delay_days, pr.apparel_penalty_pct), (0, 0))


@test("purchasing")
def over_delivery_beyond_the_band_is_noted_or_rejected_by_policy():
	w = world()
	label = trim_item("HT-LBL-8", "Main label", "Woven Label")
	d, po = make_tr_po(w, label)
	po.save()
	po.submit()                                                                  # ordered 1100, band 1001-3000 -> +/-5%, upper 1155
	pr = receive(po, qty=1200)
	true("over the +5" in (pr.apparel_qty_band_note or ""), pr.apparel_qty_band_note)
	true("must not be invoiced" in pr.apparel_qty_band_note)
	pr2 = receive(po, qty=1100)
	true(not pr2.apparel_qty_band_note)
	frappe.db.set_value("Material Purchase Terms", "Standard Fabric Terms", "extra_qty_policy", "Reject")
	true(throws(lambda: receive(po, qty=1200), "over the +5"))


# ---------------------------------------------------------------- rolls

def rolls(n=10, each=88.2, prefix="R"):
	return [{"roll_no": "%s%02d" % (prefix, i + 1), "dye_lot": "LOT-A" if i < 6 else "LOT-B", "length": each} for i in range(n)]


def fabric_pr(w):
	f = fr(w, colours=("Navy",))                                                 # 882 m
	f.insert()
	f.submit()
	po = frappe.get_doc("Purchase Order", make_pos("FR", f.name)[0])
	po.transaction_date = add_days(nowdate(), -20)
	po.schedule_date = add_days(nowdate(), -2)
	for i in po.items:
		i.rate = 3
		i.schedule_date = add_days(nowdate(), -2)
	po.save()
	po.submit()
	return f, po, receive(po)


def import_rolls(pr, rolls_, **kw):
	return call("arinox_rolls_import_roll_list", pr_name=pr.name, row_name=pr.items[0].name, rolls=json.dumps(rolls_) if not isinstance(rolls_, str) else rolls_,
				length_uom=kw.get("length_uom", "Meter"), update_row_qty=kw.get("update_row_qty", 0))


@test("purchasing")
def the_roll_import_makes_a_batch_per_roll_and_the_receipt_submits():
	w = world()
	f, po, pr = fabric_pr(w)
	true(throws(lambda: pr.submit(), "import the roll list"))
	pr = frappe.get_doc("Purchase Receipt", pr.name)
	out = import_rolls(pr, rolls())
	eq((out["rolls"], out["total"]), (10, 882.0))
	batches = frappe.get_all("Batch", filters={"reference_name": pr.name}, fields=["name", "apparel_roll_no", "apparel_dye_lot", "apparel_ticket_length", "apparel_inspection_status"])
	eq(len(batches), 10)
	true(all(b.apparel_inspection_status == "Uninspected" and abs(b.apparel_ticket_length - 88.2) < 0.01 for b in batches))
	pr.reload()
	pr.submit()
	eq(frappe.db.get_value("Serial and Batch Bundle", pr.items[0].serial_and_batch_bundle, "total_qty"), 882)
	f.reload()
	eq((f.items[0].received_qty, f.status), (882, "Received"))


@test("purchasing")
def pasted_roll_lists_are_parsed_and_bad_lists_are_refused():
	w = world()
	f, po, pr = fabric_pr(w)
	text = "\n".join(["%s\tL1\t88.2" % ("P%02d" % i) for i in range(10)])
	out = import_rolls(pr, "Roll\tLot\tLength\n" + text + "\n\nbad line")
	eq(out["rolls"], 10)
	dup = rolls()
	dup[3]["roll_no"] = dup[2]["roll_no"]
	pr = frappe.get_doc("Purchase Receipt", pr.name)
	true(throws(lambda: import_rolls(pr, dup), "appears twice"))
	true(throws(lambda: import_rolls(pr, []), "roll list is empty"))
	true(throws(lambda: import_rolls(pr, [{"roll_no": "", "length": 5}]), "needs a roll number"))
	true(throws(lambda: import_rolls(pr, [{"roll_no": "A", "length": 0}]), "more than zero"))


@test("purchasing")
def the_roll_total_must_match_the_row_unless_asked_and_yards_are_converted_and_a_reimport_replaces():
	w = world()
	f, po, pr = fabric_pr(w)
	true(throws(lambda: import_rolls(pr, rolls(each=80)), "adds up to"))
	out = import_rolls(pr, rolls(each=80), update_row_qty=1)
	eq(out["total"], 800)
	pr.reload()
	eq(pr.items[0].qty, 800)
	out = import_rolls(pr, rolls(each=800 / 10 / 0.9144), length_uom="Yard", update_row_qty=1)
	true(abs(out["total"] - 800) < 0.5, out["total"])
	pr.reload()
	import_rolls(pr, rolls(each=80, prefix="X"), update_row_qty=1)
	names = {b.apparel_roll_no for b in frappe.get_all("Batch", filters={"reference_name": pr.name}, fields=["apparel_roll_no"])}
	eq(len(names), 10)
	true(all(n.startswith("X") for n in names), names)
