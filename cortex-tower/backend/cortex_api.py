"""Functions of the Arinox layer, in the tower's calling convention ``fn(db, **params) -> dict``.

Every function that reads or writes ERP data starts with ``cx_users.require`` — identity comes from the verified
environment, never from a parameter. Writes go through ``pipeline.execute`` and nowhere else.

Registered into ``functions.FUNCTIONS`` (and the bridge list) at the bottom of ``functions.py``.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

import changefeed
import catalog
import config
import cx_users
import docs
import guardrails
import pipeline
from models import AuditLogModel, EmailDraftModel, KVModel, MailAttachmentModel, MailMessageModel
from models_cx import ApprovalModel, BreachModel, ChangeModel, ScriptStateModel, UserModel, WriteRunModel
from tsr import connection, reports as tsr_reports
from tsr.errors import TSRError, TSRNotFound, TSRUnsupported, TSRValidationError

_reports: tsr_reports.ReportRegistry | None = None


def _reg() -> tsr_reports.ReportRegistry:
    global _reports
    if _reports is None:
        _reports = tsr_reports.ReportRegistry()
    return _reports


def guarded(fn: Callable) -> Callable:
    """Resolve the caller, hand the function a ``me`` principal, and turn expected failures into sentences."""
    def wrapper(db, **kwargs):
        try:
            me = cx_users.require(db, **kwargs)
        except PermissionError as e:
            return {"ok": False, "error": str(e), "auth": False}
        kwargs.pop("_app_token", None)
        kwargs.pop("actor", None)                      # a client-supplied actor is never trusted
        try:
            return fn(db, me, **kwargs)
        except guardrails.Denied as e:
            return {"ok": False, "error": e.message, "denied": True}
        except TSRNotFound as e:
            return {"ok": False, "error": f"Not found: {e.doctype} {e.name}".strip()}
        except TSRValidationError as e:
            return {"ok": False, "error": e.message}
        except TSRError as e:
            return {"ok": False, "error": pipeline._friendly(e), "technical": str(e)[:400]}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _backend():
    return connection.get_backend()


def _admin_only(me: dict):
    if not me["is_admin"]:
        raise guardrails.Denied("Administrators only.")


def _manager(me: dict):
    if not set(me["roles"]) & set(guardrails.ALL_POWER):
        raise guardrails.Denied("Managers only.")


# ───────────────────────── navigation & search ─────────────────────────

_ALL_DT_CACHE: dict = {"t": 0.0, "v": None}


def _all_erp_doctypes() -> list[str]:
    """Every non-child Arinox doctype on the ERP (the same list ``cx_connection`` counts), cached 10 min."""
    if _ALL_DT_CACHE["v"] is not None and time.time() - _ALL_DT_CACHE["t"] < 600:
        return _ALL_DT_CACHE["v"]
    try:
        rows = _backend().get_list("DocType", [["module", "=", "Arinox Apparel"], ["istable", "=", 0]],
                                   ["name", "issingle"], limit=500)
        names = sorted(r["name"] for r in rows if r.get("name") and not int(r.get("issingle") or 0))
    except Exception:
        names = []
    if names:
        _ALL_DT_CACHE.update(t=time.time(), v=names)
    return names


def _merged_nav() -> list[dict]:
    """The hand-made process groups, plus one "All ERP records" group holding every Arinox doctype the
    groups above do not already show — so nothing the ERP has is out of reach (2026-11-07)."""
    nav = [dict(g, items=list(g["items"])) for g in catalog.NAV]
    shown = {it.get("doctype") for g in nav for it in g["items"] if it.get("kind") == "doc"}
    extra = [dt for dt in _all_erp_doctypes() if dt not in shown]
    if extra:
        nav.insert(len(nav) - 1, {"key": "all_records", "label": "All ERP records", "icon": "database", "collapsed": True,
                                  "items": [{"key": "dt_" + re.sub(r"[^a-z0-9]+", "_", dt.lower()).strip("_"), "label": dt,
                                             "kind": "doc", "doctype": dt} for dt in extra]})
    return nav


@guarded
def cx_catalog(db, me, **_):
    """The process sidebar for this person: only what their role may read."""
    out = []
    for g in _merged_nav():
        items = []
        for it in g["items"]:
            if it.get("admin") and not me["is_admin"]:
                continue
            if it["kind"] == "doc" and not guardrails.can(me["roles"], it["doctype"], "read"):
                continue
            items.append(it)
        if items:
            out.append({**g, "items": items})
    return {"ok": True, "nav": out, "me": me, "write_mode": __import__("writes").current_mode()}


@guarded
def cx_nav_counts(db, me, **_):
    items = [it for g in catalog.NAV for it in g["items"]]
    return {"ok": True, "counts": docs.nav_counts(_backend(), items, me["roles"])}


@guarded
def cx_search(db, me, q: str = "", **_):
    if len((q or "").strip()) < 2:
        return {"ok": True, "results": []}
    return {"ok": True, "results": docs.global_search(_backend(), q.strip(), me["roles"])}


# ───────────────────────── generic record workspace ─────────────────────────

@guarded
def cx_doc_meta(db, me, doctype: str = "", **_):
    guardrails.require(me["roles"], doctype, "read")
    return {"ok": True, **docs.ui_meta(_backend(), doctype, me["roles"]), "can_create": guardrails.can(me["roles"], doctype, "create")}


@guarded
def cx_doc_list(db, me, doctype: str = "", search: str = "", page: int = 1, page_size: int = 25, status: str = "",
                order_by: str = "modified desc", **_):
    return {"ok": True, **docs.list_docs(_backend(), doctype, me["roles"], search=search, page=page, page_size=page_size,
                                          status=status, order_by=order_by)}


@guarded
def cx_doc_get(db, me, doctype: str = "", name: str = "", **_):
    # An empty name used to reach the backend and come back as "'list' object has no attribute
    # 'items'" (the list endpoint answers, then docs.get_doc treats it as one document).
    # A blank name is a caller mistake: say so in words the form can show (2026-11-06).
    if not str(doctype or "").strip() or not str(name or "").strip():
        return {"ok": False, "error": "Pick a record first."}
    return {"ok": True, **docs.get_doc(_backend(), pipeline.engine().registry, doctype, name, me["roles"])}


@guarded
def cx_link_search(db, me, doctype: str = "", txt: str = "", **_):
    return {"ok": True, "results": docs.link_search(_backend(), doctype, txt, me["roles"])}


@guarded
def cx_write(db, me, op: str = "", doctype: str = "", name: str = "", data: dict | None = None, modified: str = "",
             preview: bool = False, approval_id: int = 0, idem_key: str = "", **_):
    """insert | save | submit | cancel | delete — the one way a form writes to the ERP."""
    return pipeline.execute(db, me, {"op": op, "doctype": doctype, "name": name, "data": data or {}, "modified": modified,
                                     "preview": bool(preview), "approval_id": approval_id or None, "idem_key": idem_key or None})


@guarded
def cx_run_script(db, me, method: str = "", params: dict | None = None, doctype: str = "", name: str = "",
                  preview: bool = False, approval_id: int = 0, idem_key: str = "", **_):
    """Run one of the Arinox API scripts (the buttons of the ERP forms). Allow-listed from the registry."""
    if method not in pipeline.engine().registry.api:
        return {"ok": False, "error": f"Unknown action {method}."}
    return pipeline.execute(db, me, {"op": "api", "method": method, "params": params or {}, "doctype": doctype, "name": name,
                                     "preview": bool(preview), "approval_id": approval_id or None, "idem_key": idem_key or None})


# ───────────────────────── approvals, runs ─────────────────────────

@guarded
def cx_approvals(db, me, status: str = "pending", **_):
    """Held decisions, each with the ERP page it belongs to.

    A held write is a decision about an ERP document, and the person who owns that decision makes it **in the ERP**:
    the tower's job is to say what is held, why, and where to decide it. So every row carries the document's own page
    (``url``) and the operation being held, and ``decide_in_erp`` says plainly that the decision is not taken here.
    """
    q = db.query(ApprovalModel)
    if status != "all":
        q = q.filter(ApprovalModel.status == status)
    rows = q.order_by(ApprovalModel.id.desc()).limit(100).all()
    can = bool(set(me["roles"]) & set(guardrails.ALL_POWER))
    import erp as _erp
    out = []
    for a in rows:
        req = json.loads(a.request or "{}")
        dt, name, op = req.get("doctype") or "", req.get("name") or "", req.get("op") or ""
        url = ""
        if dt and name:
            try:
                url = _erp.doc_url(dt, name)
            except Exception:
                url = ""
        out.append({"id": a.id, "requester": a.requester, "approver": a.approver, "class": a.cls, "reason": a.reason,
                    "status": a.status, "preview": json.loads(a.preview or "{}"), "request": req,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "doctype": dt, "name": name, "op": op, "url": url,
                    "decide_in_erp": bool(url),
                    "mine": a.requester == me["email"]})
    return {"ok": True, "can_decide": can, "approvals": out}


@guarded
def cx_decide(db, me, approval_id: int = 0, decision: str = "", in_erp: int = 0, **_):
    """Record the decision on a held write. Params: `approval_id`, `decision` (approve|reject), `in_erp`.

    ``in_erp=1`` is the honest answer when the decision was taken in the ERP itself: the holder is then released and
    marked as decided there, and the tower performs no write of its own. Either way the ERP's document is the one that
    changed - nothing here bypasses the ERP's own permission check.
    """
    res = pipeline.decide_approval(db, me, approval_id, decision, in_erp=bool(in_erp))
    if res.get("ok") and in_erp:
        res["note"] = "Recorded as decided in the ERP — the tower did not write anything."
    return res


@guarded
def cx_runs(db, me, limit: int = 50, **_):
    rows = db.query(WriteRunModel).order_by(WriteRunModel.id.desc()).limit(min(200, int(limit))).all()
    mine = bool(set(me["roles"]) & set(guardrails.ALL_POWER))
    return {"ok": True, "runs": [{"id": r.id, "actor": r.actor, "op": r.op, "doctype": r.doctype, "name": r.name, "class": r.cls,
                                  "status": r.status, "started_at": r.started_at.isoformat() if r.started_at else None,
                                  "result": json.loads(r.result or "{}") if mine else {}}
                                 for r in rows if mine or r.actor == me["email"]]}


@guarded
def cx_rollback_run(db, me, run_id: int = 0, **_):
    return pipeline.rollback_run(db, me, run_id)


# ───────────────────────── sync & guardrails ─────────────────────────

def sync_changes(db, **kwargs):
    """Poll the ERP for changes made outside the tower and reconcile them. Safe to call as often as you like."""
    try:
        me = cx_users.require(db, **kwargs)
    except PermissionError as e:
        return {"ok": False, "error": str(e), "auth": False}
    try:
        return changefeed.sync(db, _backend(), pipeline.engine(), pipeline._enabled_fn(db))
    except TSRError as e:
        return {"ok": False, "error": pipeline._friendly(e)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


def erp_event(db, **kwargs):
    """Webhook receiver (called by the ERP, not by a person): authenticated by the shared secret only."""
    return changefeed.erp_event(db, **kwargs)


@guarded
def cx_sync_status(db, me, **_):
    return {"ok": True, **changefeed.status(db, pipeline.engine())}


@guarded
def cx_breaches(db, me, state: str = "open", **_):
    q = db.query(BreachModel)
    if state != "all":
        q = q.filter(BreachModel.state == state)
    rows = q.order_by(BreachModel.id.desc()).limit(200).all()
    return {"ok": True, "breaches": [{"id": b.id, "doctype": b.doctype, "name": b.name, "script": b.script, "message": b.message,
                                      "state": b.state, "created_at": b.created_at.isoformat() if b.created_at else None,
                                      "remedies": _remedies(b)} for b in rows]}


def _remedies(b: BreachModel) -> list[dict]:
    r = [{"id": "open", "label": "Open the record"}, {"id": "dismiss", "label": "Dismiss (I have reviewed it)"}]
    if guardrails.can(["Management"], b.doctype, "cancel"):
        r.insert(1, {"id": "cancel", "label": f"Cancel {b.doctype} {b.name} (needs approval)", "risky": True})
    return r


@guarded
def cx_breach_decide(db, me, breach_id: int = 0, decision: str = "", note: str = "", **_):
    _manager(me)
    b = db.query(BreachModel).get(int(breach_id))
    if not b:
        return {"ok": False, "error": "No such breach."}
    if decision == "dismiss":
        b.state, b.resolved_at = "dismissed", datetime.utcnow()
        db.commit()
        pipeline.write_gate.audit(db, "breach", f"dismiss {b.doctype} {b.name}", f"{b.script}: {note}"[:300], actor=me["email"])
        return {"ok": True}
    if decision == "cancel":
        return pipeline.execute(db, me, {"op": "cancel", "doctype": b.doctype, "name": b.name})
    return {"ok": False, "error": "Unknown decision."}


@guarded
def cx_retry_change(db, me, change_id: int = 0, **_):
    _manager(me)
    ch = db.query(ChangeModel).get(int(change_id))
    if not ch or ch.state != "failed":
        return {"ok": False, "error": "Only a failed change can be retried."}
    ch.state, ch.error = "new", ""
    db.commit()
    return {"ok": True}


# ───────────────────────── script runtime (admin) ─────────────────────────

@guarded
def tsr_status(db, me, **_):
    _admin_only(me)
    reg = pipeline.engine().registry
    st = {s.name: s for s in db.query(ScriptStateModel)}
    scripts = []
    for name, r in sorted(reg.by_name.items()):
        s = st.get(name)
        scripts.append({"name": name, "type": r["script_type"], "doctype": r.get("reference_doctype") or "", "event": r.get("doctype_event") or r.get("api_method") or "",
                        "enabled": True if s is None else bool(s.enabled), "runs": s.runs if s else 0, "failures": s.failures if s else 0,
                        "avg_ms": int(s.total_ms / s.runs) if s and s.runs else 0, "last_error": s.last_error if s else ""})
    return {"ok": True, "rules_off": pipeline.rules_off(db), "count": len(scripts), "scripts": scripts, "vendor": _vendor_status()}


def _vendor_status() -> dict:
    import hashlib
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tsr", "vendor")
    try:
        sums = json.load(open(os.path.join(here, "CHECKSUMS.json")))
        recs = json.load(open(os.path.join(here, "server_scripts.json")))["records"]
        bad = [r["name"] for r in recs if sums.get(r["name"]) != hashlib.sha256(r["script"].encode()).hexdigest()]
        return {"ok": not bad, "scripts": len(recs), "drift": bad[:10]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@guarded
def tsr_set_script(db, me, name: str = "", enabled: bool = True, **_):
    _admin_only(me)
    if name not in pipeline.engine().registry.by_name:
        return {"ok": False, "error": "Unknown script."}
    if not enabled and name.startswith(pipeline.ALWAYS_ON_PREFIXES):
        return {"ok": False, "error": "This script numbers documents or runs the production ledger; it cannot be switched off one by one."}
    row = db.query(ScriptStateModel).get(name) or ScriptStateModel(name=name, runs=0, failures=0, total_ms=0)
    row.enabled = bool(enabled)
    db.merge(row)
    db.commit()
    pipeline.write_gate.audit(db, "tsr", f"{'enable' if enabled else 'disable'} {name}", "", actor=me["email"])
    return {"ok": True}


@guarded
def tsr_kill_switch(db, me, state: str = "status", **_):
    """state: off | on | status. 'off' stops every RULE script; numbering and the ledger engine stay on."""
    _admin_only(me)
    if state in ("off", "on"):
        pipeline.set_rules_off(db, state == "off")
        pipeline.write_gate.audit(db, "tsr", f"rules {state}", "kill switch", actor=me["email"])
    return {"ok": True, "rules_off": pipeline.rules_off(db)}


@guarded
def cx_connection(db, me, **_):
    """Is the tower talking to the Arinox ERP? (the S1/S2 questions in one call)"""
    _admin_only(me)
    try:
        be = _backend()
        user = None
        try:
            user = be._req("GET", "/api/method/frappe.auth.get_logged_user").get("message")
        except Exception as e:
            user = f"error: {e}"
        arinox = be.count("DocType", [["module", "=", "Arinox Apparel"]])
        scripts = be.count("Server Script") if arinox is not None else None
        missing = [r for r in ("Production Card", "Sales Contract", "Tech Pack", "Order TNA") if not be.get_list("DocType", {"name": r}, ["name"], limit=1)]
        return {"ok": True, "base": be.base.split("//")[-1], "api_user": user, "arinox_doctypes": arinox, "server_scripts_on_erp": scripts,
                "missing_core_doctypes": missing, "write_mode": __import__("writes").current_mode(),
                "note": "If server_scripts_on_erp > 0 and enabled there, every write would run its rules twice." if scripts else ""}
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "error": f"Cannot reach the ERP: {str(e)[:200]}"}


# ───────────────────────── reports ─────────────────────────

@guarded
def cx_reports(db, me, **_):
    reg = _reg()
    out = []
    for n in reg.names():
        r = reg.by_name[n]
        if guardrails.can(me["roles"], r["ref_doctype"] or "Sales Order", "read"):
            out.append({"name": n, "ref_doctype": r["ref_doctype"], "filters": r.get("filters") or []})
    return {"ok": True, "reports": out}


@guarded
def cx_report_run(db, me, name: str = "", filters: dict | None = None, **_):
    reg = _reg()
    rec = reg.by_name.get(name)
    if not rec:
        return {"ok": False, "error": "Unknown report."}
    guardrails.require(me["roles"], rec["ref_doctype"] or "Sales Order", "read")
    key = ("rep", name, json.dumps(filters or {}, sort_keys=True))
    cache = _report_cache.get(key)
    if cache and time.time() - cache[0] < 60:
        return {"ok": True, **cache[1], "cached": True}
    res = tsr_reports.run(reg, pipeline.engine(), _backend(), name, filters or {}, user=me["email"])
    _report_cache[key] = (time.time(), res)
    return {"ok": True, **res}


_report_cache: dict = {}


# ───────────────────────── today ─────────────────────────

@guarded
def cx_today(db, me, **_):
    """My queue: what needs me now."""
    out: dict[str, Any] = {"ok": True, "me": me}
    manager = bool(set(me["roles"]) & set(guardrails.ALL_POWER))
    out["approvals"] = db.query(ApprovalModel).filter(ApprovalModel.status == "pending").count() if manager else 0
    out["breaches"] = db.query(BreachModel).filter(BreachModel.state == "open").count()
    out["sync_failed"] = db.query(ChangeModel).filter(ChangeModel.state == "failed").count()
    out["inquiries_waiting"] = db.query(MailMessageModel).filter(MailMessageModel.classification == "new_enquiry",
                                                                 MailMessageModel.status == "new").count()
    out["health"] = _health(db)
    try:
        be = _backend()
        today = date.today().isoformat()
        if guardrails.can(me["roles"], "TNA Milestone", "read"):
            late = be.get_list("TNA Milestone", [["status", "in", ["Not Started", "In Progress", "Late"]], ["planned_date", "<", today]],
                               ["name", "sales_order", "label", "planned_date", "owner_user", "department"], order_by="planned_date asc", limit=25)
            out["overdue_milestones"] = late
        out["erp"] = "up"
    except Exception as e:                                                        # noqa: BLE001
        out["erp"] = "down"
        out["erp_error"] = str(e)[:160]
        out["overdue_milestones"] = []
    return out


def _health(db) -> dict:
    """Plain answers to "is it working?" for the Today screen: mail, the rules engine, writes."""
    h: dict[str, Any] = {}
    try:
        from models import MailSettingsModel
        import secret_store
        row = db.query(MailSettingsModel).order_by(MailSettingsModel.id.asc()).first()
        last = db.query(KVModel).filter(KVModel.key == "last_sync:mail").first()
        newest = db.query(MailMessageModel).order_by(MailMessageModel.id.desc()).first()
        if not row or not row.email_account:
            h["mail"] = {"state": "not_set", "text": "No mailbox set up", "fix": "mail"}
        elif not row.password:
            h["mail"] = {"state": "no_password", "text": f"{row.email_account}: no app password saved", "fix": "mail"}
        elif not secret_store.readable(row.password):
            h["mail"] = {"state": "password_unreadable", "fix": "mail",
                         "text": f"{row.email_account}: the saved password can't be unlocked — enter it again"}
        else:
            h["mail"] = {"state": "ok", "text": row.email_account}
        h["mail"]["last_sync"] = last.value if last else None
        h["mail"]["newest_mail"] = (newest.received_at if newest else None)
    except Exception as e:                                                        # noqa: BLE001
        h["mail"] = {"state": "unknown", "text": f"could not check ({type(e).__name__})"}
    try:
        reg = pipeline.engine().registry
        h["rules"] = {"scripts": len(reg.by_name), "rules_off": pipeline.rules_off(db),
                      "text": ("The ERP's business rules run inside the Tower on every change made here"
                               if not pipeline.rules_off(db) else "Rule scripts are switched OFF (kill switch)")}
    except Exception as e:                                                        # noqa: BLE001
        h["rules"] = {"scripts": 0, "text": f"rules not loaded ({type(e).__name__})"}
    h["write_mode"] = __import__("writes").current_mode()
    h["intake_write_path"] = config.INTAKE_WRITE_PATH
    return h


# ───────────────────────── order intake: review → confirm (2026-11-07) ─────────────────────────
# The legacy intake functions live in functions.py; ``bind_legacy`` hands them over at import time
# (importing functions.py from here would load a second copy of it when it runs as __main__).
_L: dict = {}


def bind_legacy(namespace: dict) -> None:
    _L.update(namespace)


_INTAKE_ROLES = {"Merchandiser"} | set(guardrails.ALL_POWER)


def _intake_role(me: dict):
    if not set(me["roles"]) & _INTAKE_ROLES:
        raise guardrails.Denied("Only a Merchandiser or a manager may approve an order intake.")


@guarded
def intake_review(db, me, run_id: int = 0, **_):
    """Every value approval would write, step by step, with a hash approval must quote back. Writes nothing."""
    return _L["intake_review_core"](db, int(run_id or 0))


@guarded
def intake_plan_edit(db, me, run_id: int = 0, step_key: str = "", field: str = "", value: Any = None, **_):
    """Change one value inside one step of the plan before approval (e.g. ``items.0.qty``)."""
    _intake_role(me)
    return _L["intake_plan_edit_core"](db, int(run_id or 0), step_key, field, value, actor=me["name"] or me["email"])


@guarded
def approve_intake(db, me, run_id: int = 0, note: str = "", review_hash: str = "", accept_blocked: int = 0, **_):
    """Approve the plan exactly as reviewed. Every ERP create runs through the guarded pipeline."""
    _intake_role(me)
    return _L["approve_intake"](db, run_id=int(run_id or 0), actor=me["name"] or me["email"], note=note or "",
                                review_hash=review_hash or "", accept_blocked=int(accept_blocked or 0), principal=me)


@guarded
def get_intake_options(db, me, kind: str = "currency", q: str = "", limit: int = 20, **_):
    """The choices behind the review sheet's dropdowns — currencies and Customers, straight from the ERP."""
    return _L["get_intake_options"](db, kind=kind or "currency", q=q or "", limit=int(limit or 20))


