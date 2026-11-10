"""Cortex Operations Control Tower — SQLAlchemy models.

All operational data (orders, BOMs, quality, shipments, gaps, …) is read LIVE
from KOGO ERP at request time — it is NOT stored here. This SQLite store only
keeps the small amount of *decision* state the dashboard owns:

* ``risk_state``   — stable id + open/resolved status per derived ``risk_key``
* ``action_state`` — approval / modification / execution state per ``action_key``
* ``audit_log``    — the local operator audit trail
"""

import json as _json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import config


class Base(DeclarativeBase):
    pass


class RiskStateModel(Base):
    """Stable identity + workflow status for a live-derived risk.

    ``risk_key`` is the upsert key (BOM_COVERAGE, NO_DELIVERY_NOTES, …); the
    row's ``id`` therefore stays constant across calls, which is what the
    frontend and the recommendation -> risk linkage depend on. The live
    evidence fields are stored as a JSON ``payload`` so the derived risk can
    change with the ERP without altering the schema.
    """

    __tablename__ = "risk_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    risk_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    payload: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        try:
            extra = _json.loads(self.payload) if self.payload else {}
        except Exception:
            extra = {}
        if not isinstance(extra, dict):
            extra = {}
        out = dict(extra)
        out.update({
            "id": self.id,
            "risk_key": self.risk_key,
            "risk_type": self.risk_type,
            "severity": self.severity,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        })
        if not isinstance(out.get("affected_orders"), list):
            out["affected_orders"] = []
        return out


class ActionStateModel(Base):
    """Stable identity + workflow state for a live-derived recommendation.

    ``action_key`` (``"<risk_key>::<slug>"``) is the upsert key. ``risk_key``
    links back to :class:`RiskStateModel`; ``risk_id`` is resolved from that
    link at serialization time so it always matches the live risk row id.
    """

    __tablename__ = "action_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    risk_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    modified_text: Mapped[str] = mapped_column(String(1000), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Result of the real ERP write (opt-in path — see writes.py)
    result_doctype: Mapped[str] = mapped_column(String(80), nullable=True)
    result_doc: Mapped[str] = mapped_column(String(140), nullable=True)
    result_docs: Mapped[str] = mapped_column(Text, nullable=True)
    write_op: Mapped[str] = mapped_column(String(20), nullable=True)
    write_status: Mapped[str] = mapped_column(String(30), nullable=True)
    write_error: Mapped[str] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        try:
            extra = _json.loads(self.payload) if self.payload else {}
        except Exception:
            extra = {}
        if not isinstance(extra, dict):
            extra = {}
        action = self.modified_text or extra.get("action") or ""
        out = dict(extra)
        out.update({
            "id": self.id,
            "action_key": self.action_key,
            "risk_key": self.risk_key,
            "risk_id": None,  # filled by functions.py from the live risk key -> id map
            "risk_title": extra.get("risk_title") or "",
            "action": action,
            "expected_impact": extra.get("expected_impact") or "",
            "responsible_team": extra.get("responsible_team") or "",
            "priority": extra.get("priority") or "medium",
            "approval_status": self.approval_status,
            "modified_text": self.modified_text,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "result_doctype": self.result_doctype,
            "result_doc": self.result_doc,
            "result_docs": _json.loads(self.result_docs) if self.result_docs else [],
            "write_op": self.write_op,
            "write_status": self.write_status,
            "write_error": self.write_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        })
        return out


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="Ops Manager")
    risk_title: Mapped[str] = mapped_column(String(400), nullable=True)
    approved: Mapped[str] = mapped_column(String(20), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "action_name": self.action_name,
            "description": self.description,
            "actor": self.actor,
            "risk_title": self.risk_title,
            "approved": self.approved,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# ────────────────────────────────────────────────────────────────────────────
# Email connector (P1) — outbound SMTP settings + approval queue
# Additive: no existing table, view or function is changed.
# ────────────────────────────────────────────────────────────────────────────

def _password_readable(value) -> bool:
    try:
        import secret_store
        return secret_store.readable(value)
    except Exception:
        return True


class MailSettingsModel(Base):
    """Single logical row holding the outbound SMTP configuration.

    The SMTP ``password`` is stored here but is **never** returned to the
    frontend — :meth:`to_dict` exposes only a ``password_set`` boolean.
    """

    __tablename__ = "mail_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_account: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String(160), nullable=False, default=config.MAIL_FROM_NAME)
    smtp_host: Mapped[str] = mapped_column(String(160), nullable=False, default=config.SMTP_HOST)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=config.SMTP_PORT)
    use_tls: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    password: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        # NEVER expose the password — only whether one has been saved.
        return {
            "id": self.id,
            "enabled": int(self.enabled or 0),
            "email_account": self.email_account or "",
            "from_name": self.from_name or "",
            "smtp_host": self.smtp_host or "",
            "smtp_port": int(self.smtp_port or 0),
            "use_tls": int(self.use_tls or 0),
            "password_set": bool(self.password),
            # False = a password is stored but the current key cannot open it (re-enter it)
            "password_readable": _password_readable(self.password),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EmailDraftModel(Base):
    """A grounded email draft that a human approves before it is sent.

    Rows are created only from the existing ``email_engine`` output (never from
    hard-coded text) and carry the engine's ``fact_sheet`` so a later edited
    send can be re-validated for grounding.
    """

    __tablename__ = "email_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action_key: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    intent: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    to_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fact_sheet: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # the chain this mail belongs to, and the headers that keep it inside the buyer's thread
    chain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    in_reply_to: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    references: Mapped[str] = mapped_column(Text, nullable=True)
    thread_key: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    cc: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    grounding_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grounding_unsourced: Mapped[str] = mapped_column(Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    edited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    message_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False, default="Ops Manager")

    @staticmethod
    def _loads(txt, default):
        try:
            return _json.loads(txt) if txt else default
        except Exception:
            return default

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_id": self.action_id,
            "action_key": self.action_key or "",
            "intent": self.intent or "",
            "to_email": self.to_email or "",
            "from_name": self.from_name or "",
            "subject": self.subject or "",
            "body": self.body or "",
            "fact_sheet": self._loads(self.fact_sheet, {}),
            "status": self.status or "draft",
            "chain_id": self.chain_id,
            "in_reply_to": self.in_reply_to or "",
            "references": self.references or "",
            "grounding_ok": int(self.grounding_ok or 0),
            "grounding_unsourced": self._loads(self.grounding_unsourced, []),
            "policy_version": self.policy_version or "",
            "edited": int(self.edited or 0),
            "idempotency_key": self.idempotency_key or "",
            "message_id": self.message_id or "",
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "decided_by": self.decided_by or "",
        }


