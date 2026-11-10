"""Cortex TnA Calendar — the opt-in overlay write path (SPEC §12).

The write target is **only** the local SQLite overlay (``milestone_overlay`` +
``action_log`` + ``audit_log``). **No ERP write exists in this build** —
``erp_write`` is always ``false`` and ``mode_gate`` is always
``config.ERP_WRITE_MODE`` (default ``draft``).

Flow (preview-first, reversible):

* :func:`stage_action`  — validate + persist a ``staged`` ``action_log`` row
  carrying ``before_json`` (the current overlay row, or null) and ``after_json``.
* :func:`apply_action`  — commit a staged action: upsert the overlay row, mark
  the action ``applied`` and append **one** ``audit_log`` row.
* :func:`rollback_action` — restore ``before_json`` (delete the row if there was
  none), mark the action ``rolled_back`` and append a ``rollback`` audit row.

History is never deleted — ``action_log`` and ``audit_log`` are append-only.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import config
from .models import ActionLogModel, AuditLogModel, MilestoneOverlayModel

MODE_ORDER = dict(config.WRITE_MODE_ORDER)

# Managed overlay columns (order defines the write target shape).
OVERLAY_FIELDS = [
    "actual_start", "actual_finish", "revised_finish", "planned_date", "status_override",
    "delay_reason", "owner", "note", "recorded_by",
]

# change field → audit action_type (single-field fallbacks).
_FIELD_ACTION = {
    "delay_reason": "set_reason",
    "owner": "set_owner",
    "note": "set_note",
    "status_override": "status_override",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(dt)


# ── mode gate ────────────────────────────────────────────────────────────────

def current_mode() -> str:
    m = (config.ERP_WRITE_MODE or "draft").strip().lower()
    return m if m in MODE_ORDER else "draft"


def mode_allows(required: str) -> bool:
    return MODE_ORDER[current_mode()] >= MODE_ORDER.get(required, 99)


def writes_enabled() -> bool:
    return current_mode() != "off"


# ── overlay helpers ──────────────────────────────────────────────────────────

def get_overlay(db, order_id: str, code: str) -> Optional[MilestoneOverlayModel]:
    return (db.query(MilestoneOverlayModel)
            .filter(MilestoneOverlayModel.order_id == order_id,
                    MilestoneOverlayModel.milestone_code == code)
            .first())


def list_overlay(db, order_id: str) -> list:
    return (db.query(MilestoneOverlayModel)
            .filter(MilestoneOverlayModel.order_id == order_id).all())


def overlay_dict(row: Optional[MilestoneOverlayModel]) -> Optional[dict]:
    return row.to_dict() if row else None


def _overlay_values(row: Optional[MilestoneOverlayModel]) -> dict:
    """The managed overlay values (all ``None`` when there is no row)."""
    base = {f: None for f in OVERLAY_FIELDS}
    if row:
        for f in OVERLAY_FIELDS:
            base[f] = getattr(row, f, None)
    return base


def _upsert(db, order_id: str, code: str, values: dict) -> MilestoneOverlayModel:
    row = get_overlay(db, order_id, code)
    if row is None:
        row = MilestoneOverlayModel(order_id=order_id, milestone_code=code)
        db.add(row)
    for f in OVERLAY_FIELDS:
        if f in values:
            setattr(row, f, values[f])
    row.updated_at = _now()
    db.flush()
    return row


def _delete(db, order_id: str, code: str) -> None:
    row = get_overlay(db, order_id, code)
    if row is not None:
        db.delete(row)
        db.flush()


# ── audit ────────────────────────────────────────────────────────────────────

def action_type_for(changes: list) -> str:
    fields = [c.get("field") for c in changes or []]
    if "actual_start" in fields or "actual_finish" in fields:
        date_changes = [c for c in changes if c.get("field") in ("actual_start", "actual_finish")]
        if date_changes and all(c.get("new") is None for c in date_changes):
            return "clear_actual"
        if any(c.get("old") is not None for c in date_changes):
            return "correct_actual"
        return "record_actual"
    for f in ("delay_reason", "owner", "note", "status_override"):
        if f in fields:
            return _FIELD_ACTION[f]
    return "update_milestone"


def _append_audit(db, *, action_id, order_id, code, action_type, status, changes,
                  reason, actor, mode, source) -> None:
    primary = (changes or [{}])[0]
    db.add(AuditLogModel(
        action_id=action_id,
        order_id=order_id,
        milestone_code=code,
        action_type=action_type,
        status=status,
        field=primary.get("field"),
        old_value=None if primary.get("old") is None else str(primary.get("old")),
        new_value=None if primary.get("new") is None else str(primary.get("new")),
        changes_json=json.dumps(changes or []),
        reason=reason,
        actor=actor or None,
        mode=mode,
        source=source,
    ))
    db.flush()


# ── public write API ─────────────────────────────────────────────────────────

def stage_action(db, order_id: str, code: str, changes: list, after: dict,
                 actor: str = "", source: str = "snapshot",
                 kind: str = "update_milestone") -> ActionLogModel:
    """Persist a ``staged`` action. Returns the action row (never raises for the
    happy path; caller validates first)."""
    row = get_overlay(db, order_id, code)
    action = ActionLogModel(
        action_id=str(uuid.uuid4()),
        order_id=order_id,
        milestone_code=code,
        kind=kind,
        before_json=json.dumps(_overlay_values(row)),
        after_json=json.dumps(after or {}),
        changes_json=json.dumps(changes or []),
        mode=current_mode(),
        status="staged",
        actor=actor or None,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def apply_action(db, action_id: str, source: str = "snapshot") -> dict:
    """Commit a staged action. Returns a result dict, or ``{"error": ...}``."""
    action = db.query(ActionLogModel).filter(ActionLogModel.action_id == action_id).first()
    if action is None:
        return {"error": f"Action '{action_id}' not found or not staged", "action_status": None}
    if action.status != "staged":
        return {"error": f"Action '{action_id}' not found or not staged", "action_status": action.status}

    after = json.loads(action.after_json) if action.after_json else {}
    changes = json.loads(action.changes_json) if action.changes_json else []

    row = _upsert(db, action.order_id, action.milestone_code, after)
    action.status = "applied"
    action.applied_at = _now()

    _append_audit(
        db, action_id=action.action_id, order_id=action.order_id, code=action.milestone_code,
        action_type=action_type_for(changes), status="applied", changes=changes,
        reason=after.get("delay_reason"), actor=action.actor, mode=action.mode, source=source,
    )
    db.commit()
    db.refresh(action)
    db.refresh(row)

    return {
        "action_id": action.action_id,
        "order_id": action.order_id,
        "code": action.milestone_code,
        "changes": changes,
        "record": row.to_dict(),
        "reversible": True,
        "erp_write": False,
        "mode_gate": current_mode(),
        "applied_at": _iso(action.applied_at),
    }


def rollback_action(db, action_id: str, source: str = "snapshot") -> dict:
    """Reverse an applied action by restoring its ``before_json``. Never deletes
    history. Returns a result dict, or ``{"error": ...}``."""
    action = db.query(ActionLogModel).filter(ActionLogModel.action_id == action_id).first()
    if action is None:
        return {"error": f"Action '{action_id}' not found or not applied", "action_status": None}
    if action.status != "applied":
        return {"error": f"Action '{action_id}' not found or not applied", "action_status": action.status}

    current = _overlay_values(get_overlay(db, action.order_id, action.milestone_code))
    before = json.loads(action.before_json) if action.before_json else {}
    before = before or {}

    changes = []
    for f in OVERLAY_FIELDS:
        old = current.get(f)
        new = before.get(f)
        if old != new:
            changes.append({"field": f, "old": old, "new": new})

    if all(v is None for v in before.values()):
        _delete(db, action.order_id, action.milestone_code)
        restored = None
    else:
        row = _upsert(db, action.order_id, action.milestone_code, before)
        restored = row.to_dict()

    action.status = "rolled_back"
    action.rolled_back_at = _now()
    _append_audit(
        db, action_id=action.action_id, order_id=action.order_id, code=action.milestone_code,
        action_type="rollback", status="rolled_back", changes=changes,
        reason=None, actor=action.actor, mode=action.mode, source=source,
    )
    db.commit()

    return {
        "action_id": action.action_id,
        "order_id": action.order_id,
        "code": action.milestone_code,
        "restored": restored,
        "changes": changes,
        "reversible": False,
        "erp_write": False,
        "mode_gate": current_mode(),
    }


def list_actions(db, order_id: str = "", limit: int = 100, offset: int = 0) -> tuple:
    q = db.query(ActionLogModel)
    if order_id:
        q = q.filter(ActionLogModel.order_id == order_id)
    total = q.count()
    rows = (q.order_by(ActionLogModel.id.desc()).offset(int(offset or 0)).limit(int(limit or 100)).all())
    return rows, total


def fmt_changes(changes: list) -> list:
    """Response shape for ``changes`` — null renders as an em-dash (SPEC §6.6)."""
    out = []
    for c in changes or []:
        out.append({
            "field": c.get("field"),
            "old": "—" if c.get("old") in (None, "") else c.get("old"),
            "new": "—" if c.get("new") in (None, "") else c.get("new"),
        })
    return out