@guarded
def set_intake_customer(db, me, run_id: int = 0, customer: str = "", create: int = 0, name: str = "", **_):
    """Answer the buyer gate from the review sheet: link an existing Customer, or name a new one."""
    _intake_role(me)
    return _L["set_intake_customer"](db, int(run_id or 0), customer=customer or "", create=int(create or 0),
                                      name=name or "", actor=me["name"] or me["email"])


# ───────────────────────── T&A: the ERP owns the plan when it has one (2026-11-07) ─────────────────────────
# Decision: when the ERP holds an Order TNA for the order, its TNA Milestone rows are the system of
# record — an edit in the calendar is written there (through the pipeline). When it does not, the
# calendar's own overlay keeps the edit, and the answer says so.
_TNA_STATUS = {"done": "Done", "complete": "Done", "completed": "Done", "in_progress": "In Progress", "in progress": "In Progress",
               "started": "In Progress", "late": "Late", "overdue": "Late", "not_started": "Not Started", "pending": "Not Started",
               "planned": "Not Started", "na": "Not Applicable", "not_applicable": "Not Applicable"}


@guarded
def cx_tna_push_milestone(db, me, order_id: str = "", code: str = "", label: str = "", actual_date: str = "",
                          revised_date: str = "", status: str = "", remarks: str = "", preview: bool = False, **_):
    """Write a calendar edit to the ERP's TNA Milestone, when the order has an Order TNA there."""
    if not order_id or not (code or label):
        return {"ok": False, "error": "order_id and code are required."}
    be = _backend()
    try:
        tna = be.get_list("Order TNA", [["sales_order", "=", order_id]], ["name"], limit=1)
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": True, "erp": "unavailable", "note": f"Kept in the calendar only — the ERP could not be read ({str(e)[:120]})."}
    if not tna:
        return {"ok": True, "erp": "no_order_tna",
                "note": "Kept in the calendar. This order has no Order TNA in the ERP yet, so there is no ERP milestone to update."}
    rows = []
    for flt in ([["order_tna", "=", tna[0]["name"]], ["milestone_type", "=", code]],
                [["order_tna", "=", tna[0]["name"]], ["label", "=", label or code]]):
        try:
            rows = be.get_list("TNA Milestone", flt, ["name", "modified"], limit=1)
        except Exception:
            rows = []
        if rows:
            break
    if not rows:
        return {"ok": True, "erp": "no_matching_milestone",
                "note": f"Kept in the calendar. {tna[0]['name']} has no milestone for “{label or code}”."}
    data: dict[str, Any] = {}
    if actual_date:
        data["actual_date"] = actual_date
    if revised_date:
        data["revised_date"] = revised_date
    if status:
        data["status"] = _TNA_STATUS.get(status.strip().lower(), status if status in
                                         ("Not Started", "In Progress", "Done", "Late", "Not Applicable") else "In Progress")
    if remarks:
        data["remarks"] = remarks[:1000]
    if not data:
        return {"ok": False, "error": "Nothing to write."}
    out = pipeline.execute(db, me, {"op": "save", "doctype": "TNA Milestone", "name": rows[0]["name"], "data": data,
                                    "modified": rows[0].get("modified") or "", "preview": bool(preview),
                                    "idem_key": None if preview else "tna-%s-%s" % (rows[0]["name"], __import__("hashlib").sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12])})
    return {**out, "erp": "written" if out.get("ok") and not preview else out.get("erp", "preview" if preview else "refused"),
            "milestone": rows[0]["name"], "order_tna": tna[0]["name"]}