class MailMessageModel(Base):
    """One inbound email, understood deterministically (no OCR).

    ``mail_message`` is the local inbox: the mailbox itself stays the source of
    truth, this is the parsed/understood view the dashboard reads.
    """

    __tablename__ = "mail_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    message_id: Mapped[str] = mapped_column(String(300), nullable=True)
    thread_id: Mapped[str] = mapped_column(String(300), nullable=True)
    from_name: Mapped[str] = mapped_column(String(200), nullable=True)
    from_addr: Mapped[str] = mapped_column(String(320), nullable=True)
    to_addr: Mapped[str] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(600), nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=True)
    received_at: Mapped[str] = mapped_column(String(40), nullable=True)
    has_attachments: Mapped[int] = mapped_column(Integer, default=0)
    attachments: Mapped[str] = mapped_column(Text, nullable=True)          # JSON list
    classification: Mapped[str] = mapped_column(String(30), default="other")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[str] = mapped_column(Text, nullable=True)              # JSON list
    po_refs: Mapped[str] = mapped_column(Text, nullable=True)              # JSON list
    matched_orders: Mapped[str] = mapped_column(Text, nullable=True)       # JSON list
    status: Mapped[str] = mapped_column(String(20), default="new")         # new|read|actioned|dismissed
    chain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # how many intake runs this one mail opened (a mail can carry several documents)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    # the conversation (2026-11-07): one key per thread, shared by the buyer's mails and our replies.
    # Gmail's own thread id when the mailbox is Gmail, else the root Message-ID of the References chain.
    thread_key: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    gm_thrid: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    in_reply_to: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    cc_addr: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    direction: Mapped[str] = mapped_column(String(4), default="in")             # in | out (from our Sent folder)
    deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)      # a person's correction of `classification`
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        def _j(v, default):
            try:
                out = _json.loads(v) if v else default
            except Exception:
                out = default
            return out
        return {
            "id": self.id,
            "uid": self.uid,
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "from_name": self.from_name,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "subject": self.subject,
            "snippet": self.snippet,
            "body_text": self.body_text,
            "received_at": self.received_at,
            "has_attachments": self.has_attachments,
            "attachments": _j(self.attachments, []),
            "classification": self.classification,
            "confidence": self.confidence,
            "reasons": _j(self.reasons, []),
            "po_refs": _j(self.po_refs, []),
            "matched_orders": _j(self.matched_orders, []),
            "status": self.status,
            "chain_id": self.chain_id,
            "document_count": int(self.document_count or 0),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OrderChangeModel(Base):
    """A flagged inbound event that affects an order — the approval queue item.

    Nothing is applied to the ERP from here; the row is the human decision point.
    """

    __tablename__ = "order_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_id: Mapped[int] = mapped_column(Integer, nullable=True)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    title: Mapped[str] = mapped_column(String(400), default="")
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    from_addr: Mapped[str] = mapped_column(String(320), nullable=True)
    so_name: Mapped[str] = mapped_column(String(80), nullable=True)
    po_no: Mapped[str] = mapped_column(String(80), nullable=True)
    customer: Mapped[str] = mapped_column(String(200), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning")   # critical|warning|info
    next_steps: Mapped[str] = mapped_column(Text, nullable=True)           # JSON list
    status: Mapped[str] = mapped_column(String(20), default="pending")     # pending|approved|dismissed
    result_doctype: Mapped[str] = mapped_column(String(80), nullable=True)
    result_doc: Mapped[str] = mapped_column(String(140), nullable=True)
    result_refs: Mapped[str] = mapped_column(Text, nullable=True)   # JSON [{doctype,name}] created
    result_note: Mapped[str] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        def _j(v, default):
            try:
                out = _json.loads(v) if v else default
            except Exception:
                out = default
            return out
        return {
            "id": self.id,
            "mail_id": self.mail_id,
            "change_type": self.change_type,
            "title": self.title,
            "summary": self.summary,
            "from_addr": self.from_addr,
            "so_name": self.so_name,
            "po_no": self.po_no,
            "customer": self.customer,
            "severity": self.severity,
            "next_steps": _j(self.next_steps, []),
            "status": self.status,
            "result_doctype": self.result_doctype,
            "result_doc": self.result_doc,
            "result_note": self.result_note,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ────────────────────────────────────────────────────────────────────────────
# Intake — attachments, the run (one mail -> one decision) and field edits
# Additive: no existing table, view or function is changed.
# ────────────────────────────────────────────────────────────────────────────

class MailAttachmentModel(Base):
    """One attachment, downloaded and READ (text extracted).

    The bytes are kept on disk (``data/mail/<mail_id>/<sha>_<name>``) so the same
    document can be re-read later; the text lives here so the pipeline never has
    to touch the network or the mailbox again.
    """

    __tablename__ = "mail_attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(400), nullable=True)
    mime: Mapped[str] = mapped_column(String(120), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(80), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(600), nullable=True)
    parser: Mapped[str] = mapped_column(String(40), nullable=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    needs_ocr: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=True)
    # where every string sat on the page ([page, y, x, text]) — what makes a size
    # grid readable by column instead of by guesswork
    layout: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self, with_text: bool = False) -> dict:
        out = {
            "id": self.id, "mail_id": self.mail_id, "filename": self.filename,
            "mime": self.mime, "size": self.size, "sha256": self.sha256,
            "parser": self.parser, "pages": self.pages, "chars": self.chars,
            "ok": int(self.ok or 0), "needs_ocr": int(self.needs_ocr or 0),
            "error": self.error or "", "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if with_text:
            out["text"] = self.text or ""
        return out


class IntakeRunModel(Base):
    """One understood inbound document = one decision.

    ``status``: ``new`` → ``understood`` → ``simulated`` → ``approved`` |
    ``rejected`` | ``blocked``. ``source_key`` is the idempotency key
    (``mail:<message_id>:<sha256>``) — the same mail can never become two orders.
    """

    __tablename__ = "intake_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mail_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    attachment_id: Mapped[int] = mapped_column(Integer, nullable=True)
    source_key: Mapped[str] = mapped_column(String(200), nullable=True, unique=True)
    route: Mapped[str] = mapped_column(String(30), default="other")
    document_type: Mapped[str] = mapped_column(String(30), default="other")
    status: Mapped[str] = mapped_column(String(20), default="new")
    facts: Mapped[str] = mapped_column(Text, nullable=True)          # JSON
    matches: Mapped[str] = mapped_column(Text, nullable=True)        # JSON
    plan: Mapped[str] = mapped_column(Text, nullable=True)           # JSON steps
    confidence: Mapped[str] = mapped_column(Text, nullable=True)     # JSON
    missing: Mapped[str] = mapped_column(Text, nullable=True)        # JSON list
    blocking: Mapped[str] = mapped_column(Text, nullable=True)       # JSON list
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    created_refs: Mapped[str] = mapped_column(Text, nullable=True)   # JSON [{doctype,name}]
    result_note: Mapped[str] = mapped_column(Text, nullable=True)
    chain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    extractor: Mapped[str] = mapped_column(String(60), default="")
    decided_by: Mapped[str] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self, full: bool = False) -> dict:
        def _j(v, default):
            try:
                out = _json.loads(v) if v else default
            except Exception:
                out = default
            return out
        out = {
            "id": self.id, "mail_id": self.mail_id, "attachment_id": self.attachment_id,
            "source_key": self.source_key, "route": self.route,
            "document_type": self.document_type, "status": self.status,
            "confidence": _j(self.confidence, {}), "missing": _j(self.missing, []),
            "blocking": _j(self.blocking, []), "summary": self.summary,
            "created_refs": _j(self.created_refs, []), "result_note": self.result_note,
            "chain_id": self.chain_id,
            "extractor": self.extractor, "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if full:
            out["facts"] = _j(self.facts, {})
            out["matches"] = _j(self.matches, {})
            out["plan"] = _j(self.plan, [])
        return out


class IntakeEditModel(Base):
    """A field the operator corrected before approval — the training record."""

    __tablename__ = "intake_edit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(120), nullable=False)
    original: Mapped[str] = mapped_column(Text, nullable=True)
    corrected: Mapped[str] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_dict(self) -> dict:
        return {"id": self.id, "run_id": self.run_id, "field": self.field,
                "original": self.original, "corrected": self.corrected,
                "actor": self.actor,
                "created_at": self.created_at.isoformat() if self.created_at else None}


# ────────────────────────────────────────────────────────────────────────────
# AI next-step layer (Phase 3) — grounded LLM suggestions, cached
# Additive: no existing table, view or function is changed.
# ────────────────────────────────────────────────────────────────────────────

class AISuggestionModel(Base):
    """A grounded, LLM-generated next-step plan for one live risk.

    Keyed by ``risk_key``; ``evidence_hash`` lets us know when the underlying
    live facts changed so a stale suggestion can be regenerated. The full
    structured response is stored as JSON in ``payload``.
    """

    __tablename__ = "ai_suggestion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    evidence_hash: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=True)      # JSON
    grounded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsourced: Mapped[str] = mapped_column(Text, nullable=True)    # JSON list
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")  # ai|fallback
    note: Mapped[str] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        def _j(v, default):
            try:
                return _json.loads(v) if v else default
            except Exception:
                return default
        out = _j(self.payload, {})
        out.update({
            "risk_key": self.risk_key,
            "grounded": bool(self.grounded),
            "unsourced": _j(self.unsourced, []),
            "source": self.source or "ai",
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        })
        return out


class MailChainModel(Base):
    """One conversation with one buyer — the thread, not the document.

    The intake reads ONE mail and decides what it is. That works for the first mail
    and fails for the twelfth: a buyer asks for a quote, we answer, they send the
    tech pack, they send the BOM, they confirm the size grid. Every one of those is
    the SAME deal. Read as separate documents the twelfth mail starts a second
    Opportunity and the deal forks (2026-11-03).

    A chain is identified by the mail THREAD — ``key`` is the root Message-ID — never
    by the subject and never by the buyer name. ``message_ids`` holds every
    Message-ID seen in or out of the chain, so an inbound reply is matched by the id
    it answers, not by a fuzzy subject.
    """

    __tablename__ = "mail_chain"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(600), nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(300), nullable=True)
    buyer_email: Mapped[str] = mapped_column(String(320), nullable=True)
    customer: Mapped[str] = mapped_column(String(200), nullable=True)       # ERP Customer
    customer_name: Mapped[str] = mapped_column(String(300), nullable=True)
    opportunity: Mapped[str] = mapped_column(String(140), nullable=True)
    client_po: Mapped[str] = mapped_column(String(140), nullable=True)
    sales_order: Mapped[str] = mapped_column(String(140), nullable=True)
    style_code: Mapped[str] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")          # open|quoted|ordered|closed
    message_ids: Mapped[str] = mapped_column(Text, nullable=True)            # JSON list
    # what has already been ingested out of this chain, by attachment sha256
    ingested: Mapped[str] = mapped_column(Text, nullable=True)               # JSON {sha: {...}}
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    last_in_at: Mapped[str] = mapped_column(String(40), nullable=True)
    last_out_at: Mapped[str] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    @staticmethod
    def _loads(txt, default):
        try:
            return _json.loads(txt) if txt else default
        except Exception:
            return default

    def to_dict(self) -> dict:
        return {
            "id": self.id, "key": self.key or "", "subject": self.subject or "",
            "buyer_name": self.buyer_name or "", "buyer_email": self.buyer_email or "",
            "customer": self.customer or "", "customer_name": self.customer_name or "",
            "opportunity": self.opportunity or "", "client_po": self.client_po or "",
            "sales_order": self.sales_order or "", "style_code": self.style_code or "",
            "status": self.status or "open",
            "message_ids": self._loads(self.message_ids, []),
            "ingested": self._loads(self.ingested, {}),
            "reply_count": int(self.reply_count or 0),
            "last_in_at": self.last_in_at or "", "last_out_at": self.last_out_at or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BuyerInquiryModel(Base):
    """One buyer enquiry — the register an enquiry sits in, and the head of its chain.

    An enquiry used to exist only as an intake card: read, approved, and then nowhere. This
    row is where it lives afterwards, with one line per style the buyer named and what the
    ERP already knows about each one (made before / costed / new).

    ``status``: ``new`` → ``costing`` → ``quoted`` → ``won`` | ``lost`` (or ``dismissed``).
    """

    __tablename__ = "buyer_inquiry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    chain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    mail_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    subject: Mapped[str] = mapped_column(String(600), nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(300), nullable=True)
    buyer_email: Mapped[str] = mapped_column(String(320), nullable=True)
    customer: Mapped[str] = mapped_column(String(200), nullable=True)
    opportunity: Mapped[str] = mapped_column(String(140), nullable=True)
    received_at: Mapped[str] = mapped_column(String(40), nullable=True)
    quote_due: Mapped[str] = mapped_column(String(40), nullable=True)
    quote_due_raw: Mapped[str] = mapped_column(String(60), nullable=True)
    quote_due_note: Mapped[str] = mapped_column(String(200), nullable=True)
    target_ship: Mapped[str] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=True)
    total_qty: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")
    asks: Mapped[str] = mapped_column(Text, nullable=True)         # JSON list
    missing: Mapped[str] = mapped_column(Text, nullable=True)      # JSON list
    lines: Mapped[str] = mapped_column(Text, nullable=True)        # JSON list of style lines
    note: Mapped[str] = mapped_column(Text, nullable=True)
    history_at: Mapped[str] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    @staticmethod
    def _loads(txt, default):
        try:
            return _json.loads(txt) if txt else default
        except Exception:
            return default

    def to_dict(self) -> dict:
        ls = self._loads(self.lines, [])
        return {
            "id": self.id, "run_id": self.run_id, "chain_id": self.chain_id,
            "mail_id": self.mail_id, "subject": self.subject or "",
            "buyer_name": self.buyer_name or "", "buyer_email": self.buyer_email or "",
            "customer": self.customer or "", "opportunity": self.opportunity or "",
            "received_at": self.received_at or "", "quote_due": self.quote_due or "",
            "quote_due_raw": self.quote_due_raw or "", "quote_due_note": self.quote_due_note or "",
            "target_ship": self.target_ship or "", "currency": self.currency or "",
            "total_qty": self.total_qty or 0,
            "status": self.status or "new",
            "asks": self._loads(self.asks, []), "missing": self._loads(self.missing, []),
            "lines": ls,
            "styles": [l.get("style") for l in ls],
            "old_styles": [l.get("style") for l in ls if l.get("verdict") in ("made", "costed")],
            "new_styles": [l.get("style") for l in ls if l.get("verdict") == "new"],
            "note": self.note or "", "history_at": self.history_at or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KVModel(Base):
    """Tiny key/value store (thread reuse, engine bookkeeping)."""

    __tablename__ = "app_kv"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

# Arinox layer tables (Tower Script Runtime, guardrails, sync, identity) — registered on the same Base.
import models_cx  # noqa: E402,F401
