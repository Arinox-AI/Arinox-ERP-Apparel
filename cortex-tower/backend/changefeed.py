"""ERP → tower: hear about changes made in the ERP, run the follow-up the missing Server Scripts would have run,
and flag the ones that break a rule. The tower → ERP direction is ``pipeline.py``.

Two intakes, one ledger
-----------------------
* **Webhook** (``erp_event``) — a Frappe Webhook record (plain data, no Server Script access needed) posts
  ``{doctype, name, event, modified}`` with a shared secret. It only *enqueues*; processing is separate so the
  ERP gets a fast answer.
* **Poller** (``sync_changes``) — the safety net that always runs: per watched doctype, rows with
  ``modified >= watermark``. The watermark advances only after the rows are recorded, equal timestamps at the page
  boundary are not skipped (``seen_at_watermark``), and deletions come from ``Deleted Document``.

Both write ``cx_change`` rows unique on ``(doctype, name, modified)``. The tower's own writes register their
``(doc, modified)`` there as ``done`` (``pipeline._ledger``), so an echo of our own write is never reconciled.

Reconcile
---------
* docstatus 0→1 seen in the ERP  → run *After Save* + *After Submit* (ledger posts, T&A stamps …)
* docstatus 1→2                  → run *After Cancel*
* any other change               → run *After Save* (derived data stays right)
* every change                   → run the *Before* scripts in **check** mode; a refusal becomes a **breach**
  (never an automatic revert — a person decides).

A transition that cannot be proven (a document the tower has never seen, no history) is treated as a plain save,
not as a submit: replaying a submit twice is worse than missing one. Such cases are counted in ``unproven``.
"""

from __future__ import annotations

import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError

import config
from models import KVModel
from models_cx import BreachModel, ChangeModel, SyncStateModel
from tsr.errors import TSRConflict, TSRError, TSRNotFound, TSRValidationError
from tsr.runner import Context, TSRScriptError
from tsr import shim

POLL_BUDGET_S = 8.0
RECONCILE_BUDGET_S = 12.0
PAGE_SIZE = 500
LOCK_S = 90


def watched_doctypes(engine) -> list[str]:
    return sorted({dt for (dt, _ev) in engine.registry.events.keys()})


# ───────────────────────── intake ─────────────────────────

def erp_event(db, secret: str = "", doctype: str = "", name: str = "", event: str = "update", modified: str = "",
              docstatus: int = 0, **_kw) -> dict:
    """Webhook receiver. Refuses anything without the shared secret; never reveals which part was wrong."""
    if not config.ERP_WEBHOOK_SECRET or not hmac.compare_digest(str(secret or ""), config.ERP_WEBHOOK_SECRET):
        return {"ok": False, "error": "refused"}
    if not doctype or not name:
        return {"ok": False, "error": "doctype and name are required"}
    try:
        db.add(ChangeModel(doctype=doctype[:140], name=name[:140], event=(event or "update")[:30], modified=str(modified or "")[:40],
                           docstatus=int(docstatus or 0), source="webhook", state="new"))
        db.commit()
        return {"ok": True, "queued": True}
    except IntegrityError:
        db.rollback()
        return {"ok": True, "queued": False, "duplicate": True}


def _lock(db, key: str) -> bool:
    row = db.query(KVModel).filter(KVModel.key == key).first()
    now = time.time()
    if row and row.value and now - float(row.value) < LOCK_S:
        return False
    if row:
        row.value = str(now)
    else:
        db.add(KVModel(key=key, value=str(now)))
    db.commit()
    return True


def _unlock(db, key: str):
    row = db.query(KVModel).filter(KVModel.key == key).first()
    if row:
        row.value = "0"
        db.commit()


# ───────────────────────── poller ─────────────────────────

