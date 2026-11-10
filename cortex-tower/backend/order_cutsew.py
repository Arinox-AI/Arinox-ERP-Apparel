"""Order page step 6, Cut and sew (ORDER_TO_SHIP_PLAN section 4), and the production board that replaces the Cortex WIP screen.

Same rules as ``order_samples`` / ``order_materials``: reads run the vendored scripts in record mode; every write goes through ``deals._ex`` (pipeline,
preview first). The production matrix is the ERP's own ``arinox_production_card_get_summary`` (stage totals of the Production Movement ledger per colour x
size); the tower only adds up, sets the totals against the order quantity and shows what was posted today. Floor documents (Daily Line Report, Lay
Report, Line Input, Cut Plan, Operation Bulletin) are made in the generic form, pre-filled by ``order_prefill`` (the ERP's validation and after-submit
rules decide; submitting one posts the ledger, which is a risky class). Issuing fabric to the cutting floor is a Stock Entry: risky, needs approval.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Callable

import deals
import guardrails
import order_flow
from order_samples import _ex, _ok, clean, groups, read_script
import deal_api

guarded = deal_api.guarded

#: matrix columns: key, label, Production Movement stage. "Finished" is what the finishing receipt put in (FIN_IN); "QC pass" is the A-grade passes of the
#: finishing audit (FIN_A).
STAGES = [("cut", "Cut", "CUT"), ("input", "Line input", "SEW_IN"), ("sewn", "Sewn", "SEW_OUT"), ("qc_pass", "QC pass", "FIN_A"), ("finished", "Finished", "FIN_IN"),
          ("packed", "Packed", "PACKED")]
CODE = {k: c for k, _l, c in STAGES}
DEAD = ("Superseded", "Cancelled")


def need(me: dict, group: str = "make", what: str = "change this"):
    """A permission check (guardrails.require on the group's lead doctype), not a role-name test."""
    guardrails.require(me["roles"], {"make": "Production Card", "materials": "Fabric Requisition"}.get(group, "Production Card"), "write")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def build_matrix(cards: list[dict], today_by_stage: dict) -> dict:
    """The production matrix from card summaries (`[{card, style, status, rows:[{colour, size, order_qty, <STAGE>: qty}]}]`) and today's movements per stage code.
    Returns `{stages, cards:[{card, style, status, rows:[{colour,size,order_qty,cut,input,...}]}], totals:{order_qty, <key>: n}, pct:{<key>: %}, today:{<key>: n}}`.
    Pure arithmetic: no rule of the ERP is decided here."""
    out_cards = []
    tot = {"order_qty": 0.0, **{k: 0.0 for k, _l, _c in STAGES}}
    for c in cards:
        rows = []
        for r in c.get("rows") or []:
            row = {"colour": r.get("colour"), "size": r.get("size"), "order_qty": _num(r.get("order_qty")), "planned_cut_qty": _num(r.get("planned_cut_qty"))}
            for k, _l, code in STAGES:
                row[k] = _num(r.get(code))
                tot[k] += row[k]
            tot["order_qty"] += row["order_qty"]
            rows.append(row)
        out_cards.append({"card": c.get("card"), "style": c.get("style"), "status": c.get("status"), "rows": rows})
    pct = {k: (round(tot[k] / tot["order_qty"] * 100.0, 1) if tot["order_qty"] else 0.0) for k, _l, _c in STAGES}
    return {"stages": [{"key": k, "label": lbl, "code": c} for k, lbl, c in STAGES], "cards": out_cards, "totals": tot, "pct": pct,
            "today": {k: _num(today_by_stage.get(c)) for k, _l, c in STAGES}}


def _live_cards(be, chain: list) -> list[dict]:
    rows = be.get_list("Production Card", [["sales_order", "in", chain], ["docstatus", "!=", 2]],
                       ["name", "status", "docstatus", "style_item", "style_no", "factory", "line", "pcd", "ex_factory_date", "revision_no", "sales_order"], limit=200)
    return sorted(rows, key=lambda r: r["name"])


def _today_stages(be, chain: list, today: _dt.date) -> dict:
    out: dict = {}
    for r in be.get_list("Production Movement", [["sales_order", "in", chain], ["posting_date", "=", today.isoformat()]], ["stage", "qty"], limit=5000):
        out[r.get("stage")] = out.get(r.get("stage"), 0.0) + _num(r.get("qty"))
    return out


def _can(me: dict) -> bool:
    return guardrails.can(me["roles"], "Production Card", "write")


@guarded
def order_cutsew_get(db, me, sales_order: str = "", **_):
    """Everything the step-6 page shows for one order: the **production matrix** (stage cut / line input / sewn / QC pass / finished / packed x colour x size,
    from the ERP's `arinox_production_card_get_summary`, with the percentage of the order and what was posted today), the production cards with what can be
    done next, the cut plans (suggest rolls / release / approve / reopen), the operation bulletins of the styles and the recent line reports. Read only.
    Params: `sales_order`. Returns `{ok, head, matrix, cards, cut_plans, bulletins, reports, summary, can_write}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    guardrails.require(me["roles"], "Production Card", "read")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    today = _dt.date.today()
    cards = _live_cards(be, chain)
    live = [c for c in cards if int(c.get("docstatus") or 0) == 1 and c.get("status") not in DEAD]
    sums = []
    for c in live:
        s = read_script(me, "arinox_production_card_get_summary", {"name": c["name"]}) or {}
        sums.append({"card": c["name"], "style": c.get("style_no") or c.get("style_item"), "status": s.get("status") or c.get("status"), "rows": s.get("rows") or []})
    mx = build_matrix(sums, _today_stages(be, chain, today))
    plans = be.get_list("Cut Plan", [["sales_order", "in", chain]], ["name", "status", "production_card", "style_no", "colour", "fabric_item", "variance_pct", "approved_by", "approval_note"], limit=200)
    for p in plans:
        p["can_reopen"] = p.get("status") == "Released"
        p["can_release"] = p.get("status") == "Draft"
        p["can_approve"] = p.get("status") == "Pending Approval"
    styles = sorted({c.get("style_item") for c in cards if c.get("style_item")})
    obs = be.get_list("Operation Bulletin", [["style_item", "in", styles]], ["name", "style_item", "version", "status", "total_sam", "operators", "target_per_day"], limit=100) if styles else []
    names = [c["name"] for c in live]
    reports: list = []
    if names:
        for dt, key in (("Daily Line Report", "report_date"), ("Lay Report", "lay_date")):
            try:
                if dt == "Daily Line Report":
                    ch = be.get_list("Daily Line Report Output", [["production_card", "in", names]], ["parent"], limit=400, parent="Daily Line Report")
                    pn = sorted({x["parent"] for x in ch})
                    rows = be.get_list(dt, [["name", "in", pn]], ["name", key, "docstatus", "line", "total_output"], limit=60, order_by=key + " desc") if pn else []
                else:
                    rows = be.get_list(dt, [["production_card", "in", names]], ["name", key, "docstatus", "line", "pieces_cut"], limit=60, order_by=key + " desc")
                reports += [{"doctype": dt, "name": r["name"], "date": str(r.get(key) or ""), "docstatus": int(r.get("docstatus") or 0), "line": r.get("line"),
                             "qty": _num(r.get("total_output") if dt == "Daily Line Report" else r.get("pieces_cut"))} for r in rows]
            except Exception:                                # noqa: BLE001 - a report list that cannot be read must not hide the matrix
                pass
    reports.sort(key=lambda r: r["date"], reverse=True)
    t = mx["totals"]
    so = be.get_doc("Sales Order", head)
    order_qty = sum(_num(g["qty"]) for g in groups(be, so))
    return {"ok": True, "head": head, "matrix": mx, "can_write": _can(me), "order_qty": order_qty,
            "cards": [{**c, "can_approve": int(c.get("docstatus") or 0) == 0, "can_revise": int(c.get("docstatus") or 0) == 1 and c.get("status") not in DEAD} for c in cards],
            "cut_plans": plans, "bulletins": obs, "reports": reports[:20],
            "styles_without_card": sorted({g["style_item"] for g in groups(be, so)} - set(styles)),
            "summary": {"order_qty": order_qty, "sewn": t["sewn"], "cut": t["cut"], "sewn_pct": round(t["sewn"] / order_qty * 100.0, 1) if order_qty else 0.0,
                        "today_sewn": mx["today"]["sewn"], "cards": len(live)}}


@guarded
def order_card_context(db, me, sales_order: str = "", style_item: str = "", **_):
    """What a new Production Card needs, from the ERP (`arinox_production_card_get_production_context` and `_get_card_lines`): the styles of the order, the
    colour x size lines with the order quantity, the allocation (factory, line, PCD) and the defaults (extra cut %, bundle size). Read only.
    Params: `sales_order`, `style_item` (optional: only that style). Returns `{ok, head, customer, company, styles:[{style_item, lines, ex_factory_date, allocation, card}], defaults}`."""
    need(me, "make", "raise a production card")
    be = deals._be()
    _c, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    ctx = read_script(me, "arinox_production_card_get_production_context", {"sales_order": head}) or {}
    styles = [s for s in ctx.get("styles") or [] if not style_item or s.get("style_item") == style_item]
    for st in styles:                                     # the fabrics of the approved requisitions, as card rows (the cut and the fabric issue read them)
        frs = sorted({f.get("parent") for f in st.get("fabric_requisitions") or [] if f.get("parent")})
        st["fabrics"] = []
        if frs:
            for it in be.get_list("Fabric Requisition Item", [["parent", "in", frs], ["style_item", "=", st.get("style_item")]],
                                  ["name", "colour", "fabric_item", "consumption", "consumption_source", "consumption_uom"], limit=200, parent="Fabric Requisition"):
                if it.get("fabric_item") and _num(it.get("consumption")) > 0:
                    st["fabrics"].append({"colour": it.get("colour"), "fabric_item": it["fabric_item"], "consumption": _num(it["consumption"]), "consumption_source": "FR",
                                          "consumption_uom": it.get("consumption_uom") or "", "fabric_requisition_item": it.get("name"), "material_role": "Shell"})
    return {"ok": True, "head": head, "customer": so.get("customer"), "company": so.get("company"), "styles": styles, "defaults": ctx.get("defaults") or {}}


@guarded
def order_card_save(db, me, sales_order: str = "", style_item: str = "", header: dict | None = None, lines: list | None = None, fabrics: list | None = None, processes: list | None = None, name: str = "", preview: bool = False, **_):
    """Save a DRAFT Production Card through the ERP's script (`arinox_production_card_save_production_card`): its validation runs. Lines with no order
    quantity are never sent. Never submits (see `order_card_approve`). Params: `sales_order`, `style_item`, `header` (factory, line, ex_factory_date, pcd,
    bundle_size, default_extra_cut_pct, ...), `lines` (colour, size, order_qty, extra_cut_pct), `fabrics` (colour, fabric_item, consumption, ... as `order_card_context` gives them), `processes` (the route: subcontract_process, position Before Sewing / After Sewing, sequence, supplier, colour; a challan can only go to a process on the route), `name` (to update a draft), `preview`. Returns `{ok, name, red_flags}`."""
    need(me, "make", "raise a production card")
    be = deals._be()
    _c, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    rows = [clean(r) for r in (lines or []) if _num(r.get("order_qty")) > 0]
    if not rows:
        return {"ok": False, "error": "There is nothing to save: every line has no order quantity."}
    data = {"company": so.get("company"), "customer": so.get("customer"), "sales_order": head, "style_item": style_item, **clean(header or {}), "lines": rows}
    if processes:
        data["processes"] = [clean(x) for x in processes if (x.get("subcontract_process") or "").strip()]
    if fabrics:
        data["fabrics"] = [clean(f) for f in fabrics if _num(f.get("consumption")) > 0]
    if name:
        data["name"] = name
    res = _ex(db, me, {"op": "api", "method": "arinox_production_card_save_production_card", "doctype": "Production Card", "params": {"data": json.dumps(data, default=str)}},
              preview, "the production card")
    if not res.get("ok"):
        return res
    r = res.get("result")
    nm = r.get("name") if isinstance(r, dict) else (r if isinstance(r, str) else name)
    return {"ok": True, "name": nm, "red_flags": r.get("red_flags") if isinstance(r, dict) else None, "rows": len(rows), "preview": res.get("preview") if preview else None,
            "saved": not preview}


@guarded
def order_card_approve(db, me, name: str = "", preview: bool = False, **_):
    """Issue (submit) a draft Production Card: the ERP's own submit rules decide (pilot, bulk gate). Params: `name`, `preview`. Returns `{ok, name}`."""
    need(me, "make", "issue a production card")
    if not name:
        return {"ok": False, "error": "Say which production card."}
    return _ok(_ex(db, me, {"op": "submit", "doctype": "Production Card", "name": name}, preview, "the production card"), name, preview)


@guarded
def order_card_revise(db, me, name: str = "", reason: str = "", preview: bool = False, **_):
    """Revise an issued Production Card: the ERP makes a new draft revision (quantities refreshed from the order when it is saved). A reason is required.
    Params: `name`, `reason`, `preview`. Returns `{ok, name}`."""
    need(me, "make", "revise a production card")
    if not (reason or "").strip():
        return {"ok": False, "error": "Say why the production card is revised."}
    doc = read_script(me, "arinox_production_card_revise_production_card", {"source_name": name}) or {}
    data = clean(doc)
    data["revision_reason"] = reason.strip()
    res = _ex(db, me, {"op": "insert", "doctype": "Production Card", "data": data}, preview, "the revision")
    if not res.get("ok"):
        return res
    return {"ok": True, "name": (res.get("doc") or {}).get("name") or "", "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_cutplan_suggest(db, me, name: str = "", **_):
    """Suggest which accepted rolls go to which lay of a Cut Plan (`arinox_cut_plan_suggest_rolls`). Read only: nothing is saved. Params: `name`.
    Returns `{ok, suggestion}` as the ERP answers it."""
    need(me, "make", "plan a cut")
    if not name:
        return {"ok": False, "error": "Say which cut plan."}
    return {"ok": True, "name": name, "suggestion": read_script(me, "arinox_cut_plan_suggest_rolls", {"name": name})}


def _plan_api(db, me, method: str, name: str, preview: bool, label: str, extra: dict | None = None):
    if not name:
        return {"ok": False, "error": "Say which cut plan."}
    res = _ex(db, me, {"op": "api", "method": method, "doctype": "Cut Plan", "params": {"name": name, **(extra or {})}}, preview, label)
    if not res.get("ok"):
        return res
    pv = res.get("preview")
    pv = pv[0] if isinstance(pv, list) and pv else pv
    return {"ok": True, "name": name, "status": res.get("result") or (pv or {}).get("result"), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_cutplan_release(db, me, name: str = "", preview: bool = False, **_):
    """Release a Cut Plan (`arinox_cut_plan_release`). A marker variance above the limit sends it to a manager instead (the answer says `Pending Approval`).
    Params: `name`, `preview`. Returns `{ok, name, status}`."""
    need(me, "make", "release a cut plan")
    return _plan_api(db, me, "arinox_cut_plan_release", name, preview, "the release")


@guarded
def order_cutplan_approve(db, me, name: str = "", note: str = "", preview: bool = False, **_):
    """Accept a marker consumption that is outside the limit (`arinox_cut_plan_approve`): production or merchandising manager, a reason is required.
    Params: `name`, `note`, `preview`. Returns `{ok, name, status}`."""
    need(me, "make", "approve a cut plan")
    if not (note or "").strip():
        return {"ok": False, "error": "Write the reason for accepting this marker consumption."}
    return _plan_api(db, me, "arinox_cut_plan_approve", name, preview, "the approval", {"note": note.strip()})


@guarded
def order_cutplan_reopen(db, me, name: str = "", preview: bool = False, **_):
    """Send a Cut Plan back to draft (`arinox_cut_plan_reopen`), unless a lay was already cut from it. Params: `name`, `preview`. Returns `{ok, name, status}`."""
    need(me, "make", "reopen a cut plan")
    return _plan_api(db, me, "arinox_cut_plan_reopen", name, preview, "the reopening")


@guarded
def order_cut_issuable(db, me, card: str = "", **_):
    """The accepted rolls in the fabric store for the fabrics of a Production Card, with their free length (`arinox_cutting_get_issuable_rolls`). Read only.
    Params: `card`. Returns `{ok, rolls}`."""
    need(me, "make", "issue fabric")
    if not card:
        return {"ok": False, "error": "Say which production card."}
    return {"ok": True, "card": card, "rolls": read_script(me, "arinox_cutting_get_issuable_rolls", {"card": card}) or []}


@guarded
def order_cut_issue(db, me, card: str = "", rolls: list | None = None, preview: bool = False, approval_id: int = 0, **_):
    """Issue rolls to the cutting floor (`arinox_cutting_issue_fabric`, a Stock Entry). Rolls with no quantity are never sent. A risky class: the answer is
    `needs_approval` with an `approval_id` until a manager approves; run it again with that `approval_id`. Params: `card`, `rolls` ([{batch_no, qty}]),
    `preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`."""
    need(me, "make", "issue fabric")
    sent = [{"batch_no": r.get("batch_no") or r.get("batch"), "qty": _num(r.get("qty"))} for r in (rolls or []) if _num(r.get("qty")) > 0]
    if not card or not sent:
        return {"ok": False, "error": "Say which production card and give at least one roll with a quantity."}
    res = deals._ex(db, me, {"op": "api", "method": "arinox_cutting_issue_fabric", "doctype": "Stock Entry", "preview": bool(preview), "approval_id": approval_id or None,
                             "params": {"card": card, "rolls": json.dumps(sent)}})
    if res.get("needs_approval"):
        return {"ok": False, "needs_approval": True, "approval_id": res.get("approval_id"), "error": res.get("error"), "preview": res.get("preview")}
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the issue.")), "preview": res.get("preview")}
    r = res.get("result")
    return {"ok": True, "name": r if isinstance(r, str) else "", "rolls": len(sent), "preview": res.get("preview") if preview else None, "saved": not preview}


@guarded
def order_ob_activate(db, me, name: str = "", preview: bool = False, **_):
    """Make an Operation Bulletin the active one of its style; the earlier one is superseded (`arinox_operation_bulletin_activate`). Needs the operation times.
    Params: `name`, `preview`. Returns `{ok, name}`."""
    need(me, "make", "activate an operation bulletin")
    if not name:
        return {"ok": False, "error": "Say which operation bulletin."}
    return _ok(_ex(db, me, {"op": "api", "method": "arinox_operation_bulletin_activate", "doctype": "Operation Bulletin", "params": {"name": name}}, preview, "the activation"), name, preview)


def _card_room(summary_rows: list) -> list[dict]:
    """Rows a daily line report can still carry: sizes with line input (or cut when nothing is on a line) not yet sewn."""
    out = []
    for r in summary_rows:
        base = _num(r.get("SEW_IN")) or _num(r.get("CUT"))
        room = base - _num(r.get("SEW_OUT")) - _num(r.get("SEW_REJECT"))
        if room > 0:
            out.append({"colour": r.get("colour"), "size": r.get("size"), "available": room})
    return out


@guarded
def order_prefill(db, me, sales_order: str = "", kind: str = "", card: str = "", name: str = "", **_):
    """The pre-filled starting values of a floor document, for the generic form: `kind` is `dlr` (Daily Line Report: today, the card's line, one output row per
    colour x size that can still be reported, quantity = what is left), `lay` (Lay Report header from the cut plan), `line_input` (one row per colour x size cut and not yet loaded), `cut_plan` or
    `operation_bulletin` (header only). Read only; nothing is created. Params: `sales_order`, `kind`, `card` (default: the first live card), `name` (a cut plan
    for `lay`). Returns `{ok, doctype, initial, note}`."""
    need(me, "make", "make a floor document")
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    today = _dt.date.today().isoformat()
    cards = [c for c in _live_cards(be, chain) if int(c.get("docstatus") or 0) == 1 and c.get("status") not in DEAD]
    c = next((x for x in cards if x["name"] == card), None) if card else (cards[0] if cards else None)
    if kind in ("dlr", "lay", "line_input", "cut_plan") and not c:
        return {"ok": False, "error": "Issue a production card first: floor documents are made against an issued card."}
    if kind == "dlr":
        s = read_script(me, "arinox_production_card_get_summary", {"name": c["name"]}) or {}
        room = _card_room(s.get("rows") or [])
        if not room:
            return {"ok": False, "error": "Nothing is left to report: there is no cut or line input that has not been sewn yet."}
        bund = be.get_list("Cut Bundle", [["production_card", "=", c["name"]], ["status", "=", "Issued"], ["purpose", "=", "Bulk"]], ["name", "colour", "size", "qty", "sewn_qty", "rejected_qty"], limit=500)
        rows = [{"production_card": c["name"], "colour": b["colour"], "size": b["size"], "qty": int(_num(b["qty"]) - _num(b.get("sewn_qty")) - _num(b.get("rejected_qty"))), "purpose": "Bulk", "bundle": b["name"]}
                for b in bund if _num(b["qty"]) - _num(b.get("sewn_qty")) - _num(b.get("rejected_qty")) > 0]
        if not rows:
            rows = [{"production_card": c["name"], "colour": r["colour"], "size": r["size"], "qty": int(r["available"]), "purpose": "Bulk"} for r in room]
        return {"ok": True, "doctype": "Daily Line Report", "note": "Quantities are what could still be reported on this card (one row per loaded bundle); change them to what the line made.",
                "initial": {"report_date": today, "line": c.get("line") or "", "outputs": rows}}
    if kind == "lay":
        initial = {"production_card": c["name"], "lay_date": today, "purpose": "Bulk", "line": c.get("line") or ""}
        if name:
            p = be.get_doc("Cut Plan", name)
            lays = p.get("lays") or []
            done = {x.get("lay_no") for x in be.get_list("Lay Report", [["cut_plan", "=", name], ["docstatus", "=", 1]], ["lay_no"], limit=200)}
            nxt = next((x for x in lays if x.get("lay_no") not in done), None)
            initial.update({"cut_plan": name, "colour": p.get("colour"), "fabric_item": p.get("fabric_item"), "component": p.get("component")})
            if nxt:
                initial.update({"lay_no": nxt.get("lay_no"), "marker_ref": nxt.get("marker_ref"), "marker_length_m": nxt.get("marker_length_m"), "marker_width_cm": nxt.get("marker_width_cm"),
                                "shade_band": nxt.get("shade_band")})
        return {"ok": True, "doctype": "Lay Report", "initial": clean(initial), "note": "Add the rolls and the size ratios of the lay."}
    if kind == "line_input":
        bund = be.get_list("Cut Bundle", [["production_card", "=", c["name"]], ["status", "in", ["Cut", "Back"]], ["purpose", "=", "Bulk"]], ["name", "colour", "size", "qty", "component"], limit=500)
        rows = [{"bundle": b["name"], "colour": b["colour"], "size": b["size"], "qty": int(_num(b["qty"]))} for b in bund if (b.get("component") or "Shell") == "Shell"]
        if not rows:
            s = read_script(me, "arinox_production_card_get_summary", {"name": c["name"]}) or {}
            rows = [{"colour": r["colour"], "size": r["size"], "qty": int(_num(r.get("CUT")) - _num(r.get("SEW_IN")))} for r in s.get("rows") or [] if _num(r.get("CUT")) - _num(r.get("SEW_IN")) > 0]
        if not rows:
            return {"ok": False, "error": "Nothing is cut and waiting to be loaded on a line."}
        return {"ok": True, "doctype": "Line Input", "initial": {"production_card": c["name"], "input_date": today, "line": c.get("line") or "", "purpose": "Bulk", "bundles": rows},
                "note": "One row per cut bundle not yet loaded; choose the line and remove the bundles that are not loaded today."}
    if kind == "cut_plan":
        return {"ok": True, "doctype": "Cut Plan", "initial": {"production_card": c["name"], "sales_order": head, "style_no": c.get("style_no")}, "note": "Choose the colour and the fabric."}
    if kind == "operation_bulletin":
        st = c["style_item"] if c else (groups(be, be.get_doc("Sales Order", head)) or [{}])[0].get("style_item")
        return {"ok": True, "doctype": "Operation Bulletin", "initial": {"style_item": st, "version": 1, "status": "Draft"}, "note": "Add the operations with their times, then activate."}
    return {"ok": False, "error": "kind is dlr, lay, line_input, cut_plan or operation_bulletin"}


# ───────────────────────── the production board (replaces the Cortex WIP screen) ─────────────────────────

@guarded
def production_board_get(db, me, limit: int = 80, **_):
    """The production board: every order with a live Production Card, one row each with order quantity, cut, line input, sewn, QC pass, finished, packed
    (the Production Movement ledger), the sewn percentage of the order and what was sewn today. Read only; this is the Arinox reader that replaces the old
    Cortex WIP screen (`erp_profile` = arinox). Params: `limit`. Returns `{ok, rows, totals, erp_profile}`."""
    guardrails.require(me["roles"], "Production Card", "read")
    be = deals._be()
    prof = order_flow.erp_profile(be)
    cards = be.get_list("Production Card", [["docstatus", "=", 1], ["status", "not in", list(DEAD)]], ["name", "sales_order", "style_no", "style_item", "status", "line", "ex_factory_date"], limit=500)
    by_so: dict = {}
    for c in cards:
        by_so.setdefault(c["sales_order"], []).append(c)
    sos = sorted(by_so)[: int(limit or 80)]
    qty: dict = {}
    for part in order_flow._chunks(sos):
        for r in be.get_list("Production Card Line", [["parent", "in", [c["name"] for s in part for c in by_so[s]]]], ["parent", "order_qty"], limit=20000, parent="Production Card"):
            qty[r["parent"]] = qty.get(r["parent"], 0.0) + _num(r.get("order_qty"))
    today = _dt.date.today().isoformat()
    led: dict = {}
    tod: dict = {}
    for part in order_flow._chunks(sos):
        for r in be.get_list("Production Movement", [["sales_order", "in", part]], ["sales_order", "stage", "qty", "posting_date"], limit=50000):
            d = led.setdefault(r["sales_order"], {})
            d[r["stage"]] = d.get(r["stage"], 0.0) + _num(r.get("qty"))
            if str(r.get("posting_date") or "")[:10] == today and r["stage"] == "SEW_OUT":
                tod[r["sales_order"]] = tod.get(r["sales_order"], 0.0) + _num(r.get("qty"))
    rows = []
    for s in sos:
        cs = by_so[s]
        oq = sum(qty.get(c["name"], 0.0) for c in cs)
        l = led.get(s, {})
        row = {"sales_order": s, "styles": sorted({c.get("style_no") or c.get("style_item") or "" for c in cs}), "cards": len(cs), "order_qty": oq,
               "ex_factory_date": min((str(c.get("ex_factory_date") or "") for c in cs if c.get("ex_factory_date")), default=""), "today_sewn": tod.get(s, 0.0),
               **{k: l.get(code, 0.0) for k, _l, code in STAGES}}
        row["sewn_pct"] = round(row["sewn"] / oq * 100.0, 1) if oq else 0.0
        rows.append(row)
    keys = ["order_qty", "today_sewn"] + [k for k, _l, _c in STAGES]
    return {"ok": True, "rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "stages": [{"key": k, "label": lbl} for k, lbl, _c in STAGES], "erp_profile": prof}


FUNCTIONS: dict[str, Callable] = {"order_cutsew_get": order_cutsew_get, "order_card_context": order_card_context, "order_card_save": order_card_save,
                                  "order_card_approve": order_card_approve, "order_card_revise": order_card_revise, "order_cutplan_suggest": order_cutplan_suggest,
                                  "order_cutplan_release": order_cutplan_release, "order_cutplan_approve": order_cutplan_approve, "order_cutplan_reopen": order_cutplan_reopen,
                                  "order_cut_issuable": order_cut_issuable, "order_cut_issue": order_cut_issue, "order_ob_activate": order_ob_activate,
                                  "order_prefill": order_prefill, "production_board_get": production_board_get}
