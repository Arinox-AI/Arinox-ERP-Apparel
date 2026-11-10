"""Order page step 4, Samples and PP (ORDER_TO_SHIP_PLAN section 4): the approval matrix, the bulk gate card and the actions behind them.

Reads run the vendored Arinox scripts in record mode (``read_script``: nothing can be written, it is checked); every write goes through
``deals._ex`` (the pipeline), so the ERP's own rules (``sample_approval_validate``, ``pp_meeting_before_submit``, the bulk gate) decide.
The tower never invents a rule: which sample types an order needs, per colour or per style, comes from ``arinox_sample_approval_get_sample_rules``.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Callable

import deals
import guardrails
import order_flow
import pipeline
from tsr.runner import Context

import deal_api

guarded = deal_api.guarded

OK = ("Approved", "Approved with Comments", "Not Required")
NEEDS_COMMENT = ("Approved with Comments", "Rejected", "Resubmit")
DECISIONS = ("Pending", "Approved", "Approved with Comments", "Rejected", "Resubmit")


def need(me: dict, group: str, what: str = "change this"):
    allowed = set(guardrails.WRITE[group]) | set(guardrails.ALL_POWER)
    if not set(me["roles"]) & allowed:
        raise guardrails.Denied(f"Your role cannot {what}. Ask a planner, sampling or merchandising user, or a manager.")


def read_script(me: dict, method: str, params: dict | None = None):
    """Run one Arinox API script in record mode: a read. Refuses a script that tried to write. Returns the script's result."""
    eng = pipeline.engine()
    ctx = Context(deals._be(), eng, user=me["email"], roles=me["roles"], mode="record", perm_checker=pipeline._perm_checker(me["roles"]))
    flags = eng.run_api(ctx, method, dict(params or {}))
    if ctx.sink.ops:
        raise RuntimeError(f"{method} tried to write while the page was only reading")
    return flags.get("arinox_result", flags)


_STRIP = frozenset({"idx", "name", "parent", "parentfield", "parenttype", "doctype", "creation", "modified", "modified_by", "owner", "docstatus", "amended_from", "__islocal", "__unsaved"})


def clean(v, top: bool = False):
    """Rows as the ERP takes them back: no bookkeeping (idx, name, parent, ...) at any level; empty values dropped. The top-level `doctype` is kept by the caller."""
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items() if k not in _STRIP and x not in (None, "")}
    return v


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def groups(be, so: dict) -> list[dict]:
    """The style x colour lines of a Sales Order: `{style_item, colour, qty, production_item, ship_to}` (first variant item of the colour)."""
    out: dict = {}
    cache: dict = {}
    for it in so.get("items") or []:
        code = it.get("item_code")
        if code not in cache:
            r = be.get_list("Item", [["name", "=", code]], ["variant_of"], limit=1)
            cache[code] = (r[0].get("variant_of") if r else None) or code
        k = (cache[code], (it.get("apparel_colour") or "").strip())
        g = out.setdefault(k, {"style_item": k[0], "colour": k[1], "qty": 0.0, "production_item": code, "ship_to": set()})
        g["qty"] += _num(it.get("qty"))
        if it.get("apparel_ship_to"):
            g["ship_to"].add(str(it["apparel_ship_to"]).strip().upper())
    return [{**g, "ship_to": sorted(g["ship_to"])} for g in out.values()]


def _norm(c) -> str:
    return (c or "").strip().upper()


def _rule_gate(rule: dict, split: bool) -> str:
    g = rule.get("gate") or "No"
    return "No" if g != "No" and rule.get("split_po_exempt") and split else g


def _cell(rule_gate: str, per_colour: bool, samples: list[dict], style: str, colour: str, stype: str) -> dict:
    mine = [s for s in samples if s.get("style_item") == style and s.get("sample_type") == stype and (not per_colour or _norm(s.get("colour")) == _norm(colour))]
    live = [s for s in mine if int(s.get("docstatus") or 0) != 2]
    if not live:
        if rule_gate == "Required":
            return {"status": "Missing", "tone": "bad", "sample": None, "gate": rule_gate}
        return {"status": "Not raised" if rule_gate == "If Raised" else "", "tone": None, "sample": None, "gate": rule_gate}
    pick = next((s for s in live if s.get("status") in OK), None) or sorted(live, key=lambda s: s["name"])[-1]
    st = pick.get("status") or "Open"
    tone = "ok" if st in OK else "bad" if st == "Rejected" else "warn"
    return {"status": st, "tone": tone, "sample": pick["name"], "gate": rule_gate, "due_date": str(pick.get("due_date") or ""), "rounds": pick.get("rounds") or [],
            "count": len(live)}


