"""Order page step 9, Ship (ORDER_TO_SHIP_PLAN section 4): the shipment wizard. Pick the packing lists, create the Shipment, make the Delivery Notes (a risky
class: approval), record the booking, bill of lading and tracking. Today's "Ship & track" of the Deal page (the four clocks, the papers, the Incoterm,
`ship_track.py`) lives in this step now; the Deal's step 7 is a link here.

Same rules as the other steps: reads run the vendored scripts in record mode; every write goes through ``deals._ex`` (pipeline, preview first). The Shipment is
inserted with the packing lists on it; the ERP fills it from them (contracts, parcels, value). Submitting a Delivery Note or a Shipment posts the ledger: risky.
"""

from __future__ import annotations

import json
from typing import Callable

import deals
import guardrails
import order_flow
import ship_track
from order_cutsew import _num
from order_pack import need_dt, PASS
from order_samples import read_script
import deal_api

guarded = deal_api.guarded
MODES = ("Sea LCL", "Sea FCL", "Air", "Courier", "Road")
SUBMITTABLE = ("Delivery Note", "Shipment")


def stage_of(sh: dict, dns: list[dict]) -> dict:
    """Where one shipment stands in the wizard, from its own facts. Pure. Stages: `picked` (lists on it, no delivery note), `dn_draft` (notes made, not all submitted),
    `dn_done` (every note submitted, not yet on board), `on_board` (the on-board date is recorded or the ERP says so). `next` is the sentence for the button."""
    live = [d for d in dns if int(d.get("docstatus") or 0) != 2]
    subm = [d for d in live if int(d.get("docstatus") or 0) == 1]
    onb = bool(sh.get("apparel_on_board_date") or sh.get("on_board")) or (sh.get("apparel_ship_status") or sh.get("ship_status")) in ("On Board", "Arrived", "Delivered", "Closed")
    if onb and subm:
        return {"key": "on_board", "next": "On board. Record the arrival and the delivery as they happen."}
    if not live:
        return {"key": "picked", "next": "Make the delivery notes (a manager approves it)."}
    if len(subm) < len(live):
        return {"key": "dn_draft", "next": f"Submit the {len(live) - len(subm)} draft delivery note(s) (a manager approves each)."}
    return {"key": "dn_done", "next": "Record the booking, the bill of lading and the on-board date."}


def _view(be, name: str, me) -> dict:
    doc = be.get_doc("Shipment", name)
    v = ship_track.shipment_view(doc)
    pls = [r.get("packing_list") for r in (doc.get("apparel_packing_lists") or []) if r.get("packing_list")]
    dns = []
    for r in doc.get("shipment_delivery_note") or []:
        dn = r.get("delivery_note")
        if dn:
            row = (be.get_list("Delivery Note", [["name", "=", dn]], ["name", "docstatus", "status", "posting_date", "customer"], limit=1) or [{"name": dn}])[0]
            dns.append(row)
    st = stage_of(doc, dns)
    freight = None
    try:
        f = read_script(me, "arinox_freight_allocated_costs", {"shipment": name}) or {}
        freight = {"basis": f.get("basis"), "cost": f.get("cost"), "rows": f.get("rows") or []}
    except Exception:                                       # noqa: BLE001 - freight is advice; the wizard never fails for it
        freight = None
    live = [d for d in dns if int(d.get("docstatus") or 0) != 2]
    return {**v, "docstatus": int(doc.get("docstatus") or 0), "packing_lists": pls, "delivery_notes": dns, "stage": st, "freight": freight, "modified": doc.get("modified"),
            "can_make_dns": int(doc.get("docstatus") or 0) != 2 and bool(pls) and not live, "can_submit": int(doc.get("docstatus") or 0) == 0 and bool(live) and all(int(d.get("docstatus") or 0) == 1 for d in live)}


def _deal_id(db, chain: list[str]) -> int:
    """The Deal this order came from, if the tower has one (an order made straight in the ERP has none)."""
    from models_deal import DealModel
    for d in db.query(DealModel).order_by(DealModel.id.desc()).limit(2000).all():
        refs = d.refs_dict()
        if refs.get("sales_order") in chain:
            return int(d.id)
    return 0


