import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, throws, true
from arinox_apparel.portable.hosted_tests.mat_world import call
from arinox_apparel.portable.hosted_tests.test_contract import contract
from arinox_apparel.portable.hosted_tests.test_invoicing import prepare, shipped_note


def ready():
    """A finished card, a submitted Packing List and its Final Inspection (accepted), and a Shipment carrying the list."""
    card = fx.finished_card(100)
    pl = fx.packing_list(card, pcs_per_carton=24)
    fx.inspect_lot(card, pl, "Accepted")
    sh = fx.shipment([], apparel_packing_lists=[{"packing_list": pl.name}])
    pl.reload()
    return card, pl, sh


@test("shipment")
def a_shipment_fills_itself_from_the_packing_list_and_removing_the_list_frees_it():
    card, pl, sh = ready()
    eq(sh.apparel_contracts, card.sales_contract or card.sales_order)
    true(abs(sh.apparel_declared_cbm - pl.total_cbm) < 0.000001 and abs(sh.apparel_declared_gross_kg - pl.total_gross_kg) < 0.001)
    eq(sum(p.count for p in sh.shipment_parcel), pl.total_cartons)
    true(sh.value_of_goods > 0)
    eq((pl.shipment, pl.status), (sh.name, "On Shipment"))
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_ship_status"), "Booked")
    avail = call("arinox_shipment_get_available_packing_lists")
    true(pl.name not in [r["name"] for r in avail], "a list on a shipment is not available")
    sh.set("apparel_packing_lists", [])
    sh.save()
    pl.reload()
    eq((pl.shipment, pl.status), (None, "Open"))
    true(pl.name in [r["name"] for r in call("arinox_shipment_get_available_packing_lists", customer=fx.customer())])


@test("shipment")
def a_list_cannot_be_on_two_shipments_or_taken_off_once_shipped_and_air_needs_a_reason_and_measures_are_noted():
    card, pl, sh = ready()
    raises(lambda: fx.shipment([], apparel_packing_lists=[{"packing_list": pl.name}]), "already on shipment")
    sh.apparel_carrier_cbm = round(sh.apparel_declared_cbm * 1.2, 6)
    sh.apparel_carrier_gross_kg = sh.apparel_declared_gross_kg
    sh.save()
    true("Carrier CBM" in sh.apparel_measure_note and "weight" not in sh.apparel_measure_note.lower(), sh.apparel_measure_note)
    true(abs(sh.apparel_declared_cbm - pl.total_cbm) < 0.000001, "declared figures are not overwritten")
    if sh.apparel_contracts and frappe.db.exists("Sales Contract", sh.apparel_contracts.splitlines()[0]):
        frappe.db.set_value("Sales Contract", sh.apparel_contracts.splitlines()[0], "shipment_mode", "Sea", update_modified=False)
        sh.apparel_mode = "Air"
        raises(lambda: sh.save(), "contract is for sea freight")
        sh = frappe.get_doc("Shipment", sh.name)
        sh.apparel_mode = "Air"
        sh.apparel_reason_for_air = "Late fabric"
        sh.apparel_air_cost_borne_by = "Factory"
        sh.save()


@test("shipment")
def delivery_notes_are_made_per_order_tied_to_the_list_and_status_and_stamps_follow():
    card, pl, sh = ready()
    made = call("arinox_shipment_make_delivery_notes", shipment=sh.name)
    eq(len(made), 1)
    dn = frappe.get_doc("Delivery Note", made[0])
    eq(sum(i.qty for i in dn.items), pl.total_pieces)
    true(all(i.apparel_packing_list == pl.name for i in dn.items))
    eq(dn.apparel_shipment, sh.name)
    raises(lambda: call("arinox_shipment_make_delivery_notes", shipment=sh.name), "already has a delivery note")
    frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", 20)
    dn.submit()
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_ship_status"), "Cargo Handed Over")
    eq(frappe.db.get_value("Packing List", pl.name, "status"), "Shipped")
    sh.reload()
    sh.set("apparel_packing_lists", [])
    raises(lambda: sh.save(), "cannot be taken off the shipment")
    sh = frappe.get_doc("Shipment", sh.name)
    sh.apparel_on_board_date = nowdate()
    sh.save()
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_ship_status"), "On Board")
    dn.cancel()
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_ship_status"), "On Board")      # a person's later date stands


def forwarder_bill(shipment, amount):
    if not frappe.db.exists("Supplier", "HT Forwarder"):
        frappe.get_doc({"doctype": "Supplier", "supplier_name": "HT Forwarder", "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert()
    if not frappe.db.exists("Item", "HT-FREIGHT"):
        frappe.get_doc({"doctype": "Item", "item_code": "HT-FREIGHT", "item_name": "Freight", "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
                        "stock_uom": "Nos", "is_stock_item": 0}).insert()
    pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": fx.company(), "supplier": "HT Forwarder", "apparel_shipment": shipment, "bill_no": "HT-" + frappe.generate_hash(length=5),
                         "items": [{"item_code": "HT-FREIGHT", "qty": 1, "rate": amount}]})
    pi.insert()
    return pi