def _samples(be, chain: list) -> list[dict]:
    rows = be.get_list("Sample Approval", [["sales_order", "in", chain]],
                       ["name", "sample_type", "status", "style_item", "style_no", "colour", "due_date", "submitted_on", "approved_on", "docstatus", "in_bulk_fabric", "waived"], limit=500)
    rounds: dict = {}
    if rows:
        for r in be.get_list("Sample Approval Round", [["parent", "in", [x["name"] for x in rows]]],
                             ["parent", "round_no", "sent_on", "decision", "decision_on", "remarks"], limit=3000, parent="Sample Approval"):
            rounds.setdefault(r["parent"], []).append({k: r.get(k) for k in ("round_no", "sent_on", "decision", "decision_on", "remarks")})
    for r in rows:
        r["rounds"] = sorted(rounds.get(r["name"], []), key=lambda x: x.get("round_no") or 0)
    return rows


@guarded
def order_samples_get(db, me, sales_order: str = "", **_):
    """Everything the step-4 page shows for one order: the **approval matrix** (sample type x style/colour; each cell is the status of the approval, its
    rounds, or Missing when the rule requires it and none is raised), the **bulk gate card** per style/colour (green when the ERP's own gate script
    reports no blockers, else red with the missing items in plain sentences) and the PP meetings with their attendance and open actions. Read only. The
    rules come from the ERP (`arinox_sample_approval_get_sample_rules`). Params: `sales_order`. Returns `{ok, head, types, rows:[{style_item, colour, qty,
    cells, gate}], meetings, summary}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Sample Approval", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    gs = groups(be, so)
    split = len({s for g in gs for s in g["ship_to"]}) > 1
    samples = _samples(be, chain)
    rules_by_style: dict = {}
    for g in gs:
        if g["style_item"] not in rules_by_style:
            rules_by_style[g["style_item"]] = read_script(me, "arinox_sample_approval_get_sample_rules",
                                                          {"customer": so.get("customer"), "sales_order": head, "style_item": g["style_item"]}) or {}
    used = [t for t in order_flow_sample_types(rules_by_style, split, samples)]
    rows = []
    for g in gs:
        rules = rules_by_style.get(g["style_item"]) or {}
        cells = {}
        for t in used:
            rule = rules.get(t) or {"gate": "No", "per_colour": 0}
            cells[t] = _cell(_rule_gate(rule, split), bool(rule.get("per_colour")), samples, g["style_item"], g["colour"], t)
        gate = read_script(me, "arinox_work_order_get_bulk_gate", {"production_item": g["production_item"], "sales_order": head}) or {}
        blockers = list(gate.get("blockers") or [])
        rows.append({"style_item": g["style_item"], "colour": g["colour"], "qty": g["qty"], "production_item": g["production_item"], "cells": cells,
                     "gate": {"applies": bool(gate.get("applies", True)), "open": bool(gate.get("applies", True)) and not blockers, "blockers": blockers}})
    meetings = _meetings(be, chain)
    missing = sum(1 for r in rows for c in r["cells"].values() if c["status"] == "Missing")
    return {"ok": True, "head": head, "types": [{"type": t, **_type_info(rules_by_style, t)} for t in used], "rows": rows, "meetings": meetings,
            "summary": {"missing": missing, "gate_open": sum(1 for r in rows if r["gate"]["open"]), "gate_total": len(rows),
                        "meeting_submitted": any(m["docstatus"] == 1 for m in meetings)},
            "can_write": bool(set(me["roles"]) & (set(guardrails.WRITE["plan"]) | set(guardrails.ALL_POWER)))}


def order_flow_sample_types(rules_by_style: dict, split: bool, samples: list[dict]) -> list[str]:
    """The columns: every type some style requires or has raised, in the ERP's order of rules."""
    seen: list[str] = []
    for rules in rules_by_style.values():
        for t, r in rules.items():
            if _rule_gate(r, split) != "No" and t not in seen:
                seen.append(t)
    for s in samples:
        if s.get("sample_type") not in seen and int(s.get("docstatus") or 0) != 2:
            seen.append(s["sample_type"])
    return seen