# ───────────────────────── users & roles (appster core-builder HARD RULE 0, E0 repair 2026-11-07) ─────────────────────────
# The tower's own user screen calls list_tower_users / set_tower_user; these are the platform's names for the
# same things, so KOGO can manage people of this app the standard way.

def kogo_list_users(db, **kwargs):
    r = cx_users.list_tower_users(db, **kwargs)
    if "users" in r:
        r["users"] = [{**u, "role": "admin" if u["is_admin"] else (", ".join(u["roles"]) or "member")} for u in r["users"]]
    return r


def kogo_add_user(db, email: str = "", name: str = "", role: str = "", roles: list | None = None, **kwargs):
    try:
        me = cx_users.require(db, **kwargs)
    except PermissionError as e:
        return {"ok": False, "error": str(e), "auth": False}
    if not me["is_admin"]:
        return {"ok": False, "error": "Administrators only"}
    email = (email or "").strip().lower()
    if "@" not in email:
        return {"ok": False, "error": "A valid email is required"}
    if db.query(UserModel).filter(UserModel.email == email).first():
        return {"ok": False, "error": "That person already has access"}
    want = list(roles or ([role] if role in guardrails.ROLES else []))
    bad = [r for r in want if r not in guardrails.ROLES]
    if bad:
        return {"ok": False, "error": f"Unknown role(s): {', '.join(bad)}"}
    db.add(UserModel(email=email, name=name or email, role="admin" if "Admin" in want else "member",
                     is_admin="Admin" in want, tower_roles=json.dumps(want)))
    db.commit()
    return {"ok": True, "email": email, "roles": want}


