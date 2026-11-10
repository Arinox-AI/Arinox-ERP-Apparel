"""Cortex Control Tower — proactive monitor (Phase 2: prevention & push).

Runs the live detection engine on a schedule and **pushes** a notification when a
new **critical** appears (or a warning escalates to critical). This is what turns
the Tower from "open it and look" into "it tells you".

Design
------
* **Stateless-safe** — remembers the last-seen risk set in `app_kv`, so a restart
  never re-alerts on the whole backlog. The first ever run seeds a baseline and
  sends a single "monitor armed" summary.
* **Idempotent** — a risk is alerted once; it re-alerts only if it disappeared and
  came back, or escalated warning→critical.
* **Throttled** — `maybe_run` is a cheap, best-effort call the dashboard can make
  (won't fire more than once per cooldown window and never blocks).
* **Best-effort notify** — reuses the existing SMTP transport; a failure to email
  is recorded, never raised.
* **Read-only on the ERP** — it only reads; it never writes to the ERP.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import mailer
import rulebook

_ALERT_KEY = "monitor_alerted"       # {"RISK_KEY": "severity", ...}
_LAST_KEY = "monitor_last_run"       # ISO timestamp
_ARMED_KEY = "monitor_armed"         # "1" once the baseline is seeded
_EMAIL_KEY = "monitor_alert_email"   # optional override recipient
_COOLDOWN_MIN = 25


# ── tiny KV helpers ─────────────────────────────────────────────────────────
def _kv_get(db, key, default=None):
    from models import KVModel
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        return row.value if row else default
    except Exception:
        return default


def _kv_set(db, key, value):
    from models import KVModel
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        if row:
            row.value = value
        else:
            db.add(KVModel(key=key, value=value))
        db.commit()
    except Exception:
        db.rollback()


def _settings(db):
    """The saved SMTP settings row (or {}). Reuses the P1 email connector."""
    try:
        from models import MailSettingsModel
        row = db.query(MailSettingsModel).order_by(MailSettingsModel.id.asc()).first()
        if not row:
            return {}
        d = row.to_dict()
        import secret_store as _secrets
        d["password"] = _secrets.dec(row.password)
        return d
    except Exception:
        return {}


def _recipient(db, settings):
    return (_kv_get(db, _EMAIL_KEY) or settings.get("email_account") or "").strip()


# ── diffing ─────────────────────────────────────────────────────────────────
def _diff(risks, alerted):
    """Return (new_criticals, escalated) risk dicts."""
    new, escalated = [], []
    for r in risks:
        key = r.get("key") or r.get("risk_key")
        sev = r.get("severity")
        prev = alerted.get(key)
        if sev == "critical" and prev != "critical":
            (new if prev is None else escalated).append(r)
    return new, escalated


# ── notification ────────────────────────────────────────────────────────────
def _html(rows, summary, armed=False):
    rail = {"critical": "#dc2626", "warning": "#f59e0b", "info": "#2563eb"}
    items = []
    for r in rows[:20]:
        sev = r.get("severity", "warning")
        items.append(
            f'<tr><td style="padding:12px 16px;border-bottom:1px solid #eef2f7;border-left:4px solid {rail.get(sev,"#f59e0b")};">'
            f'<div style="font-size:11px;font-weight:800;letter-spacing:.4px;text-transform:uppercase;color:{rail.get(sev)};">{sev}</div>'
            f'<div style="font-size:14px;font-weight:600;color:#0f2a4a;margin-top:2px;">{r.get("title","")}</div>'
            f'<div style="font-size:12px;color:#64748b;margin-top:3px;">{r.get("risk_key","")}</div>'
            f'</td></tr>')
    more = f'<tr><td style="padding:10px 16px;font-size:12px;color:#64748b;">+ {len(rows)-20} more…</td></tr>' if len(rows) > 20 else ""
    headline = ("Monitor armed — current critical baseline" if armed
                else f"{len(rows)} new critical item{'s' if len(rows) != 1 else ''}")
    return f"""<div style="background:#eef2f7;padding:24px 12px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #dbe3ec;border-radius:14px;overflow:hidden;width:100%;">
