# Proactive monitor + push alerts (Phase 2)

`backend/monitor.py` runs the live detection engine and **pushes** an alert when a
**new critical** appears (or a warning escalates to critical). This is what turns
the Tower from "open it and look" into "it tells you".

## How it works

```
scheduler ─► monitor.run(db)
                 │
   rulebook.build_risks()  (live ERP, read-only)
                 │
   diff vs last-seen set (app_kv: monitor_alerted)
                 │
        ┌────────┴─────────┐
   new/escalated         nothing new
        │                    │
   email alert          stay silent
   (existing SMTP)
        │
   persist new baseline + audit log
```

* **Baseline, not backlog** — the first ever run seeds the current state and sends
  one "monitor armed" summary. After that it alerts **only on change**, so it never
  re-spams the same 15 criticals.
* **Detects** new criticals, warning→critical escalations, and (baseline-tracked)
  returns of previously-seen risks.
* **Throttled** — `maybe_run(db)` is a cheap, best-effort call the dashboard makes;
  it won't fire more than once per cooldown (25 min) and never blocks.
* **Best-effort notify** — reuses the existing SMTP transport (`mailer.py`); a send
  failure is recorded, never raised. Recipient defaults to the configured account,
  overridable with `app_kv["monitor_alert_email"]`.
* **Read-only on the ERP** — it never writes to the ERP.

## Entrypoints
- `monitor.run(db, notify=True, force=False)` → scan + alert; returns counts.
- `monitor.maybe_run(db, cooldown_min=25)` → throttled (used by `get_dashboard`).
- `monitor.is_due(db, cooldown_min)` → cooldown check.
- Backend function `run_monitor(db, notify=1, force=0)` — registered in `FUNCTIONS`.

## Scheduling
A KOGO **agent heartbeat** ("Cortex Tower — live monitor", category *Operations*,
every **25 minutes**) runs the monitor out-of-band. Combined with the dashboard's
throttled `maybe_run`, alerts fire whether or not anyone opens the Tower.

## State
`app_kv` keys: `monitor_alerted` (last-seen risk→severity), `monitor_last_run`,
`monitor_armed`, `monitor_alert_email` (optional).