def poll(db, backend, engine, budget_s: float = POLL_BUDGET_S, baseline_only: bool = False) -> dict:
    """Record new ERP changes. Oldest-polled doctype first, until the time budget is used."""
    t0 = time.time()
    dts = watched_doctypes(engine)
    states = {s.doctype: s for s in db.query(SyncStateModel)}
    order = sorted(dts, key=lambda d: (states[d].last_run or datetime.min) if d in states else datetime.min)
    found, polled, errors = 0, 0, []
    for dt in order:
        if time.time() - t0 > budget_s:
            break
        st = states.get(dt) or SyncStateModel(doctype=dt, watermark="", seen_at_watermark="[]")
        try:
            if not st.watermark:
                # first sight of this doctype: baseline = "now", history is NOT replayed
                top = backend.get_list(dt, None, ["modified"], order_by="modified desc", limit=1)
                st.watermark = str(top[0]["modified"]) if top else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
                st.seen_at_watermark = json.dumps([r["name"] for r in backend.get_list(dt, {"modified": st.watermark}, ["name"])] if top else [])
            else:
                rows = backend.get_list(dt, [["modified", ">=", st.watermark]], ["name", "modified", "docstatus"],
                                        order_by="modified asc", limit=PAGE_SIZE)
                seen = set(json.loads(st.seen_at_watermark or "[]"))
                new_rows = [r for r in rows if not (str(r["modified"]) == st.watermark and r["name"] in seen)]
                for r in new_rows:
                    if not baseline_only and _record(db, dt, r, "poll"):
                        found += 1
                if rows:
                    last = str(rows[-1]["modified"])
                    names_at_last = [r["name"] for r in rows if str(r["modified"]) == last]
                    if last == st.watermark:
                        names_at_last = sorted(set(names_at_last) | seen)
                    st.watermark, st.seen_at_watermark = last, json.dumps(names_at_last)
            st.last_error = ""
        except TSRNotFound:
            st.last_error = "doctype missing on this ERP"
        except Exception as e:                                                  # noqa: BLE001
            st.last_error = str(e)[:300]
            errors.append(f"{dt}: {st.last_error}")
        st.last_run = datetime.utcnow()
        db.merge(st)
        db.commit()
        polled += 1
    found += _poll_deletes(db, backend)
    return {"polled": polled, "of": len(dts), "found": found, "errors": errors[:5], "ms": int((time.time() - t0) * 1000)}


def _record(db, dt: str, row: dict, source: str) -> bool:
    mod = str(row["modified"])
    if db.query(ChangeModel).filter_by(doctype=dt, name=row["name"], modified=mod).first():
        return False
    db.add(ChangeModel(doctype=dt, name=row["name"], event="update", modified=mod, docstatus=int(row.get("docstatus") or 0),
                       source=source, state="new"))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _poll_deletes(db, backend) -> int:
    row = db.query(KVModel).filter(KVModel.key == "cx_del_watermark").first()
    wm = row.value if row and row.value else ""
    try:
        if not wm:
            top = backend.get_list("Deleted Document", None, ["creation"], order_by="creation desc", limit=1)
            wm = str(top[0]["creation"]) if top else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
            n = 0
        else:
            rows = backend.get_list("Deleted Document", [["creation", ">", wm]], ["name", "deleted_doctype", "deleted_name", "creation"],
                                    order_by="creation asc", limit=PAGE_SIZE)
            n = 0
            for r in rows:
                try:
                    db.add(ChangeModel(doctype=r["deleted_doctype"], name=r["deleted_name"], event="delete", modified=str(r["creation"]),
                                       docstatus=2, source="poll", state="new"))
                    db.commit()
                    n += 1
                except IntegrityError:
                    db.rollback()
            if rows:
                wm = str(rows[-1]["creation"])
    except Exception:
        return 0
    if row:
        row.value = wm
    else:
        db.add(KVModel(key="cx_del_watermark", value=wm))
    db.commit()
    return n


# ───────────────────────── reconcile ─────────────────────────

def _previous_docstatus(db, ch: ChangeModel) -> Optional[int]:
    prev = (db.query(ChangeModel).filter(ChangeModel.doctype == ch.doctype, ChangeModel.name == ch.name, ChangeModel.id < ch.id,
                                         ChangeModel.state.in_(("done", "skipped")))
            .order_by(ChangeModel.id.desc()).first())
    return None if prev is None else int(prev.docstatus or 0)


def reconcile(db, backend, engine, enabled=lambda n: True, budget_s: float = RECONCILE_BUDGET_S, limit: int = 40) -> dict:
    from pipeline import _ledger        # the tower's writes register themselves the same way
    t0 = time.time()
    done = failed = skipped = breaches = unproven = 0
    rows = db.query(ChangeModel).filter(ChangeModel.state == "new").order_by(ChangeModel.id).limit(limit).all()
    for ch in rows:
        if time.time() - t0 > budget_s:
            break
        try:
            if ch.event == "delete":
                _resolve_breaches(db, ch.doctype, ch.name)
                _finish(db, ch, "done")
                done += 1
                continue
            try:
                d = backend.get_doc(ch.doctype, ch.name)
            except TSRNotFound:
                _finish(db, ch, "skipped", "gone before it could be read")
                skipped += 1
                continue
            if str(d.get("modified")) != ch.modified and ch.source == "webhook":
                ch.modified = str(d.get("modified"))        # the webhook was early: use the settled state
            now_ds = int(d.get("docstatus") or 0)
            ch.docstatus = now_ds
            prev = _previous_docstatus(db, ch)
            if prev is None:
                phase = "save"
                if now_ds != 0:
                    unproven += 1
            elif prev == 0 and now_ds == 1:
                phase = "submit"
            elif prev == 1 and now_ds == 2:
                phase = "cancel"
            else:
                phase = "save"
            n_breach = _check(db, backend, engine, d, ch.doctype, enabled)
            breaches += n_breach
            ctx = Context(backend, engine, user="Administrator", mode="live", script_enabled=enabled)
            doc = shim.Doc(ctx, {**d, "doctype": ch.doctype})
            doc.__dict__["_before"] = json.loads(json.dumps(doc.as_dict(), default=str))
            events = {"submit": ("After Save", "After Submit"), "cancel": ("After Cancel",),
                      "save": ("After Save (Submitted Document)",) if now_ds == 1 else ("After Save",)}[phase]
            try:
                for ev in events:
                    engine.run_event(ctx, doc, ev)
            except Exception as e:                                                  # noqa: BLE001
                undo = ctx.sink.compensate()
                _finish(db, ch, "failed", f"{type(e).__name__}: {str(e)[:300]} (undone: {len(undo['undone'])})")
                failed += 1
                continue
            _ledger(db, backend, [(a["doctype"], a["name"]) for a in ctx.sink.entries if a["doctype"]])
            _finish(db, ch, "done")
            done += 1
        except Exception as e:                                                      # noqa: BLE001
            _finish(db, ch, "failed", f"{type(e).__name__}: {str(e)[:300]}")
            failed += 1
    return {"done": done, "failed": failed, "skipped": skipped, "breaches": breaches, "unproven": unproven,
            "left": db.query(ChangeModel).filter(ChangeModel.state == "new").count(), "ms": int((time.time() - t0) * 1000)}


