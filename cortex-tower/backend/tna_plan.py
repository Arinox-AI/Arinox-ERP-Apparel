"""The T&A writer and reader of the Order page (TNA plan phases 0 and 1): the one module that writes the tower's T&A fields.

Reads: the order's `Order TNA` documents and their `TNA Milestone` rows (the plan of record) and computes the plan with
``tna_engine.scheduler`` (baseline, earliest, latest, forecast, float, feasibility as a number). Writes: only through the ERP's own
scripts run by the pipeline (``arinox_planner_make_order_tnas``, ``arinox_tna_apply_plan``, ``arinox_order_tna_lock_baseline``), so
role checks, the field guard, the journal and the audit apply, and ``tna_engine.ownership`` says which fields are the tower's.
Baselines and revisions are kept in the tower's own tables (``models_tna``), forever.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

import deals
import guardrails
from models_tna import PlanBaselineModel, PlanRevisionModel
from tna_engine import ownership, scheduler, template, vocab
from tna_engine.calendars import as_date, load_calendars

REASON_CODES = ("Buyer", "Supplier", "Factory", "Logistics", "Other")
_TPL = None


def tpl() -> dict:
    global _TPL
    if _TPL is None:
        _TPL = template.load()
    return _TPL


def order_tnas(be, so_names: list) -> list[dict]:
    return be.get_list("Order TNA", [["sales_order", "in", so_names], ["status", "!=", "Cancelled"]],
                       ["name", "sales_order", "style_item", "style_no", "colour", "order_qty", "ex_factory_date", "order_received_date", "pcd", "factory", "template",
                        "plan_feasible", "feasibility_note", "baseline_locked", "critical_delay_days", "status"], limit=500)


def read_milestones(be, tna: str) -> list[dict]:
    return be.get_list("TNA Milestone", [["order_tna", "=", tna]],
                       ["name", "milestone_type", "planned_start", "planned_date", "revised_date", "revision_reason", "actual_date", "partial", "not_applicable", "owner_user",
                        "delay_reason_category", "is_critical", "source_doctype", "source_name", "status", "delay_days"], limit=500)


def state_of(rows: list[dict]) -> dict:
    out = {}
    for m in rows:
        out[m["milestone_type"]] = {"actual_date": m.get("actual_date") or None, "partial": int(m.get("partial") or 0), "not_applicable": int(m.get("not_applicable") or 0),
                                    "revised_date": m.get("revised_date") or None}
    return out


def baseline_of(rows: list[dict]) -> dict:
    return {m["milestone_type"]: {"planned_start": m.get("planned_start"), "planned_finish": m.get("planned_date")} for m in rows if m.get("planned_date")}


def anchors_of(tna: dict, so: Optional[dict] = None) -> dict:
    return {"ex_factory": tna.get("ex_factory_date"), "order_received": tna.get("order_received_date") or (so or {}).get("transaction_date"), "pcd": tna.get("pcd") or None}


def compute(tna: dict, rows: list[dict], today: date, so: Optional[dict] = None) -> dict:
    """The plan of one Order TNA. Locked: measured against the frozen planned dates of the ERP rows; unlocked: the engine's own baseline."""
    locked = int(tna.get("baseline_locked") or 0)
    return scheduler.schedule(tpl(), anchors_of(tna, so), state_of(rows), today, baseline=baseline_of(rows) if (locked and rows) else None)


def view(plan: dict, rows: list[dict]) -> dict:
    """JSON for the screen: one row per milestone with the lanes (baseline, forecast, actual), the ERP row it is stored in, and the summary."""
    by_type = {m["milestone_type"]: m for m in rows}
    out = []
    for r in scheduler.as_rows(plan):
        m = by_type.get(r["code"]) or {}
        out.append({**{k: r[k] for k in ("code", "name", "category", "owner_role", "calendar", "duration", "is_critical", "status", "float_wd", "slip_wd", "critical", "driver",
                                         "not_applicable", "pinned")},
                    "planned_start": r["planned_start"], "planned_finish": r["planned_finish"], "latest_finish": r["latest_finish"], "earliest_finish": r["earliest_finish"],
                    "forecast_start": r["forecast_start"], "forecast_finish": r["forecast_finish"], "actual_date": r.get("actual_date"), "revised_date": r.get("revised_date"),
                    "stored": bool(m), "erp_name": m.get("name") or "", "erp_planned": str(m.get("planned_date") or ""), "source": (m.get("source_doctype") or "") or ("person" if r.get("actual_date") else "")})
    s = plan["summary"]
    return {"rows": out, "summary": {"ex_factory": str(s["ex_factory"]), "ship_forecast": str(s["ship_forecast"]), "ship_miss_wd": s["ship_miss_wd"], "feasible": s["feasible"],
                                      "plan_feasible": s["plan_feasible"], "plan_infeasible_by_wd": s["plan_infeasible_by_wd"], "message": s["message"], "driver": s["driver"],
                                      "critical": len(s["critical_codes"]), "late": s["late"]}}


# ───────────────────────── baselines, revisions ─────────────────────────

