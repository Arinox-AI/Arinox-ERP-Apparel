"""Outbound SMTP transport for the Cortex Control Tower email connector (P1).

This is the ONLY module allowed to talk SMTP. It uses the Python standard
library exclusively — no external dependencies.

``email_engine`` remains the only thing that writes an email *body*; this module
simply transports a plain-text message that a human has already approved.

Usage::

    from mailer import send_via_smtp
    result = send_via_smtp(settings, to_email, subject, body, from_name)
    # -> {"ok": bool, "message_id": str, "error": str}
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

import config


_BREAKS = re.compile(r"[\r\n\t]+")


def clean_header(value: str, limit: int = 900) -> str:
    """One line, no CR/LF. A buyer's subject can carry a line break — the raw header of
    "SUBJECT: Enquiry … quote\r\n (DDP Los Angeles)" did — and `msg["Subject"] = …` then
    raises ValueError *before* any transport is touched, so the whole send died with no
    error anywhere the operator could see (2026-11-03)."""
    return _BREAKS.sub(" ", str(value or "")).strip()[:limit]


def send_via_smtp(settings: dict, to_email: str, subject: str, body: str,
                  from_name: str = "", html: str = "",
                  in_reply_to: str = "", references: str = "", cc: str = "") -> dict:
    """Send an email over SMTP.

    ``settings`` carries the SMTP configuration (including the live password);
    callers must never return this dict to the frontend.  STARTTLS is used when
    ``settings["use_tls"]`` is truthy.  ``body`` is always sent as the plain-text
    part; when ``html`` is provided it is attached as a rich alternative so mail
    clients show the formatted version and plain-text readers still work.

    ``in_reply_to`` / ``references`` are the thread headers. Without them a reply is a
    NEW conversation to every mail client: the buyer's answer comes back as a separate
    subject, and the chain cannot be followed. They are optional so existing callers
    (and the SMTP test) are unchanged.
    """
    result = {"ok": False, "message_id": "", "error": ""}

    settings = settings or {}
    host = str(settings.get("smtp_host") or config.SMTP_HOST)
    try:
        port = int(settings.get("smtp_port") or config.SMTP_PORT)
    except Exception:
        port = config.SMTP_PORT
    use_tls = bool(int(settings.get("use_tls") or 0))
    account = str(settings.get("email_account") or "").strip()
    password = settings.get("password") or ""

    if not account:
        result["error"] = "No sender email account is configured."
        return result
    if not to_email:
        result["error"] = "No recipient address."
        return result
    if not password:
        result["error"] = "No SMTP password is saved."
        return result

    msg = EmailMessage()
    sender = f"{from_name} <{account}>" if from_name else account
    msg.set_content(body or "")
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        # every header is written INSIDE the try: an invalid one must come back as an
        # error the operator can read, never as an exception out of the send
        msg["From"] = clean_header(sender)
        msg["To"] = clean_header(to_email)
        if cc:
            msg["Cc"] = clean_header(cc)
        msg["Subject"] = clean_header(subject)
        msg["Message-ID"] = make_msgid()
        if in_reply_to:
            irt = clean_header(in_reply_to)
            msg["In-Reply-To"] = irt if irt.startswith("<") else f"<{irt}>"
        if references:
            msg["References"] = clean_header(references, 4000)
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(account, password)
            server.send_message(msg)
        result["ok"] = True
        result["message_id"] = msg.get("Message-ID") or ""
    except Exception as exc:  # transport/auth failure — reported, never raised
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
