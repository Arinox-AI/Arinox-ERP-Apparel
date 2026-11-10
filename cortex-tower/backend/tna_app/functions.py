"""Cortex TnA Calendar — backend entry point (SPEC §6).

Every function takes ``db: Session`` **first** and returns a dict. A ``FUNCTIONS``
registry maps names → callables; the KOGO middleware invokes this file as::

    python functions.py <function_name> <json_params>

There is **no server, no port, no localhost** — the middleware executes this file
directly and the frontend reaches it only through ``API_BASE``.

Exposed functions
-----------------
``get_tna_calendar`` · ``get_tna_orders`` · ``get_tna_template`` · ``get_holidays``
· ``get_tna_kpis`` · ``update_milestone`` · ``run_action`` · ``rollback_action``
· ``get_audit_log`` · ``get_tna_alerts`` · ``get_tna_owners`` · ``get_tna_program``
· ``get_tna_intake`` · ``approve_tna_order`` · ``reject_tna_order`` · ``snooze_tna_order``
· ``get_bridge_status``

Data is read **live, GET-only** from the KOGO ERP (``erp.py``). Every order comes
from the ERP: when it holds none, the response says ``no_orders`` rather than showing
sample data. Every plan-bearing response carries ``source: "live" | "unavailable"``.
Writes touch only the local overlay (``writes.py``) and are preview-first and
reversible. Errors are returned as ``{"error": ...}`` — never raised.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import config
from . import erp
from . import tna
from . import writes
from .models import AuditLogModel

_DATE_FIELDS = ("actual_start", "actual_finish", "revised_finish")
_TEXT_FIELDS = ("delay_reason", "owner", "note", "status_override")
_MANAGED_FIELDS = _DATE_FIELDS + _TEXT_FIELDS


# ────────────────────────────────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return date.today().isoformat()


def _valid_date(v: str) -> bool:
    try:
        datetime.strptime(str(v)[:10], "%Y-%m-%d")
        return True
    except Exception:
        return False


def _source_warnings(norm: dict) -> list:
    """Human words for where this answer came from. No sample data is ever implied."""
    w = list(norm.get("warnings") or [])
    src = norm.get("source")
    if src == "unavailable":
        err = erp.last_error()
        if err and not w:
            w.append(f"The ERP could not be read ({err}).")
    elif src == "snapshot":
        if not w:
            w.append("Offline snapshot (TNA_OFFLINE is on). Orders are not being read from the ERP.")
    return w


def _view_with_overlay(norm: dict, tmpl: dict, calendar: str, as_of: str, overlay: dict) -> dict:
    return tna.build_calendar(norm, tmpl, calendar, as_of, overlay)


def _milestone_status(view: dict, code: str) -> Optional[str]:
    for r in view.get("milestones") or []:
        if r.get("code") == code:
            return r.get("status")
    return None


def _status_pair(norm, tmpl, calendar, as_of, overlay_before, overlay_after, code):
    vb = tna.build_calendar(norm, tmpl, calendar, as_of, overlay_before)
    va = tna.build_calendar(norm, tmpl, calendar, as_of, overlay_after)
    return (vb, va, _milestone_status(vb, code), _milestone_status(va, code),
            (vb.get("kpis") or {}).get("rag"), (va.get("kpis") or {}).get("rag"))


# ────────────────────────────────────────────────────────────────────────────
# 1) get_tna_calendar
# ────────────────────────────────────────────────────────────────────────────

def get_tna_calendar(db: Session, order_id: str = "", calendar: str = "",
                     product_type: str = "", as_of: str = "", force_snapshot: bool = False) -> dict:
    """The flagship read: header + 37 milestones (planned/actual/status/delay) +
    KPI block + holiday calendar + data-quality + ``source``."""
    try:
        order_id = (order_id or "").strip()
        tmpl = tna.load_template(product_type or config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        norm = erp.fetch_order(order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            err = dict(norm)
            err.setdefault("source", "live")
            return err
        oid = (norm.get("order") or {}).get("sales_order") or order_id
        overlay = tna.overlay_index(writes.list_overlay(db, oid))
        view = _view_with_overlay(norm, tmpl, calendar, as_of, overlay)

        return {
            "source": view["source"],
            "generated_at": _now_iso(),
            "as_of": view["as_of"],
            "header": view["header"],
            "milestones": view["milestones"],
            "kpis": view["kpis"],
            "exceptions": view["exceptions"],
            "alerts": view["alerts"],
            "alert_summary": view["alert_summary"],
            "owners": view["owners"],
            "calendar": view["calendar"],
            "template": view["template"],
            "data_quality": view["data_quality"],
            "warnings": _source_warnings(norm),
        }
    except Exception as e:  # never raise
        return {"error": str(e), "function": "get_tna_calendar"}


# ────────────────────────────────────────────────────────────────────────────
# 2) get_tna_orders
# ────────────────────────────────────────────────────────────────────────────

def get_tna_orders(db: Session, product_type: str = "", search_query: str = "",
                   limit: int = 50, offset: int = 0, force_snapshot: bool = False) -> dict:
    """In-scope orders for the picker (never invents orders)."""
    try:
        res = erp.list_orders(product_type=product_type, search_query=search_query,
                              limit=int(limit or 50), offset=int(offset or 0),
                              force_snapshot=bool(force_snapshot))
        if res.get("source") == "snapshot":
            res["warnings"] = _source_warnings({"source": "snapshot", "warnings": res.get("warnings")})
        return res
    except Exception as e:
        return {"error": str(e), "function": "get_tna_orders"}


# ────────────────────────────────────────────────────────────────────────────
# 3) get_tna_template
# ────────────────────────────────────────────────────────────────────────────

def get_tna_template(db: Session, product_type: str = "", template_id: str = "") -> dict:
    """The product-type TnA template (data, not code)."""
    try:
        return tna.load_template(product_type or template_id or config.DEFAULT_PRODUCT_TYPE)
    except Exception as e:
        return {"error": str(e), "function": "get_tna_template"}


# ────────────────────────────────────────────────────────────────────────────
# 4) get_holidays
# ────────────────────────────────────────────────────────────────────────────

def get_holidays(db: Session, calendar: str = "VN_FACTORY") -> dict:
    """One working-day calendar, or all of them when ``calendar=""``."""
    try:
        return tna.load_holidays(calendar)
    except Exception as e:
        return {"error": str(e), "function": "get_holidays"}


# ────────────────────────────────────────────────────────────────────────────
# 5) get_tna_kpis
# ────────────────────────────────────────────────────────────────────────────

def get_tna_kpis(db: Session, order_id: str = "", calendar: str = "",
                 as_of: str = "", force_snapshot: bool = False) -> dict:
    """The delivery KPI block for one order."""
    try:
        order_id = (order_id or "").strip()
        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        norm = erp.fetch_order(order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            err = dict(norm)
            err.setdefault("source", "live")
            return err
        oid = (norm.get("order") or {}).get("sales_order") or order_id
        overlay = tna.overlay_index(writes.list_overlay(db, oid))
        view = _view_with_overlay(norm, tmpl, calendar, as_of, overlay)
        return {
            "order_id": oid,
            "as_of": view["as_of"],
            "source": view["source"],
            "kpis": view["kpis"],
            "warnings": _source_warnings(norm),
        }
    except Exception as e:
        return {"error": str(e), "function": "get_tna_kpis"}


# ────────────────────────────────────────────────────────────────────────────
# 6) update_milestone  (preview-first, overlay-only)
# ────────────────────────────────────────────────────────────────────────────

def update_milestone(db: Session, order_id: str = "", code: str = "",
                     actual_start=None, actual_finish=None, revised_finish=None,
                     delay_reason=None,
                     owner=None, note=None, status_override=None,
                     apply: bool = False, actor: str = "",
                     force_snapshot: bool = False, calendar: str = "",
                     as_of: str = "") -> dict:
    """The only write path — an editor for the local overlay (never an ERP write).

    Preview-first: with ``apply=false`` (default) an action is staged and the diff
    is returned **without** touching the overlay. With ``apply=true`` it stages and
    applies in one call.

    Only the fields you pass are considered; omit a field (or send ``null``/``""``)
    to leave it unchanged. Send ``"__clear__"`` to clear a date or text field.
    """
    try:
        order_id = (order_id or "").strip()
        if not code:
            return {"error": "A milestone 'code' is required", "mode": "preview", "source": "live"}

        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        defs = {m.get("code"): m for m in tmpl.get("milestones") or []}
        if code not in defs:
            return {"error": f"Unknown milestone '{code}'", "mode": "preview",
                    "available": list(defs.keys())}

        norm = erp.fetch_order(order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            err = dict(norm)
            err.setdefault("mode", "preview")
            return err
        oid = (norm.get("order") or {}).get("sales_order") or order_id
        source = norm.get("source") or "live"

        if not writes.writes_enabled():
            return {"error": f"Writes are disabled (ERP_WRITE_MODE={writes.current_mode()})",
                    "mode": "preview", "mode_gate": writes.current_mode(), "source": source}

        cur_row = writes.get_overlay(db, oid, code)
        cur_vals = writes._overlay_values(cur_row)
        act = (norm.get("actuals") or {}).get(code) or {}

        # Effective (displayed) values — overlay first, then the ERP-derived actual.
        effective = dict(cur_vals)
        effective["actual_start"] = cur_vals.get("actual_start") or act.get("start")
        effective["actual_finish"] = cur_vals.get("actual_finish") or act.get("finish")

        provided = {}
        if actual_start is not None:
            provided["actual_start"] = actual_start
        if actual_finish is not None:
            provided["actual_finish"] = actual_finish
        if revised_finish is not None:
            provided["revised_finish"] = revised_finish
        if delay_reason is not None:
            provided["delay_reason"] = delay_reason
        if owner is not None:
            provided["owner"] = owner
        if note is not None:
            provided["note"] = note
        if status_override is not None:
            provided["status_override"] = status_override

        updates = {}
        errors = []
        for field, raw in provided.items():
            val = raw
            if isinstance(val, str):
                val = val.strip()
            if val == "":
                continue  # unchanged (never silently wipe)
            if val == config.CLEAR_SENTINEL:
                updates[field] = None
                continue
            if field in _DATE_FIELDS:
                if not _valid_date(val):
                    errors.append(f"'{field}' must be YYYY-MM-DD")
                    continue
                updates[field] = str(val)[:10]
            elif field == "status_override":
                if val not in config.STATUS_VOCAB:
                    errors.append(f"'status_override' must be one of: {', '.join(config.STATUS_VOCAB)}")
                    continue
                updates[field] = val
            else:
                updates[field] = str(val)

        if errors:
            return {"error": "; ".join(errors), "mode": "preview",
                    "mode_gate": writes.current_mode(), "source": source}

        # Cross-field validation on the resulting state.
        new_start = updates.get("actual_start", effective.get("actual_start"))
        new_finish = updates.get("actual_finish", effective.get("actual_finish"))
        if new_start and new_finish and str(new_start) > str(new_finish):
            return {"error": "actual_start must be on or before actual_finish",
                    "mode": "preview", "source": source}

        # Build the change list (old = effective displayed value).
        changes = []
        for field, new in updates.items():
            old = effective.get(field)
            if old != new:
                changes.append({"field": field, "old": old, "new": new})

        # Resulting overlay state.
        after = dict(cur_vals)
        after.update(updates)
        after["recorded_by"] = actor or cur_vals.get("recorded_by")

        # Freeze the planned finish for the record.
        base_view = tna.build_calendar(norm, tmpl, calendar, as_of,
                                       tna.overlay_index(writes.list_overlay(db, oid)))
        for r in base_view.get("milestones") or []:
            if r.get("code") == code:
                after["planned_date"] = r.get("planned_finish")
                break

        overlay_before = tna.overlay_index(writes.list_overlay(db, oid))
        overlay_after = dict(overlay_before)
        overlay_after[code] = after

        _vb, _va, status_before, status_after, rag_before, rag_after = _status_pair(
            norm, tmpl, calendar, as_of, overlay_before, overlay_after, code)

        if not changes:
            return {
                "mode": "preview", "action_id": None, "order_id": oid, "code": code,
                "changes": [], "status_before": status_before, "status_after": status_before,
                "rag_before": rag_before, "rag_after": rag_before,
                "write_target": "local_overlay", "erp_write": False,
                "mode_gate": writes.current_mode(), "requires_confirmation": False,
                "message": "No changes to record.", "source": source,
            }

        action = writes.stage_action(db, oid, code, changes, after, actor=actor, source=source)

        if apply:
            res = writes.apply_action(db, action.action_id, source=source)
            if res.get("error"):
                return {**res, "mode": "applied", "source": source}
            return {
                "mode": "applied", "action_id": res["action_id"], "order_id": res["order_id"],
                "code": res["code"], "changes": writes.fmt_changes(changes),
                "record": res.get("record"),
                "status_before": status_before, "status_after": status_after,
                "rag_before": rag_before, "rag_after": rag_after,
                "reversible": True, "write_target": "local_overlay", "erp_write": False,
                "mode_gate": writes.current_mode(), "source": source,
                "applied_at": res.get("applied_at"),
            }

        return {
            "mode": "preview", "action_id": action.action_id, "order_id": oid, "code": code,
            "changes": writes.fmt_changes(changes),
            "status_before": status_before, "status_after": status_after,
            "rag_before": rag_before, "rag_after": rag_after,
            "write_target": "local_overlay", "erp_write": False,
            "mode_gate": writes.current_mode(), "requires_confirmation": True,
            "source": source,
        }
    except Exception as e:
        return {"error": str(e), "function": "update_milestone", "mode": "preview"}


# ────────────────────────────────────────────────────────────────────────────
# 7) run_action  (commit a previously staged action)
# ────────────────────────────────────────────────────────────────────────────

def run_action(db: Session, action_id: str = "", calendar: str = "",
               as_of: str = "", force_snapshot: bool = False) -> dict:
    """Commit a staged action (``action_log.status == "staged"``)."""
    try:
        from .models import ActionLogModel
        action = db.query(ActionLogModel).filter(ActionLogModel.action_id == action_id).first()
        if action is None or action.status != "staged":
            return {"error": f"Action '{action_id}' not found or not staged",
                    "action_status": action.status if action else None,
                    "source": "live"}

        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        norm = erp.fetch_order(action.order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            return dict(norm)

        after = json.loads(action.after_json) if action.after_json else {}
        overlay_before = tna.overlay_index(writes.list_overlay(db, action.order_id))
        overlay_after = dict(overlay_before)
        overlay_after[action.milestone_code] = after
        _vb, _va, status_before, status_after, rag_before, rag_after = _status_pair(
            norm, tmpl, calendar, as_of, overlay_before, overlay_after, action.milestone_code)

        res = writes.apply_action(db, action_id, source=norm.get("source") or "live")
        if res.get("error"):
            return {**res, "source": norm.get("source") or "live"}
        changes = res.get("changes") or []
        return {
            "mode": "applied", "action_id": res["action_id"], "order_id": res["order_id"],
            "code": res["code"], "changes": writes.fmt_changes(changes),
            "record": res.get("record"),
            "status_before": status_before, "status_after": status_after,
            "rag_before": rag_before, "rag_after": rag_after,
            "reversible": True, "erp_write": False,
            "mode_gate": writes.current_mode(), "source": norm.get("source") or "live",
            "applied_at": res.get("applied_at"),
        }
    except Exception as e:
        return {"error": str(e), "function": "run_action"}


# ────────────────────────────────────────────────────────────────────────────
# 8) rollback_action  (reverse an applied action)
# ────────────────────────────────────────────────────────────────────────────

def rollback_action(db: Session, action_id: str = "", calendar: str = "",
                    as_of: str = "", force_snapshot: bool = False) -> dict:
    """Reverse an applied action by restoring its ``before_json`` (history kept)."""
    try:
        from .models import ActionLogModel
        action = db.query(ActionLogModel).filter(ActionLogModel.action_id == action_id).first()
        if action is None or action.status != "applied":
            return {"error": f"Action '{action_id}' not found or not applied",
                    "action_status": action.status if action else None,
                    "source": "live"}

        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        norm = erp.fetch_order(action.order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            return dict(norm)

        before = json.loads(action.before_json) if action.before_json else {}
        before = before or {}
        overlay_before = tna.overlay_index(writes.list_overlay(db, action.order_id))
        overlay_after = dict(overlay_before)
        if all(v is None for v in before.values()):
            overlay_after.pop(action.milestone_code, None)
        else:
            overlay_after[action.milestone_code] = before
        _vb, _va, status_before, status_after, rag_before, rag_after = _status_pair(
            norm, tmpl, calendar, as_of, overlay_before, overlay_after, action.milestone_code)

        res = writes.rollback_action(db, action_id, source=norm.get("source") or "live")
        if res.get("error"):
            return {**res, "source": norm.get("source") or "live"}
        return {
            "mode": "rolled_back", "action_id": res["action_id"], "order_id": res["order_id"],
            "code": res["code"], "restored": res.get("restored"),
            "changes": writes.fmt_changes(res.get("changes") or []),
            "status_before": status_before, "status_after": status_after,
            "rag_before": rag_before, "rag_after": rag_after,
            "reversible": False, "erp_write": False,
            "mode_gate": writes.current_mode(), "source": norm.get("source") or "live",
        }
    except Exception as e:
        return {"error": str(e), "function": "rollback_action"}


# ────────────────────────────────────────────────────────────────────────────
# 9) get_audit_log
# ────────────────────────────────────────────────────────────────────────────

def get_audit_log(db: Session, order_id: str = "", action_id: str = "",
                  limit: int = 100, offset: int = 0) -> dict:
    """The append-only audit journal (newest first) plus the ``action_log`` history
    for the same filter (staged / applied / rolled_back)."""
    try:
        limit = int(limit or 100)
        offset = int(offset or 0)
        q = db.query(AuditLogModel)
        if order_id:
            q = q.filter(AuditLogModel.order_id == order_id)
        if action_id:
            q = q.filter(AuditLogModel.action_id == action_id)
        total_count = q.count()
        rows = (q.order_by(AuditLogModel.id.desc()).offset(offset).limit(limit).all())
        logs = [r.to_dict() for r in rows]

        act_rows, act_total = writes.list_actions(db, order_id=order_id, limit=limit, offset=offset)
        actions = []
        for a in act_rows:
            d = a.to_dict()
            actions.append({
                "action_id": d.get("action_id"),
                "milestone_code": d.get("milestone_code"),
                "kind": d.get("kind"),
                "status": d.get("status"),
                "changes": d.get("changes") or [],
                "actor": d.get("actor"),
                "mode": d.get("mode"),
                "created_at": d.get("created_at"),
                "applied_at": d.get("applied_at"),
                "rolled_back_at": d.get("rolled_back_at"),
            })

        return {"logs": logs, "total": len(logs), "total_count": total_count,
                "offset": offset, "limit": limit,
                "actions": actions, "actions_total": act_total}
    except Exception as e:
        return {"error": str(e), "function": "get_audit_log"}


# ────────────────────────────────────────────────────────────────────────────
# 10) get_tna_alerts  — ranked, escalated alerts + reminder digest
# ────────────────────────────────────────────────────────────────────────────

def get_tna_alerts(db: Session, order_id: str = "", as_of: str = "", calendar: str = "",
                   force_snapshot: bool = False, include_digest: bool = True) -> dict:
    """Ranked alerts (severity + working-days open + escalation level + owner +
    next action) and an optional plain-text reminder digest."""
    try:
        order_id = (order_id or "").strip()
        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        norm = erp.fetch_order(order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            err = dict(norm)
            err.setdefault("source", "live")
            return err
        oid = (norm.get("order") or {}).get("sales_order") or order_id
        overlay = tna.overlay_index(writes.list_overlay(db, oid))
        view = _view_with_overlay(norm, tmpl, calendar, as_of, overlay)
        out = {
            "order_id": oid, "as_of": view["as_of"], "source": view["source"],
            "header": view["header"],
            "alerts": view["alerts"], "summary": view["alert_summary"],
            "owners": view["owners"], "kpis": view["kpis"],
            "warnings": _source_warnings(norm),
        }
        if include_digest:
            out["digest"] = tna.alert_digest(view["header"], view["alerts"],
                                             view["alert_summary"], view["as_of"])
        return out
    except Exception as e:
        return {"error": str(e), "function": "get_tna_alerts"}


# ────────────────────────────────────────────────────────────────────────────
# 11) get_tna_owners  — workload by owner / role
# ────────────────────────────────────────────────────────────────────────────

def get_tna_owners(db: Session, order_id: str = "", as_of: str = "", calendar: str = "",
                   force_snapshot: bool = False) -> dict:
    """Milestone workload grouped by the effective owner (assigned name, else role)."""
    try:
        order_id = (order_id or "").strip()
        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        norm = erp.fetch_order(order_id, force_snapshot=bool(force_snapshot))
        if "error" in norm:
            err = dict(norm)
            err.setdefault("source", "live")
            return err
        oid = (norm.get("order") or {}).get("sales_order") or order_id
        overlay = tna.overlay_index(writes.list_overlay(db, oid))
        view = _view_with_overlay(norm, tmpl, calendar, as_of, overlay)
        return {
            "order_id": oid, "as_of": view["as_of"], "source": view["source"],
            "owners": view["owners"], "summary": view["alert_summary"],
            "warnings": _source_warnings(norm),
        }
    except Exception as e:
        return {"error": str(e), "function": "get_tna_owners"}


# ────────────────────────────────────────────────────────────────────────────
# 12) get_tna_program  — multi-order / capacity view
# ────────────────────────────────────────────────────────────────────────────

def get_tna_program(db: Session, as_of: str = "", horizon_wd: int = 0, limit: int = 100,
                    calendar: str = "", force_snapshot: bool = False, detail: bool = False,
                    status: str = "", search_query: str = "") -> dict:
    """Multi-order / capacity view.

    ``detail=False`` (default, fast) scores every order **from the plan** using the
    already-loaded order list — no per-order ERP evidence sweep. ``detail=True``
    additionally reads each order's live milestones (accurate statuses but slower,
    ~1 ERP round per order). The per-order ERP reads run in parallel; the SQLite
    overlay is read up-front (a Session is not thread-safe). Never raises.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor
        horizon = int(horizon_wd or config.PROGRAM_HORIZON_WD)
        tmpl = tna.load_template(config.DEFAULT_PRODUCT_TYPE)
        if "error" in tmpl:
            return tmpl
        lst = erp.list_orders(product_type="", search_query=search_query,
                              limit=int(limit or 100), force_snapshot=bool(force_snapshot))
        rows_in = lst.get("orders") or []
        source = lst.get("source") or "live"
        # Read overlays sequentially (one Session), then fetch in parallel.
        overlays = {o.get("order_id"): tna.overlay_index(writes.list_overlay(db, o.get("order_id")))
                    for o in rows_in}

        def _plan_norm(o):
            return {
                "source": source, "warnings": [], "data_quality": [],
                "order": {
                    "sales_order": o.get("order_id"), "customer": o.get("customer"),
                    "style_no": o.get("style_no"), "style_name": o.get("style_name"),
                    "colour": o.get("colour"), "qty": o.get("qty"),
                    "delivery_date": o.get("ship_date"),
                    "sales_order_status": o.get("sales_order_status"),
                    "template_id": o.get("template_id"),
                },
                "actuals": {},
            }

        def one(o):
            oid = o.get("order_id")
            try:
                if detail:
                    norm = erp.fetch_order(oid, force_snapshot=bool(force_snapshot), light=True)
                    if "error" in norm:
                        return None
                else:
                    norm = _plan_norm(o)
                view = tna.build_calendar(norm, tmpl, calendar, as_of, overlays.get(oid) or {})
                h, k = view["header"], view["kpis"]
                return {
                    "order_id": oid, "customer": h.get("customer"),
                    "customer_legal": h.get("customer_legal"), "style_no": h.get("style_no"),
                    "style_name": h.get("style_name"), "qty": h.get("qty"),
                    "currency": h.get("currency"), "order_value": h.get("order_value"),
                    "ship_date": h.get("ship_date"), "days_to_ship": k.get("days_to_ship"),
                    "rag": k.get("rag"), "overall_status": h.get("overall_status"),
                    "sales_order_status": h.get("sales_order_status"),
                    "overdue_count": k.get("overdue_count"), "at_risk_count": k.get("at_risk_count"),
                    "blocked_count": k.get("blocked_count"), "progress_pct": k.get("progress_pct"),
                    "erp_linked_count": k.get("erp_linked_count"),
                    "critical_path_delay_days": k.get("critical_path_delay_days"),
                    "alert_count": k.get("alert_count"), "max_escalation": k.get("max_escalation"),
                    "ship_overdue_days": k.get("ship_overdue_days"),
                    "source": view["source"],
                    "plan_based": not detail,
                }
            except Exception:
                return None

        results = []
        if detail:
            with ThreadPoolExecutor(max_workers=6) as ex:
                for r in ex.map(one, rows_in):
                    if r:
                        results.append(r)
        else:
            for o in rows_in:
                r = one(o)
                if r:
                    results.append(r)

        results.sort(key=lambda r: (str(r.get("ship_date") or "9999"), str(r.get("order_id"))))

        def _month(iso):
            return str(iso)[:7] if iso else "unknown"

        months: dict = {}
        for r in results:
            m = _month(r.get("ship_date"))
            g = months.setdefault(m, {"month": m, "orders": 0, "qty": 0.0,
                                      "overdue": 0, "red": 0, "amber": 0, "green": 0})
            g["orders"] += 1
            g["qty"] += float(r.get("qty") or 0)
            g["overdue"] += int(r.get("overdue_count") or 0)
            g["red"] += 1 if r.get("rag") == "red" else 0
            g["amber"] += 1 if r.get("rag") == "amber" else 0
            g["green"] += 1 if r.get("rag") == "green" else 0
        by_month = [months[k] for k in sorted(months)]

        soon = [r for r in results
                if r.get("days_to_ship") is not None and 0 <= int(r["days_to_ship"]) <= horizon]
        past = [r for r in results if r.get("days_to_ship") is not None and int(r["days_to_ship"]) < 0]

        return {
            "as_of": as_of or _today_iso(),
            "source": source,
            "detail": bool(detail),
            "orders": results,
            "total_orders": len(results),
            "qty_total": sum(float(r.get("qty") or 0) for r in results),
            "by_rag": {
                "red": sum(1 for r in results if r.get("rag") == "red"),
                "amber": sum(1 for r in results if r.get("rag") == "amber"),
                "green": sum(1 for r in results if r.get("rag") == "green"),
            },
            "orders_ship_past": len(past),
            "orders_ship_within_horizon": len(soon),
            "horizon_wd": horizon,
            "capacity_by_ship_month": by_month,
            "warnings": _source_warnings({"source": lst.get("source") or "live",
                                          "warnings": lst.get("warnings") or []}),
        }
    except Exception as e:
        return {"error": str(e), "function": "get_tna_program"}


