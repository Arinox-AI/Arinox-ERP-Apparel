"""Cortex TnA Calendar — SQLAlchemy models.

Only the **human overlay** lives here. The ERP is the master for the order, the
template and the production actuals — none of that is duplicated into SQLite.

Three tables (SPEC §5.2):

* ``milestone_overlay`` — the editable human layer over the ERP-derived plan
  (recorded actuals, delay reasons, owner, notes). One row per
  ``(order_id, milestone_code)``.
* ``action_log``        — staged / applied / rolled-back write actions. Required
  because ``run_action`` / ``rollback_action`` act on a *staged* action between
  two separate middleware calls.
* ``audit_log``         — append-only event journal (never updated, never deleted).
"""

from __future__ import annotations

import json as _json
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _iso(v) -> str | None:
    if v is None:
        return None
    try:
        return v.isoformat()
    except Exception:
        return str(v)


class MilestoneOverlayModel(Base):
    """Editable human layer over the ERP-derived milestone plan."""

    __tablename__ = "milestone_overlay"
    __table_args__ = (UniqueConstraint("order_id", "milestone_code", name="uq_overlay_order_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    milestone_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_start: Mapped[str] = mapped_column(String(10), nullable=True)
    actual_finish: Mapped[str] = mapped_column(String(10), nullable=True)
    revised_finish: Mapped[str] = mapped_column(String(10), nullable=True)
    planned_date: Mapped[str] = mapped_column(String(10), nullable=True)
    status_override: Mapped[str] = mapped_column(String(40), nullable=True)
    delay_reason: Mapped[str] = mapped_column(String(200), nullable=True)
    owner: Mapped[str] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(String(2000), nullable=True)
    recorded_by: Mapped[str] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "milestone_code": self.milestone_code,
            "actual_start": self.actual_start,
            "actual_finish": self.actual_finish,
            "revised_finish": self.revised_finish,
            "planned_date": self.planned_date,
            "status_override": self.status_override,
            "delay_reason": self.delay_reason,
            "owner": self.owner,
            "note": self.note,
            "recorded_by": self.recorded_by,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class ActionLogModel(Base):
    """A staged / applied / rolled-back write action (preview-first + reversibility)."""

    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    milestone_code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="update_milestone")
    before_json: Mapped[str] = mapped_column(Text, nullable=True)
    after_json: Mapped[str] = mapped_column(Text, nullable=True)
    changes_json: Mapped[str] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="staged")
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    rolled_back_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def _load(self, raw):
        try:
            return _json.loads(raw) if raw else None
        except Exception:
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_id": self.action_id,
            "order_id": self.order_id,
            "milestone_code": self.milestone_code,
            "kind": self.kind,
            "before": self._load(self.before_json),
            "after": self._load(self.after_json),
            "changes": self._load(self.changes_json) or [],
            "mode": self.mode,
            "status": self.status,
            "actor": self.actor,
            "created_at": _iso(self.created_at),
            "applied_at": _iso(self.applied_at),
            "rolled_back_at": _iso(self.rolled_back_at),
        }


class TnaIntakeModel(Base):
    """New-order intake queue — the notification inbox.

    When a new order is detected (from the ERP or via the Cortex Tower bridge) it
    lands here as ``detected`` and shows in the app as a notification. Approving it
    (``start_tna``) flips the row to ``approved`` and *starts the TnA plan* — the
    order then appears in the Plan / Program views like any other. One row per order.
    """

    __tablename__ = "tna_intake"
    __table_args__ = (UniqueConstraint("order_id", name="uq_intake_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer: Mapped[str] = mapped_column(String(200), nullable=True)
    style_no: Mapped[str] = mapped_column(String(120), nullable=True)
    style_name: Mapped[str] = mapped_column(String(200), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=True)
    ship_date: Mapped[str] = mapped_column(String(10), nullable=True)
    product_type: Mapped[str] = mapped_column(String(80), nullable=True)
    # detected | approved | rejected | snoozed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="detected")
    # erp | tower | manual
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="erp")
    # cross-app reference (e.g. the Tower order-change id) + opaque tower context
    tower_ref: Mapped[str] = mapped_column(String(120), nullable=True)
    tower_context: Mapped[str] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(String(2000), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        try:
            ctx = _json.loads(self.tower_context) if self.tower_context else None
        except Exception:
            ctx = None
        return {
            "id": self.id,
            "order_id": self.order_id,
            "customer": self.customer,
            "style_no": self.style_no,
            "style_name": self.style_name,
            "qty": self.qty,
            "ship_date": self.ship_date,
            "product_type": self.product_type,
            "status": self.status,
            "source": self.source,
            "tower_ref": self.tower_ref,
            "tower_context": ctx,
            "note": self.note,
            "actor": self.actor,
            "detected_at": _iso(self.detected_at),
            "decided_at": _iso(self.decided_at),
        }


class AppSettingModel(Base):
    """Tiny key/value store for app-level settings (e.g. the Cortex Tower jump URL).

    Kept local (SQLite) so a setting can be changed from the UI without a rebuild.
    Environment variables always win over a stored value.
    """

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    updated_by: Mapped[str] = mapped_column(String(200), nullable=True)

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value,
                "updated_at": _iso(self.updated_at), "updated_by": self.updated_by}


class AuditLogModel(Base):
    """Append-only journal of every applied / rolled-back overlay change."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    milestone_code: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="applied")
    field: Mapped[str] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=True)
    changes_json: Mapped[str] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="snapshot")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        try:
            changes = _json.loads(self.changes_json) if self.changes_json else []
        except Exception:
            changes = []
        return {
            "id": self.id,
            "action_id": self.action_id,
            "order_id": self.order_id,
            "milestone_code": self.milestone_code,
            "action_type": self.action_type,
            "status": self.status,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "changes": changes,
            "reason": self.reason,
            "actor": self.actor,
            "mode": self.mode,
            "source": self.source,
            "created_at": _iso(self.created_at),
        }
