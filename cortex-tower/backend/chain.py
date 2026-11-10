"""The mail chain — one conversation with one buyer, followed from the first mail to the order.

Why this module exists
----------------------
Intake reads ONE mail and decides what it is. That is right for the first mail and wrong
for the twelfth. A real deal is a conversation:

    buyer: "quote C9533-U71-725, 3,100 pcs, DDP LA"      → enquiry
    us:    "here is our offer"                            → reply, in thread
    buyer: "tech pack and BOM attached"                   → the pack, in the SAME thread
    buyer: "approved, go ahead"                           → the order

Read as separate documents, mail 3 starts a second Opportunity and mail 4 a third, and the
deal forks into three unrelated records. That is not a theory — on 2026-11-03 the first
enquiry could not even create its Opportunity (the buyer was not a Customer), and the
only thing the approval produced was a to-do.

So a chain is the unit of work, and it is identified by the mail **thread**, never by the
subject and never by the buyer name:

* ``thread_key()`` = the ROOT Message-ID — the first id in ``References``, else
  ``In-Reply-To``, else the message's own id.
* every reply the Tower sends carries ``In-Reply-To`` + ``References`` for the chain, so
  the buyer's client keeps the thread and the answer comes back to us with the id we know.
* ``message_ids`` holds every Message-ID seen in or out, so an inbound reply is matched by
  the id it answers. Two buyers can send the same subject; ids are unique.

Nothing here writes to the ERP. It only keeps the conversation straight.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func

from models import MailChainModel, MailMessageModel, EmailDraftModel, IntakeRunModel

_MSGID = re.compile(r"<[^<>@\s]+@[^<>\s]+>")


# ── message-id plumbing ──────────────────────────────────────────────────────
def ids_of(raw) -> list[str]:
    """Every Message-ID inside a References / In-Reply-To header, in header order.

    Accepts a header string, a list, or None. Angle brackets are dropped so the same
    id compares equal whether it came from a header or from our own send result.
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts: list[str] = []
        for item in raw:
            parts.extend(ids_of(item))
        return parts
    text = str(raw)
    found = _MSGID.findall(text)
    if found:
        return [f.strip("<>") for f in found]
    # a bare id with no angle brackets is still an id
    return [t.strip().strip("<>") for t in text.split() if "@" in t]


def normalise(mid: Optional[str]) -> str:
    return (mid or "").strip().strip("<>").strip()


def thread_key(references=None, in_reply_to=None, own_id: Optional[str] = None) -> str:
    """The id that identifies the conversation: the oldest id we can see."""
    refs = ids_of(references)
    if refs:
        return refs[0]
    irt = ids_of(in_reply_to)
    if irt:
        return irt[0]
    return normalise(own_id)


# ── lookup / create ─────────────────────────────────────────────────────────
def _all_ids(*raws) -> list[str]:
    out: list[str] = []
    for r in raws:
        for i in ids_of(r):
            if i and i not in out:
                out.append(i)
    return out


_SUBJ_PREFIX = re.compile(r"(?i)^\s*(?:(?:re|aw|fw|fwd)\s*:\s*)+")


def subject_key(text: str) -> str:
    """The subject with reply/forward prefixes and whitespace stripped — for the LAST-RESORT
    match only, used when a client sends a reply with no reference headers at all."""
    t = _SUBJ_PREFIX.sub("", str(text or ""))
    return re.sub(r"\s+", " ", t).strip().lower()[:200]