# ────────────────────────────────────────────────────────────────────────────
# 12) get_tna_intake — new-order notification inbox (+ Cortex Tower bridge)
# ────────────────────────────────────────────────────────────────────────────

def get_tna_intake(db: Session, status: str = "", sync: bool = True,
                   force: bool = False) -> dict:
    """The new-order intake queue: orders that arrived but whose TnA plan has not
    been started. Pulls from the ERP and enriches from the Cortex Tower bridge."""
    try:
        from . import bridge
        res = bridge.list_intake(db, status=status, sync=bool(sync))
        res["generated_at"] = _now_iso()
        return res
    except Exception as e:  # never raise
        return {"error": str(e), "function": "get_tna_intake"}


# ────────────────────────────────────────────────────────────────────────────
# 13) approve_tna_order — the "Approve" click: start the TnA work for an order
# ────────────────────────────────────────────────────────────────────────────

def approve_tna_order(db: Session, order_id: str = "", actor: str = "", note: str = "") -> dict:
    """Approve a new-order notification → START the TnA plan for that order."""
    try:
        from . import bridge
        return bridge.decide_intake(db, order_id, "approved", actor=actor, note=note)
    except Exception as e:
        return {"error": str(e), "function": "approve_tna_order"}


# ────────────────────────────────────────────────────────────────────────────
# 14) reject_tna_order — dismiss a new-order notification (no plan started)
# ────────────────────────────────────────────────────────────────────────────

