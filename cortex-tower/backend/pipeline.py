"""The single guarded write pipeline. Every tower → ERP write, from any source (a form, a button, a
recommendation, an intake approval, the chatbot), goes through :func:`execute`; nothing else may call the
ERP write primitives (``tests/test_pipeline_guard.py`` enforces that by grep).

Order of the steps (plan §2.3):

 1 identity & role      2 mode gate          3 field guard        4 preview (dry run of the Before-scripts)
 5 approval             6 document lock      7 optimistic lock    8 execute through the TSR + journal
 9 audit                10 ERP trace comment 11 event ledger      12 cache invalidation

Nothing is "queued blindly": if the ERP cannot be reached the call fails and says so.
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from datetime import datetime
from typing import Any, Optional

import config
import guardrails
import write_gate
import writes
from models_cx import (ApprovalModel, BreachModel, ChangeModel, DocLockModel, ScriptStateModel, WriteRunModel)
from tsr import connection
from tsr.errors import (TSRBackendError, TSRConflict, TSRError, TSRNotFound, TSRUnsupported, TSRValidationError)
from tsr.runner import Context, Engine, Registry, TSRScriptError, ALWAYS_ON_PREFIXES
from tsr import shim

_engine: Optional[Engine] = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(Registry.load())
    return _engine


def _json(o) -> str:
    return json.dumps(o, default=str)


# ───────────────────────── kill switch / script state ─────────────────────────

def rules_off(db) -> bool:
    from models import KVModel
    row = db.query(KVModel).filter(KVModel.key == "tsr_rules_off").first()
    return bool(row and row.value == "1")


def set_rules_off(db, off: bool):
    from models import KVModel
    row = db.query(KVModel).filter(KVModel.key == "tsr_rules_off").first()
    if row:
        row.value = "1" if off else "0"
    else:
        db.add(KVModel(key="tsr_rules_off", value="1" if off else "0"))
    db.commit()


def _enabled_fn(db):
    off = rules_off(db)
    disabled = {r.name for r in db.query(ScriptStateModel).filter(ScriptStateModel.enabled == False)}   # noqa: E712

    def enabled(name: str) -> bool:
        if name in disabled:
            return False
        if off and not name.startswith(ALWAYS_ON_PREFIXES):
            return False
        return True
    return enabled


def _record_runs(db, ctx: Context, error: Optional[BaseException], ms: int):
    try:
        for name in set(ctx.ran):
            row = db.query(ScriptStateModel).get(name) or ScriptStateModel(name=name, enabled=True, runs=0, failures=0, total_ms=0)
            row.runs = (row.runs or 0) + ctx.ran.count(name)
            row.total_ms = (row.total_ms or 0) + ms // max(1, len(set(ctx.ran)))
            row.last_run = datetime.utcnow()
            if isinstance(error, TSRScriptError) and error.script == name:
                row.failures = (row.failures or 0) + 1
                row.last_error = str(error)[:500]
            db.merge(row)
        db.commit()
    except Exception:
        db.rollback()


# ───────────────────────── permission hook for scripts ─────────────────────────

def _perm_checker(roles: list[str]):
    def check(user, doctype, perm, name=None):
        # Scripts create, change and delete helper documents on the user's behalf (numbers, ledger rows, T&A
        # stamps) — on the hosted site they do it with ignore_permissions. The user-visible operation was
        # authorised in step 1, so the only thing re-checked here is what a script explicitly asks to READ
        # (``doc.check_permission("read")``), exactly as the ERP would.
        if perm == "read":
            guardrails.require(roles, doctype, "read", name)
    return check


# ───────────────────────── locks ─────────────────────────

def _acquire(db, key: str, owner: str) -> Optional[str]:
    now = time.time()
    row = db.query(DocLockModel).get(key)
    if row and row.expires > now and row.owner != owner:
        return row.owner
    ttl = config.LOCK_TTL_SECONDS
    db.merge(DocLockModel(key=key, owner=owner, expires=now + ttl))
    db.commit()
    return None


def _release(db, key: str, owner: str):
    row = db.query(DocLockModel).get(key)
    if row and row.owner == owner:
        db.delete(row)
        db.commit()


# ───────────────────────── helpers ─────────────────────────

def _fp(req: dict) -> str:
    keys = {k: req.get(k) for k in ("op", "doctype", "name", "data", "method", "params")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True, default=str).encode()).hexdigest()


def _value_of(req: dict) -> float:
    d = req.get("data") or {}
    for k in ("base_grand_total", "grand_total", "total_amount", "total", "amount"):
        try:
            if d.get(k):
                return float(d[k])
        except (TypeError, ValueError):
            pass
    return 0.0


def _api_doctype(method: str) -> Optional[str]:
    slug = (method or "").lower()
    best = None
    for dt in guardrails.GROUP:
        s = "arinox_" + dt.lower().replace(" ", "_") + "_"
        if slug.startswith(s) and (best is None or len(dt) > len(best)):
            best = dt
    return best


def _error(message: str, **extra) -> dict:
    return {"ok": False, "error": message, **extra}


def _run_op(ctx: Context, req: dict) -> dict:
    """Drive one operation through the event engine. Returns what the caller wants to show."""
    eng = engine()
    op, dt, name = req["op"], req.get("doctype", ""), req.get("name", "")
    out: dict[str, Any] = {}
    if op == "api":
        flags = eng.run_api(ctx, req["method"], dict(req.get("params") or {}))
        out["result"] = flags.get("arinox_result", flags)
    elif op == "insert":
        d = shim.Doc(ctx, {**(req.get("data") or {}), "doctype": dt}, is_new=True)
        eng.insert(ctx, d)
        out["doc"] = d.as_dict()
    elif op == "save":
        d = ctx.backend.get_doc(dt, name)
        d.setdefault("doctype", dt)
        if req.get("modified") and str(d.get("modified")) != str(req["modified"]):
            raise TSRConflict(dt, name, str(req["modified"]), str(d.get("modified")))
        doc = shim.Doc(ctx, d)
        doc.__dict__["_before"] = json.loads(_json(doc.as_dict()))
        for k, v in (req.get("data") or {}).items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                doc.set(k, [{**r, "doctype": r.get("doctype")} for r in v])   # rows renumbered, as Frappe does on save
            else:
                doc.__dict__[k] = v
        eng.save(ctx, doc)
        out["doc"] = doc.as_dict()
    elif op in ("submit", "cancel"):
        d = ctx.backend.get_doc(dt, name)
        d.setdefault("doctype", dt)
        if req.get("modified") and str(d.get("modified")) != str(req["modified"]):
            raise TSRConflict(dt, name, str(req["modified"]), str(d.get("modified")))
        doc = shim.Doc(ctx, d)
        doc.__dict__["_before"] = json.loads(_json(doc.as_dict()))
        (eng.submit if op == "submit" else eng.cancel)(ctx, doc)
        out["doc"] = doc.as_dict()
    elif op == "delete":
        eng.delete(ctx, dt, name)
    else:
        raise TSRUnsupported(f"operation {op!r}")
    return out


def _touched(entries: list) -> list[tuple[str, str]]:
    seen, out = set(), []
    for e in entries:
        k = (e["doctype"], e["name"])
        if e["op"] in ("call",) or not k[0] or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


# ───────────────────────── the pipeline ─────────────────────────

def execute(db, principal: dict, req: dict, backend=None) -> dict:
    """Run one guarded operation. ``principal`` comes from ``cx_users.require`` — never from request params.

    ``req``: ``{op, doctype, name, data, method, params, modified, preview, approval_id, idem_key}``.
    Returns ``{ok, ...}``; ``ok: False`` always carries ``error`` (a sentence for the user) and, when something
    was undone or could not be, ``undone`` / ``attention``.
    """
    t0 = time.time()
    actor, roles = principal["email"], principal["roles"]
    op = req.get("op")
    dt, name = req.get("doctype", ""), req.get("name", "")
    method = req.get("method", "")
    if op == "api":
        dt = dt or _api_doctype(method) or ""
        req = {**req, "doctype": dt}

    # 1 identity & role -----------------------------------------------------------------
    try:
        if op == "api":
            if dt:
                guardrails.require(roles, dt, "write", name or None)
            elif not set(roles) & set(guardrails.ALL_POWER):
                raise guardrails.Denied(f"Only a manager may run {method}.")
        elif op in ("insert", "save"):
            guardrails.require(roles, dt, "create" if op == "insert" else "write", name or None)
        elif op in ("submit", "cancel", "delete"):
            guardrails.require(roles, dt, op, name)
        else:
            return _error(f"Unknown operation {op!r}.")
    except guardrails.Denied as e:
        return _error(e.message, denied=True)

    cls = guardrails.classify(op, dt, method)

    # 3 field guard ---------------------------------------------------------------------
    if op in ("insert", "save"):
        problems = guardrails.check_fields(dt, req.get("data") or {})
        if problems:
            return _error("Not saved: " + "; ".join(problems[:5]), problems=problems)

    try:
        be = backend or connection.get_backend()
    except Exception as e:
        return _error(f"The ERP is not connected: {e}", unreachable=True)

    enabled = _enabled_fn(db)

    def make_ctx(mode: str, persist=None) -> Context:
        return Context(be, engine(), user=principal.get("erp_user") or actor, roles=roles, mode=mode, persist=persist,
                       perm_checker=_perm_checker(roles), script_enabled=enabled)

    # 4 preview -------------------------------------------------------------------------
    pctx = make_ctx("record")
    partial = False
    try:
        pout: dict = {}
        try:
            pout = _run_op(pctx, req)
        except TSRNotFound:
            if op != "api":
                raise
            partial = True            # an API script read something its own earlier (simulated) step would have created
        preview = {"partial": partial, "operations": pctx.sink.ops, "messages": pctx.messages, "class": cls,
                   # what the business rules made of the document — a costing screen shows the price before saving
                   "doc": pout.get("doc"), "result": pout.get("result"),
                   "scripts": sorted(set(pctx.ran)), "warnings": [m["message"] for m in pctx.messages if not m.get("alert")]}
        if cls == "risky" and op in ("cancel", "submit"):
            preview["note"] = ("Cancelling reverses the stock/ledger entries; it cannot be reopened." if op == "cancel"
                               else "Submitting posts stock/ledger entries; undoing it means cancelling.")
    except TSRValidationError as e:
        return _error(e.message, blocked=True, title=e.title)
    except TSRConflict as e:
        return _error(str(e), conflict=True, theirs=e.theirs)
    except TSRNotFound as e:
        return _error(f"Not found: {e.doctype} {e.name}".strip())
    except (TSRUnsupported, TSRScriptError, TSRBackendError) as e:
        return _error(_friendly(e), technical=str(e)[:600])
    if req.get("preview"):
        return {"ok": True, "preview": preview, "class": cls}

    # 2 mode gate (previews above are always allowed) ----------------------------------------
    need = guardrails.MODE_FOR_CLASS[cls]
    if not writes.mode_allows(need):
        return _error(f"Writes of this kind are off (mode '{writes.current_mode()}', needs '{need}').", mode=writes.current_mode())

    # rate limit ------------------------------------------------------------------------
    recent = db.query(WriteRunModel).filter(WriteRunModel.actor == actor,
                                            WriteRunModel.started_at >= datetime.utcfromtimestamp(time.time() - 60)).count()
    if recent >= config.MAX_WRITES_PER_MINUTE:
        return _error("Too many changes in the last minute. Wait a moment and try again.", rate_limited=True)

    # 5 approval ------------------------------------------------------------------------
    fp = _fp(req)
    needs_approval = cls == "risky" or (config.APPROVAL_VALUE_LIMIT and _value_of(req) > config.APPROVAL_VALUE_LIMIT)
    approval = None
    if needs_approval:
        aid = req.get("approval_id")
        approval = db.query(ApprovalModel).get(int(aid)) if aid else None
        if not approval:
            a = ApprovalModel(requester=actor, cls=cls, reason=f"{op} {dt} {name}".strip() if op != "api" else f"run {method}",
                              request=_json({**req, "fp": fp}), preview=_json(preview))
            db.add(a)
            db.commit()
            return {"ok": False, "needs_approval": True, "approval_id": a.id, "class": cls, "preview": preview,
                    "error": "A manager must approve this before it runs."}
        if approval.status != "approved":
            return _error(f"Approval #{approval.id} is {approval.status}.", approval_id=approval.id)
        if json.loads(approval.request).get("fp") != fp:
            return _error("The request changed after it was approved. Ask again.", approval_id=approval.id)
        if approval.approver == actor or approval.requester == approval.approver:
            return _error("The person who approves cannot be the person who asked.", approval_id=approval.id)

    # idempotency -----------------------------------------------------------------------
    key = req.get("idem_key")
    if key:
        prev = db.query(WriteRunModel).filter(WriteRunModel.idem_key == key).first()
        if prev:
            if prev.status == "done":
                return {**json.loads(prev.result or "{}"), "ok": True, "replayed": True, "run_id": prev.id}
            if prev.status in ("started",) and (datetime.utcnow() - prev.started_at).total_seconds() < 120:
                return _error("This is already running. Wait for it to finish.", in_progress=True)
            _compensate_run(db, be, prev)             # a crashed attempt: undo what it left, then run again
            db.delete(prev)
            db.commit()

    # 6 lock ----------------------------------------------------------------------------
    lock_key = f"{dt}::{name}" if name else ""
    if lock_key:
        holder = _acquire(db, lock_key, actor)
        if holder:
            return _error(f"{dt} {name} is being edited by {holder}.", locked_by=holder)

    run = WriteRunModel(idem_key=key or None, actor=actor, op=op, doctype=dt, name=name, cls=cls, status="started",
                        request=_json({k: v for k, v in req.items() if k not in ("approval_id",)}))
    db.add(run)
    db.commit()

    def persist(entry: dict):
        try:
            j = json.loads(run.journal or "[]")
            j = [x for x in j if x.get("seq") != entry.get("seq")] + [entry]
            run.journal = _json(sorted(j, key=lambda x: x.get("seq", 0)))
            db.commit()
        except Exception:
            db.rollback()

    ctx = make_ctx("live", persist=persist)
    try:
        # 7 optimistic lock is inside _run_op (compares `modified`) and again by the server on save
        out = _run_op(ctx, req)
        ms = int((time.time() - t0) * 1000)
        _record_runs(db, ctx, None, ms)
        entries = ctx.sink.entries
        res: dict[str, Any] = {"ok": True, "run_id": run.id, "class": cls, **out,
                               "messages": ctx.messages, "scripts": sorted(set(ctx.ran)), "skipped_writes": getattr(ctx.sink, "skipped", []),
                               "written": [f'{e["op"]} {e["doctype"]} {e["name"]}' for e in entries if e["op"] != "call"]}
        # 10 ERP trace comment + 11 event ledger ------------------------------------------------
        touched = _touched(entries)
        primary = (out.get("doc") or {}).get("name") or name
        if dt and primary:
            _trace(be, dt, primary, actor, run.id, op, method)
        elif dt:                                    # an `api` run names no document: leave the line on every document of the request's doctype it made or changed
            for d, n in [k for k in touched if k[0] == dt or k[0] in _TRACED_KINDS][:20]:
                _trace(be, d, n, actor, run.id, op, method)
        _ledger(db, be, touched)
        run.status, run.result, run.finished_at = "done", _json({k: v for k, v in res.items() if k != "doc"}), datetime.utcnow()
        db.commit()
        # 9 audit -----------------------------------------------------------------------------
        write_gate.audit(db, "erp_write", f"{op} {dt} {primary}".strip(), f"run #{run.id}: " + "; ".join(res["written"][:12]),
                         actor=actor, approved="yes" if approval else None)
        if approval:
            approval.status = "used"
            db.commit()
        # 12 cache --------------------------------------------------------------------------
        try:
            import erp
            erp.erp_invalidate_cache()
        except Exception:
            pass
        return res
    except Exception as e:                                                       # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        _record_runs(db, ctx, e, ms)
        undo = ctx.sink.compensate()
        run.status = "compensated" if not undo["failed"] else "partial"
        run.result = _json({"error": str(e)[:600], "undo": undo})
        run.finished_at = datetime.utcnow()
        db.commit()
        attention = None
        if undo["failed"] or undo["irreversible"]:
            attention = undo["failed"] + undo["irreversible"]
            import changefeed
            changefeed._open_breach(db, dt or "-", name or "-", "partial-write",
                                    f"Run #{run.id} left something behind: " + "; ".join(attention[:5]))
        write_gate.audit(db, "erp_write_failed", f"{op} {dt} {name}".strip(), f"run #{run.id}: {str(e)[:300]}", actor=actor)
        if isinstance(e, TSRValidationError):
            return _error(e.message, run_id=run.id, undone=undo["undone"], attention=attention)
        if isinstance(e, TSRConflict):
            return _error(str(e), conflict=True, theirs=e.theirs, run_id=run.id, undone=undo["undone"])
        return _error(_friendly(e), technical=str(e)[:600], run_id=run.id, undone=undo["undone"], attention=attention)
    finally:
        if lock_key:
            _release(db, lock_key, actor)


def _friendly(e: BaseException) -> str:
    if isinstance(e, TSRUnsupported):
        return "This action needs something the tower cannot do yet: " + str(e)[:200]
    if isinstance(e, TSRScriptError):
        return f"A business rule failed to run ({e.script}). Nothing was changed. Tell your administrator."
    if isinstance(e, TSRBackendError):
        if e.status == 0:
            return "The ERP did not answer. Nothing was changed; try again in a moment."
        return "The ERP refused: " + (e.detail or str(e))[:300]
    if isinstance(e, TSRValidationError):
        return e.message
    return "Something went wrong: " + str(e)[:200]


#: business documents an `api` run may make that people look for on the ERP form (side records such as movements, batches, bundles and milestones are not listed)
_TRACED_KINDS = {"Factory Allocation", "Purchase Order", "Purchase Invoice", "Stock Entry", "Material Request", "Quality Inspection", "Sales Invoice", "Delivery Note",
                 "Shipment", "Payment Entry", "Packing List", "Final Inspection", "Cut Plan", "Production Card", "Sample Approval", "PP Meeting", "Fabric Inspection", "Trim Inspection"}


def _trace(be, dt: str, name: str, actor: str, run_id: int, op: str, method: str):
    try:
        link = f" {config.TOWER_URL}#/doc/{dt}/{name}" if config.TOWER_URL else ""
        what = f"ran {method}" if op == "api" else op
        be.add_comment(dt, name, f"Cortex Tower: {what} by {actor} (run #{run_id}).{link}")
    except Exception:
        pass


def _ledger(db, be, touched: list[tuple[str, str]]):
    """Record (doc, modified) of everything we just wrote, so the sync does not treat our own write as an ERP-side edit."""
    for dt, name in touched[:80]:
        try:
            row = be.get_list(dt, {"name": name}, ["name", "modified", "docstatus"], limit=1)
            if not row:
                continue
            m = str(row[0].get("modified"))
            if not db.query(ChangeModel).filter_by(doctype=dt, name=name, modified=m).first():
                db.add(ChangeModel(doctype=dt, name=name, event="tower", modified=m, docstatus=int(row[0].get("docstatus") or 0),
                                   source="tower", state="done", processed_at=datetime.utcnow()))
        except Exception:
            continue
    try:
        db.commit()
    except Exception:
        db.rollback()


def _compensate_run(db, be, run: WriteRunModel):
    from tsr.journal import LiveSink
    sink = LiveSink(be)
    sink.entries = [dict(e) for e in json.loads(run.journal or "[]")]
    res = sink.compensate()
    run.status = "compensated" if not res["failed"] else "partial"
    db.commit()
    return res


# ───────────────────────── approvals ─────────────────────────

def decide_approval(db, principal: dict, approval_id: int, decision: str, in_erp: bool = False) -> dict:
    """Close a held write. ``in_erp`` means the decision itself was taken in the ERP, so the tower only records it.

    The held operations are ERP decisions — a submit, a cancel, a delete of a real document — and the person who owns
    that decision is the one who owns the ERP document. A single-person workspace makes the "somebody else must
    approve" rule impossible to satisfy, so the honest path is the one the customer asked for: decide it in the ERP,
    and let the tower record that it is decided (``in_erp``). Nothing here performs the write either way.
    """
    a = db.query(ApprovalModel).get(int(approval_id))
    if not a:
        return _error("No such approval.")
    if a.status != "pending":
        return _error(f"Already {a.status}.")
    if not set(principal["roles"]) & set(guardrails.ALL_POWER):
        return _error("Only a manager can approve.")
    if decision not in ("approve", "reject"):
        return _error("decision must be approve or reject")
    if a.requester == principal["email"] and not in_erp:
        req = json.loads(a.request or "{}")
        return _error("You cannot approve your own request here. Make this decision in the ERP on "
                      f"{req.get('doctype') or 'the document'} {req.get('name') or ''}".strip()
                      + " and record it as decided there.", in_erp_required=True)
    a.status = ("approved" if decision == "approve" else "rejected") if not in_erp else \
        ("approved-in-erp" if decision == "approve" else "rejected-in-erp")
    a.approver, a.decided_at = principal["email"], datetime.utcnow()
    db.commit()
    write_gate.audit(db, "approval", f"{decision}{' (in the ERP)' if in_erp else ''} #{a.id}", a.reason,
                     actor=principal["email"], approved="yes" if decision == "approve" else "no")
    return {"ok": True, "status": a.status, "approval_id": a.id, "in_erp": bool(in_erp)}


def rollback_run(db, principal: dict, run_id: int) -> dict:
    """Undo a finished run from its journal (managers). What cannot be undone is listed, not hidden."""
    if not set(principal["roles"]) & set(guardrails.ALL_POWER):
        return _error("Only a manager can undo a run.")
    run = db.query(WriteRunModel).get(int(run_id))
    if not run or run.status != "done":
        return _error("Only a finished run can be undone.")
    res = _compensate_run(db, connection.get_backend(), run)
    write_gate.audit(db, "erp_rollback", f"run #{run.id}", _json(res)[:500], actor=principal["email"])
    return {"ok": not res["failed"], **res}