def lock(db, me: dict, be, tna: dict, rows: list[dict], plan: dict) -> dict:
    """Freeze the baseline: gate (feasible, every applicable milestone has a date), snapshot row (kept forever), then the ERP's lock script."""
    if int(tna.get("baseline_locked") or 0):
        return {"ok": False, "error": f"{tna['name']} is already locked. Revise a date, or ask a manager to re-lock."}
    s = plan["summary"]
    if not s["plan_feasible"] or not s["feasible"]:
        return {"ok": False, "error": "The plan is not feasible, so it cannot be locked: " + s["message"] + " Move the ex-factory date or the PCD first."}
    missing = [m for m in plan["order"] if not plan["tasks"][m]["not_applicable"] and not any(r["milestone_type"] == m for r in rows)]
    if missing:
        return {"ok": False, "error": f"{len(missing)} milestone(s) are not written to the ERP yet ({', '.join(missing[:4])}...). Write the plan first."}
    ver = (db.query(PlanBaselineModel).filter(PlanBaselineModel.order_tna == tna["name"]).count() or 0) + 1
    snap = [{"code": c, "planned_start": str(plan["tasks"][c]["planned_start"]), "planned_finish": str(plan["tasks"][c]["planned_finish"])} for c in plan["order"]]
    db.add(PlanBaselineModel(order_tna=tna["name"], version=ver, locked_by=me["email"], ex_factory=str(s["ex_factory"]), feasible=1, note=s["message"], rows_json=json.dumps(snap)))
    res = deals._ex(db, me, {"op": "api", "method": "arinox_order_tna_lock_baseline", "params": {"name": tna["name"]}, "doctype": "Order TNA", "name": tna["name"],
                             "idem_key": f"tna-lock-{tna['name']}-{ver}"})
    if not res.get("ok"):
        db.rollback()
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the lock."))}
    db.commit()
    return {"ok": True, "version": ver, "locked": True}


def revise(db, me: dict, be, tna: dict, rows: list[dict], plan: dict, code: str, new_date: str, reason_code: str, note: str, approver: str = "") -> dict:
    """Move one milestone's forecast on a locked plan: reason code and party required; a move that moves the ship date needs a manager."""
    if reason_code not in REASON_CODES:
        return {"ok": False, "error": f"Say who caused it: one of {', '.join(REASON_CODES)}."}
    if not (note or "").strip():
        return {"ok": False, "error": "Write the reason for the new date."}
    if code not in plan["tasks"]:
        return {"ok": False, "error": f"{code} is not a milestone of this plan."}
    t = plan["tasks"][code]
    if t["actual_date"]:
        return {"ok": False, "error": f"{code} is done; its actual date is not a plan date."}
    nd = as_date(new_date)
    if not nd:
        return {"ok": False, "error": "Give the new date."}
    state = state_of(rows)
    state.setdefault(code, {})["revised_date"] = nd.isoformat()
    after = scheduler.schedule(tpl(), anchors_of(tna), state, plan["summary"]["today"], baseline=baseline_of(rows) if int(tna.get("baseline_locked") or 0) else None)
    before_ship, after_ship = plan["summary"]["ship_forecast"], after["summary"]["ship_forecast"]
    ship_moves = after_ship != before_ship
    if ship_moves and not (set(me["roles"]) & set(guardrails.ALL_POWER) or me.get("is_admin")):
        return {"ok": False, "need_approval": True, "error": f"This moves the ship forecast from {before_ship} to {after_ship}. A merchandising manager has to make or approve it.",
                "ship_before": str(before_ship), "ship_after": str(after_ship)}
    ownership.check("TNA Milestone", {"revised_date", "revision_reason"}, locked=False)
    res = deals._ex(db, me, {"op": "api", "method": "arinox_tna_apply_plan", "doctype": "Order TNA", "name": tna["name"],
                             "params": {"order_tna": tna["name"], "reason": f"{reason_code}: {note.strip()}"[:140],
                                        "rows": [{"milestone_type": code, "planned_date": str(t["planned_finish"]), "revised_date": nd.isoformat()}]}})
    if not res.get("ok"):
        return {"ok": False, "error": deals._strip_html(str(res.get("error") or "The ERP refused the revision."))}
    ver = db.query(PlanBaselineModel).filter(PlanBaselineModel.order_tna == tna["name"]).count() or 1
    moves = scheduler.moves(plan, after)
    db.add(PlanRevisionModel(order_tna=tna["name"], baseline_version=ver, code=code, old_date=str(t["forecast_finish"]), new_date=nd.isoformat(), reason_code=reason_code,
                             reason_note=note.strip(), actor=me["email"], approved_by=(me["email"] if ship_moves else ""),
                             ship_impact_wd=int(after["summary"]["ship_miss_wd"]) - int(plan["summary"]["ship_miss_wd"]), moves_json=json.dumps(moves[:80])))
    db.commit()
    return {"ok": True, "ship_before": str(before_ship), "ship_after": str(after_ship), "moves": len(moves), "result": res.get("result")}