def reject_tna_order(db: Session, order_id: str = "", actor: str = "", note: str = "") -> dict:
    try:
        from . import bridge
        return bridge.decide_intake(db, order_id, "rejected", actor=actor, note=note)
    except Exception as e:
        return {"error": str(e), "function": "reject_tna_order"}


# ────────────────────────────────────────────────────────────────────────────
# 15) snooze_tna_order — keep a notification for later
# ────────────────────────────────────────────────────────────────────────────

def snooze_tna_order(db: Session, order_id: str = "", actor: str = "", note: str = "") -> dict:
    try:
        from . import bridge
        return bridge.decide_intake(db, order_id, "snoozed", actor=actor, note=note)
    except Exception as e:
        return {"error": str(e), "function": "snooze_tna_order"}


# ────────────────────────────────────────────────────────────────────────────
# 16) get_bridge_status — health of the Cortex Tower link
# ────────────────────────────────────────────────────────────────────────────

def get_bridge_status(db: Session = None) -> dict:
    try:
        from . import bridge
        st = bridge.bridge_status(db)
        st["generated_at"] = _now_iso()
        return st
    except Exception as e:
        return {"error": str(e), "function": "get_bridge_status"}


# ────────────────────────────────────────────────────────────────────────────
# 17) set_tower_link — save the Cortex Tower app URL so the UI can jump to it
# ────────────────────────────────────────────────────────────────────────────