def _type_info(rules_by_style: dict, t: str) -> dict:
    for rules in rules_by_style.values():
        if t in rules:
            r = rules[t]
            return {"gate": r.get("gate"), "per_colour": bool(r.get("per_colour")), "due_basis": r.get("due_basis"), "days_before": r.get("days_before")}
    return {"gate": "No", "per_colour": False}


def _meetings(be, chain: list) -> list[dict]:
    ms = be.get_list("PP Meeting", [["sales_order", "in", chain], ["docstatus", "!=", 2]],
                     ["name", "style_item", "status", "docstatus", "meeting_date", "pp_sample", "production_card_issued_on", "meeting_type"], limit=100)
    out = []
    for m in ms:
        kids = {"parts": [], "acts": []}
        try:
            kids["parts"] = be.get_list("PP Meeting Participant", [["parent", "=", m["name"]]], ["department", "attended"], limit=50, parent="PP Meeting")
            kids["acts"] = be.get_list("PP Meeting Action", [["parent", "=", m["name"]]], ["idx", "comment", "action_taken", "action_owner", "target_date", "status"], limit=200, parent="PP Meeting")
        except Exception:                                   # noqa: BLE001 - a courtesy read
            pass
        out.append({**m, "participants": kids["parts"], "actions": kids["acts"], "docstatus": int(m.get("docstatus") or 0),
                    "open_actions": sum(1 for a in kids["acts"] if a.get("status") != "Closed")})
    return out


# ───────────────────────── actions ─────────────────────────

def _ex(db, me, req: dict, preview: bool, what: str) -> dict:
    res = deals._ex(db, me, {**req, "preview": bool(preview)})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or f"The ERP refused {what}.")), "preview": res.get("preview")}
    return res


@guarded
def order_samples_create(db, me, sales_order: str = "", types: list | None = None, preview: bool = False, **_):
    """Create the Sample Approvals the order needs from the ERP's rules: one per style and colour for a per-colour type (Lab Dip, Bulk Fabric), one per
    style for the others, only for types the rule marks Required (plus any in `types`, for If Raised ones) and only where none exists yet, so it can be
    run again safely. Each is inserted through the pipeline; the ERP sets the due date from the rule. With `preview` nothing is written and the ERP's
    own preview of each document comes back. Params: `sales_order`, `types`, `preview`. Returns `{ok, made:[names], planned:[{sample_type, style_item,
    colour}], skipped, previews}`."""
    need(me, "plan", "create sample approvals")
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    if int(so.get("docstatus") or 0) != 1:
        return {"ok": False, "error": f"Sales Order {head} must be submitted first."}
    gs = groups(be, so)
    split = len({s for g in gs for s in g["ship_to"]}) > 1
    have = _samples(be, chain)
    plan, seen = [], set()
    for g in gs:
        rules = read_script(me, "arinox_sample_approval_get_sample_rules", {"customer": so.get("customer"), "sales_order": head, "style_item": g["style_item"]}) or {}
        for t, r in rules.items():
            if not (_rule_gate(r, split) == "Required" or t in (types or [])):
                continue
            per = bool(r.get("per_colour"))
            colour = g["colour"] if per else ""
            k = (g["style_item"], t, _norm(colour))
            if k in seen:
                continue
            seen.add(k)
            if any(s["style_item"] == g["style_item"] and s["sample_type"] == t and int(s.get("docstatus") or 0) != 2 and (not per or _norm(s.get("colour")) == _norm(colour)) for s in have):
                continue
            plan.append({"sample_type": t, "style_item": g["style_item"], "colour": colour})
    if not plan:
        return {"ok": True, "made": [], "planned": [], "skipped": "Every approval the rules ask for already exists.", "previews": []}
    made, previews = [], []
    for p in plan:
        data = {"sample_type": p["sample_type"], "style_item": p["style_item"], "sales_order": head, "colour": p["colour"] or None}
        if p["sample_type"] in ("Bulk Fabric", "Bulk Trim"):
            data["material_description"] = f"{p['sample_type']} of {p['style_item']} (name the material before sending)"
        data = {k: v for k, v in data.items() if v not in (None, "")}
        res = _ex(db, me, {"op": "insert", "doctype": "Sample Approval", "data": data},
                  preview, "the sample approval")
        if not res.get("ok"):
            return {**res, "made": made, "planned": plan}
        if preview:
            previews.append(res.get("preview"))
        else:
            made.append((res.get("doc") or {}).get("name") or "")
    return {"ok": True, "made": made, "planned": plan, "previews": previews, "preview": preview}


