# Cortex Control Tower — Email Connector (P1) — Build Spec

**Goal:** turn the existing draft-only email engine into a real **Approve → Send** loop over
Gmail SMTP, plus a **Mail Settings** panel. Outbound only (inbound sync is P2).

**Hard rules (do not break):**
- The frontend calls **only** the middleware (`callApi(...)`). No direct URLs, no SMTP in the browser.
- SMTP sending happens **only** in `backend/`. `email_engine.py` stays unchanged and remains the
  only thing that writes an email body (already grounded + validated).
- Never return the SMTP password to the frontend. Mask it.
- Do **not** remove or rewrite any existing function, view or model. Additive only.
- Never send without an explicit human approval call.

---

## 1. Models (append to `backend/models.py` — additive)

### `MailSettingsModel` — table `mail_settings` (single logical row)
| Field | Type | Default |
|---|---|---|
| id | Integer PK | auto |
| enabled | Integer (0/1) | 0 |
| email_account | String(160) | "" |
| from_name | String(160) | "Cortex Textile Limited" |
| smtp_host | String(160) | "smtp.gmail.com" |
| smtp_port | Integer | 587 |
| use_tls | Integer (0/1) | 1 |
| password | Text (nullable) | null |
| updated_at | DateTime | now |
| `to_dict()` returns `password_set: bool` and **never** the password. |

### `EmailDraftModel` — table `email_draft`
| Field | Type | Notes |
|---|---|---|
| id | Integer PK | |
| action_id | Integer null | action_state.id it came from |
| action_key | String(160) | |
| intent | String(40) | from engine |
| to_email | String(320) | |
| from_name | String(200) | |
| subject | String(500) | |
| body | Text | |
| fact_sheet | Text (JSON) | engine fact sheet |
| status | String(20) | `draft` \| `sent` \| `failed` \| `rejected` |
| grounding_ok | Integer | 0/1 |
| grounding_unsourced | Text (JSON list) | |
| policy_version | String(60) | |
| edited | Integer | 0/1 (body/subject edited by approver) |
| idempotency_key | String(80) unique | `f"{action_key}:{sha1(subject+body)}"` |
| message_id | String(200) | SMTP Message-ID after send |
| error | Text | failure text |
| created_at / decided_at / sent_at | DateTime | |
| decided_by | String(100) | default "Ops Manager" |
| `to_dict()` mirrors the columns (dates isoformat). |

## 2. New module `backend/mailer.py`

```
def send_via_smtp(settings: dict, to_email: str, subject: str, body: str, from_name: str = "") -> dict
    # returns {"ok": bool, "message_id": str, "error": str}
    # smtplib.SMTP(host, port, timeout=30) -> ehlo -> starttls(ssl.create_default_context()) when use_tls
    # -> ehlo -> login(email_account, password) -> send EmailMessage(From: "<from_name> <email_account>", To, Subject, body)
    # body is plain text (the engine emits plain text) — set_content(body)
```
No external deps beyond stdlib (`smtplib`, `ssl`, `email.message`).

## 3. New backend functions (append to `backend/functions.py`, register in `FUNCTIONS`)

All take `db: Session` first (existing convention) and return plain dicts.

| Function | Signature | Returns |
|---|---|---|
| `get_mail_settings` | `(db)` | `{settings: {...}, connected: bool}` — password masked |
| `save_mail_settings` | `(db, email_account, from_name=None, smtp_host="smtp.gmail.com", smtp_port=587, use_tls=1, password=None, enabled=1)` | `{ok, settings}`; only overwrite `password` when a non-empty value is passed |
| `test_mail_settings` | `(db, to=None)` | `{ok, error, to}` — sends a short test mail to `to or email_account` |
| `create_email_draft` | `(db, action_id, subject=None, body=None)` | `{ok, draft, blocked, blocked_reason}` — uses `_live_ctx` + `_email_preview` exactly like the preview; if the engine blocks, return `ok:false` + reason and store nothing |
| `get_email_drafts` | `(db, status="draft")` | `{drafts: [...]}` newest first; `status="all"` returns every row |
| `approve_and_send_email` | `(db, draft_id, subject=None, body=None, actor="Ops Manager")` | `{ok, status, message_id, error, draft}` — applies optional edits, re-runs `email_engine.validate_grounding` against the stored fact sheet; if ungrounded **refuse** (`ok:false`, `error:"ungrounded"`); then send; set status sent/failed; write `audit_log` |
| `reject_email_draft` | `(db, draft_id, reason="")` | `{ok, draft}` — status `rejected`, audit_log |
| `delete_email_draft` | `(db, draft_id)` | `{ok}` — only when status != `sent` |

Reuse existing helpers: `_live_ctx`, `_email_preview`, `AuditLogModel`, `json`, `Session`.
`sent` is idempotent: if a row is already `sent`, `approve_and_send_email` returns it unchanged.

## 4. Frontend

### 4a. New component `frontend/src/components/MailPanel.tsx`
- **Approval Queue** section: list of drafts (`get_email_drafts`) as cards/rows showing
  intent, To, subject, a preview of the body, grounding badge (Grounded ✅ / Blocked ⛔), created time.
  Each row: **Approve & Send**, **Edit**, **Reject**.
  - Edit opens an inline editor (subject + body); on save calls `approve_and_send_email` with edits.
  - Reject prompts for a reason → `reject_email_draft`.
  - Approve & Send → `approve_and_send_email`; toast result; refresh.
  - Empty state: "No drafts awaiting approval."
- **Mail Settings** (collapsible/modal): account, from name, SMTP host/port, TLS, password
  (type=password, placeholder "•••• (saved)" when `password_set`), **Save** → `save_mail_settings`,
  **Send test email** → `test_mail_settings`, showing ok/error.
- Tone/visual language must match the existing app (navy/teal/amber, existing `ui.tsx` primitives).

### 4b. Wire-in
- Add a view `frontend/src/views/MailView.tsx` (or a section) rendering `MailPanel`.
- Add it to the sidebar/nav (`components/Sidebar.tsx`) and to `App.tsx` view switching, e.g. label
  **"Outbound Mail"**.
- In the existing email-preview modal (`components/Modals.tsx`), when a preview is an email and not
  blocked, add a **"Queue for approval"** button calling `create_email_draft({action_id})`, then
  toast and (optionally) switch to the Outbound Mail view.
- Add the new functions to `frontend/src/services/api.ts` if it enumerates them; otherwise `callApi` is generic.
- Rebuild the bundle per appster Edit Flow (Phase 4B steps; `bundle-artifact.sh` + re-inject
  `<script src="./config.js">`), and clean `node_modules dist bundle.html .parcel-cache`.

## 5. Document
Append the 8 new functions to `backend/document.md`.

## 6. Acceptance
- `python functions.py get_mail_settings '{}'` → `password_set` true after seeding, never a password.
- `python functions.py test_mail_settings '{}'` → `{ok: true}` (a real mail arrives).
- A draft can be created, approved and sent; `get_email_drafts '{"status":"sent"}'` shows it with a message id.
- Frontend bundle rebuilt with the Outbound Mail view present and no direct-URL calls.