def _finish(db, ch: ChangeModel, state: str, error: str = ""):
    ch.state, ch.error, ch.processed_at = state, error, datetime.utcnow()
    db.commit()


def _check(db, backend, engine, d: dict, dt: str, enabled) -> int:
    """Run the Before-scripts against the stored document; each refusal is an open breach."""
    ctx = Context(backend, engine, user="Administrator", mode="record", script_enabled=enabled)
    doc = shim.Doc(ctx, {**d, "doctype": dt})
    ds = int(d.get("docstatus") or 0)
    events = ("Before Validate", "Before Save") if ds == 0 else ("Before Validate", "Before Save (Submitted Document)")
    n = 0
    for ev in events + (("Before Submit",) if ds == 1 else ()):
        for rec in engine.registry.events.get((dt, ev), ()):
            if not enabled(rec["name"]):
                continue
            try:
                engine._run(ctx, rec, doc=doc)
                _resolve_one(db, dt, d["name"], rec["name"])
            except TSRValidationError as e:
                _open_breach(db, dt, d["name"], rec["name"], e.message)
                n += 1
            except (TSRScriptError, TSRError):
                continue            # a script that cannot run is the runtime's problem, not a rule breach
    return n


def _open_breach(db, dt: str, name: str, script: str, message: str):
    row = db.query(BreachModel).filter_by(doctype=dt, name=name, script=script).first()
    if row:
        if row.state != "open":
            row.state, row.resolved_at = "open", None
        row.message = message[:1000]
    else:
        db.add(BreachModel(doctype=dt, name=name, script=script, message=message[:1000], state="open"))
    db.commit()


def _resolve_one(db, dt: str, name: str, script: str):
    row = db.query(BreachModel).filter_by(doctype=dt, name=name, script=script, state="open").first()
    if row:
        row.state, row.resolved_at = "resolved", datetime.utcnow()
        db.commit()


def _resolve_breaches(db, dt: str, name: str):
    for row in db.query(BreachModel).filter_by(doctype=dt, name=name, state="open"):
        row.state, row.resolved_at = "resolved", datetime.utcnow()
    db.commit()


# ───────────────────────── one call to do it all ─────────────────────────

def sync(db, backend, engine, enabled=lambda n: True) -> dict:
    """poll + reconcile under a lock, so two overlapping calls never reconcile the same change twice."""
    if not _lock(db, "cx_sync_lock"):
        return {"ok": True, "skipped": "another sync is running"}
    try:
        p = poll(db, backend, engine)
        r = reconcile(db, backend, engine, enabled)
        return {"ok": True, "poll": p, "reconcile": r}
    finally:
        _unlock(db, "cx_sync_lock")


def status(db, engine) -> dict:
    states = {s.doctype: s for s in db.query(SyncStateModel)}
    q = db.query(ChangeModel)
    return {
        "queue": {"new": q.filter(ChangeModel.state == "new").count(), "failed": q.filter(ChangeModel.state == "failed").count(),
                  "done": q.filter(ChangeModel.state == "done").count()},
        "doctypes": [{"doctype": d, "watermark": getattr(states.get(d), "watermark", ""),
                      "last_run": states[d].last_run.isoformat() if d in states and states[d].last_run else None,
                      "error": getattr(states.get(d), "last_error", "")} for d in watched_doctypes(engine)],
        "breaches_open": db.query(BreachModel).filter(BreachModel.state == "open").count(),
        "webhook_configured": bool(config.ERP_WEBHOOK_SECRET),
    }