<tr><td style="background:#0f2a4a;padding:18px 20px;color:#fff;font-size:16px;font-weight:700;">Cortex Control Tower — alert</td></tr>
<tr><td style="padding:16px 20px 4px;">
<div style="font-size:18px;font-weight:800;color:#0f2a4a;">{headline}</div>
<div style="font-size:13px;color:#64748b;margin-top:4px;">{summary.get('critical',0)} critical · {summary.get('warning',0)} warning · {summary.get('total',0)} total live risks</div>
</td></tr>
<tr><td><table style="width:100%;border-collapse:collapse;">{''.join(items)}{more}</table></td></tr>
<tr><td style="padding:14px 20px;font-size:12px;color:#94a3b8;">Live from KOGO ERP · open the Cortex Control Tower for full detail and AI next steps.</td></tr>
</table></div>"""


def _text(rows, summary, armed=False):
    head = ("Monitor armed — current critical baseline" if armed
            else f"{len(rows)} new critical item(s)")
    lines = [head,
             f"{summary.get('critical',0)} critical / {summary.get('warning',0)} warning / {summary.get('total',0)} total",
             ""]
    for r in rows[:20]:
        lines.append(f"- [{r.get('severity')}] {r.get('title')}")
    if len(rows) > 20:
        lines.append(f"… +{len(rows)-20} more")
    return "\n".join(lines)


def _notify(db, rows, summary, armed=False):
    # GUARDRAIL: automatic alert emails are OFF unless the operator explicitly
    # enables them (app_kv key `email_auto_notify` = "1"). Default = no send.
    if str(_kv_get(db, "email_auto_notify", "0")) != "1":
        return {"ok": False, "error": "auto_notify_disabled"}
    s = _settings(db)
    to = _recipient(db, s)
    if not (s.get("email_account") and s.get("password")) or not to:
        return {"ok": False, "error": "notify_not_configured"}
    n = len(rows)
    subject = ("Cortex Tower — monitor armed (critical baseline)" if armed
               else f"Cortex Tower — {n} new critical alert{'s' if n != 1 else ''}")
    return mailer.send_via_smtp(
        {"smtp_host": s.get("smtp_host"), "smtp_port": s.get("smtp_port"),
         "use_tls": s.get("use_tls", 1), "email_account": s["email_account"], "password": s["password"]},
        to_email=to, subject=subject, body=_text(rows, summary, armed),
        html=_html(rows, summary, armed), from_name=s.get("from_name") or "Cortex Control Tower",
    )


# ── public entrypoints ──────────────────────────────────────────────────────
def run(db, notify: bool = True, force: bool = False) -> dict:
    """Scan live risks and push an alert for new/escalated criticals."""
    risks = rulebook.build_risks()
    summary = rulebook.summarize(risks)
    current = {(r.get("key") or r.get("risk_key")): r.get("severity") for r in risks}
    try:
        alerted = json.loads(_kv_get(db, _ALERT_KEY, "{}") or "{}")
    except Exception:
        alerted = {}
    armed_before = _kv_get(db, _ARMED_KEY) == "1"

    new, escalated = _diff(risks, alerted)
    changed = new + escalated

    sent = {"ok": False, "error": "no_change"}
    if notify:
        if not armed_before:
            # First ever run — seed the baseline and send ONE "armed" summary.
            sent = _notify(db, [r for r in risks if r.get("severity") == "critical"], summary, armed=True)
            _kv_set(db, _ARMED_KEY, "1")
        elif changed or force:
            sent = _notify(db, changed, summary, armed=False)

    # persist the new baseline (all risks, so we can detect returns/escalations)
    _kv_set(db, _ALERT_KEY, json.dumps(current))
    _kv_set(db, _LAST_KEY, datetime.utcnow().isoformat())

    try:
        from models import AuditLogModel
        db.add(AuditLogModel(action_type="monitor", action_name="run_monitor",
                             description=(f"critical {summary.get('critical',0)} · new {len(new)} · "
                                          f"escalated {len(escalated)} · notify={sent.get('ok')}")))
        db.commit()
    except Exception:
        db.rollback()

    return {"scanned": len(risks), "summary": summary,
            "new_criticals": len(new), "escalated": len(escalated),
            "notified": bool(sent.get("ok")), "notify_error": sent.get("error"),
            "armed": bool(armed_before or sent.get("ok")),
            "generated_at": datetime.utcnow().isoformat()}


def is_due(db, cooldown_min: int = _COOLDOWN_MIN) -> bool:
    last = _kv_get(db, _LAST_KEY)
    if not last:
        return True
    try:
        return datetime.utcnow() - datetime.fromisoformat(last) > timedelta(minutes=cooldown_min)
    except Exception:
        return True


def maybe_run(db, cooldown_min: int = _COOLDOWN_MIN) -> dict:
    """Best-effort, throttled run for the dashboard. Never raises, never blocks long."""
    try:
        if not is_due(db, cooldown_min):
            return {"skipped": "cooldown"}
        # GUARDRAIL: the dashboard never triggers an automatic email.
        return run(db, notify=False)
    except Exception as e:
        return {"skipped": "error", "error": str(e)[:200]}
