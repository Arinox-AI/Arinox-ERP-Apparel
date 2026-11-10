"""The functions the Order page calls (one Sales Order from confirmation to commercial close).

Calling convention ``fn(db, **params) -> dict``. Every function resolves the signed-in caller first (``guarded``) and
checks role permission server-side. S1 is read-only: nothing here writes to the ERP. Writes (allocation, T&A, ...) arrive
with their slices and go through ``pipeline.execute`` like every other write.
"""

from __future__ import annotations

from typing import Callable

from tsr.errors import TSRError

import allocation
import deal_api
import tna_plan
import order_alloc
import requests
import deals
import guardrails
import order_flow

guarded = deal_api.guarded

#: what "the ERP is down" means: a network failure or a TSR transport error. Anything else is a bug and is not hidden.
_DOWN = (requests.RequestException, ConnectionError, TimeoutError, TSRError)

#: step -> guardrail group whose read restriction applies to its documents (``guardrails.READ_RESTRICTED``)
_STEP_GROUP = {"invoice": "accounts"}


def _readable(me: dict, step: str) -> bool:
    group = _STEP_GROUP.get(step)
    allowed = guardrails.READ_RESTRICTED.get(group) if group else None
    return not allowed or bool(set(me["roles"]) & set(allowed)) or bool(me.get("is_admin"))


def _filter_for(me: dict, out: dict) -> dict:
    """Hide the steps the caller's role may not read: the shape stays, the contents go."""
    for st in out.get("steps", []):
        if not _readable(me, st["key"]):
            st.update(docs=[], blockers=[], counts={}, by_type={}, next={}, restricted=True)
    return out


def _timeline(db, be, chain: list) -> list:
    """ERP comments on the order and the tower's own audit lines that name it, newest first (at most 40)."""
    import re
    from models import AuditLogModel
    rows: list = []
    try:
        for c in be.get_list("Comment", [["reference_doctype", "=", "Sales Order"], ["reference_name", "in", chain], ["comment_type", "=", "Comment"]],
                             ["content", "creation", "owner"], order_by="creation desc", limit=30):
            rows.append({"at": str(c.get("creation") or "")[:19], "by": c.get("owner") or "", "kind": "erp",
                         "text": re.sub(r"<[^>]+>", " ", str(c.get("content") or "")).strip()[:300]})
    except Exception:                                       # noqa: BLE001 - the timeline is a courtesy, never a failure
        pass
    try:
        from sqlalchemy import or_
        q = db.query(AuditLogModel).filter(or_(*[AuditLogModel.description.contains(n) for n in chain])).order_by(AuditLogModel.id.desc()).limit(30)
        for a in q.all():
            rows.append({"at": (a.timestamp.isoformat() if a.timestamp else "")[:19].replace("T", " "), "by": a.actor or "", "kind": "tower",
                         "text": (a.description or "")[:300]})
    except Exception:                                       # noqa: BLE001
        pass
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:40]


