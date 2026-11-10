"""One inbox, as conversations.

A *thread* is every mail of one conversation — the buyer's messages and our replies — under one ``thread_key``:

* Gmail's own conversation id (``X-GM-THRID``) when the mailbox is Gmail, so the tower groups exactly as Gmail does;
* otherwise the conversation a mail answers (``In-Reply-To`` / ``References``) — a reply joins the thread of the
  message it quotes, whether that message was the buyer's or ours;
* otherwise the mail starts its own thread.

Replies are sent **in the thread**: ``Re:`` the thread's subject, ``In-Reply-To`` the last message, ``References`` the
whole chain. That keeps the conversation together in the buyer's mail client and in ours, and the buyer's answer comes
back into the same thread, where the deal that lives in it notices it.

Nothing here writes to the ERP.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Optional

import inbound
import mailer
from models import EmailDraftModel, KVModel, MailAttachmentModel, MailMessageModel

#: business labels, most decisive first (a thread shows the strongest label among its messages)
LABEL_ORDER = ["new_order", "order_amendment", "inquiry", "invoice", "remittance", "query", "other"]
LABEL_NAME = {"new_order": "Order", "order_amendment": "Amendment", "inquiry": "Inquiry", "invoice": "Invoice",
              "remittance": "Payment", "query": "Question", "other": "Other", "noise": "System"}
FOLDERS = {
    "all": None,
    "inquiry": {"inquiry"},
    "orders": {"new_order", "order_amendment"},
    "money": {"invoice", "remittance"},
    "questions": {"query"},
    "other": {"other"},
}
_ID = re.compile(r"<[^<>\s]+>")


def _ids(*values: str) -> list[str]:
    out = []
    for v in values:
        for m in _ID.findall(v or ""):
            if m not in out:
                out.append(m)
        v = (v or "").strip()
        if v and not _ID.search(v) and "@" in v and " " not in v:   # a bare id without brackets
            b = f"<{v}>"
            if b not in out:
                out.append(b)
    return out


def _norm_mid(mid: str) -> str:
    mid = (mid or "").strip()
    if mid and not mid.startswith("<"):
        mid = f"<{mid}>"
    return mid


def clean_subject(subject: str) -> str:
    s = re.sub(r"\s+", " ", subject or "").strip()
    while True:
        t = re.sub(r"^\s*(re|fw|fwd|aw|sv|antw)\s*(\[\d+\])?\s*:\s*", "", s, flags=re.I)
        t = re.sub(r"^\s*subject\s*:\s*", "", t, flags=re.I)
        if t == s:
            break
        s = t
    return s.strip() or "(no subject)"


def _kv_get(db, key: str) -> Optional[str]:
    row = db.query(KVModel).filter(KVModel.key == key).first()
    return row.value if row else None


def _kv_set(db, key: str, value: str) -> None:
    row = db.query(KVModel).filter(KVModel.key == key).first()
    if row:
        row.value = value
    else:
        db.add(KVModel(key=key, value=value))


# ───────────────────────── threading ─────────────────────────

def _key_of_mid(db, mid: str) -> Optional[str]:
    mid = _norm_mid(mid)
    if not mid:
        return None
    bare = mid.strip("<>")
    r = db.query(MailMessageModel.thread_key).filter(MailMessageModel.message_id.in_([mid, bare]),
                                                     MailMessageModel.thread_key.isnot(None)).first()
    if r and r[0]:
        return r[0]
    r = db.query(EmailDraftModel.thread_key).filter(EmailDraftModel.message_id.in_([mid, bare]),
                                                    EmailDraftModel.thread_key.isnot(None)).first()
    return r[0] if r and r[0] else None


def resolve_key(db, message_id: str, references: str, in_reply_to: str, gm_thrid: str, fallback: str) -> str:
    """The thread a mail belongs to. A conversation already known (by any id it quotes) wins, so a Gmail thread and a
    thread rebuilt from headers before Gmail ids were stored stay one thread."""
    for mid in reversed(_ids(references, in_reply_to)):
        k = _key_of_mid(db, mid)
        if k:
            return k
    if gm_thrid:
        alias = _kv_get(db, f"thread_alias:gm:{gm_thrid}")
        if alias:
            return alias
        return f"gm:{gm_thrid}"
    chain = _ids(references, in_reply_to)
    if chain:
        return f"mid:{chain[0]}"
    if message_id:
        return f"mid:{_norm_mid(message_id)}"
    return fallback


def assign_threads(db) -> int:
    """Give every stored mail (and every reply we sent) its thread. Idempotent; returns how many rows it keyed."""
    n = 0
    rows = (db.query(MailMessageModel).filter(MailMessageModel.thread_key.is_(None))
            .order_by(MailMessageModel.received_at.asc(), MailMessageModel.id.asc()).all())
    for r in rows:
        refs = r.thread_id or ""
        key = resolve_key(db, r.message_id or "", refs, r.in_reply_to or "", r.gm_thrid or "", f"id:{r.id}")
        r.thread_key = key
        if r.gm_thrid and not key.startswith("gm:"):
            _kv_set(db, f"thread_alias:gm:{r.gm_thrid}", key)
        db.flush()
        n += 1
    for d in db.query(EmailDraftModel).filter(EmailDraftModel.thread_key.is_(None), EmailDraftModel.status == "sent").all():
        key = resolve_key(db, d.message_id or "", d.references or "", d.in_reply_to or "", "", "")
        if key:
            d.thread_key = key
            db.flush()
            n += 1
    db.commit()
    return n


# ───────────────────────── reading threads ─────────────────────────

def _label(m: MailMessageModel, own: str = "") -> str:
    if m.label:
        return m.label
    if m.status == "ignored":
        return "noise"
    if own and (m.from_addr or "").lower() == own and (m.direction or "in") == "in":
        return "noise"                       # our own test / alert mail delivered to the inbox
    return m.classification or "other"


CLASSIFIER_VERSION = "2026-11-07.1"


def ensure_classified(db) -> int:
    """Re-read every stored mail with the current classifier once per classifier version (the old one had no
    "inquiry" class). A label a person set by hand is never overwritten. Returns how many rows changed."""
    if _kv_get(db, "classifier_version") == CLASSIFIER_VERSION:
        return 0
    n = 0
    for m in db.query(MailMessageModel).filter(MailMessageModel.direction != "out").all():
        if m.status == "ignored":
            continue
        atts = _safe_json(m.attachments, [])
        r = inbound.classify(m.subject or "", m.body_text or "", atts)
        if r["classification"] != m.classification:
            m.classification, m.confidence, m.reasons = r["classification"], int(r["confidence"]), json.dumps(r["reasons"])
            n += 1
    _kv_set(db, "classifier_version", CLASSIFIER_VERSION)
    db.commit()
    return n


def _att_rows(db, mail_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if not mail_ids:
        return out
    for a in db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id.in_(mail_ids)).all():
        out.setdefault(a.mail_id, []).append({"id": a.id, "filename": a.filename, "mime": a.mime, "size": a.size,
                                              "readable": bool(a.ok), "needs_ocr": bool(a.needs_ocr)})
    return out


def _external(addr: str, own: str) -> bool:
    return bool(addr) and addr.lower() != (own or "").lower()


def _own_address(db) -> str:
    import functions
    row = functions._mail_settings_row(db)
    return (row.email_account or "").lower() if row else ""


def list_threads(db, folder: str = "all", q: str = "", limit: int = 60, offset: int = 0, show_archived: bool = False) -> dict:
    ensure_classified(db)
    if db.query(MailMessageModel.id).filter(MailMessageModel.thread_key.is_(None)).first():
        assign_threads(db)
    own = _own_address(db)
    msgs = db.query(MailMessageModel).filter(MailMessageModel.thread_key.isnot(None)).all()
    sent = db.query(EmailDraftModel).filter(EmailDraftModel.status == "sent", EmailDraftModel.thread_key.isnot(None)).all()
    from models_deal import DealModel
    deals = {d.thread_key: d for d in db.query(DealModel).filter(DealModel.thread_key.isnot(None)).all()}
    threads: dict[str, dict] = {}
    for m in msgs:
        t = threads.setdefault(m.thread_key, {"key": m.thread_key, "msgs": [], "out": []})
        t["msgs"].append(m)
    for d in sent:
        t = threads.setdefault(d.thread_key, {"key": d.thread_key, "msgs": [], "out": []})
        t["out"].append(d)
    out = []
    counts = {k: 0 for k in list(FOLDERS) + ["needs_reply", "archived", "system"]}
    ql = (q or "").strip().lower()
    for key, t in threads.items():
        ins = [m for m in t["msgs"] if (m.direction or "in") == "in"]
        if not ins and not t["msgs"]:
            continue                                          # only our own sent mail: not an inbox thread
        everything = [("in" if (m.direction or "in") == "in" else "out", m.received_at or "", m) for m in t["msgs"]] + \
                     [("out", d.sent_at.isoformat() if d.sent_at else "", d) for d in t["out"]]
        everything.sort(key=lambda x: x[1] or "")
        first = everything[0][2]
        last_dir, last_at, last = everything[-1]
        labels = [_label(m, own) for m in ins] or ["other"]
        business = [x for x in labels if x != "noise"]
        if not business:
            label = "noise"
        else:
            label = sorted(business, key=lambda x: LABEL_ORDER.index(x) if x in LABEL_ORDER else 99)[0]
        archived = bool(ins) and all(m.status in ("dismissed",) for m in ins if m.status != "ignored") and label != "noise"
        unread = any(m.status == "new" for m in ins)
        needs_reply = last_dir == "in" and label in ("inquiry", "new_order", "order_amendment", "query") and not archived
        party = next((m for m in reversed(ins) if _external(m.from_addr, own)), None)
        deal = deals.get(key)
        subj = clean_subject(getattr(first, "subject", "") or "")
        snippet = (inbound.strip_quoted(getattr(last, "body_text", None) or getattr(last, "body", "") or "") or
                   getattr(last, "snippet", "") or "")[:200]
        row = {"key": key, "subject": subj, "label": label, "label_name": LABEL_NAME.get(label, label.title()),
               "count": len(everything), "unread": unread, "needs_reply": needs_reply, "archived": archived,
               "from_name": (party.from_name if party else "") or "", "from_addr": (party.from_addr if party else "") or "",
               "last_at": last_at, "last_from": "us" if last_dir == "out" else ((last.from_name or last.from_addr) if last else ""),
               "snippet": re.sub(r"\s+", " ", snippet).strip(), "attachments": sum(int(m.has_attachments or 0) for m in ins),
               "deal": ({"id": deal.id, "stage": deal.stage, "title": deal.title} if deal else None)}
        if label == "noise":
            counts["system"] += 1
        elif archived:
            counts["archived"] += 1
        else:
            for f, allowed in FOLDERS.items():
                if allowed is None or label in allowed:
                    counts[f] += 1
            if needs_reply:
                counts["needs_reply"] += 1
        # folder filter
        if folder == "system":
            if label != "noise":
                continue
        elif folder == "archived":
            if not archived:
                continue
        else:
            if label == "noise" or (archived and not show_archived):
                continue
            if folder == "needs_reply":
                if not needs_reply:
                    continue
            elif FOLDERS.get(folder) and label not in FOLDERS[folder]:
                continue
        if ql and ql not in (subj + " " + row["from_name"] + " " + row["from_addr"] + " " + row["snippet"]).lower():
            continue
        out.append(row)
    out.sort(key=lambda r: r["last_at"] or "", reverse=True)
    return {"ok": True, "threads": out[offset: offset + limit], "total": len(out), "counts": counts}


def _msg_out(m, own: str, atts: dict) -> dict:
    if isinstance(m, MailMessageModel):
        direction = m.direction or "in"
        body = m.body_text or ""
        return {"id": m.id, "kind": "mail", "direction": direction, "from_name": m.from_name or "", "from_addr": m.from_addr or "",
                "to": m.to_addr or "", "cc": m.cc_addr or "", "subject": m.subject or "", "at": m.received_at,
                "body": body, "fresh": inbound.strip_quoted(body) or body, "attachments": atts.get(m.id, []),
                "label": _label(m, own), "label_name": LABEL_NAME.get(_label(m, own), _label(m, own)), "reasons": _safe_json(m.reasons, []),
                "message_id": m.message_id or "", "unread": m.status == "new"}
    return {"id": m.id, "kind": "sent", "direction": "out", "from_name": m.from_name or "", "from_addr": own,
            "to": m.to_email or "", "cc": m.cc or "", "subject": m.subject or "", "at": m.sent_at.isoformat() if m.sent_at else None,
            "body": m.body or "", "fresh": inbound.strip_quoted(m.body or "") or (m.body or ""), "attachments": [],
            "label": "", "label_name": "", "reasons": [], "message_id": m.message_id or "", "unread": False}


def _safe_json(v, default):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def get_thread(db, key: str, mark_read: bool = True) -> dict:
    own = _own_address(db)
    msgs = db.query(MailMessageModel).filter(MailMessageModel.thread_key == key).all()
    sent = db.query(EmailDraftModel).filter(EmailDraftModel.thread_key == key, EmailDraftModel.status == "sent").all()
    if not msgs and not sent:
        return {"ok": False, "error": "This conversation is not in the inbox any more."}
    atts = _att_rows(db, [m.id for m in msgs])
    items = [_msg_out(m, own, atts) for m in msgs] + [_msg_out(d, own, atts) for d in sent]
    # one message can exist twice: sent from the tower (email_draft) and read back from Gmail's Sent folder
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["at"] or ""):
        k = it["message_id"].strip("<>") if it["message_id"] else f"{it['kind']}:{it['id']}"
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    ins = [m for m in msgs if (m.direction or "in") == "in"]
    if mark_read:
        for m in ins:
            if m.status == "new":
                m.status = "read"
        db.commit()
    from models_deal import DealModel
    deal = db.query(DealModel).filter(DealModel.thread_key == key).first()
    party = next((m for m in reversed(ins) if _external(m.from_addr, own)), None)
    labels = [_label(m, own) for m in ins if _label(m, own) != "noise"]
    label = sorted(labels, key=lambda x: LABEL_ORDER.index(x) if x in LABEL_ORDER else 99)[0] if labels else "other"
    first_inquiry = next((m for m in sorted(ins, key=lambda x: x.received_at or "") if _label(m, own) == "inquiry"), None)
    archived = bool(ins) and all(m.status == "dismissed" for m in ins if m.status != "ignored") and any(m.status != "ignored" for m in ins)
    return {"ok": True, "key": key, "subject": clean_subject(uniq[0]["subject"]), "label": label, "archived": archived,
            "label_name": LABEL_NAME.get(label, label), "messages": uniq,
            "party": {"name": party.from_name if party else "", "email": party.from_addr if party else ""},
            "deal": deal.to_dict() if deal else None,
            "inquiry_mail_id": first_inquiry.id if first_inquiry else (ins[0].id if ins else None),
            "own": own}


def set_label(db, key: str, label: str) -> dict:
    if label not in LABEL_ORDER:
        return {"ok": False, "error": "Unknown label."}
    rows = db.query(MailMessageModel).filter(MailMessageModel.thread_key == key, MailMessageModel.direction != "out").all()
    for m in rows:
        m.label = label
        if m.status == "ignored":
            m.status = "read"
    db.commit()
    return {"ok": True, "label": label}


def archive(db, key: str, archived: bool = True) -> dict:
    rows = db.query(MailMessageModel).filter(MailMessageModel.thread_key == key).all()
    for m in rows:
        if m.status == "ignored":
            continue
        m.status = "dismissed" if archived else "read"
    db.commit()
    return {"ok": True, "archived": archived}


# ───────────────────────── replying in the thread ─────────────────────────

def reply_headers(db, key: str) -> dict:
    """Subject, In-Reply-To and References for the next message in this thread, and who it goes to."""
    t = get_thread(db, key, mark_read=False)
    if not t.get("ok"):
        return t
    msgs = t["messages"]
    last = msgs[-1]
    chain: list[str] = []
    for it in msgs:
        mid = _norm_mid(it.get("message_id") or "")
        if mid and mid not in chain:
            chain.append(mid)
    in_reply_to = _norm_mid(last.get("message_id") or "")
    last_in = next((m for m in reversed(msgs) if m["direction"] == "in"), None)
    to = (last_in or {}).get("from_addr") or t["party"]["email"]
    return {"ok": True, "subject": "Re: " + t["subject"], "in_reply_to": in_reply_to,
            "references": " ".join(chain[-20:]), "to": to, "party": t["party"]}


def send_in_thread(db, me: dict, key: str, body: str, to: str = "", cc: str = "", subject: str = "",
                   deal_id: Optional[int] = None, intent: str = "thread_reply", html: str = "") -> dict:
    """Send ``body`` as the next message of thread ``key`` and record it in the thread."""
    body = (body or "").strip()
    if not body:
        return {"ok": False, "error": "Write the message first."}
    h = reply_headers(db, key)
    if not h.get("ok"):
        return h
    to = (to or h["to"] or "").strip()
    if not to or "@" not in to:
        return {"ok": False, "error": "No recipient: this conversation has no buyer address. Type one in To."}
    settings, err = _smtp(db)
    if err:
        return err
    subj = (subject or h["subject"]).strip()
    res = mailer.send_via_smtp(settings, to, subj, body, settings.get("from_name") or "", html=html,
                               in_reply_to=h["in_reply_to"], references=h["references"], cc=cc)
    d = EmailDraftModel(action_key=f"thread:{key}"[:160], intent=intent, to_email=to, from_name=settings.get("from_name") or "",
                        subject=subj[:500], body=body, status="sent" if res.get("ok") else "failed",
                        in_reply_to=h["in_reply_to"][:300], references=h["references"], thread_key=key, deal_id=deal_id, cc=cc or None,
                        grounding_ok=1, policy_version="thread-1", idempotency_key=f"thr-{uuid.uuid4().hex[:24]}",
                        message_id=res.get("message_id") or "", error=None if res.get("ok") else res.get("error"),
                        decided_by=me.get("email") or "", decided_at=datetime.now(), sent_at=datetime.now() if res.get("ok") else None)
    db.add(d)
    db.commit()
    if not res.get("ok"):
        return {"ok": False, "error": f"Not sent: {res.get('error') or 'the mail server refused it'}"}
    return {"ok": True, "message_id": d.message_id, "sent_id": d.id, "to": to, "subject": subj}


def _smtp(db) -> tuple[Optional[dict], Optional[dict]]:
    import functions
    import secret_store
    row = functions._mail_settings_row(db)
    if row is None or not row.email_account or not row.password:
        return None, {"ok": False, "error": "The mailbox is not set up yet. Open Settings → Mailbox."}
    try:
        pw = secret_store.dec(row.password)
    except secret_store.SecretUnreadable:
        return None, {"ok": False, "error": functions.MAIL_PASSWORD_UNREADABLE, "password_unreadable": True}
    return {"email_account": row.email_account, "from_name": row.from_name, "smtp_host": row.smtp_host,
            "smtp_port": row.smtp_port, "use_tls": row.use_tls, "password": pw}, None


def send_new(db, me: dict, to: str, subject: str, body: str, cc: str = "", deal_id: Optional[int] = None, intent: str = "new") -> dict:
    """A first message (a deal typed in by hand has no thread yet). The thread starts with it."""
    to = (to or "").strip()
    if not to or "@" not in to:
        return {"ok": False, "error": "Type the buyer's e-mail address."}
    if not (body or "").strip():
        return {"ok": False, "error": "Write the message first."}
    settings, err = _smtp(db)
    if err:
        return err
    res = mailer.send_via_smtp(settings, to, subject, body, settings.get("from_name") or "", cc=cc)
    mid = res.get("message_id") or ""
    key = f"mid:{_norm_mid(mid)}" if mid else None
    d = EmailDraftModel(action_key=f"new:{deal_id or ''}"[:160], intent=intent, to_email=to, from_name=settings.get("from_name") or "",
                        subject=(subject or "")[:500], body=body, status="sent" if res.get("ok") else "failed", thread_key=key,
                        deal_id=deal_id, cc=cc or None, grounding_ok=1, policy_version="thread-1",
                        idempotency_key=f"new-{uuid.uuid4().hex[:24]}", message_id=mid, error=None if res.get("ok") else res.get("error"),
                        decided_by=me.get("email") or "", decided_at=datetime.now(), sent_at=datetime.now() if res.get("ok") else None)
    db.add(d)
    db.commit()
    if not res.get("ok"):
        return {"ok": False, "error": f"Not sent: {res.get('error') or 'the mail server refused it'}"}
    return {"ok": True, "message_id": mid, "sent_id": d.id, "to": to, "subject": subject, "thread_key": key}


# ───────────────────────── sync ─────────────────────────

def store_sent(db, messages: list[dict]) -> int:
    """Our own replies read back from Gmail's Sent folder, kept only when they belong to a conversation we know."""
    n = 0
    known = {u for (u,) in db.query(MailMessageModel.uid).filter(MailMessageModel.uid.like("sent:%")).all()}
    ours = {(m or "").strip("<>") for (m,) in db.query(EmailDraftModel.message_id).filter(EmailDraftModel.status == "sent").all() if m}
    for m in messages:
        if m["uid"] in known or (m.get("message_id") or "").strip("<>") in ours:
            continue
        key = resolve_key(db, m.get("message_id") or "", m.get("thread_id") or "", m.get("in_reply_to") or "", m.get("gm_thrid") or "", "")
        if not key or (key.startswith("gm:") and not db.query(MailMessageModel.id).filter(MailMessageModel.thread_key == key).first()):
            continue                                             # a sent mail with no conversation in the inbox
        db.add(MailMessageModel(uid=m["uid"], message_id=m.get("message_id"), thread_id=m.get("thread_id"),
                                from_name=m.get("from_name"), from_addr=m.get("from_addr"), to_addr=m.get("to_addr"),
                                subject=m.get("subject"), snippet=m.get("snippet"), body_text=m.get("body_text"),
                                received_at=m.get("received_at"), has_attachments=m.get("has_attachments") or 0,
                                attachments=json.dumps([{k: v for k, v in a.items() if k != "data"} for a in (m.get("attachments") or [])]),
                                classification="other", confidence=0, status="read", direction="out",
                                gm_thrid=m.get("gm_thrid") or None, in_reply_to=(m.get("in_reply_to") or "")[:300] or None,
                                cc_addr=(m.get("cc_addr") or "")[:600] or None, thread_key=key))
        db.commit()
        n += 1
    return n