@guarded
def order_sample_round(db, me, sales_order: str = "", sample_approval: str = "", decision: str = "", sent_on: str = "", decision_on: str = "", comment: str = "",
                       category: str = "Other", relevant_to_cutting: bool = False, in_bulk_fabric: bool = False, tested_after_wash: bool = False,
                       remarks: str = "", preview: bool = False, **_):
    """Record a round on a Sample Approval: sent to the buyer (decision Pending) or the buyer's decision. A Pending last round is decided in place;
    otherwise a new round is added. Approved with Comments, Rejected and Resubmit need the buyer's comment (the ERP refuses without). `in_bulk_fabric`
    marks a PP sample made in bulk fabric (the ERP will not approve a PP sample otherwise). Params: `sales_order`, `sample_approval`, `decision`,
    `sent_on`, `decision_on`, `comment`, `category`, `relevant_to_cutting`, `in_bulk_fabric`, `tested_after_wash`, `remarks`, `preview`. Returns
    `{ok, name, round_no}` or `{ok: false, error}`."""
    need(me, "plan", "record a sample round")
    if decision not in DECISIONS:
        return {"ok": False, "error": "Choose a decision: " + ", ".join(DECISIONS) + "."}
    if decision in NEEDS_COMMENT and not (comment or "").strip():
        return {"ok": False, "error": f"The buyer's comment is needed when the decision is {decision}."}
    be = deals._be()
    chain, _head = order_flow._sales_order_chain(be, str(sales_order))
    try:
        d = be.get_doc("Sample Approval", sample_approval)
    except Exception:                                       # noqa: BLE001
        return {"ok": False, "error": f"Sample approval {sample_approval} was not found."}
    if d.get("sales_order") not in chain:
        return {"ok": False, "error": f"{sample_approval} does not belong to {sales_order}."}
    today = _dt.date.today().isoformat()
    rounds = clean(d.get("rounds") or [])
    comments = clean(d.get("comments") or [])
    last = rounds[-1] if rounds else None
    if last and last.get("decision") == "Pending" and decision != "Pending":
        last.update(decision=decision, decision_on=decision_on or today, tested_after_wash=1 if tested_after_wash else last.get("tested_after_wash", 0))
        if remarks:
            last["remarks"] = remarks
        rno = len(rounds)
    else:
        rno = len(rounds) + 1
        row = {"round_no": rno, "sent_on": sent_on or (today if decision == "Pending" else None), "decision": decision,
               "decision_on": None if decision == "Pending" else (decision_on or today), "tested_after_wash": 1 if tested_after_wash else 0, "remarks": remarks or None}
        rounds.append({k: v for k, v in row.items() if v not in (None, "")})
    if comment.strip():
        comments.append({"round_no": rno, "category": category or "Other", "comment": comment.strip(), "relevant_to_cutting": 1 if relevant_to_cutting else 0, "status": "Open"})
    data = {"rounds": rounds, "comments": comments}
    if in_bulk_fabric:
        data["in_bulk_fabric"] = 1
    res = _ex(db, me, {"op": "save", "doctype": "Sample Approval", "name": sample_approval, "data": data, "modified": str(d.get("modified") or "") or None}, preview, "the round")
    if not res.get("ok"):
        return res
    doc = res.get("doc") or {}
    return {"ok": True, "name": sample_approval, "round_no": rno, "status": doc.get("status"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_sample_load(db, me, sales_order: str = "", sample_approval: str = "", what: str = "spec", sample_size: str = "", preview: bool = False, **_):
    """Fill a Sample Approval's table from the ERP's own scripts: `what` = `spec` (the Tech Pack measurements for `sample_size`,
    `arinox_sample_approval_load_spec_from_tech_pack`) or `tests` (the standard test list from Apparel Settings,
    `arinox_sample_approval_load_standard_tests`). The rows come back from the script and are saved through the pipeline. Params: `sales_order`,
    `sample_approval`, `what`, `sample_size`, `preview`. Returns `{ok, count}`."""
    need(me, "plan", "load rows into a sample approval")
    if what not in ("spec", "tests"):
        return {"ok": False, "error": "`what` is spec or tests."}
    be = deals._be()
    chain, _h = order_flow._sales_order_chain(be, str(sales_order))
    d = be.get_doc("Sample Approval", sample_approval)
    if d.get("sales_order") not in chain:
        return {"ok": False, "error": f"{sample_approval} does not belong to {sales_order}."}
    doc = {"tech_pack": d.get("tech_pack"), "sample_size": sample_size or d.get("sample_size"), "tests": d.get("tests") or []}
    method = "arinox_sample_approval_load_spec_from_tech_pack" if what == "spec" else "arinox_sample_approval_load_standard_tests"
    try:
        out = read_script(me, method, {"doc": json.dumps(doc, default=str)})
    except Exception as e:                                  # noqa: BLE001 - the script's own sentence ("Select the Tech Pack first.")
        return {"ok": False, "error": deals._strip_html(str(getattr(e, "message", None) or e))[:300]}
    rows = (out.get("arinox_doc") or {}).get("measurements" if what == "spec" else "tests") or []
    if not rows:
        return {"ok": False, "error": "The ERP has nothing to load here yet."}
    res = _ex(db, me, {"op": "save", "doctype": "Sample Approval", "name": sample_approval,
                       "data": {("measurements" if what == "spec" else "tests"): rows, **({"sample_size": sample_size} if sample_size else {})}}, preview, "the rows")
    return {**res, "count": len(rows)} if not res.get("ok") else {"ok": True, "count": len(rows), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_pp_meeting_make(db, me, sales_order: str = "", style_item: str = "", attended: list | None = None, card_issued_on: str = "", meeting_date: str = "",
                          preview: bool = False, **_):
    """Make the PP meeting of one style as a draft: the PP sample is the style's approved PP approval, the attendance list has a row for every required
    department (`arinox_pp_meeting_add_standard_participants`; `attended` lists the departments that came), fabric and trim readiness per colour come from
    the requisitions (`arinox_pp_meeting_load_from_requisitions`) and every open buyer comment is an action row (`arinox_pp_meeting_get_buyer_comments`).
    The meeting is held after the production card is issued (`card_issued_on`). It is not submitted here. Params: `sales_order`, `style_item`, `attended`,
    `card_issued_on`, `meeting_date`, `preview`. Returns `{ok, name, actions, colours}`."""
    need(me, "plan", "make a PP meeting")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    if style_item not in {g["style_item"] for g in groups(be, so)}:
        return {"ok": False, "error": f"Style {style_item or '(none)'} is not on {head}."}
    if be.get_list("PP Meeting", [["sales_order", "in", chain], ["style_item", "=", style_item], ["docstatus", "!=", 2]], ["name"], limit=1):
        return {"ok": False, "error": f"A PP meeting for {style_item} already exists on this order."}
    pps = [s for s in _samples(be, chain) if s["style_item"] == style_item and s["sample_type"] == "PP" and int(s.get("docstatus") or 0) != 2]
    pp = next((s for s in pps if s.get("status") in ("Approved", "Approved with Comments")), None) or (pps[-1] if pps else None)
    today = _dt.date.today().isoformat()
    doc = {"meeting_type": "PP Meeting", "sales_order": head, "style_item": style_item, "meeting_date": meeting_date or today,
           "production_card_issued_on": card_issued_on or None, "pp_sample": pp["name"] if pp else None,
           "colours": [{"colour": g["colour"], "order_qty": int(g["qty"])} for g in groups(be, so) if g["style_item"] == style_item and g["colour"]]}
    doc = {k: v for k, v in doc.items() if v not in (None, "")}
    for method in ("arinox_pp_meeting_add_standard_participants", "arinox_pp_meeting_load_from_requisitions", "arinox_pp_meeting_get_buyer_comments"):
        out = read_script(me, method, {"doc": json.dumps(doc, default=str)}) or {}
        doc.update(out.get("arinox_doc") or {})
    for p in doc.get("participants") or []:
        if p.get("department") in (attended or []):
            p["attended"] = 1
    res = _ex(db, me, {"op": "insert", "doctype": "PP Meeting", "data": doc}, preview, "the PP meeting")
    if not res.get("ok"):
        return res
    made = res.get("doc") or {}
    return {"ok": True, "name": made.get("name") or "", "actions": len(doc.get("actions") or []), "colours": len(doc.get("colours") or []),
            "participants": [p.get("department") for p in doc.get("participants") or []], "pp_sample": doc.get("pp_sample"),
            "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_pp_meeting_actions(db, me, name: str = "", actions: list | None = None, attended: list | None = None, card_issued_on: str = "", preview: bool = False, **_):
    """Fill a draft PP meeting: for each action row the action taken, its owner (a user) and a target date (`actions` = `[{idx, action_taken, action_owner,
    target_date}]`), and the departments that attended. A row with no change is left alone. The ERP checks everything again at submit. Params: `name`,
    `actions`, `attended`, `card_issued_on`, `preview`. Returns `{ok, name}`."""
    need(me, "plan", "edit a PP meeting")
    be = deals._be()
    d = be.get_doc("PP Meeting", name)
    if int(d.get("docstatus") or 0) != 0:
        return {"ok": False, "error": "Only a draft meeting can be edited."}
    rows = []
    for i, a in enumerate(d.get("actions") or [], 1):
        rows.append({**clean(a), "_n": int(a.get("idx") or i)})
    for ch in actions or []:
        row = next((r for r in rows if r["_n"] == int(ch.get("idx") or -1)), None)
        if row is None:
            return {"ok": False, "error": f"Action row {ch.get('idx')} does not exist."}
        for k in ("action_taken", "action_owner", "target_date"):
            if ch.get(k):
                row[k] = ch[k]
    rows = [{k: v for k, v in r.items() if k != "_n"} for r in rows]
    parts = clean(d.get("participants") or [])
    for p in parts:
        if attended is not None:
            p["attended"] = 1 if p.get("department") in attended else 0
    data = {"actions": rows, "participants": parts}
    if card_issued_on:
        data["production_card_issued_on"] = card_issued_on
    return _ok(_ex(db, me, {"op": "save", "doctype": "PP Meeting", "name": name, "data": data}, preview, "the meeting"), name, preview)


@guarded
def order_pp_meeting_submit(db, me, name: str = "", preview: bool = False, **_):
    """Submit a PP meeting (the ERP checks: the PP sample is buyer approved, every required department attended, every buyer comment is an action with an
    owner and a date, and the production card date). Submitting it is the last condition of the bulk gate. Params: `name`, `preview`. Returns `{ok, name}`."""
    need(me, "plan", "submit a PP meeting")
    if not name:
        return {"ok": False, "error": "Say which PP meeting."}
    return _ok(_ex(db, me, {"op": "submit", "doctype": "PP Meeting", "name": name}, preview, "the meeting"), name, preview)


def _ok(res: dict, name: str, preview: bool) -> dict:
    if not res.get("ok"):
        return res
    return {"ok": True, "name": name, "preview": res.get("preview") if preview else None, "saved": not preview}


FUNCTIONS: dict[str, Callable] = {"order_samples_get": order_samples_get, "order_samples_create": order_samples_create, "order_sample_round": order_sample_round,
                                  "order_sample_load": order_sample_load, "order_pp_meeting_make": order_pp_meeting_make,
                                  "order_pp_meeting_actions": order_pp_meeting_actions, "order_pp_meeting_submit": order_pp_meeting_submit}
