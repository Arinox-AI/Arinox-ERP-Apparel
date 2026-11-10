"""Cortex Operations Control Tower — Inbound mail (IMAP).

Read-only mailbox ingestion plus **deterministic** understanding:

    fetch (IMAP) -> classify -> extract references -> match to live ERP orders

Two decisions from the client shape this module:

* **No OCR for now.** We read headers, the plain-text/HTML body and the attachment
  *names/sizes* — never the attachment contents. Anything that would need OCR is
  routed to the exception queue instead of guessed.
* **Nothing is written to the ERP here.** This module only produces facts + flags;
  the human-approved write path lives in ``writes.py`` / the change queue.

Everything is pure functions plus one IMAP fetch; no raising, no side effects.
"""

from __future__ import annotations

import base64
import email
import imaplib
import re
import ssl
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Optional

import config

# ── Classification ──────────────────────────────────────────────────────────
CLASS_NEW_ORDER = "new_order"
CLASS_AMENDMENT = "order_amendment"
CLASS_INVOICE = "invoice"
CLASS_REMITTANCE = "remittance"
CLASS_QUERY = "query"
CLASS_INQUIRY = "inquiry"
CLASS_OTHER = "other"

CLASS_LABEL = {
    CLASS_INQUIRY: "Inquiry",
    CLASS_NEW_ORDER: "New order",
    CLASS_AMENDMENT: "Order amendment",
    CLASS_INVOICE: "Invoice",
    CLASS_REMITTANCE: "Remittance",
    CLASS_QUERY: "Query",
    CLASS_OTHER: "General",
}

# Ordered rules — first strong match wins. Each is (classification, keywords).
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (CLASS_AMENDMENT, (
        "revised po", "revision", "amended", "amendment", "change order",
        "changes to the order", "updated po", "update to po", "modified po",
        "supersedes", "supersede", "please replace", "revised order",
        "change in quantity", "quantity change",
    )),
    (CLASS_REMITTANCE, (
        "remittance", "payment advice", "payment confirmation", "proof of payment",
        "payment advice", "tt copy", "swift copy", "paid in full", "payment has been",
        "we have transferred", "remitting",
    )),
    (CLASS_INVOICE, (
        "invoice", "tax invoice", "commercial invoice", "proforma", "debit note",
        "credit note", "inv no", "inv#", "inv-",
    )),
    (CLASS_NEW_ORDER, (
        "purchase order", "new order", "order confirmation", "po attached",
        "po no", "po #", "po number", "please find our order", "we would like to order",
        "order for", "enclosed our order", "placing an order", "confirm our order",
    )),
    (CLASS_QUERY, (
        "?", "please advise", "please confirm", "clarification", "could you",
        "kindly advise", "request for", "when will", "any update",
    )),
]

_INVOICE_ATT = ("invoice", "inv-", "tax-invoice", "proforma")
_PO_ATT = ("po", "purchase", "order")

# A PO reference: "PO 12345", "P.O. No. 12345", "PO#AB-123", "PO-12345".
# Only the *label* is case-insensitive — the captured ref is an explicit class,
# otherwise re.I would let "PO. Please" capture the word "Please".
_PO_RE = re.compile(
    r"\b(?i:P\.?\s?O\.?)\s*(?:(?i:NO\.?|NUMBER|#|:))?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-/]{2,24})\b")
# Bare long numbers that look like PO numbers (e.g. 69785), used only as a weak signal
_BARE_NUM_RE = re.compile(r"\b(\d{5,8})\b")