def sync(db, me: dict, limit: int = 40) -> dict:
    """Read new mail (inbox and, on Gmail, our Sent folder), thread it, and tell the deals that got a buyer reply."""
    import functions
    before = db.query(MailMessageModel.id).order_by(MailMessageModel.id.desc()).first()
    high = before[0] if before else 0
    res = functions.sync_inbox(db, limit=int(limit))
    if not res.get("ok"):
        return {"ok": False, "error": res.get("message") or _sync_error(res.get("error")), "password_unreadable": bool(res.get("password_unreadable"))}
    sent_n = 0
    try:
        s = functions._mailbox_settings(db)
        known = {u for (u,) in db.query(MailMessageModel.uid).filter(MailMessageModel.uid.like("sent:%")).all()}
        sres = inbound.fetch_sent(s, known)
        if sres.get("ok"):
            assign_threads(db)
            sent_n = store_sent(db, sres.get("messages") or [])
    except Exception:
        pass
    keyed = assign_threads(db)
    ensure_classified(db)
    import deals
    replies = deals.notice_replies(db, high)
    return {"ok": True, "fetched": int(res.get("fetched") or 0), "sent_read": sent_n, "threaded": keyed,
            "deal_replies": replies, "remaining": res.get("remaining", 0)}


def _sync_error(code: str) -> str:
    return {"mailbox_not_configured": "No mailbox is set up yet. Open Settings → Mailbox.",
            "password_unreadable": "The saved mailbox password can't be unlocked. Enter it again in Settings → Mailbox."}.get(
        code or "", f"The mailbox did not answer ({code})." if code else "The mailbox did not answer.")
