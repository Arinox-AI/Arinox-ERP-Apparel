import json

import frappe
from frappe.utils import nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, raises, test, true
from arinox_apparel.portable.hosted_tests.mat_world import call
from arinox_apparel.portable.hosted_tests.prod_world import card, navy_fabrics, order, setup, stage_total


def start(*route):
    w = setup()
    so = order()
    procs = [{"subcontract_process": p, "position": pos, "sequence": (i + 1) * 10, "item_state": "Garments"} for i, (p, pos) in enumerate(route)]
    c = card(so, navy_fabrics(w), processes=procs)
    return w, c, so


def post(c, stage, qty=100, colour="Navy", size="S", **kw):
    fx.engine(action="post", card=c.name, rows=json.dumps([dict(stage=stage, colour=colour, size=size, qty=qty, **kw)]), source_doctype="Production Adjustment",
              source_name="HT-E-%s-%s%s" % (stage, colour, size), posting_date=nowdate(), check="0")


def seed_sewn(c, qty=100):
    for stage in ("CUT", "SEW_IN", "SEW_OUT"):
        post(c, stage, qty)


def supplier():
    if not frappe.db.exists("Supplier", "HT Wash House"):
        frappe.get_doc({"doctype": "Supplier", "supplier_name": "HT Wash House", "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert()
    return "HT Wash House"


def challan(c, qty=100, **kw):
    d = frappe.get_doc(dict({"doctype": "Subcontract Challan", "production_card": c.name, "supplier": supplier(), "subcontract_process": "Wash",
                             "rows": [{"colour": "Navy", "size": "S", "qty": qty, "unit_value": 10}]}, **kw))
    d.insert()
    d.submit()
    return d


def back(ch, good=90, vendor=4, factory=2, repair=0, **kw):
    d = frappe.get_doc(dict({"doctype": "Subcontract Return", "challan": ch.name, "rows": [{"colour": "Navy", "size": "S", "good_qty": good, "reject_vendor_qty": vendor,
                                                                                          "reject_factory_qty": factory, "accepted_for_repair": repair}]}, **kw))
    d.insert()
    d.submit()
    return d


@test("subcontract")
def a_round_trip_posts_the_ledger_and_the_challan_status_follows_the_returns():
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    true(ch.name.startswith(so.apparel_sales_contract or so.name) or "-SC-" in ch.name, ch.name)
    eq(stage_total(c, "SC_OUT", "Navy", "S"), 100)
    true(ch.expected_return_date, "the due date counts working days")
    back(ch, good=60, vendor=0, factory=0)
    ch.reload()
    eq((ch.status, ch.returned_qty), ("Partly Returned", 60))
    back(ch, good=30, vendor=4, factory=6)
    ch.reload()
    eq((ch.status, ch.returned_qty), ("Returned", 100))
    eq((stage_total(c, "SC_BACK_GOOD", "Navy", "S"), stage_total(c, "SC_BACK_REJECT_VENDOR", "Navy", "S")), (90, 4))


@test("subcontract")
def limits_repair_cancel_and_short_close():
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c, 50)
    raises(lambda: challan(c, qty=60), "")                                      # cannot send more than sewn
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    raises(lambda: back(ch, good=100, vendor=1, factory=0), "only 100 were sent")
    raises(lambda: back(ch, good=90, vendor=4, factory=2, repair=3), "only factory-fault pieces")
    ret = back(ch)
    raises(lambda: ch.cancel(), "Cancel the returns")
    ret.cancel()
    ch.reload()
    eq(ch.status, "Open")
    ch.cancel()
    eq(stage_total(c, "SC_OUT", "Navy", "S"), 0)
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    raises(lambda: call("arinox_subcontract_challan_short_close", challan=ch.name, reason="  "), "Write the reason")
    call("arinox_subcontract_challan_short_close", challan=ch.name, reason="Vendor lost 10 pieces")
    eq(frappe.db.get_value("Subcontract Challan", ch.name, "status"), "Short Closed")
    ch.reload()
    raises(lambda: back(ch), "short-closed")


@test("subcontract")
def settlement_penalty_payable_and_one_per_challan_and_invoices():
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    back(ch, good=90, vendor=4, factory=2)
    st = frappe.get_doc({"doctype": "Subcontract Settlement", "challan": ch.name, "rate": 2, "invoiced_qty": 100})
    st.insert()
    # 4 of 100 (4 %) vendor-damaged is above the 1 % limit: all four are penalised at the 10 unit value; 92 pieces are payable
    eq((st.short_qty, st.penalty_qty, st.penalty_amount, st.payable_qty), (4, 4, 40, 92))
    eq((st.gross_amount, st.net_amount), (184, 144))
    true(st.variance_note, "the vendor invoices 100, we owe 92")
    norate = frappe.get_doc({"doctype": "Subcontract Settlement", "challan": ch.name})
    st.submit()
    raises(lambda: frappe.get_doc({"doctype": "Subcontract Settlement", "challan": ch.name, "rate": 2}).insert(), "already has a settlement")
    item = frappe.db.get_value("Subcontract Process", "Wash", "service_item")
    if not item:
        raises(lambda: call("arinox_subcontract_settlement_make_invoices", settlement=st.name), "Set the Service Item")
    else:
        res = call("arinox_subcontract_settlement_make_invoices", settlement=st.name)
        true(res["purchase_invoice"] and res["debit_note"], res)


@test("subcontract")
def finishing_takes_only_what_came_back_from_the_wash():
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    back(ch, good=90, vendor=4, factory=2)

    def fr(q):
        return frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "source": "Subcontract Return", "supplier": supplier(), "rows": [{"colour": "Navy", "size": "S", "qty": q}]})
    bad = fr(91)
    bad.insert()
    raises(lambda: bad.submit(), "")
    ok = fr(90)
    ok.insert()
    ok.submit()
    true("-FIN-" in ok.name, ok.name)
    eq(stage_total(c, "FIN_IN", "Navy", "S"), 90)
    ok.cancel()
    eq(stage_total(c, "FIN_IN", "Navy", "S"), 0)


@test("subcontract")
def a_ledger_rebuild_reproduces_what_the_documents_posted():
    w, c, so = start(("Wash", "After Sewing"))
    seed_sewn(c)
    ch = challan(c)
    back(ch, good=90, vendor=4, factory=2)
    fr = frappe.get_doc({"doctype": "Finishing Receipt", "production_card": c.name, "source": "Subcontract Return", "supplier": supplier(), "receipt_date": nowdate(), "rows": [{"colour": "Navy", "size": "S", "qty": 60}]})
    fr.insert()
    fr.submit()
    keys = ["SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_IN"]       # the seeded CUT / SEW rows are not documents, so a rebuild drops them
    before = {k: stage_total(c, k, "Navy", "S") for k in keys}
    n = call("arinox_ledger_rebuild_movements", card=c.name)
    eq(n, 5)
    eq({k: stage_total(c, k, "Navy", "S") for k in keys}, before)
    floor = fx.user("ht_floor@example.com", ["Apparel Production User"])
    try:
        frappe.set_user(floor)
        raises(lambda: call("arinox_ledger_rebuild_movements", card=c.name), "Only a System Manager")
    finally:
        frappe.set_user("Administrator")