# ── Header / body helpers ───────────────────────────────────────────────────
def _decode(value: Any) -> str:
    """Decode an RFC2047 header into plain text. Never raises."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).strip()
    except Exception:
        try:
            return str(value).strip()
        except Exception:
            return ""


def _body_text(msg: email.message.Message, limit: int = 20000) -> str:
    """Extract readable text from a message: prefer text/plain, else strip HTML."""
    try:
        if msg.is_multipart():
            plain, html = "", ""
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                if part.get_filename():
                    continue
                if ctype == "text/plain" and not plain:
                    plain = part.get_payload(decode=True, ) and part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace") or ""
                elif ctype == "text/html" and not html:
                    html = part.get_payload(decode=True, ) and part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace") or ""
            text = plain or html
        else:
            payload = msg.get_payload(decode=True)
            text = payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""
    except Exception:
        text = ""
    if "<" in text and ">" in text:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?s)<br\s*/?>|</p>|</div>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


# The cap lives in config (env: MAX_ATTACHMENT_MB) so nothing here hardcodes a size. Anything over it keeps a metadata
# row and says why - it must never vanish from the mail as if it had not been sent.
MAX_ATTACHMENT_BYTES = getattr(config, "MAX_ATTACHMENT_BYTES", 40 * 1024 * 1024)


def _attachments(msg: email.message.Message) -> list[dict]:
    """Attachment metadata **and contents**.

    Until 2026-11-03 this returned names and sizes only ("no OCR by decision"),
    which meant a buyer's PO PDF was never read and the intake agent had nothing
    to understand. The bytes are now carried as base64 for documents — the caller
    writes them to disk, extracts the text and never asks the mailbox again.
    An image is kept too (so a human can look at the scan), but it is flagged.
    """
    out = []
    try:
        for part in msg.walk():
            fn = part.get_filename()
            if not fn:
                continue
            fn = _decode(fn)
            mime = (part.get_content_type() or "").lower()
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            item = {"filename": fn, "mime": mime, "size": len(payload)}
            if payload and len(payload) <= MAX_ATTACHMENT_BYTES:
                item["data"] = base64.b64encode(payload).decode("ascii")
            elif payload:
                item["too_large"] = 1
            out.append(item)
    except Exception:
        pass
    return out


def parse_message(raw: bytes, uid: str) -> dict:
    """Turn a raw RFC822 message into the flat dict we store. Never raises."""
    try:
        msg = email.message_from_bytes(raw)
    except Exception:
        msg = email.message_from_string("")

    from_name, from_addr = parseaddr(_decode(msg.get("From")))
    to_name, to_addr = parseaddr(_decode(msg.get("To")))
    subj = _decode(msg.get("Subject"))
    date_iso = None
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        date_iso = dt.astimezone(timezone.utc).isoformat()
    except Exception:
        date_iso = None

    body = _body_text(msg)
    atts = _attachments(msg)
    return {
        "uid": str(uid),
        "message_id": (msg.get("Message-ID") or "").strip(),
        "thread_id": (msg.get("References") or msg.get("In-Reply-To") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
        "cc_addr": ", ".join(a for _, a in getaddresses([_decode(msg.get("Cc"))]) if a).lower()[:600],
        "from_name": from_name or (from_addr.split("@")[0] if from_addr else ""),
        "from_addr": (from_addr or "").lower(),
        "to_addr": (to_addr or "").lower(),
        "subject": subj,
        "body_text": body,
        "snippet": re.sub(r"\s+", " ", body)[:280],
        "received_at": date_iso,
        "has_attachments": 1 if atts else 0,
        "attachments": atts,
    }


# ── IMAP fetch ──────────────────────────────────────────────────────────────
def fetch_inbox(settings: dict, known_uids: set[str], limit: int = 50,
                folder: str = "INBOX", since_uid: Optional[int] = None,
                full: bool = False) -> dict:
    """Fetch recent messages that are new to us.

    ``since_uid`` is the high-water mark already stored. When it is given we only
    look at UIDs above it (true incremental sync). On the very first sync
    (``since_uid is None``) we take only the newest ``limit`` messages so the
    whole mailbox history is never ingested at once.

    Returns ``{"ok", "error", "messages":[...], "scanned":n}``. Never raises.
    """
    host = (settings or {}).get("imap_host") or config.IMAP_HOST
    port = int((settings or {}).get("imap_port") or config.IMAP_PORT)
    user = (settings or {}).get("email_account") or ""
    pw = (settings or {}).get("password") or ""
    if not user or not pw:
        return {"ok": False, "error": "mailbox_not_configured", "messages": [], "scanned": 0,
                "remaining": 0}

    M = None
    try:
        M = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
        M.login(user, pw)
        M.select(folder)
        typ, data = M.uid("search", None, "ALL")
        if typ != "OK":
            return {"ok": False, "error": "imap_search_failed", "messages": [], "scanned": 0,
                    "remaining": 0}
        uids = [u.decode() for u in (data[0] or b"").split()]
        # UIDs are monotonic, so sorting is the mailbox order. The old code took the
        # FIRST `limit` of everything above the high-water mark but the caller only
        # called once — so a burst of junk mail hid the one real order (2026-11-03).
        # Now the caller drains in batches and `remaining` says how much is left.
        if full:
            # a FULL sweep ignores the high-water mark: a gap below it (mail that an
            # earlier truncated sync skipped) is otherwise invisible for ever
            fresh = [u for u in uids if u not in known_uids]
        elif since_uid is not None:
            try:
                fresh = sorted((u for u in uids if int(u) > int(since_uid)), key=lambda x: int(x))
            except Exception:
                fresh = list(uids)
            fresh = [u for u in fresh if u not in known_uids]
        else:
            fresh = [u for u in uids if u not in known_uids][-limit:]
        remaining = max(0, len(fresh) - int(limit))
        fresh = fresh[:int(limit)]
        messages = []
        gmail = _is_gmail(host)
        for uid in fresh:
            typ, payload = M.uid("fetch", uid, "(X-GM-THRID RFC822)" if gmail else "(RFC822)")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            m = parse_message(payload[0][1], uid)
            m["gm_thrid"] = _thrid(payload[0][0])
            messages.append(m)
        return {"ok": True, "error": "", "messages": messages, "scanned": len(fresh),
                "remaining": remaining}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "messages": [], "scanned": 0,
                "remaining": 0}
    finally:
        try:
            if M is not None:
                M.logout()
        except Exception:
            pass


_THRID = re.compile(rb"X-GM-THRID (\d+)")


def _is_gmail(host: str) -> bool:
    return "gmail" in (host or "").lower() or "googlemail" in (host or "").lower()


def _thrid(meta) -> str:
    """Gmail's own conversation id from a FETCH response line (``1 (X-GM-THRID 1789… UID 7 RFC822 {…}``)."""
    try:
        m = _THRID.search(meta if isinstance(meta, (bytes, bytearray)) else str(meta).encode())
        return m.group(1).decode() if m else ""
    except Exception:
        return ""