def kogo_set_user_role(db, email: str = "", role: str = "", roles: list | None = None, **kwargs):
    want = list(roles) if roles is not None else ([role] if role else [])
    return cx_users.set_tower_user(db, email=email, roles=want, **kwargs)


def kogo_remove_user(db, email: str = "", **kwargs):
    """Switches the person off (their history and audit trail are kept)."""
    return cx_users.set_tower_user(db, email=email, active=False, **kwargs)


def kogo_list_roles(db, **kwargs):
    try:
        cx_users.require(db, **kwargs)
    except PermissionError as e:
        return {"ok": False, "error": str(e), "auth": False}
    return {"ok": True, "roles": [{"name": r, "groups": sorted(g for g, rs in guardrails.WRITE.items() if r in rs)}
                                  for r in guardrails.ROLES]}


# ───────────────────────── inquiries (any format) ─────────────────────────

_INQ_CLASSES = ("new_enquiry", "inquiry")


def _load_bytes(att: MailAttachmentModel) -> bytes:
    import deals
    return deals._load_bytes(att)


def _kv(db, key, value=None):
    row = db.query(KVModel).filter(KVModel.key == key).first()
    if value is None:
        return json.loads(row.value) if row and row.value else None
    if row:
        row.value = json.dumps(value, default=str)
    else:
        db.add(KVModel(key=key, value=json.dumps(value, default=str)))
    db.commit()
    return value