def set_tower_link(db: Session, url: str = "", actor: str = "") -> dict:
    """Save (or clear) the Cortex Tower app URL used by the "Open in Cortex Tower" jump."""
    try:
        from . import bridge
        return bridge.set_tower_app_url(db, url, actor=actor)
    except Exception as e:
        return {"error": str(e), "function": "set_tower_link"}


# ────────────────────────────────────────────────────────────────────────────
# Registry + caller
# ────────────────────────────────────────────────────────────────────────────

FUNCTIONS = {
    "get_tna_calendar": get_tna_calendar,
    "get_tna_orders": get_tna_orders,
    "get_tna_template": get_tna_template,
    "get_holidays": get_holidays,
    "get_tna_kpis": get_tna_kpis,
    "update_milestone": update_milestone,
    "run_action": run_action,
    "rollback_action": rollback_action,
    "get_audit_log": get_audit_log,
    "get_tna_alerts": get_tna_alerts,
    "get_tna_owners": get_tna_owners,
    "get_tna_program": get_tna_program,
    "get_tna_intake": get_tna_intake,
    "approve_tna_order": approve_tna_order,
    "reject_tna_order": reject_tna_order,
    "snooze_tna_order": snooze_tna_order,
    "get_bridge_status": get_bridge_status,
    "set_tower_link": set_tower_link,
}


def call_function(name: str, db: Session, **kwargs) -> dict:
    func = FUNCTIONS.get(name)
    if not func:
        raise ValueError(f"Function '{name}' not found. Available: {list(FUNCTIONS.keys())}")
    return func(db=db, **kwargs)


if __name__ == "__main__":
    import sys
    from .database import get_session, init_db

    init_db()

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python functions.py <function_name> [json_params]"}))
        sys.exit(1)

    func_name = sys.argv[1]
    params = {}
    if len(sys.argv) > 2:
        try:
            params = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON params: {e}"}))
            sys.exit(1)

    db = get_session()
    try:
        func = FUNCTIONS.get(func_name)
        if not func:
            print(json.dumps({"error": f"Function '{func_name}' not found. Available: {list(FUNCTIONS.keys())}"}))
            sys.exit(1)
        result = func(db=db, **params)
        print(json.dumps(result, default=str))
    except Exception as e:
        db.rollback()
        print(json.dumps({"error": str(e), "function": func_name, "params": params}))
        sys.exit(1)
    finally:
        db.close()
