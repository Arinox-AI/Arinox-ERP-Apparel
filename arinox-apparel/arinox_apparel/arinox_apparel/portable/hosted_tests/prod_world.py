"""Fixtures for the production-floor tests: an order by colour and size, an issued Production Card with fabrics, the fabric store and Cutting WIP warehouses, and rolls."""
import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.mat_world import call, fabric_items, warehouses

_roll = {"n": 0}


def setup():
    """Settings and warehouses (idempotent); returns {store, wip, navy_fabric, black_fabric}."""
    wh = warehouses()
    wip = frappe.db.get_value("Warehouse", {"warehouse_name": "HT Cutting WIP", "company": fx.company()}, "name")
    if not wip:
        wip = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "HT Cutting WIP", "company": fx.company()}).insert().name
    frappe.db.set_single_value("Apparel Settings", "cutting_wip_warehouse", wip)
    frappe.db.set_single_value("Apparel Settings", "require_pp_meeting", 0)
    frappe.db.set_single_value("Apparel Settings", "enforce_bulk_gate", 1)
    frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
    frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
    nf, bf = fabric_items()
    return {"store": wh["store_warehouse_fabric"], "wip": wip, "navy_fabric": nf, "black_fabric": bf}


def order(extra=None):
    cells = {("Navy", "S"): 200, ("Navy", "M"): 300, ("Navy", "L"): 200, ("Black", "S"): 150, ("Black", "M"): 200, ("Black", "L"): 150}
    cells.update(extra or {})
    return fx.colour_so(cells)


def card(so, fabrics, **kw):
    """An issued Production Card (all sizes of both colours) with the given fabric rows."""
    lines = []
    for r in frappe.get_all("Sales Order Item", filters={"parent": so.name}, fields=["apparel_colour", "apparel_size"]):
        lines.append({"colour": r.apparel_colour, "size": r.apparel_size})
    d = {"doctype": "Production Card", "company": fx.company(), "customer": fx.customer(), "sales_order": so.name, "style_item": fx.item(), "lines": lines, "fabrics": fabrics}
    d.update(kw)
    c = frappe.get_doc(d)
    c.insert()
    c.submit()
    return c


def navy_fabrics(w):
    return [{"colour": "Navy", "fabric_item": w["navy_fabric"], "consumption": 1.2, "consumption_uom": "Meter", "consumption_source": "Manual"}]


def make_roll(w, length, shade="A", width=132, status="Accepted", warehouse=None, item=None, dye_lot="L1"):
    _roll["n"] += 1
    item = item or w["navy_fabric"]
    bid = "HT-R%s-%s" % (_roll["n"], frappe.generate_hash(length=4))
    b = frappe.get_doc({"doctype": "Batch", "batch_id": bid, "item": item}).insert(ignore_permissions=True)
    frappe.db.set_value("Batch", b.name, {"apparel_roll_no": str(_roll["n"]), "apparel_shade_band": shade, "apparel_width_cm": width, "apparel_inspection_status": status,
                                          "apparel_dye_lot": dye_lot, "apparel_actual_length": length})
    se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt", "company": fx.company(),
                         "items": [{"item_code": item, "qty": length, "t_warehouse": warehouse or w["wip"], "batch_no": b.name, "use_serial_batch_fields": 1, "basic_rate": 1}]})
    se.insert(ignore_permissions=True)
    se.submit()
    return b.name


def rolls_for(w, plies=105, per_roll=35, **kw):
    return [(make_roll(w, per_roll * 8.4 + 6, **kw), per_roll) for _ in range(plies // per_roll)]


def plan(w, c, plies=105, ratios=(("S", 2), ("M", 3), ("L", 2)), marker=8.4, shade="A", **kw):
    d = {"doctype": "Cut Plan", "production_card": c.name, "colour": "Navy", "fabric_item": w["navy_fabric"],
         "lays": [{"lay_no": 1, "marker_ref": "M1", "marker_length_m": marker, "planned_plies": plies, "shade_band": shade}],
         "ratios": [{"lay_no": 1, "size": s, "ratio": r} for s, r in ratios]}
    d.update(kw)
    p = frappe.get_doc(d)
    p.insert()
    return p


def lay(w, c, rolls, sizes=(("S", 2), ("M", 3), ("L", 2)), submit=False, **kw):
    d = {"doctype": "Lay Report", "production_card": c.name, "colour": "Navy", "fabric_item": w["navy_fabric"], "lay_no": 1, "marker_length_m": 8.4, "lay_date": nowdate(),
         "gate_override": 1, "gate_override_reason": "test", "rolls": [{"batch": b, "plies": p} for b, p in rolls], "sizes": [{"size": s, "ratio": r} for s, r in sizes]}
    d.update(kw)
    doc = frappe.get_doc(d)
    doc.insert()
    if submit:
        doc.submit()
    return doc


def totals(c):
    return fx.engine(action="totals", card=c.name)["arinox_result"]


def stage_total(c, stage, colour, size, purpose=None):
    return fx.engine(action="total", card=c.name, stage=stage, colour=colour, size=size, purpose=purpose or "")["arinox_total"]