def _customers() -> list[dict]:
    try:
        return _backend().get_list("Customer", None, ["name", "customer_name"], limit=2000)
    except Exception:
        return []


@guarded
def cx_inquiry_analyse(db, me, mail_id: int = 0, refresh: bool = False, **_):
    """Read a stored mail with all its attachments, in any format, and return fields, completeness and proposals."""
    import inquiry_v2
    key = f"iq2:{int(mail_id)}"
    if not refresh:
        hit = _kv(db, key)
        if hit:
            return {"ok": True, **hit, "cached": True}
    m = db.query(MailMessageModel).get(int(mail_id))
    if not m:
        return {"ok": False, "error": "No such mail."}
    atts = [{"filename": a.filename, "mime": a.mime, "data": _load_bytes(a)} for a in db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == m.id)]
    existing = _kv(db, "iq2:register") or []
    llm = None
    if config.llm_available():
        import ai_nextsteps
        llm = lambda prompt: ai_nextsteps._llm(db, prompt, timeout=60) or ""                 # noqa: E731
    res = inquiry_v2.understand(m.subject or "", m.body_text or "", atts, m.from_addr or "", m.from_name or "", m.message_id or "",
                                _customers(), existing, llm)
    res["mail"] = {"id": m.id, "subject": m.subject, "from": m.from_addr, "received_at": m.received_at}
    res["steps_done"] = {}
    _kv(db, key, res)
    return {"ok": True, **res}