def fetch_sent(settings: dict, known_uids: set[str], days: int = 21, limit: int = 60) -> dict:
    """Messages in Gmail's Sent folder from the last ``days`` days that we have not stored yet.

    Replies a merchandiser sends from Gmail itself (not from the tower) belong to the same conversation; without them
    a thread shows the buyer's side only. Only Gmail is supported: other servers name their Sent folder differently and
    do not expose a thread id. UIDs are returned as ``sent:<uid>`` so they never collide with the inbox's.
    """
    host = (settings or {}).get("imap_host") or config.IMAP_HOST
    if not _is_gmail(host):
        return {"ok": True, "messages": [], "skipped": "not_gmail"}
    port = int((settings or {}).get("imap_port") or config.IMAP_PORT)
    user = (settings or {}).get("email_account") or ""
    pw = (settings or {}).get("password") or ""
    if not user or not pw:
        return {"ok": False, "error": "mailbox_not_configured", "messages": []}
    M = None
    try:
        M = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
        M.login(user, pw)
        typ, _ = M.select('"[Gmail]/Sent Mail"', readonly=True)
        if typ != "OK":
            return {"ok": False, "error": "no_sent_folder", "messages": []}
        since = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime("%d-%b-%Y")
        typ, data = M.uid("search", None, f"(SINCE {since})")
        uids = [u.decode() for u in (data[0] or b"").split()] if typ == "OK" else []
        fresh = [u for u in uids if f"sent:{u}" not in known_uids][-int(limit):]
        out = []
        for uid in fresh:
            typ, payload = M.uid("fetch", uid, "(X-GM-THRID RFC822)")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            m = parse_message(payload[0][1], f"sent:{uid}")
            m["gm_thrid"] = _thrid(payload[0][0])
            out.append(m)
        return {"ok": True, "messages": out}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "messages": []}
    finally:
        try:
            if M is not None:
                M.logout()
        except Exception:
            pass


