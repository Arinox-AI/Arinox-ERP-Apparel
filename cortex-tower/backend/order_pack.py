"""Order page step 8, Pack and inspect (ORDER_TO_SHIP_PLAN section 4): the carton plan, the packing list, the final inspection (with the AQL result) and the
needle detector log.

Same rules as ``order_cutsew`` / ``order_subcontract``: reads run the vendored scripts in record mode (``read_script``); the carton plan and the carton draw are
the ERP's own scripts (`arinox_packing_list_generate_cartons`, `arinox_final_inspection_pick_cartons`) run as reads, so the tower only sets the result against the
order. The documents themselves are made in the generic form, pre-filled by ``order_prefill_pack``; submitting a Packing List posts the production ledger and is a
risky class (approval).
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Callable

import deals
import guardrails
import order_flow
from order_cutsew import DEAD, _live_cards, _num
from order_samples import read_script
import deal_api

guarded = deal_api.guarded
PACK_TYPES = ("Solid Colour Solid Size", "Solid Colour Assorted Size", "Assorted")
PASS = ("Accepted", "Accepted with Concession")


def need_dt(me: dict, dt: str, what: str):
    """A permission check on the document type, never a role-name test."""
    if not guardrails.can(me["roles"], dt, "write"):
        raise guardrails.Denied(f"Your role cannot {what}. Ask shipping or QC, or a manager.")


def summarise_plan(plan: list[dict], order_rows: list[dict]) -> dict:
    """The carton plan set against the order. `plan` is the ERP's `[{carton_from, carton_to, tail, contents: [[colour, size, qty_per_carton]]}]`;
    `order_rows` are `{colour, size, order_qty, packable}`. Returns per colour x size `{cartons, pieces, order_qty, packable, over}`, the totals and the carton count.
    Pure arithmetic: a carton row of `n` cartons holds `n x qty` pieces of each content line."""
    per: dict = {}
    for o in order_rows:
        per[(o.get("colour"), o.get("size"))] = {"colour": o.get("colour"), "size": o.get("size"), "cartons": 0, "pieces": 0, "order_qty": _num(o.get("order_qty")), "packable": _num(o.get("packable"))}
    cartons = 0
    for row in plan or []:
        n = max(int(_num(row.get("carton_to")) - _num(row.get("carton_from")) + 1), 0)
        cartons += n
        for c in row.get("contents") or []:
            k = (c[0], c[1])
            p = per.setdefault(k, {"colour": c[0], "size": c[1], "cartons": 0, "pieces": 0, "order_qty": 0.0, "packable": 0.0})
            p["cartons"] += n
            p["pieces"] += n * int(_num(c[2]))
    rows = sorted(per.values(), key=lambda r: (str(r["colour"]), str(r["size"])))
    for r in rows:
        r["over"] = r["pieces"] > r["packable"] + 1e-9 if r["packable"] else r["pieces"] > 0
    pieces = sum(r["pieces"] for r in rows)
    oq = sum(r["order_qty"] for r in rows)
    return {"rows": rows, "cartons": cartons, "pieces": pieces, "order_qty": oq, "pct_of_order": round(pieces / oq * 100.0, 1) if oq else 0.0,
            "any_over": any(r["over"] for r in rows)}


def aql_view(fi: dict) -> dict:
    """What an inspection found set against what its AQL plan allows: per class `{found, accept, reject, ok}`; `verdict` is the ERP's computed result."""
    out = {}
    for k in ("critical", "major", "minor"):
        found, ac, re_ = _num(fi.get(f"{k}_found")), _num(fi.get(f"{k}_ac")), _num(fi.get(f"{k}_re"))
        out[k] = {"found": found, "accept": ac, "reject": re_, "ok": found <= ac}
    return {"classes": out, "within_plan": all(v["ok"] for v in out.values()), "verdict": fi.get("computed_result") or "", "result": fi.get("result") or ""}


def _cards(be, chain: list) -> list[dict]:
    return [c for c in _live_cards(be, chain) if int(c.get("docstatus") or 0) == 1 and c.get("status") not in DEAD]