@guarded
def order_get(db, me, sales_order: str = "", **_):
    """One Sales Order's whole post-order picture: header, ten steps (state, counts, documents, blockers, next action), each
    step's ERP page and the one the order is on now. Read only; follows amendments (`-1`) and shows earlier documents as
    history. Params: `sales_order`. Returns `{ok, sales_order, head, steps, by_step, focus, next, kpis, header, timeline, errors, erp_profile}`;
    on an ERP outage `{ok: false, stale: true, error}` (the page keeps what it showed and refuses writes)."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    try:
        out = order_flow.status(deals._be(), str(sales_order))
    except _DOWN as e:                                      # ERP down: tell the page, never a traceback
        return {"ok": False, "stale": True, "error": f"The ERP could not be reached: {str(e)[:160]}"}
    if not out.get("ok"):
        return out
    out["timeline"] = _timeline(db, deals._be(), out["chain"])
    return _filter_for(me, out)


@guarded
def order_list(db, me, q: str = "", limit: int = 60, open_only: bool = True, **_):
    """The order book: submitted Sales Orders with one chip per step. Params: `q` (name or customer), `limit`, `open_only`.
    Returns `{ok, orders:[{name, customer, customer_name, delivery_date, grand_total, currency, status, url, chips}], erp_profile}`."""
    be = deals._be()
    try:
        rows = order_flow.order_book(be, int(limit or 60), q or "", bool(open_only))
    except _DOWN as e:
        return {"ok": False, "stale": True, "error": f"The ERP could not be reached: {str(e)[:160]}"}
    return {"ok": True, "orders": rows, "erp_profile": order_flow.erp_profile(be)}


# ───────────────────────── 2 · plan and allocate (where to produce) ─────────────────────────

def _planner(me: dict):
    if not set(me["roles"]) & set(guardrails.WRITE["plan"] + guardrails.ALL_POWER):
        raise guardrails.Denied("Your role can read the allocation but not change it. Ask a planner or a manager.")


def _planning(db, me, sales_order: str) -> dict:
    """The planning-context script of the ERP, through the pipeline (so the same rules and the same audit as every other write)."""
    res = deals._must(deals._ex(db, me, {"op": "api", "method": "arinox_factory_allocation_get_planning_context",
                                         "params": {"sales_order": sales_order}}), "The ERP could not give the planning context")
    return res.get("result") or {}


def _head_of(be, sales_order: str) -> str:
    """An amended Sales Order (`-1`) replaces the one it amends: allocation and planning always work on the live version."""
    try:
        return order_flow._sales_order_chain(be, str(sales_order))[1] or str(sales_order)
    except _DOWN:
        raise
    except Exception:                                       # noqa: BLE001 - an unknown name falls through to the ERP's own answer
        return str(sales_order)


@guarded
def order_allocation_get(db, me, sales_order: str = "", suggest: bool = True, **_):
    """Everything the allocation board shows for one order: the order's style x colour lines, the factories with their lines and
    headcount, the 8-week load of each line, the allocation already saved, the suggestion (deterministic, with a reason sentence
    per line and a shortfall for what does not fit) and the setup checklist. Read only. Params: `sales_order`, `suggest`.
    Returns `{ok, order_lines, factories, load_strip, current, suggestion, setup, settings, planned_by}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    _planner(me)
    import datetime as _dt
    be = deals._be()
    sales_order = _head_of(be, sales_order)
    planning = _planning(db, me, str(sales_order))
    ctx = order_alloc.build_ctx(be, planning, _dt.date.today())
    out = {"ok": True, "sales_order": sales_order, "order_lines": ctx["order_lines"], "factories": ctx["factories"],
           "load_strip": order_alloc.load_strip(ctx), "current": planning.get("current_allocation"),
           "setup": order_alloc.setup_checklist(be, ctx),
           "settings": {k: ctx["settings"][k] for k in ("work_minutes_per_day", "planned_efficiency_pct", "finish_pack_days", "cut_lead_days", "min_batch_qty")}}
    if suggest:
        out["suggestion"] = allocation.suggest(ctx)
    return out


@guarded
def order_alloc_suggest_defaults(db, me, **_):
    """Propose SAM and efficiency per Product Type from the tenant's own Operation Bulletins and Daily Line Reports. Read only."""
    _planner(me)
    return order_alloc.suggest_defaults(deals._be())


@guarded
def order_allocation_save(db, me, sales_order: str = "", lines: list | None = None, planned_by: str = "Manual", agent_notes: str = "",
                          preview: bool = False, **_):
    """Save the allocation of an order through the ERP's own script (`arinox_factory_allocation_save_allocation`), so the ERP's
    validation runs: the order must be submitted, each row a style x colour of the order, the line in its factory, the dates in
    order, and nothing above the order plus tolerance. With `preview` nothing is saved and the ERP's answer (or refusal) comes
    back, which is the live validation the board shows before save. `planned_by` is `AI Agent` when the suggestion was saved
    untouched, else `Manual`; `agent_notes` keeps the reasoning. Zero-quantity rows are never sent. Params: `sales_order`, `lines`,
    `planned_by`, `agent_notes`, `preview`. Returns `{ok, name}` or `{ok: false, error}`."""
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    _planner(me)
    keep = ("style_item", "style_no", "colour", "qty", "factory", "line", "pcd", "sewing_start", "sewing_end", "ship_to", "buyer_po", "reason")
    clean = []
    for ln in lines or []:
        try:
            q = int(float(ln.get("qty") or 0))
        except (TypeError, ValueError):
            q = 0
        if q <= 0:
            continue                                         # never a zero-quantity row (FIXES 2026-11-09 section 1)
        row = {k: ln.get(k) for k in keep if ln.get(k) not in (None, "")}
        row["qty"] = q
        clean.append(row)
    if not clean:
        return {"ok": False, "error": "There is nothing to save: every row has no quantity."}
    by = "AI Agent" if planned_by == "AI Agent" else "Manual"
    sales_order = _head_of(deals._be(), sales_order)
    res = deals._ex(db, me, {"op": "api", "method": "arinox_factory_allocation_save_allocation", "preview": bool(preview),
                             "params": {"sales_order": sales_order, "lines": clean, "planned_by": by, "agent_notes": agent_notes or ""}})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the allocation.")), "preview": res.get("preview")}
    name = res.get("result")
    return {"ok": True, "name": name if isinstance(name, str) else "", "preview": res.get("preview"), "saved": not preview, "planned_by": by}


# ───────────────────────── 3 · T&A plan ─────────────────────────

def _plan_pack(db, be, tna: dict, so: dict | None, today) -> dict:
    from models_tna import PlanBaselineModel, PlanRevisionModel
    rows = tna_plan.read_milestones(be, tna["name"]) if tna.get("name") and not str(tna["name"]).startswith("(") else []
    plan = tna_plan.compute(tna, rows, today, so)
    out = {"order_tna": tna.get("name"), "style_no": tna.get("style_no") or tna.get("style_item"), "colour": tna.get("colour"), "qty": tna.get("order_qty"),
           "ex_factory": str(tna.get("ex_factory_date") or ""), "locked": bool(int(tna.get("baseline_locked") or 0)), "url": "", **tna_plan.view(plan, rows)}
    if out["order_tna"] and not str(out["order_tna"]).startswith("("):
        import erp as _erp
        out["url"] = _erp.url_for("Order TNA", out["order_tna"])
        out["baselines"] = [{"version": b.version, "locked_by": b.locked_by, "locked_at": b.locked_at.isoformat() if b.locked_at else "", "ex_factory": b.ex_factory}
                            for b in db.query(PlanBaselineModel).filter(PlanBaselineModel.order_tna == tna["name"]).order_by(PlanBaselineModel.version).all()]
        out["revisions"] = [{"code": r.code, "old": r.old_date, "new": r.new_date, "reason_code": r.reason_code, "note": r.reason_note, "by": r.actor, "approved_by": r.approved_by,
                             "ship_impact_wd": r.ship_impact_wd, "at": r.created_at.isoformat() if r.created_at else ""}
                            for r in db.query(PlanRevisionModel).filter(PlanRevisionModel.order_tna == tna["name"]).order_by(PlanRevisionModel.id.desc()).limit(30).all()]
    return out


@guarded
def order_tna_get(db, me, sales_order: str = "", **_):
    """The T&A of one order, per style x colour: every milestone with its three date lanes (baseline, forecast, actual), float, status
    and the document that proves it, the ship feasibility as a number of working days, the baselines and revisions. Read only. When the ERP
    has no Order TNA yet the plan is a **proposal** computed from the allocation's PCD and the order's ex-factory dates (nothing written).
    Params: `sales_order`. Returns `{ok, proposed, plans:[{order_tna, style_no, colour, ex_factory, locked, rows, summary, baselines, revisions}]}`."""
    import datetime as _dt
    import order_flow
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    be = deals._be()
    try:
        chain, head = order_flow._sales_order_chain(be, str(sales_order))
        tnas = tna_plan.order_tnas(be, chain)
        so = be.get_doc("Sales Order", head)
        today = _dt.date.today()
        if tnas:
            return {"ok": True, "proposed": False, "head": head, "plans": [_plan_pack(db, be, t, so, today) for t in tnas]}
        fa = be.get_list("Factory Allocation", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["name"], limit=1)
        lines = be.get_list("Factory Allocation Line", [["parent", "=", fa[0]["name"]]], ["style_item", "colour", "qty", "pcd", "ex_factory_date", "factory"], limit=200, parent="Factory Allocation") if fa else []
        groups: dict = {}
        for it in so.get("items") or []:
            k = ((it.get("item_code") or "").rsplit("-", 2)[0], it.get("apparel_colour") or "")
            g = groups.setdefault(k, {"qty": 0, "ex": it.get("delivery_date") or so.get("delivery_date")})
            g["qty"] += float(it.get("qty") or 0)
        plans = []
        for ln in lines or []:
            t = {"name": "(proposed)", "style_item": ln["style_item"], "style_no": ln["style_item"], "colour": ln.get("colour"), "order_qty": ln.get("qty"), "ex_factory_date": ln.get("ex_factory_date") or so.get("delivery_date"),
                 "order_received_date": so.get("transaction_date"), "pcd": ln.get("pcd"), "baseline_locked": 0}
            plans.append(_plan_pack(db, be, t, so, today))
        if not plans:
            t = {"name": "(proposed)", "style_item": "", "style_no": "the order", "colour": "", "order_qty": sum(g["qty"] for g in groups.values()), "ex_factory_date": so.get("delivery_date"),
                 "order_received_date": so.get("transaction_date"), "pcd": None, "baseline_locked": 0}
            plans.append(_plan_pack(db, be, t, so, today))
        return {"ok": True, "proposed": True, "head": head, "plans": plans, "note": "Proposed from the allocation and the order. Nothing is written to the ERP until you make the plan."}
    except _DOWN as e:
        return {"ok": False, "stale": True, "error": f"The ERP could not be reached: {str(e)[:160]}"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def _t_planner(me: dict):
    if not set(me["roles"]) & set(guardrails.WRITE["plan"] + guardrails.ALL_POWER):
        raise guardrails.Denied("Your role can read the T&A but not change it. Ask a planner, a merchandiser or a manager.")


def _tna_groups(be, chain: list, head: str, so: dict) -> list[dict]:
    """One group per style x colour x ex-factory date: from the saved allocation when there is one (it carries the PCD), else from the order."""
    fa = be.get_list("Factory Allocation", [["sales_order", "in", chain], ["docstatus", "!=", 2]], ["name"], limit=1)
    out = []
    if fa:
        for ln in be.get_list("Factory Allocation Line", [["parent", "=", fa[0]["name"]]], ["style_item", "colour", "qty", "pcd", "ex_factory_date", "factory"], limit=200, parent="Factory Allocation"):
            out.append({"style_item": ln["style_item"], "colour": ln.get("colour") or "", "qty": ln.get("qty"), "pcd": ln.get("pcd"), "factory": ln.get("factory"),
                        "ex_factory": ln.get("ex_factory_date") or so.get("delivery_date")})
    if out:
        merged: dict = {}
        for g in out:                                           # two lines of one style x colour (a split) are one plan
            k = (g["style_item"], g["colour"], str(g["ex_factory"]))
            m = merged.setdefault(k, {**g, "qty": 0})
            m["qty"] += float(g["qty"] or 0)
            m["pcd"] = min([x for x in (m.get("pcd"), g.get("pcd")) if x] or [None]) if (m.get("pcd") or g.get("pcd")) else None
        return list(merged.values())
    groups: dict = {}
    for it in so.get("items") or []:
        style = (it.get("item_code") or "").split("-")[0] if False else None
        base = be.get_list("Item", [["name", "=", it.get("item_code")]], ["variant_of"], limit=1)
        style = (base[0].get("variant_of") if base else None) or it.get("item_code")
        k = (style, it.get("apparel_colour") or "", str(it.get("delivery_date") or so.get("delivery_date")))
        g = groups.setdefault(k, {"style_item": style, "colour": it.get("apparel_colour") or "", "qty": 0, "pcd": None, "factory": None, "ex_factory": it.get("delivery_date") or so.get("delivery_date")})
        g["qty"] += float(it.get("qty") or 0)
    return list(groups.values())


@guarded
def order_tna_make(db, me, sales_order: str = "", preview: bool = False, **_):
    """Make the T&A of the order: one Order TNA per style x colour x ex-factory date (created through the pipeline, so the ERP's rules
    and the audit apply), then the tower's computed dates written onto its milestones in ONE call per plan (`arinox_tna_apply_plan`), so
    the ERP desk and the tower show the same plan. Idempotent: an existing Order TNA is kept and only re-dated; a locked plan is never
    touched here. With `preview` nothing is written and the ERP's own preview of each Order TNA comes back. Roles: planner, sampling,
    merchandiser, manager. Params: `sales_order`, `preview`. Returns `{ok, made:[names], written:[{order_tna, made, moved, kept}], preview}`."""
    import datetime as _dt
    import order_flow
    _t_planner(me)
    if not sales_order:
        return {"ok": False, "error": "Say which Sales Order."}
    be = deals._be()
    chain, head = order_flow._sales_order_chain(be, str(sales_order))
    so = be.get_doc("Sales Order", head)
    if int(so.get("docstatus") or 0) != 1:
        return {"ok": False, "error": f"Sales Order {head} must be submitted before its T&A is planned."}
    tnas = tna_plan.order_tnas(be, chain)
    have = {(t.get("style_item"), (t.get("colour") or ""), str(t.get("ex_factory_date"))) for t in tnas}
    groups = _tna_groups(be, chain, head, so)
    if not groups:
        return {"ok": False, "error": "The order has no lines to plan."}
    made, previews = [], []
    for g in groups:
        if (g["style_item"], g["colour"], str(g["ex_factory"])) in have:
            continue
        data = {"doctype": "Order TNA", "sales_order": head, "style_item": g["style_item"], "style_no": g["style_item"], "colour": g["colour"], "order_qty": int(g["qty"] or 0),
                "ex_factory_date": str(g["ex_factory"]), "order_received_date": str(so.get("transaction_date") or ""), "pcd": g.get("pcd") or None, "factory": g.get("factory") or None}
        data = {k: v for k, v in data.items() if v not in (None, "")}
        res = deals._ex(db, me, {"op": "insert", "doctype": "Order TNA", "data": data, "preview": bool(preview),
                                 "idem_key": f"tna-make-{head}-{g['style_item']}-{g['colour']}-{g['ex_factory']}"})
        if not res.get("ok"):
            return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the Order TNA.")), "made": made}
        if preview:
            previews.append(res.get("preview"))
        else:
            made.append((res.get("doc") or {}).get("name") or "")
    if preview:
        return {"ok": True, "preview": previews, "made": [], "written": []}
    tnas = tna_plan.order_tnas(be, chain)
    written, today = [], _dt.date.today()
    for t in tnas:
        if int(t.get("baseline_locked") or 0):
            written.append({"order_tna": t["name"], "locked": True, "note": "locked: use a revision"})
            continue
        rows = tna_plan.read_milestones(be, t["name"])
        plan = tna_plan.compute(t, rows, today, so)
        payload = [{"milestone_type": c, "planned_start": str(plan["tasks"][c]["planned_start"]), "planned_date": str(plan["tasks"][c]["planned_finish"]), "sequence": (i + 1) * 10,
                    "is_critical": 1 if plan["tasks"][c]["is_critical"] else 0} for i, c in enumerate(plan["order"]) if not plan["tasks"][c]["not_applicable"]]
        s = plan["summary"]
        res = deals._ex(db, me, {"op": "api", "method": "arinox_tna_apply_plan", "doctype": "Order TNA", "name": t["name"],
                                 "params": {"order_tna": t["name"], "rows": payload, "plan_feasible": 1 if s["plan_feasible"] else 0, "feasibility_note": s["message"][:140],
                                            "critical_delay_days": s["plan_infeasible_by_wd"]}})
        if not res.get("ok"):
            return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the plan.")), "made": made, "written": written}
        written.append({"order_tna": t["name"], **(res.get("result") if isinstance(res.get("result"), dict) else {})})
    return {"ok": True, "made": made, "written": written, "preview": False}


@guarded
def order_tna_lock(db, me, sales_order: str = "", order_tna: str = "", **_):
    """Lock the baseline of one Order TNA (the agreed plan). Refused when the plan is infeasible or not fully written to the ERP. The
    snapshot is kept forever (version 1, 2, ...). Params: `sales_order`, `order_tna`. Returns `{ok, version}`."""
    import datetime as _dt
    _t_planner(me)
    be = deals._be()
    t = next((x for x in tna_plan.order_tnas(be, [sales_order]) if x["name"] == order_tna), None) if True else None
    if not t:
        import order_flow
        chain, _h = order_flow._sales_order_chain(be, str(sales_order))
        t = next((x for x in tna_plan.order_tnas(be, chain) if x["name"] == order_tna), None)
    if not t:
        return {"ok": False, "error": f"Order T&A {order_tna} was not found on {sales_order}."}
    rows = tna_plan.read_milestones(be, t["name"])
    return tna_plan.lock(db, me, be, t, rows, tna_plan.compute(t, rows, _dt.date.today(), None))


@guarded
def order_tna_revise(db, me, sales_order: str = "", order_tna: str = "", code: str = "", new_date: str = "", reason_code: str = "", note: str = "", **_):
    """Move one milestone's date on a locked plan (the revised date): a reason code (Buyer, Supplier, Factory, Logistics, Other) and a note
    are required; a move that changes the forecast ship date needs a merchandising manager. The baseline never moves; every revision is
    kept with who, why and the ship impact. Params: `sales_order`, `order_tna`, `code`, `new_date`, `reason_code`, `note`.
    Returns `{ok, ship_before, ship_after}` or `{ok: false, need_approval: true}`."""
    import datetime as _dt
    _t_planner(me)
    be = deals._be()
    import order_flow
    chain, _h = order_flow._sales_order_chain(be, str(sales_order))
    t = next((x for x in tna_plan.order_tnas(be, chain) if x["name"] == order_tna), None)
    if not t:
        return {"ok": False, "error": f"Order T&A {order_tna} was not found on {sales_order}."}
    if not int(t.get("baseline_locked") or 0):
        return {"ok": False, "error": "The plan is not locked. Before the lock a date is simply re-planned; revisions are for a locked plan."}
    rows = tna_plan.read_milestones(be, t["name"])
    return tna_plan.revise(db, me, be, t, rows, tna_plan.compute(t, rows, _dt.date.today(), None), code, new_date, reason_code, note)


@guarded
def order_tna_health(db, me, **_):
    """Evidence sources at a glance: for every Arinox document type the T&A reads, whether it exists on the ERP and how many documents it
    has, plus the contract test of every field the rules read (a missing document type is a configuration error, never skipped).
    Returns `{ok, sources, missing, empty, contract}`."""
    from tna_engine import evidence_rules
    be = deals._be()
    h = evidence_rules.health(be)
    return {"ok": True, **h, "contract": evidence_rules.contract(be), "rules": len(evidence_rules.RULES)}


FUNCTIONS: dict[str, Callable] = {"order_get": order_get, "order_list": order_list,
                                  "order_allocation_get": order_allocation_get, "order_allocation_save": order_allocation_save, "order_alloc_suggest_defaults": order_alloc_suggest_defaults,
                                  "order_tna_get": order_tna_get, "order_tna_make": order_tna_make, "order_tna_lock": order_tna_lock,
                                  "order_tna_revise": order_tna_revise, "order_tna_health": order_tna_health}