def fetch_one(settings: dict, uid: str, folder: str = "INBOX") -> dict:
    """Re-fetch ONE message by UID (used to re-read mail stored before intake existed)."""
    host = (settings or {}).get("imap_host") or config.IMAP_HOST
    port = int((settings or {}).get("imap_port") or config.IMAP_PORT)
    user = (settings or {}).get("email_account") or ""
    pw = (settings or {}).get("password") or ""
    if not user or not pw:
        return {"ok": False, "error": "mailbox_not_configured", "message": None}
    M = None
    try:
        M = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
        M.login(user, pw)
        M.select(folder)
        typ, payload = M.uid("fetch", str(uid), "(RFC822)")
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            return {"ok": False, "error": "uid_not_found", "message": None}
        return {"ok": True, "error": "", "message": parse_message(payload[0][1], str(uid))}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "message": None}
    finally:
        try:
            if M is not None:
                M.logout()
        except Exception:
            pass


# ── Noise filter — system mail that must never become a business action ─────
_NOISE_SENDERS = ("mailer-daemon@", "postmaster@", "no-reply@", "noreply@", "donotreply@",
                  "mail delivery subsystem", "notification@")
_NOISE_SUBJECTS = ("delivery status notification", "undeliverable", "returned mail",
                   "mail delivery failed", "out of office", "automatic reply", "auto-reply",
                   "autoreply", "read receipt", "read:", "undelivered mail", "failure notice",
                   "vacation", "abwesenheit")


def is_noise(subject: str, from_addr: str, body: str = "") -> bool:
    """System/automated mail (bounces, auto-replies, receipts) — never a decision."""
    subj = (subject or "").lower()
    addr = (from_addr or "").lower()
    if any(k in subj for k in _NOISE_SUBJECTS):
        return True
    if any(k in addr for k in _NOISE_SENDERS):
        return True
    head = (body or "")[:400].lower()
    if "this is an automatically generated" in head or "do not reply to this email" in head:
        return True
    return False


# ── Understanding (deterministic) ───────────────────────────────────────────
_QUOTE_HEAD = re.compile(r"^(on .{4,200}wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+@.+|_{5,})\s*$", re.I)


def strip_quoted(body: str) -> str:
    """The new part of a reply: everything above "On … wrote:" / "-----Original Message-----", minus "> " lines."""
    out = []
    for line in (body or "").splitlines():
        t = line.strip()
        if _QUOTE_HEAD.match(t):
            break
        if t.startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


# A buyer asking for a price, with or without a BOM / tech pack. These were missing altogether: the classifier had no
# "inquiry" class, so "Enquiry on style C9043-U70-629" with its BOM attached was filed as General (2026-11-07).
_INQUIRY_WORDS = (r"\benquir(y|ies)\b", r"\binquir(y|ies)\b", r"\brfq\b", r"request for (a )?(quot|price|costing)", r"please (quote|price|cost)",
                  r"\bquot(e|ation) (for|request|on)\b", r"\bbest (price|quot)", r"\byour (best )?price\b", r"\bprice (for|on|of)\b",
                  r"\bcosting (for|on|of|request)\b", r"\bnew styles?\b", r"\btarget price\b", r"\bbill of materials?\b", r"\bbom\b",
                  r"\btech ?packs?\b", r"\bgive (me|us) (a |your )?(price|quote)")
_ORDER_WORDS = (r"\bpurchase order\b", r"\bpo (attached|enclosed|no\.?|number|#)", r"\bplease find (our|the) (po|purchase order|order)",
                r"\bnew order\b", r"\border confirmation\b", r"\bconfirm (our|the) order\b", r"\bplacing (an|the|our) order\b",
                r"\bwe would like to order\b", r"\benclosed (is )?our order\b")