def _order_rows(me, card: str) -> list[dict]:
    """Colour x size of one card: the order quantity and what is packable now (finished A-grade less samples less already packed, as the ERP counts)."""
    s = read_script(me, "arinox_production_card_get_summary", {"name": card}) or {}
    out = []
    for r in s.get("rows") or []:
        pk = max(_num(r.get("FIN_A")) - _num(r.get("SAMPLE_OUT")) - _num(r.get("PACKED")), 0.0)
        out.append({"colour": r.get("colour"), "size": r.get("size"), "order_qty": _num(r.get("order_qty")), "fin_a": _num(r.get("FIN_A")), "packed": _num(r.get("PACKED")),
                    "shipped": _num(r.get("SHIPPED")), "packable": pk})
    return out


@guarded
def order_pack_get(db, me, sales_order: str = "", **_):
    """Everything the step-8 page shows for one order: the **packing position** per colour and size (order quantity, finished A-grade, packed, still packable), the
    packing lists with their carton and piece totals and the share of the order, the final inspections with the AQL result (what was found against what
    the plan accepts, the ERP's computed result and the recorded one) and the recent needle detector checks. Read only. Params: `sales_order`.
    Returns `{ok, head, cards, matrix, packing_lists, inspections, needle, summary, can_pack, can_inspect, can_needle}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Packing List", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    cards = _cards(be, chain)
    matrix = []
    for c in cards:
        for r in _order_rows(me, c["name"]):
            matrix.append({**r, "card": c["name"], "style": c.get("style_no") or c.get("style_item")})
    pls = be.get_list("Packing List", [["sales_order", "in", chain], ["docstatus", "!=", 2]],
                      ["name", "docstatus", "status", "production_card", "pack_type", "pcs_per_carton", "packing_date", "total_cartons", "total_pieces", "total_vs_order_pct", "final_inspection", "shipment", "ship_to"], limit=300)
    fis = be.get_list("Final Inspection", [["sales_order", "in", chain], ["docstatus", "!=", 2]],
                      ["name", "docstatus", "inspection_type", "inspection_date", "result", "computed_result", "offered_qty", "sample_size", "inspected_cartons", "total_cartons", "packed_pct",
                       "critical_found", "major_found", "minor_found", "critical_ac", "critical_re", "major_ac", "major_re", "minor_ac", "minor_re", "draw_seed", "production_card"], limit=100)
    in_fi: dict = {}
    for f in fis:
        try:
            lots = [l.get("packing_list") for l in (be.get_doc("Final Inspection", f["name"]).get("lots") or [])]
        except Exception:                                   # noqa: BLE001 - a missing child table must not stop the page
            lots = []
        f["lots"] = lots
        f["aql"] = aql_view(f)
        if int(f.get("docstatus") or 0) != 2:
            for l in lots:
                in_fi.setdefault(l, []).append(f["name"])
    for p in pls:
        sub = int(p.get("docstatus") or 0) == 1
        p["inspections"] = in_fi.get(p["name"], [])
        p["can_inspect"] = sub and not p["inspections"]
    lines = sorted({c.get("line") for c in cards if c.get("line")})
    needle = be.get_list("Needle Detector Log", [["line", "in", lines]], ["name", "check_date", "check_time", "line", "machine", "test_piece_mm", "result", "garments_rescanned", "rescan_done", "action"], limit=15) if lines else []
    needle.sort(key=lambda r: (str(r.get("check_date") or ""), str(r.get("check_time") or "")), reverse=True)
    today = _dt.date.today().isoformat()
    oq = sum(r["order_qty"] for r in matrix)
    packed_sub = sum(_num(p.get("total_pieces")) for p in pls if int(p.get("docstatus") or 0) == 1)
    accepted = [f for f in fis if int(f.get("docstatus") or 0) == 1 and f.get("result") in PASS]
    rejected = [f for f in fis if int(f.get("docstatus") or 0) == 1 and f.get("result") == "Rejected"]
    return {"ok": True, "head": head, "cards": [c["name"] for c in cards], "matrix": matrix, "packing_lists": pls, "inspections": fis, "needle": needle,
            "can_pack": guardrails.can(me["roles"], "Packing List", "write"), "can_inspect": guardrails.can(me["roles"], "Final Inspection", "write"),
            "can_needle": guardrails.can(me["roles"], "Needle Detector Log", "write"),
            "summary": {"order_qty": oq, "packable": sum(r["packable"] for r in matrix), "packed": packed_sub, "pct_packed": round(packed_sub / oq * 100.0, 1) if oq else 0.0,
                        "cartons": sum(_num(p.get("total_cartons")) for p in pls if int(p.get("docstatus") or 0) == 1), "lists_submitted": sum(1 for p in pls if int(p.get("docstatus") or 0) == 1),
                        "inspection_passed": bool(accepted), "inspection_rejected": bool(rejected) and not accepted,
                        "needle_today": any(str(n.get("check_date"))[:10] == today for n in needle), "needle_failed": any(n.get("result") == "Fail" and not n.get("rescan_done") for n in needle)}}


def _plan_doc(card: str, pack_type: str, pcs_per_carton: int, ratios: list | None, tail: str, carton_start: int, ship_to: str = "") -> dict:
    return {"production_card": card, "pack_type": pack_type, "pcs_per_carton": int(pcs_per_carton or 0), "tail_carton_rule": tail or "Mixed Colour and Size", "carton_start": int(carton_start or 1),
            "ship_to": ship_to or None, "ratios": [{"colour": r.get("colour"), "size": r.get("size"), "pieces_per_pack": int(_num(r.get("pieces_per_pack")))} for r in (ratios or []) if r.get("size")]}


def _generate(me, doc: dict, quantities: dict | None) -> tuple[dict | None, str]:
    params = {"doc": json.dumps(doc, default=str)}
    if quantities:
        params["quantities"] = json.dumps(quantities)
    try:
        out = read_script(me, "arinox_packing_list_generate_cartons", params) or {}
    except Exception as e:                                  # noqa: BLE001 - the script's own sentence ("Nothing is available to pack ...")
        return None, deals._strip_html(str(getattr(e, "message", None) or e))[:300]
    return out, ""


def _check_plan_args(card: str, pack_type: str, pcs_per_carton: int, ratios: list | None) -> str:
    if not card:
        return "Say which production card."
    if pack_type not in PACK_TYPES:
        return "Choose how it is packed: " + ", ".join(PACK_TYPES) + "."
    if int(pcs_per_carton or 0) <= 0:
        return "Pieces per carton must be more than zero."
    if pack_type != "Solid Colour Solid Size" and not [r for r in (ratios or []) if r.get("size") and int(_num(r.get("pieces_per_pack"))) > 0]:
        return "An assorted pack needs a ratio: pieces per pack for each size."
    return ""


@guarded
def order_pack_plan(db, me, sales_order: str = "", card: str = "", pack_type: str = "", pcs_per_carton: int = 0, ratios: list | None = None, tail_carton_rule: str = "",
                    carton_start: int = 1, ship_to: str = "", **_):
    """The **carton plan**, worked out by the ERP's own script and set against the order, writing nothing: for the `pack_type` (solid colour and size, solid
    colour with an assorted-size ratio, or assorted), the pieces per carton and the ratio rows (`{colour, size, pieces_per_pack}`), the cartons needed per colour
    and size, the pieces, what is packable now and the total against the order. Params: `sales_order`, `card`, `pack_type`, `pcs_per_carton`, `ratios`,
    `tail_carton_rule`, `carton_start`, `ship_to`. Returns `{ok, plan, summary:{rows, cartons, pieces, order_qty, pct_of_order, any_over}}`."""
    need_dt(me, "Packing List", "plan the cartons")
    err = _check_plan_args(card, pack_type, pcs_per_carton, ratios)
    if err:
        return {"ok": False, "error": err}
    out, e = _generate(me, _plan_doc(card, pack_type, pcs_per_carton, ratios, tail_carton_rule, carton_start, ship_to), None)
    if out is None:
        return {"ok": False, "error": e}
    plan = out.get("plan") or []
    if not plan:
        return {"ok": False, "error": "Nothing is available to pack: finish pieces into A-grade first."}
    return {"ok": True, "plan": plan, "summary": summarise_plan(plan, _order_rows(me, card))}


@guarded
def order_prefill_pack(db, me, sales_order: str = "", kind: str = "", card: str = "", pack_type: str = "", pcs_per_carton: int = 0, ratios: list | None = None,
                       tail_carton_rule: str = "", carton_start: int = 1, ship_to: str = "", packing_lists: list | None = None, seed: int = 0, line: str = "", **_):
    """Pre-filled starting values of a pack or inspection document for the generic form: `kind` is `packing` (a Packing List with the cartons and contents the
    ERP's generator planned from the same arguments as `order_pack_plan`), `inspection` (a Final Inspection over the `packing_lists` of the lot, with the cartons
    drawn at random by the ERP and the seed kept so the draw can be repeated) or `needle` (a Needle Detector Log for today on a `line`). Writes nothing.
    Params: `sales_order`, `kind`, plus the plan or lot arguments. Returns `{ok, doctype, initial, note}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    today = _dt.date.today().isoformat()
    cards = _cards(be, chain)
    c = next((x for x in cards if x["name"] == card), None) if card else (cards[0] if cards else None)
    if kind == "needle":
        need_dt(me, "Needle Detector Log", "log a needle check")
        ln = line or (c or {}).get("line") or ""
        return {"ok": True, "doctype": "Needle Detector Log", "note": "Pass only if the test piece was found; a failure needs the rescan of everything since the last good check.",
                "initial": {"check_date": today, "line": ln, "result": "Pass"}}
    if not c:
        return {"ok": False, "error": "Issue a production card first."}
    if kind == "packing":
        need_dt(me, "Packing List", "make a packing list")
        err = _check_plan_args(c["name"], pack_type, pcs_per_carton, ratios)
        if err:
            return {"ok": False, "error": err}
        doc = _plan_doc(c["name"], pack_type, pcs_per_carton, ratios, tail_carton_rule, carton_start, ship_to)
        out, e = _generate(me, doc, None)
        if out is None:
            return {"ok": False, "error": e}
        gen = out.get("arinox_doc") or {}
        if not (gen.get("cartons") or []):
            return {"ok": False, "error": "Nothing is available to pack: finish pieces into A-grade first."}
        o = be.get_doc("Sales Order", head)
        initial = {"production_card": c["name"], "sales_order": head, "customer": o.get("customer"), "packing_date": today, "pack_type": pack_type, "pcs_per_carton": int(pcs_per_carton),
                   "tail_carton_rule": doc["tail_carton_rule"], "carton_start": doc["carton_start"], "ratios": doc["ratios"], "cartons": gen["cartons"], "contents": gen.get("contents") or [],
                   **({"ship_to": ship_to} if ship_to else {})}
        return {"ok": True, "doctype": "Packing List", "note": f"{out.get('rows') or len(gen['cartons'])} carton row(s) planned by the ERP; check the totals against the order before you submit.", "initial": initial}
    if kind == "inspection":
        need_dt(me, "Final Inspection", "make a final inspection")
        lots = [x for x in (packing_lists or []) if x]
        if not lots:
            return {"ok": False, "error": "Pick the submitted packing lists in the lot."}
        have = {p["name"]: p for p in be.get_list("Packing List", [["name", "in", lots]], ["name", "docstatus", "production_card", "sales_order"], limit=200)}
        for n in lots:
            p = have.get(n)
            if not p or int(p.get("docstatus") or 0) != 1:
                return {"ok": False, "error": f"Packing list {n} is not submitted."}
            if p.get("sales_order") not in chain:
                return {"ok": False, "error": f"Packing list {n} belongs to another order."}
        cards_of = {p.get("production_card") for p in have.values()}
        if len(cards_of) > 1:
            return {"ok": False, "error": "A lot covers one production card: pick the packing lists of one card."}
        doc = {"lots": [{"packing_list": n} for n in lots]}
        try:
            out = read_script(me, "arinox_final_inspection_pick_cartons", {"doc": json.dumps(doc), **({"seed": int(seed)} if seed else {})}) or {}
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "error": deals._strip_html(str(getattr(e, "message", None) or e))[:300]}
        gen = out.get("arinox_doc") or {}
        return {"ok": True, "doctype": "Final Inspection", "note": f"{len(gen.get('cartons_picked') or [])} carton(s) drawn at random (seed {gen.get('draw_seed')}); the ERP sets the AQL sample and the result rules when you save.",
                "initial": {"production_card": cards_of.pop(), "sales_order": head, "inspection_type": "Final", "inspection_date": today, "lots": doc["lots"],
                            "cartons_picked": gen.get("cartons_picked") or [], "draw_seed": gen.get("draw_seed")}}
    return {"ok": False, "error": "kind is packing, inspection or needle"}


FUNCTIONS: dict[str, Callable] = {"order_pack_get": order_pack_get, "order_pack_plan": order_pack_plan, "order_prefill_pack": order_prefill_pack}
