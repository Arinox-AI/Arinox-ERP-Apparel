"""Cortex Operations Control Tower — Configuration.

Single source of truth. Business code imports from here and NEVER reads
``os.environ`` itself (appster core-builder rule). Runtime values that pi-api
injects per request (identity, API URLs, JWT) are read from the environment at
import time; integration constants carry the current production value as a
default but can be overridden by env for other installations.
"""

import os as _os

# ── Project identity — the ONLY fixed literal (this project's folder/slug) ────
PROJECT_SLUG    = "cortex_operations_control_tower"

# ── Identity (injected by pi-api at runtime — never literal) ──────────────────
AGENT_ID        = _os.environ.get("AGENT_ID")        or ""
DEPLOYMENT_ID   = _os.environ.get("DEPLOYMENT_ID")   or ""
USER_ID         = _os.environ.get("USER_ID")         or ""
SWARM_ID        = _os.environ.get("SWARM_ID")        or ""
USER_JWT_TOKEN  = _os.environ.get("USER_JWT_TOKEN")  or ""   # runtime secret

# ── API URLs (ALL from env — never derived, never guessed) ────────────────────
KOGO_API_BASE   = _os.environ.get("KOGO_API_BASE")   or ""
API_PATH        = _os.environ.get("API_PATH")        or ""
TOOL_URL        = _os.environ.get("TOOL_URL")        or ""
CHAT_API_PATH   = _os.environ.get("CHAT_API_PATH")   or ""

# ── Integration constants (env-overridable; defaults = current production) ────
# Centralised here so NO business module hardcodes them (appster rule 1/5).
# The KOGO ERP application id (app_type KOGO_SAS) for this workspace's ERP.
ERP_APP_ID       = _os.environ.get("ERP_APP_ID")        or "6a84626b933cd6f2680eedac"

# ERP write-path mode: off | safe | draft | all
ERP_WRITE_MODE   = (_os.environ.get("ERP_WRITE_MODE")    or "draft").strip().lower()

# Company / currency / price-list defaults for generated records & emails.
# These MUST match the company this workspace's KOGO ERP actually holds, otherwise every
# generated draft is refused by the ERP ("Could not find Company: ..."). Verified live
# 2026-11-06: the ERP carries ONE company, Go Go International (GGI), default currency INR.
DEFAULT_COMPANY  = _os.environ.get("DEFAULT_COMPANY")   or "Go Go International"
DEFAULT_CURRENCY = _os.environ.get("DEFAULT_CURRENCY")  or "INR"
SELLING_PRICE_LIST = _os.environ.get("SELLING_PRICE_LIST") or "Standard Selling"

# How big an e-mail attachment may be and still be kept, read and shown. A buyer's tech pack is a photo-heavy
# spreadsheet or PDF and is routinely 15-25 MB, so a small cap silently loses the most important document in the mail.
# Set MAX_ATTACHMENT_MB in the environment to change it; the tower stores a row for anything bigger and says so,
# instead of pretending the mail never had it.
MAX_ATTACHMENT_MB = int(_os.environ.get("MAX_ATTACHMENT_MB") or 40)
MAX_ATTACHMENT_BYTES = MAX_ATTACHMENT_MB * 1024 * 1024

# Secret-at-rest key (secret_store.py). Set CORTEX_SECRET_KEY to keep the key out of the
# filesystem entirely; when empty a 0600 key file is created under data/ instead.
SECRET_KEY      = _os.environ.get("CORTEX_SECRET_KEY") or ""

# The one cap on how many ERP records a single execution may create. Read by
# write_gate.py and re-exported as ``write_gate.MAX_PER_RUN``; writes.py and
# intake_exec.py both import that, so the two paths cannot drift (2026-11-04).
MAX_WRITES_PER_RUN = int(_os.environ.get("MAX_WRITES_PER_RUN") or 60)

# Outbound/inbound mail defaults (a saved MailSettings row overrides these).
MAIL_FROM_NAME   = _os.environ.get("MAIL_FROM_NAME")    or "Cortex Textile Limited"
SMTP_HOST        = _os.environ.get("SMTP_HOST")         or "smtp.gmail.com"
SMTP_PORT        = int(_os.environ.get("SMTP_PORT")     or 587)
IMAP_HOST        = _os.environ.get("IMAP_HOST")         or "imap.gmail.com"
IMAP_PORT        = int(_os.environ.get("IMAP_PORT")     or 993)

# ── Arinox layer (Tower Script Runtime, guardrails, two-way sync) ─────────────
# The Arinox ERP site the TSR writes to. When empty, the tower falls back to the KOGO_SAS credentials that
# ``erp.py`` already discovers (same site as the Cortex "Evidence" data).
ARINOX_ERP_BASE   = _os.environ.get("ARINOX_ERP_BASE")    or ""
ARINOX_ERP_TOKEN  = _os.environ.get("ARINOX_ERP_TOKEN")   or ""    # "key:secret" — runtime secret
# Shared secret an ERP Webhook must present to ``erp_event`` (empty = webhook intake refused).
ERP_WEBHOOK_SECRET = _os.environ.get("ERP_WEBHOOK_SECRET") or ""
# Public URL of this tower, used for "Open in Cortex Tower" links written into the ERP.
TOWER_URL         = _os.environ.get("TOWER_URL")          or ""
# Hard ceilings for guarded writes.
MAX_WRITES_PER_MINUTE = int(_os.environ.get("MAX_WRITES_PER_MINUTE") or 120)
LOCK_TTL_SECONDS  = int(_os.environ.get("LOCK_TTL_SECONDS") or 120)
# Value above which a second person must approve (USD-equivalent, 0 = off).
APPROVAL_VALUE_LIMIT = float(_os.environ.get("APPROVAL_VALUE_LIMIT") or 0)
# How an approved order intake writes to the ERP (2026-11-07):
#   pipeline (default) — every create goes through pipeline.execute: role check, field guard, the ERP's
#                        business rules run inside the tower (needed while ERP server scripts are OFF), audit.
#   direct             — the older REST create, for an emergency only.
INTAKE_WRITE_PATH = (_os.environ.get("INTAKE_WRITE_PATH") or "pipeline").strip().lower()
# TnA calendar: when the ERP holds no Sales Orders yet, show the bundled sample order (clearly marked
# "Sample") instead of an empty page. Set TNA_SAMPLE_WHEN_EMPTY=0 to show the empty state instead.
TNA_SAMPLE_WHEN_EMPTY = (_os.environ.get("TNA_SAMPLE_WHEN_EMPTY") or "0").strip() == "1"   # 2026-11-09: off by default (TNA plan G25); set 1 only for a demo
# The Arinox ERP user the REST token belongs to (for the audit comment); informational.
ARINOX_API_USER   = _os.environ.get("ARINOX_API_USER")    or "Administrator"


def verified_identity() -> dict:
    """The caller KOGO has verified for THIS request (appster core-builder HARD RULE 0). ``{}`` = anonymous.

    Only ``KOGO_AUTH_VERIFIED == "1"`` makes the rest trustworthy; it is never read from request parameters.
    """
    if _os.environ.get("KOGO_AUTH_VERIFIED") != "1":
        return {}
    email = (_os.environ.get("USER_EMAIL") or "").strip().lower()
    if not email:
        return {}
    return {"email": email, "name": _os.environ.get("USER_NAME") or email, "is_admin": _os.environ.get("USER_IS_ADMIN") == "1"}


def sso_present() -> bool:
    return _os.environ.get("KOGO_AUTH_VERIFIED") == "1"


def llm_available() -> bool:
    return bool(USER_JWT_TOKEN) or sso_present()