_PO_FILE = re.compile(r"(^|[^a-z])(po|purchase[ _-]?order)([^a-z]|\d|$)", re.I)
_BOM_FILE = re.compile(r"(^|[^a-z])(bom|bill[ _-]?of[ _-]?materials?|cost ?sheet|sty360|tech[ _-]?pack|spec)([^a-z]|$)", re.I)
_SHEET_EXT = (".xls", ".xlsx", ".csv")


def _hits(patterns, text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.I)]


def classify(subject: str, body: str, attachments: list[dict] | None = None) -> dict:
    """Deterministic classification. Returns {classification, confidence, reasons}.

    Reads only what is new in the mail (quoted history of a reply is ignored), scores order and inquiry signals
    instead of taking the first keyword that matches, and treats an attached PO document as decisive: a buyer who
    replies to our quote with their POs attached has placed an order, even though the subject still says "Enquiry".
    """
    attachments = attachments or []
    subj = (subject or "").strip()
    is_reply = bool(re.match(r"^\s*(re|fw|fwd|aw)\s*:", subj, re.I))
    fresh = strip_quoted(body or "")
    text = f"{subj}\n{fresh}".lower()
    names = [(a.get("filename") or "") for a in attachments]
    reasons: list[str] = []

    po_docs = [n for n in names if _PO_FILE.search(n.rsplit(".", 1)[0]) and not _BOM_FILE.search(n)]
    bom_docs = [n for n in names if _BOM_FILE.search(n) or n.lower().endswith(_SHEET_EXT)]

    # 1. amendment / remittance / invoice keep their earlier, specific keywords (first strong match wins)
    for cls, keys in _RULES:
        if cls in (CLASS_NEW_ORDER, CLASS_QUERY):
            continue
        hits = [k for k in keys if k in text or any(k in n.lower() for n in names)]
        if cls == CLASS_INVOICE and po_docs and not any(n for n in names if any(x in n.lower() for x in _INVOICE_ATT)):
            continue                                    # "invoice" in a PO's terms is not an invoice
        if hits:
            reasons.append(f"{CLASS_LABEL[cls]}: matched {', '.join(hits[:3])}")
            conf = 55 + min(len(hits), 3) * 12
            if cls == CLASS_INVOICE and any(n for n in _INVOICE_ATT if any(n in x.lower() for x in names)):
                conf += 15
                reasons.append("invoice attachment present")
            if cls == CLASS_AMENDMENT and re.search(r"\bpo\b", subj, re.I):
                conf += 10
                reasons.append("PO reference in subject")
            return {"classification": cls, "confidence": min(conf, 97), "reasons": reasons}

    # 2. order vs inquiry, scored
    subj_w = 1 if is_reply else 2                       # a reply inherits its subject; it says less about this mail
    inq_subj, inq_body = _hits(_INQUIRY_WORDS, subj), _hits(_INQUIRY_WORDS, fresh)
    ord_subj, ord_body = _hits(_ORDER_WORDS, subj), _hits(_ORDER_WORDS, fresh)
    inquiry = subj_w * len(inq_subj) + len(inq_body) + (2 if bom_docs else 0)
    order = subj_w * len(ord_subj) + len(ord_body) + (6 if po_docs else 0)
    if re.search(r"\bpo\s*#?\s*\d{4,}", text, re.I):
        order += 2
    if po_docs:
        reasons.append(f"PO document attached: {po_docs[0]}")
    if bom_docs and not po_docs:
        reasons.append(f"BOM / spec attached: {bom_docs[0]}")
    if order >= 3 and order >= inquiry:
        reasons.insert(0, "New order: " + ", ".join((["PO document"] if po_docs else []) + [h.strip("\\b") for h in (ord_subj + ord_body)[:2]]))
        return {"classification": CLASS_NEW_ORDER, "confidence": min(60 + order * 6, 97), "reasons": reasons}
    if inquiry >= 2:
        reasons.insert(0, "Inquiry: asks for a price / sends styles to cost")
        return {"classification": CLASS_INQUIRY, "confidence": min(55 + inquiry * 7, 96), "reasons": reasons}

    # 3. a question
    q_keys = [k for k in dict(_RULES)[CLASS_QUERY] if k != "?" and k in text]
    if q_keys or ("?" in fresh and len(fresh) < 1500):
        reasons.append("Query: " + (", ".join(q_keys[:3]) or "asks a question"))
        return {"classification": CLASS_QUERY, "confidence": 60 + min(len(q_keys), 3) * 8, "reasons": reasons}

    if attachments:
        return {"classification": CLASS_OTHER, "confidence": 40,
                "reasons": ["attachment only — manual review"]}
    return {"classification": CLASS_OTHER, "confidence": 30, "reasons": ["no rule matched"]}