def find(db, references=None, in_reply_to=None, own_id: Optional[str] = None,
         subject: Optional[str] = None, from_addr: Optional[str] = None,
         days: int = 90) -> Optional[MailChainModel]:
    """The chain this mail belongs to, or None.

    Matched on the ids the mail carries — the chain's own key first (cheap), then every id
    ever seen in or out of it. **Only when the mail carries no id at all** (some clients
    strip `References`/`In-Reply-To`) does it fall back to the SAME SENDER on the SAME
    subject within the window — never subject alone, because two buyers share subjects.
    """
    key = thread_key(references, in_reply_to, own_id)
    if key:
        hit = db.query(MailChainModel).filter(MailChainModel.key == key).first()
        if hit:
            return hit
    # what the mail SAYS it answers. `own_id` alone is not a reference — every mail has one,
    # so keying the fallback on "no ids at all" made it unreachable (2026-11-03).
    ref_ids = set(_all_ids(references, in_reply_to))
    if ref_ids:
        for row in db.query(MailChainModel).order_by(MailChainModel.id.desc()).all():
            known = set(json.loads(row.message_ids or "[]") or [])
            if known & ref_ids:
                return row
        return None
    # no reference headers at all — last resort, the same sender on the same subject
    want = subject_key(subject or "")
    sender = (from_addr or "").strip().lower()
    if not want or not sender:
        return None
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    for row in (db.query(MailChainModel)
                .filter(func.lower(MailChainModel.buyer_email) == sender)
                .order_by(MailChainModel.id.desc()).all()):
        last = row.last_in_at or (row.created_at.isoformat() if row.created_at else "")
        if subject_key(row.subject) == want and last >= cutoff:
            return row
    return None


def _merge_ids(chain: MailChainModel, new_ids: list[str]) -> None:
    try:
        have = json.loads(chain.message_ids or "[]") or []
    except Exception:
        have = []
    changed = False
    for i in new_ids:
        if i and i not in have:
            have.append(i)
            changed = True
    if changed:
        chain.message_ids = json.dumps(have)


def attach(db, mail: MailMessageModel, commit: bool = True) -> Optional[MailChainModel]:
    """Find or open the chain for one inbound mail, and stamp the mail with it.

    ``mail.thread_id`` is the References/In-Reply-To header as inbound.read stored it.
    An inbound message with no References starts a chain of its own — that is a new
    conversation, not a failure.
    """
    refs = mail.thread_id or ""
    own = normalise(mail.message_id) or f"uid:{mail.uid}"
    row = find(db, references=refs, own_id=own, subject=mail.subject,
               from_addr=mail.from_addr)
    if row is None:
        key = thread_key(refs, None, own)
        row = MailChainModel(
            key=key or own,
            subject=(mail.subject or "")[:600],
            buyer_name=(mail.from_name or "")[:300],
            buyer_email=(mail.from_addr or "")[:320],
            status="open",
            message_ids=json.dumps([i for i in _all_ids(refs, own)]),
            ingested=json.dumps({}),
        )
        db.add(row)
        db.flush()
    else:
        _merge_ids(row, _all_ids(refs, own))
        if not row.buyer_email and mail.from_addr:
            row.buyer_email = (mail.from_addr or "")[:320]
    was_placed = (mail.chain_id == row.id)
    mail.chain_id = row.id
    row.last_in_at = (mail.received_at or datetime.now().isoformat())[:40]
    # count MAILS, not reads: a re-read of the same mail must not inflate the thread
    if not was_placed:
        row.reply_count = int(row.reply_count or 0) + 1
    if commit:
        db.commit()
        db.refresh(row)
    return row


def reply_headers(db, chain: MailChainModel) -> dict:
    """The headers that keep our answer inside the buyer's thread.

    ``In-Reply-To`` must be a real id the buyer's client already knows — the last one we
    hold. ``References`` is the whole chain, oldest first, which is what makes clients
    (and Gmail) fold the message into the existing conversation instead of starting one.
    """
    ids = []
    try:
        ids = json.loads(chain.message_ids or "[]") or []
    except Exception:
        ids = []
    # The message being answered must be one the BUYER sent: replying on top of a copy we
    # forwarded to ourselves references an id the buyer's mailbox never saw, and their
    # client then starts a new conversation (2026-11-03).
    buyer = (chain.buyer_email or "").strip().lower()
    q = db.query(MailMessageModel).filter(MailMessageModel.chain_id == chain.id)
    theirs = (q.filter(func.lower(MailMessageModel.from_addr) == buyer)
              .order_by(MailMessageModel.id.desc()).first()) if buyer else None
    last_in = theirs or q.order_by(MailMessageModel.id.desc()).first()
    in_reply_to = normalise(last_in.message_id) if (last_in and last_in.message_id) else (ids[-1] if ids else "")
    return {"in_reply_to": in_reply_to,
            "references": " ".join(f"<{i}>" for i in ids)}