@test("shipment")
def forwarder_bills_add_up_on_the_shipment_and_the_cost_is_shared_by_cbm():
    card, pl, sh = ready()
    pi = forwarder_bill(sh.name, 1100)
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_actual_total"), 1100)
    pi2 = forwarder_bill(sh.name, 400)
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_actual_total"), 1500)
    res = call("arinox_freight_allocated_costs", shipment=sh.name)
    eq((res["basis"], res["cost"], len(res["rows"])), ("cbm", 1500, 1))
    eq((res["rows"][0][1], res["rows"][0][2]), (1.0, 1500))
    pi2.apparel_shipment = None             # moved off this shipment: both are refreshed
    pi2.save()
    eq(frappe.db.get_value("Shipment", sh.name, "apparel_actual_total"), 1100)


def invoiced(with_contract=None):
    card, pl, dn = shipped_note(with_contract=with_contract)
    sh = fx.shipment([dn])
    prepare(sh)
    done = call("arinox_invoicing_submit_invoices", shipment=sh.name)
    return card, sh, frappe.get_doc("Sales Invoice", done[0])


@test("shipment")
def a_claim_is_capped_windowed_numbered_and_settled_by_credit_note():
    card, sh, si = invoiced()
    claim = frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Quality", "claimed_amount": 5000, "rows": [{"colour": "Navy", "size": "S", "pieces": 10}]})
    claim.insert()
    true("-CL-" in claim.name, claim.name)
    eq(claim.sales_contract, si.apparel_sales_contract)
    true(abs(claim.cap_amount - round(si.net_total / si.total_qty * 10, 2)) < 0.01, claim.cap_amount)
    true("Open claim" in (frappe.db.get_value("Sales Invoice", si.name, "apparel_dispute_reason") or ""), "no reminders while it is open")
    claim.status = "Accepted"
    claim.accepted_amount = claim.cap_amount + 100
    claim.settlement = "Credit Note"
    raises(lambda: claim.submit(), "Write why this is accepted")                  # above the cap needs a written reason
    claim = frappe.get_doc("Buyer Claim", claim.name)
    claim.status = "Accepted"
    claim.accepted_amount = claim.cap_amount + 100
    claim.settlement = "Credit Note"
    claim.override_reason = "Buyer holds the full value; agreed by sales director"
    claim.save()
    claim.submit()
    true(not frappe.db.get_value("Sales Invoice", si.name, "apparel_dispute_reason"))
    cn = frappe.get_doc("Sales Invoice", call("arinox_buyer_claim_make_credit_note", claim=claim.name))
    eq((cn.docstatus, cn.is_return), (0, 1))
    true(abs(abs(cn.net_total) - claim.accepted_amount) < 0.01, (cn.net_total, claim.accepted_amount))
    eq(call("arinox_buyer_claim_make_credit_note", claim=claim.name), cn.name)       # asking again does not draft a second one


@test("shipment")
def a_late_claim_an_undecided_claim_and_a_claim_with_no_amount_are_refused():
    sc = contract(300).insert()
    frappe.db.set_value("Sales Contract", sc.name, {"quality_claim_days": 60, "quantity_claim_days": 30}, update_modified=False)
    card, sh, si = invoiced(with_contract=sc.name)
    claim = frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Chargeback", "claimed_amount": 200})
    claim.insert()
    raises(lambda: claim.submit(), "Decide the claim")
    raises(lambda: frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Chargeback", "claimed_amount": 0}).insert(), "amount claimed")
    raises(lambda: frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Quality", "claimed_amount": 10, "rows": [{"colour": "Navy", "size": "S", "pieces": 0}]}).insert(), "enter the pieces")
    # a quality claim made long after arrival is outside the 60-day window
    frappe.db.set_value("Shipment", sh.name, "apparel_arrival_date", add_days(nowdate(), -90), update_modified=False)
    frappe.db.set_value("Sales Invoice", si.name, "apparel_shipment", sh.name, update_modified=False)
    late = frappe.get_doc({"doctype": "Buyer Claim", "sales_invoice": si.name, "claim_type": "Quality", "claimed_amount": 50, "rows": [{"colour": "Navy", "size": "S", "pieces": 1}]})
    late.insert()
    true("after arrival" in late.window_note, late.window_note)
    late.status = "Accepted"
    late.accepted_amount = 10
    late.settlement = "Credit Note"
    raises(lambda: late.submit(), "Write why this is accepted")


@test("shipment")
def commercial_close_waits_for_payment_and_the_checklist_reads_the_chain():
    card, sh, si = invoiced()
    rows = {r["label"]: r for r in call("arinox_close_get_checklist", sales_order=card.sales_order)}
    true(rows["Everything shipped is invoiced"]["ok"], rows)
    true(not rows["Customer invoices paid"]["ok"] and si.name in rows["Customer invoices paid"]["detail"], rows["Customer invoices paid"])
    raises(lambda: call("arinox_close_commercial_close", sales_order=card.sales_order), "Customer invoices paid")