def extract_po_refs(subject: str, body: str, attachments: list[dict] | None = None) -> list[str]:
    """Pull PO references from subject, body and attachment filenames (no OCR)."""
    names = " ".join((a.get("filename") or "") for a in (attachments or []))
    text = f"{subject or ''}\n{body or ''}\n{names}"
    refs: list[str] = []
    for m in _PO_RE.finditer(text):
        refs.append(m.group(1).strip())
    if not refs:
        # only consider bare long numbers if the text talks about a PO/order
        if re.search(r"\b(po|purchase order|order)\b", text, re.I):
            refs.extend(_BARE_NUM_RE.findall(text))
    # de-dupe, keep order, drop noise. A real PO reference carries at least one
    # digit (pure words like "Please" are never a reference).
    seen, out = set(), []
    for r in refs:
        k = _norm(r)
        if len(k) < 4 or k in seen or not any(ch.isdigit() for ch in k):
            continue
        if k.isdigit() and len(k) < 5:
            continue
        seen.add(k)
        out.append(r)
    return out[:8]


def _norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def match_orders(po_refs: list[str], sales_orders: list[dict]) -> list[dict]:
    """Match extracted PO refs to live Sales Orders by their ``po_no``."""
    out = []
    for so in sales_orders or []:
        po = so.get("po_no") or ""
        npo = _norm(po)
        if not npo:
            continue
        for ref in po_refs:
            nref = _norm(ref)
            if nref and (nref == npo or nref in npo or npo in nref):
                out.append({"so": so.get("name"), "po_no": po, "matched_ref": ref,
                            "customer": so.get("customer")})
                break
    return out


def next_steps(classification: str, matched: list[dict], po_refs: list[str]) -> list[str]:
    """Human-readable recommended next steps for a flagged item."""
    steps: list[str] = []
    if classification == CLASS_NEW_ORDER:
        if matched:
            steps = [f"Confirm this is an amendment of existing order {matched[0]['so']}",
                     "If it is a new order, create the Sales Order as a draft",
                     "Verify price and delivery date against the customer PO"]
        else:
            steps = ["Match the buyer to a Customer in the ERP",
                     "Create the Sales Order as a draft for approval",
                     "Confirm size breakdown, price and delivery date"]
    elif classification == CLASS_AMENDMENT:
        if matched:
            steps = [f"Compare the revised PO against order {matched[0]['so']}",
                     "Approve the quantity/price/date change only if production allows",
                     "Issue a revised confirmation to the buyer"]
        else:
            steps = ["Locate the original order this revision belongs to",
                     "Do not action the change until the base order is identified"]
    elif classification == CLASS_INVOICE:
        steps = ["Check the invoice against the Sales Order and purchase order",
                 "Log/route for payment processing",
                 "Flag any price or quantity mismatch"]
    elif classification == CLASS_REMITTANCE:
        steps = ["Match the payment to the outstanding invoice",
                 "Record the payment reference against the receivable"]
    elif classification == CLASS_QUERY:
        steps = ["Read the question and draft a reply for approval"]
    elif classification == CLASS_INQUIRY:
        steps = ["Start a deal from this inquiry (styles and BOM are read from the mail)",
                 "Link or add the customer", "Cost each style, then send the quote in this thread"]
    else:
        steps = ["Review manually — no automatic action"]
    return steps