def note_outbound(db, chain: MailChainModel, message_id: str) -> None:
    """Record what we sent, so the answer to it lands in this chain."""
    mid = normalise(message_id)
    if mid:
        _merge_ids(chain, [mid])
        chain.last_out_at = datetime.now().isoformat()[:40]
        db.commit()


# ── what the chain has produced ─────────────────────────────────────────────
_RECORD_FIELD = {
    "Opportunity": "opportunity",
    "Client Purchase Order": "client_po",
    "Sales Order": "sales_order",
    "Buyer Tech Pack": "pack",
}


def link(db, chain: MailChainModel, doctype: str, name: str) -> None:
    """Attach an ERP record to the chain — the chain is how you find it later."""
    if doctype == "Customer":
        chain.customer = name
        return
    field = _RECORD_FIELD.get(doctype)
    if not field:
        return
    if field == "pack":
        try:
            have = json.loads(chain.ingested or "{}") or {}
        except Exception:
            have = {}
        have.setdefault("_packs", [])
        if name not in have["_packs"]:
            have["_packs"].append(name)
        chain.ingested = json.dumps(have)
        return
    setattr(chain, field, name)


def context(db, chain_id: Optional[int]) -> dict:
    """The chain as the planner needs to see it."""
    if not chain_id:
        return {}
    row = db.query(MailChainModel).filter(MailChainModel.id == int(chain_id)).first()
    if not row:
        return {}
    approved = (db.query(IntakeRunModel)
                .filter(IntakeRunModel.chain_id == row.id,
                        IntakeRunModel.status == "approved")
                .order_by(IntakeRunModel.id).all())
    return {
        "id": row.id,
        "live": bool(approved),
        "runs": [r.id for r in approved],
        "opportunity": row.opportunity or "",
        "client_po": row.client_po or "",
        "sales_order": row.sales_order or "",
        "customer": row.customer or "",
        "status": row.status or "open",
        "reply_count": int(row.reply_count or 0),
        "ingested": json.loads(row.ingested or "{}") or {},
    }


def timeline(db, chain: MailChainModel) -> list[dict]:
    """Everything in and out of this chain, oldest first."""
    rows: list[dict] = []
    for m in (db.query(MailMessageModel)
              .filter(MailMessageModel.chain_id == chain.id)
              .order_by(MailMessageModel.id).all()):
        run = (db.query(IntakeRunModel)
               .filter(IntakeRunModel.mail_id == m.id)
               .order_by(IntakeRunModel.id.desc()).first())
        rows.append({
            "dir": "in", "id": m.id, "at": m.received_at or "",
            "from": m.from_addr or "", "to": m.to_addr or "",
            "subject": m.subject or "",
            "body": (m.body_text or "")[:4000],
            "attachments": json.loads(m.attachments or "[]") or [],
            "run_id": run.id if run else None,
            "route": run.route if run else "",
            "status": run.status if run else "",
        })
    for d in (db.query(EmailDraftModel)
              .filter(EmailDraftModel.chain_id == chain.id)
              .order_by(EmailDraftModel.id).all()):
        rows.append({
            "dir": "out", "id": d.id, "at": (d.sent_at.isoformat() if d.sent_at
                                             else (d.created_at.isoformat() if d.created_at else "")),
            "from": d.from_name or "", "to": d.to_email or "",
            "subject": d.subject or "",
            "body": (d.body or "")[:4000],
            "attachments": [],
            "status": d.status or "draft",
            "message_id": d.message_id or "",
        })
    rows.sort(key=lambda r: (r.get("at") or "", 0 if r["dir"] == "in" else 1))
    return rows


def newest_for_run(db, run: IntakeRunModel) -> Optional[MailChainModel]:
    """The chain for a run, and never a dangling pointer: a chain id that no longer
    resolves falls through to the mail's own chain (the id survives a re-read)."""
    if getattr(run, "chain_id", None):
        row = db.query(MailChainModel).filter(MailChainModel.id == run.chain_id).first()
        if row is not None:
            return row
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
    if mail is not None and mail.chain_id:
        return db.query(MailChainModel).filter(MailChainModel.id == mail.chain_id).first()
    return None