@guarded
def order_ship_get(db, me, sales_order: str = "", **_):
    """Everything the step-9 wizard shows for one order: the **packing lists waiting for a shipment** (submitted, not on one, with the state of their final
    inspection), the shipments of the order with where each stands (lists picked, delivery notes made, delivery notes submitted, on board), their delivery
    notes, the booking / bill of lading / tracking facts, the freight shared over the orders on board, and the `deal_id` of the Deal this order came from (the
    shipping clocks and papers of `deal_track` belong to this step). Read only. Params: `sales_order`.
    Returns `{ok, head, deal_id, available, shipments, summary, can_write}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Shipment", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    pls = be.get_list("Packing List", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["name", "shipment", "docstatus"], limit=300)
    names = sorted({p["shipment"] for p in pls if p.get("shipment")})
    avail = []
    try:
        for r in read_script(me, "arinox_shipment_get_available_packing_lists", {}) or []:
            if r.get("sales_order") in chain:
                avail.append({"name": r["name"], "total_cartons": r.get("total_cartons"), "total_pieces": r.get("total_pieces"), "total_gross_kg": r.get("total_gross_kg"), "total_cbm": r.get("total_cbm"),
                              "customer": r.get("customer"), "ship_to": r.get("ship_to"), "buyer_po": r.get("buyer_po"), "final_inspection": r.get("final_inspection"),
                              "inspection_result": r.get("inspection_result"), "ready": r.get("inspection_result") in PASS})
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": deals._strip_html(str(getattr(e, "message", None) or e))[:300]}
    ships = [_view(be, n, me) for n in names]
    on_board = [s for s in ships if s["stage"]["key"] == "on_board"]
    return {"ok": True, "head": head, "deal_id": _deal_id(db, chain), "available": avail, "shipments": ships, "can_write": guardrails.can(me["roles"], "Shipment", "write"),
            "summary": {"waiting_lists": len(avail), "shipments": len(ships), "on_board": len(on_board), "delivery_notes_submitted": sum(1 for s in ships for d in s["delivery_notes"] if int(d.get("docstatus") or 0) == 1),
                        "done": bool(on_board)}}


def _risky(res: dict, what: str) -> dict:
    """The answer of a pipeline call that may need approval: `needs_approval` is passed up with the approval id, a refusal becomes one plain sentence."""
    if res.get("needs_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": res.get("approval_id"), "error": res.get("error"), "preview": res.get("preview")}
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or f"The ERP refused {what}.")), "preview": res.get("preview")}
    return res


@guarded
def order_shipment_create(db, me, sales_order: str = "", packing_lists: list | None = None, mode: str = "Sea FCL", preview: bool = False, **_):
    """Create the Shipment (a draft) from the picked packing lists: they must be submitted, not on another shipment, belong to this order, have an accepted
    final inspection and be for one customer. The ERP fills the contracts, parcels, weight, volume and value from the lists. With `preview` nothing is
    written. Params: `sales_order`, `packing_lists`, `mode` (Sea LCL, Sea FCL, Air, Courier, Road), `preview`. Returns `{ok, name}`."""
    need_dt(me, "Shipment", "create a shipment")
    lists = [x for x in (packing_lists or []) if x]
    if not sales_order or not lists:
        return {"ok": False, "error": "Pick at least one packing list."}
    if mode not in MODES:
        return {"ok": False, "error": "Mode is " + ", ".join(MODES) + "."}
    if len(set(lists)) != len(lists):
        return {"ok": False, "error": "A packing list is picked twice."}
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    have = {r["name"]: r for r in read_script(me, "arinox_shipment_get_available_packing_lists", {}) or []}
    for n in lists:
        r = have.get(n)
        if not r:
            return {"ok": False, "error": f"Packing list {n} is not available: it must be submitted and not already on a shipment."}
        if r.get("sales_order") not in chain:
            return {"ok": False, "error": f"Packing list {n} belongs to another order."}
        if r.get("inspection_result") not in PASS:
            return {"ok": False, "error": f"Packing list {n} has no accepted final inspection."}
    if len({have[n].get("customer") for n in lists}) > 1:
        return {"ok": False, "error": "A shipment goes to one customer: pick the packing lists of one customer."}
    o = be.get_doc("Sales Order", head)
    data = {"pickup_from_type": "Company", "pickup_company": o.get("company"), "delivery_to_type": "Customer", "delivery_customer": o.get("customer"),
            "description_of_content": "Garments", "apparel_mode": mode, "apparel_packing_lists": [{"packing_list": n} for n in lists]}
    res = deals._ex(db, me, {"op": "insert", "doctype": "Shipment", "data": data, "preview": bool(preview)})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the shipment.")), "preview": res.get("preview")}
    return {"ok": True, "name": (res.get("doc") or {}).get("name") or "", "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_ship_make_dns(db, me, shipment: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Make the draft Delivery Notes of a shipment, one per Sales Order on it, quantities exactly as packed (`arinox_shipment_make_delivery_notes`). A risky
    class: `needs_approval` until a manager approves; run it again with the `approval_id`. Params: `shipment`, `preview`, `approval_id`.
    Returns `{ok, made:[names]}` or `{ok: false, needs_approval: true, approval_id}`."""
    need_dt(me, "Delivery Note", "make delivery notes")
    if not shipment:
        return {"ok": False, "error": "Say which shipment."}
    res = _risky(deals._ex(db, me, {"op": "api", "method": "arinox_shipment_make_delivery_notes", "doctype": "Shipment", "preview": bool(preview), "approval_id": approval_id or None,
                                    "params": {"shipment": shipment}}), "the delivery notes")
    if not res.get("ok"):
        return res
    r = res.get("result")
    made = [x for x in (r if isinstance(r, list) else [r] if r else []) if isinstance(x, str)]
    return {"ok": True, "name": shipment, "made": made, "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_ship_submit(db, me, doctype: str = "", name: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Submit a Delivery Note or a Shipment of the order. Both post to the ledger: a risky class, `needs_approval` until a manager approves; run it again with
    the `approval_id`. Params: `doctype` (Delivery Note or Shipment), `name`, `preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`."""
    if doctype not in SUBMITTABLE:
        return {"ok": False, "error": "Only a Delivery Note or a Shipment is submitted here."}
    need_dt(me, doctype, f"submit a {doctype.lower()}")
    if not name:
        return {"ok": False, "error": f"Say which {doctype.lower()}."}
    res = _risky(deals._ex(db, me, {"op": "submit", "doctype": doctype, "name": name, "preview": bool(preview), "approval_id": approval_id or None}), f"the {doctype.lower()}")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": name, "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_ship_record(db, me, shipment: str = "", values: dict | None = None, preview: bool = False, **_):
    """Record the booking, bill of lading and tracking on the ERP's Shipment: carrier, AWB, tracking link and status, forwarder, booking number and date,
    cut-off, ETD, ETA, on-board, arrival and delivery dates, vessel, HBL and MBL. Only fields the Shipment has are written (`ship_track.WRITABLE_SHIPMENT`); an
    empty value is not sent. Params: `shipment`, `values`, `preview`. Returns `{ok, name, fields}`."""
    need_dt(me, "Shipment", "record the booking")
    if not shipment:
        return {"ok": False, "error": "Say which shipment."}
    clean = {k: v for k, v in (values or {}).items() if k in ship_track.WRITABLE_SHIPMENT and v not in (None, "")}
    if not clean:
        return {"ok": False, "error": "Nothing to save: fill the booking, bill of lading, tracking or a date first."}
    be = deals._be()
    cur = be.get_doc("Shipment", shipment)
    res = deals._ex(db, me, {"op": "save", "doctype": "Shipment", "name": shipment, "data": clean, "modified": cur.get("modified"), "preview": bool(preview)})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the change.")), "preview": res.get("preview")}
    return {"ok": True, "name": shipment, "fields": sorted(clean), "preview": res.get("preview") if preview else None, "saved": not preview}


FUNCTIONS: dict[str, Callable] = {"order_ship_get": order_ship_get, "order_shipment_create": order_shipment_create, "order_ship_make_dns": order_ship_make_dns,
                                  "order_ship_submit": order_ship_submit, "order_ship_record": order_ship_record}