@guarded
def cx_inquiry_queue(db, me, **_):
    """Mails that look like inquiries, with their analysis state."""
    rows = db.query(MailMessageModel).filter(MailMessageModel.classification.in_(_INQ_CLASSES + ("other", "query"))
                                             ).order_by(MailMessageModel.id.desc()).limit(80).all()
    out = []
    for m in rows:
        a = _kv(db, f"iq2:{m.id}")
        out.append({"id": m.id, "subject": m.subject, "from": m.from_addr, "received_at": m.received_at, "attachments": m.has_attachments,
                    "analysed": bool(a), "type": (a or {}).get("classification", {}).get("type"),
                    "score": (a or {}).get("completeness", {}).get("score"), "steps_done": list((a or {}).get("steps_done", {}))})
    return {"ok": True, "mails": [x for x in out if x["analysed"] or x["attachments"] or "enq" in (x["subject"] or "").lower()
                                  or "rfq" in (x["subject"] or "").lower() or "quot" in (x["subject"] or "").lower() or x["type"] not in (None, "noise")]}


def _subst(obj, results: dict):
    if isinstance(obj, str):
        return re.sub(r"\{\{(\w+)\.(\w+)\}\}", lambda m: str((results.get(m.group(1)) or {}).get(m.group(2), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: _subst(v, results) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, results) for v in obj]
    return obj


@guarded
def cx_inquiry_step(db, me, mail_id: int = 0, step_id: str = "", preview: bool = False, approval_id: int = 0, **_):
    """Run one proposed step through the pipeline. A later step uses the result of an earlier one."""
    key = f"iq2:{int(mail_id)}"
    a = _kv(db, key)
    if not a:
        return {"ok": False, "error": "Analyse the mail first."}
    step = next((s for s in a["proposals"] if s["id"] == step_id), None)
    if not step or not step.get("request"):
        return {"ok": False, "error": "Nothing to run for this step."}
    done = a.setdefault("steps_done", {})
    if step.get("needs") and step["needs"] not in done:
        return {"ok": False, "error": f"Do “{step['needs']}” first."}
    if step_id in done and not preview:
        return {"ok": True, "already": True, "result": done[step_id]}
    results = {k: v for k, v in done.items()}
    req = _subst(step["request"], results)
    idem = f"iq2-{mail_id}-{step_id}"
    out = pipeline.execute(db, me, {**req, "preview": bool(preview), "approval_id": approval_id or None, "idem_key": idem})
    if out.get("ok") and not preview:
        doc = out.get("doc") or {}
        result = {"name": doc.get("name") or (out.get("result") or {}).get("name", ""), "doctype": req.get("doctype")}
        # the Tech Pack step runs an API script that returns an unsaved document; the tower then inserts it
        if step.get("then_insert") and isinstance(out.get("result"), dict):
            base = dict(out["result"])
            base.update(step["then_insert"]["extra"])
            base.pop("name", None)
            base["doctype"] = step["then_insert"]["doctype"]
            ins = pipeline.execute(db, me, {"op": "insert", "doctype": base["doctype"], "data": base, "idem_key": idem + "-insert",
                                            "preview": False})
            out["second"] = ins
            if not ins.get("ok"):
                return {**ins, "step": step_id, "note": "The script ran, but saving the Tech Pack failed."}
            result = {"name": (ins.get("doc") or {}).get("name", ""), "doctype": base["doctype"]}
        done[step_id] = result
        _kv(db, key, a)
        if step_id == "opportunity":
            reg = _kv(db, "iq2:register") or []
            reg.append({"id": mail_id, "customer": req["data"].get("party_name"), "styles": (a["fields"].get("style_refs") or {}).get("value", []),
                        "opportunity": result["name"], "fields": a["fields"]})
            _kv(db, "iq2:register", reg[-500:])
    return {**out, "step": step_id}


@guarded
def cx_inquiry_draft_reply(db, me, mail_id: int = 0, **_):
    """Store the 'please send us …' reply as a draft in Outbound Mail. Nothing is sent from here."""
    a = _kv(db, f"iq2:{int(mail_id)}")
    m = db.query(MailMessageModel).get(int(mail_id))
    if not a or not m:
        return {"ok": False, "error": "Analyse the mail first."}
    step = next((s for s in a["proposals"] if s["id"] == "ask_buyer"), None)
    if not step:
        return {"ok": False, "error": "Nothing is missing — no reply needed."}
    key = f"iq2-reply-{m.id}"
    d = db.query(EmailDraftModel).filter(EmailDraftModel.idempotency_key == key).first()
    if not d:
        d = EmailDraftModel(action_key=f"inquiry:{m.id}", intent="inquiry_info", to_email=m.from_addr or "", from_name=config.MAIL_FROM_NAME,
                            subject="Re: " + (m.subject or ""), body=step["reply_draft"], status="draft", in_reply_to=m.message_id or "",
                            grounding_ok=1, policy_version="iq2-1", idempotency_key=key, decided_by=me["email"])
        db.add(d)
        db.commit()
    return {"ok": True, "draft_id": d.id, "status": d.status}


FUNCTIONS: dict[str, Callable] = {
    # identity (appster core-builder HARD RULE 0)
    "kogo_me": cx_users.kogo_me, "kogo_register_users": cx_users.kogo_register_users, "kogo_login": cx_users.kogo_login,
    "kogo_logout": cx_users.kogo_logout, "kogo_set_password": cx_users.kogo_set_password,
    "kogo_admin_set_password": cx_users.kogo_admin_set_password, "list_tower_users": cx_users.list_tower_users,
    "set_tower_user": cx_users.set_tower_user,
    "kogo_list_users": kogo_list_users, "kogo_add_user": kogo_add_user, "kogo_set_user_role": kogo_set_user_role,
    "kogo_remove_user": kogo_remove_user, "kogo_list_roles": kogo_list_roles,
    # order intake: review → confirm (replaces the legacy approve_intake)
    "intake_review": intake_review, "intake_plan_edit": intake_plan_edit, "approve_intake": approve_intake,
    "get_intake_options": get_intake_options, "set_intake_customer": set_intake_customer,
    # T&A → ERP
    "cx_tna_push_milestone": cx_tna_push_milestone,
    # navigation, records
    "cx_catalog": cx_catalog, "cx_nav_counts": cx_nav_counts, "cx_search": cx_search, "cx_doc_meta": cx_doc_meta,
    "cx_doc_list": cx_doc_list, "cx_doc_get": cx_doc_get, "cx_link_search": cx_link_search,
    # guarded writes
    "cx_write": cx_write, "cx_run_script": cx_run_script, "cx_approvals": cx_approvals, "cx_decide": cx_decide,
    "cx_runs": cx_runs, "cx_rollback_run": cx_rollback_run,
    # two-way sync
    "sync_changes": sync_changes, "erp_event": erp_event, "cx_sync_status": cx_sync_status, "cx_breaches": cx_breaches,
    "cx_breach_decide": cx_breach_decide, "cx_retry_change": cx_retry_change,
    # script runtime
    "tsr_status": tsr_status, "tsr_set_script": tsr_set_script, "tsr_kill_switch": tsr_kill_switch, "cx_connection": cx_connection,
    # reports, today, inquiries
    "cx_reports": cx_reports, "cx_report_run": cx_report_run, "cx_today": cx_today,
    "cx_inquiry_analyse": cx_inquiry_analyse, "cx_inquiry_queue": cx_inquiry_queue, "cx_inquiry_step": cx_inquiry_step,
    "cx_inquiry_draft_reply": cx_inquiry_draft_reply,
}

#: functions the ERP (not a person) may call; they authenticate themselves.
PUBLIC = {"erp_event", "kogo_register_users", "kogo_login"}
