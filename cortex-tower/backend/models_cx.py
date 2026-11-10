"""Tables of the Arinox layer (Tower Script Runtime, guardrails, two-way sync, identity).

Additive only: no existing table is touched. Registered on the same ``Base`` so ``init_db`` creates them.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class UserModel(Base):
    """KOGO SSO users (core-builder HARD RULE 0). ``tower_roles`` is a JSON list of guardrail roles."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(50), default="member")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    tower_roles: Mapped[str] = mapped_column(Text, default="[]")
    erp_user: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WriteRunModel(Base):
    """One guarded ERP write (or script run): who, what, the journal that undoes it. ``idem_key`` makes a retry safe."""
    __tablename__ = "cx_write_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idem_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    op: Mapped[str] = mapped_column(String(40), nullable=False)
    doctype: Mapped[str] = mapped_column(String(140), default="")
    name: Mapped[str] = mapped_column(String(140), default="")
    cls: Mapped[str] = mapped_column(String(10), default="draft")        # safe | draft | risky
    status: Mapped[str] = mapped_column(String(20), default="started")   # started | done | failed | compensated | partial
    request: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str] = mapped_column(Text, default="{}")
    journal: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class ApprovalModel(Base):
    __tablename__ = "cx_approval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester: Mapped[str] = mapped_column(String(255), nullable=False)
    approver: Mapped[str] = mapped_column(String(255), default="")
    cls: Mapped[str] = mapped_column(String(10), default="risky")
    reason: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[str] = mapped_column(Text, default="{}")
    preview: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(12), default="pending")   # pending | approved | rejected | used
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class DocLockModel(Base):
    __tablename__ = "cx_lock"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    expires: Mapped[float] = mapped_column(Float, nullable=False)


class ChangeModel(Base):
    """An ERP change we have heard of (webhook or poll) and what became of it. Unique per (doc, modified)."""
    __tablename__ = "cx_change"
    __table_args__ = (UniqueConstraint("doctype", "name", "modified", name="uq_cx_change"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctype: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    event: Mapped[str] = mapped_column(String(30), default="update")     # insert | update | submit | cancel | delete
    modified: Mapped[str] = mapped_column(String(40), default="")
    docstatus: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(10), default="poll")      # poll | webhook | tower
    state: Mapped[str] = mapped_column(String(10), default="new", index=True)   # new | done | failed | skipped
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class SyncStateModel(Base):
    __tablename__ = "cx_sync_state"

    doctype: Mapped[str] = mapped_column(String(140), primary_key=True)
    watermark: Mapped[str] = mapped_column(String(40), default="")
    seen_at_watermark: Mapped[str] = mapped_column(Text, default="[]")   # names already handled at exactly the watermark
    last_run: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class ScriptStateModel(Base):
    __tablename__ = "cx_script_state"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_run: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class BreachModel(Base):
    """An ERP-side change that breaks a rule the scripts would have enforced. Never auto-reverted."""
    __tablename__ = "cx_breach"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctype: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    script: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(10), default="open", index=True)   # open | resolved | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("doctype", "name", "script", name="uq_cx_breach"),)


class JobModel(Base):
    """A resumable job for work longer than one call (the middleware allows about 30 s)."""
    __tablename__ = "cx_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(10), default="queued")     # queued | running | done | failed
    params: Mapped[str] = mapped_column(Text, default="{}")
    cursor: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str] = mapped_column(Text, default="{}")
    progress: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
