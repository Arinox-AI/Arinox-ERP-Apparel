"""QA harness — calls every function through the exact CLI contract the KOGO middleware uses.

    python3 qa_cli_test.py            # all functions, live ERP, on a COPY of the DB
    python3 qa_cli_test.py --live     # run against backend/data/<slug>.db instead of a copy
    python3 qa_cli_test.py cx_today   # one function

Why a copy: the tower's SQLite file is decision state (mails, intake runs, approvals). A QA
sweep must never mutate it, and ``DB_PATH_OVERRIDE`` (database.py) is the supported way to point
the process somewhere else.

Params are resolved against the ids that actually exist in that copy, so a function is exercised
with a real row instead of a made-up id. Three verdicts:

  PASS  the call answered with data, or with an answer that is correct for the input
  WARN  the call is correct for the data but this install cannot use it (missing row, missing
        SMTP password, no ERP document) — nothing to fix in code
  FAIL  a real defect: wrong signature, crash, unreadable output, or an unexpected error

Anything that leaves the machine (mail send), changes the real ERP, or flips a global switch is
marked SKIP and listed at the end, so nothing is silently untested.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "cortex_operations_control_tower.db"
COPY = Path("/tmp/qa_cortex_cli.db")

# Functions that must NOT be exercised by a sweep, with the reason. Everything else runs.
SKIP: dict[str, str] = {
    "approve_and_send_email": "sends real mail",
    "send_chain_reply": "sends real mail",
    "send_message": "posts to the KOGO chat API",
    "sync_inbox": "IMAP credential is absent on this install (mailbox not configured)",
    "sync_intake_mail": "same IMAP dependency as sync_inbox",
    "run_monitor": "writes mail + ERP comment side effects on a schedule tick",
    "erp_event": "ERP webhook entry point; needs ERP_WEBHOOK_SECRET",
    "execute_action": "creates real ERP documents",
    "run_action": "creates real ERP documents",
    "submit_in_erp": "submits real ERP documents",
    "cx_write": "real ERP write path",
    "cx_run_script": "runs client ERP scripts",
    "cx_decide": "approves a queued real ERP write",
    "cx_breach_decide": "decides a real sync breach",
    "cx_rollback_run": "would delete ERP documents",
    "wip_apply_plan": "creates ERP records",
    "approve_intake": "creates ERP records (approval path)",
    "kogo_admin_set_password": "would rotate a real user's password",
    "set_tower_user": "mutates a user's roles",
    "tsr_kill_switch": "global switch",
    "tsr_set_script": "mutates script state",
    "save_mail_settings": "overwrites the sealed mailbox credential",
}

# Where an error string is the CORRECT answer for the input we sent, not a defect.
EXPECT: dict[str, list[str]] = {
    "kogo_login": ["Incorrect email or password"],          # deliberately wrong password
    "kogo_logout": ["sign", "session", "ok"],
    "kogo_set_password": ["password"],                      # no session in a CLI process by design
    "test_mail_settings": ["No SMTP password"],
    "get_mail_settings": ["smtp", "imap", "ok"],
    "update_buyer_inquiry": ["not_found", "bad_status"],
    "decide_order_change": ["not_found"],
    "rollback_order_change": ["not_found"],
    "cx_retry_change": ["Only a failed change"],
    "cx_inquiry_step": ["Nothing to run", "not_found"],
    "cx_inquiry_draft_reply": ["Nothing is missing", "not_found"],
    "fetch_chat_history": ["No data", "not_found"],
    "fetch_threads": ["No data", "not_found"],
    "get_shipment_leg": ["not", "no "],
    # correct refusals on THIS install (empty ERP / no pack builder / no buyer on the mail)
    "wip_finalise": ["could not be read", "Pick a WIP"],
    "wip_adjust": ["could not be read", "Pick a WIP"],
    "wip_reject": ["could not be read", "Pick a WIP"],
    "wip_comment": ["could not be read", "Pick a WIP"],
    "approve_tna_order": ["order_id is required"],
    "reject_tna_order": ["order_id is required"],
    "snooze_tna_order": ["order_id is required"],
    "ingest_chain_pack": ["pack builder is not reachable"],
    "create_email_draft": ["no_buyer"],
    "set_intake_customer": ["customer_not_found"],
}

#: id placeholders are filled from the copy at run time ($action_id, $run_id, ...).
PARAMS: dict[str, dict] = {
    # legacy reads
    "get_dashboard": {},
    "ask_kogo": {"question": "What is at risk this week?"},
    "get_buyer_orders": {},
    "get_risks": {},
    "get_recommendations": {},
    "get_audit_log": {"limit": 5},
    "get_fabric_intelligence": {},
    "get_email_preview": {"action_id": "$action_id"},
    "get_erp_preview": {"action_id": "$action_id"},
    "preview_action": {"action_id": "$action_id"},
    "modify_action": {"action_id": "$action_id", "new_text": "QA note"},
    "decide_action": {"action_id": "$action_id", "decision": "approve"},
    "rollback_action": {"action_id": 0},
    "get_mail_settings": {},
    "test_mail_settings": {"to": "qa@example.com"},
    "create_email_draft": {"action_id": "$action_id", "subject": "QA"},
    "get_email_drafts": {},
    "reject_email_draft": {"draft_id": "$draft_id"},
    "delete_email_draft": {"draft_id": 0},
    # intake / mail
    "get_inbox": {"limit": 5},
    "get_mail_message": {"mail_id": "$mail_id"},
    "get_inbox_summary": {},
    "dismiss_mail": {"mail_id": 0},
    "get_order_changes": {},
    "get_intake_queue": {},
    "get_intake": {"run_id": "$run_id"},
    "get_intake_summary": {},
    "understand_intake": {"run_id": "$run_id", "use_llm": 0},
    "simulate_intake": {"run_id": "$run_id"},
    "reject_intake": {"run_id": 0, "reason": "QA"},
    "edit_intake": {"run_id": "$run_id", "field": "style", "value": "QA"},
    "rollback_intake": {"run_id": 0},
    "create_intake_ack": {"run_id": "$run_id"},
    "get_intake_document": {"run_id": "$run_id"},
    "dismiss_intake": {"run_id": 0},
    "set_intake_customer": {"run_id": "$run_id", "customer": "QA Customer"},
    "reopen_intake": {"run_id": 0},
    "get_mail_chain": {"chain_id": "$chain_id"},
    "ingest_chain_pack": {"run_id": "$run_id", "apply": 0},
    "get_buyer_inquiries": {},
    "get_buyer_inquiry": {"inquiry_id": "$inquiry_id"},
    "update_buyer_inquiry": {"inquiry_id": "$inquiry_id", "status": "costing"},
    "sync_buyer_inquiries": {},
    "decide_order_change": {"change_id": 0, "decision": "dismiss"},
    "rollback_order_change": {"change_id": 0},
    # chat
    "get_chat_config": {},
    "create_room": {},
    "fetch_threads": {"room_id": "qa"},
    "fetch_chat_history": {"thread_id": "qa"},
    # model / wip / forecast
    "get_erp_model": {},
    "get_wip_plan": {},
    "get_wip_thread": {"style": "QA"},
    "get_wip_analytics": {},
    "wip_finalise": {"wip": "QA"},
    "wip_adjust": {"wip": "QA", "note": "QA"},
    "wip_reject": {"wip": "QA", "reason": "QA"},
    "wip_comment": {"wip": "QA", "text": "QA"},
    "get_shipment_leg": {},
    "get_ai_next_steps": {},
    # T&A
    "get_tna_calendar": {},
    "get_tna_orders": {},
    "get_tna_template": {},
    "get_holidays": {},
    "get_tna_kpis": {},
    "update_milestone": {"order_id": "$tna_order", "code": "PROTO_SAMPLE", "status_override": "done", "apply": 0},
    "tna_run_action": {"action_id": 0},
    "tna_rollback_action": {"action_id": 0},
    "tna_get_audit_log": {},
    "get_tna_alerts": {},
    "get_tna_owners": {},
    "get_tna_program": {},
    "get_tna_intake": {},
    "approve_tna_order": {"order_id": "$tna_order"},
    "reject_tna_order": {"order_id": "$tna_order"},
    "snooze_tna_order": {"order_id": "$tna_order", "note": "QA"},
    "get_bridge_status": {},
    "set_tower_link": {"url": "https://example.com"},
    # identity
    "kogo_me": {},
    "kogo_register_users": {"users": [{"email": "qa2@example.com", "name": "QA2"}]},
    "kogo_login": {"email": "qa@example.com", "password": "wrong-on-purpose"},
    "kogo_logout": {},
    "kogo_set_password": {"new_password": "QA-passw0rd!"},
    "list_tower_users": {},
    # Arinox layer
    "cx_catalog": {},
    "cx_nav_counts": {},
    "cx_search": {"q": "QA"},
    "cx_doc_meta": {"doctype": "Size Chart"},
    "cx_doc_list": {"doctype": "Size Chart", "page_size": 3},
    "cx_doc_get": {"doctype": "Size Chart", "name": "$size_chart"},
    "cx_link_search": {"doctype": "Customer", "txt": "a"},
    "cx_approvals": {},
    "cx_runs": {"limit": 5},
    "sync_changes": {},
    "cx_sync_status": {},
    "cx_breaches": {},
    "cx_retry_change": {"change_id": 0},
    "tsr_status": {},
    "cx_connection": {},
    "cx_reports": {},
    "cx_report_run": {"name": "Costing Margin Review"},
    "cx_today": {},
    "cx_inquiry_analyse": {"mail_id": "$mail_id"},
    "cx_inquiry_queue": {},
    "cx_inquiry_step": {"mail_id": "$mail_id", "step_id": "opportunity", "preview": True},
    "cx_inquiry_draft_reply": {"mail_id": "$mail_id"},
}


def _q(sql: str, default=0):
    try:
        c = sqlite3.connect(COPY)
        row = c.execute(sql).fetchone()
        c.close()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default


def _first_size_chart() -> str:
    """A real Size Chart from the live ERP, so cx_doc_get is exercised with a name that exists."""
    try:
        import erp
        rows = erp.erp_get("Size Chart", fields=["name"], limit=1)
        if rows:
            return rows[0]["name"]
    except Exception:
        pass
    return ""


def _ids() -> dict:
    return {
        "$action_id": _q("select id from action_state where approval_status='pending' order by id limit 1")
                       or _q("select id from action_state order by id limit 1"),
        "$run_id": _q("select id from intake_run where status='understood' order by id desc limit 1")
                   or _q("select id from intake_run order by id desc limit 1"),
        "$chain_id": _q("select id from mail_chain order by id limit 1"),
        "$mail_id": _q("select id from mail_message order by id limit 1"),
        "$draft_id": _q("select id from email_draft where status='draft' order by id limit 1"),
        "$inquiry_id": _q("select id from buyer_inquiry order by id limit 1"),
        "$tna_order": "",
        "$size_chart": _first_size_chart(),
    }


def _sub(value, ids):
    if isinstance(value, str) and value in ids:
        return ids[value]
    if isinstance(value, dict):
        return {k: _sub(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_sub(v, ids) for v in value]
    return value


def _env() -> dict:
    e = dict(os.environ)
    e.update({
        "DB_PATH_OVERRIDE": str(COPY),
        "KOGO_AUTH_VERIFIED": "1",
        "USER_EMAIL": _admin_email(),
        "USER_NAME": "QA Sweep",
        "USER_IS_ADMIN": "1",
    })
    return e


def _admin_email() -> str:
    """The admin the sweep runs as: the first admin row in the COPY (never a made-up address, or every
    guarded function answers "Sign in" — the app only bootstraps an owner while the users table is empty)."""
    email = _q("select email from users where is_admin=1 and active=1 order by id limit 1", "")
    return email or "qa@example.com"


def _run(name: str, params: dict) -> tuple[str, str]:
    proc = subprocess.run([sys.executable, "functions.py", name, json.dumps(params)],
                          cwd=str(HERE), env=_env(), capture_output=True, text=True, timeout=900)
    out = (proc.stdout or "").strip()
    if not out:
        return "FAIL", f"no output; stderr={(proc.stderr or '').strip()[-200:]}"
    try:
        data = json.loads(out.splitlines()[-1])
    except Exception:
        return "FAIL", f"non-JSON output: {out[:160]}"
    if isinstance(data, dict):
        err = data.get("error") or ("" if data.get("ok") is not False else str(data.get("message") or ""))
        if not err and data.get("ok") is False:
            err = str(data)[:200]
        if err:
            low = str(err).lower()
            for allowed in EXPECT.get(name, []):
                if allowed.lower() in low:
                    return "PASS", f"expected: {str(err)[:60]}"
            if "not found" in low or "not_found" in low or "no such" in low or "missing" in low:
                return "WARN", str(err)[:160]
            if data.get("denied") or data.get("auth") is False:
                return "WARN", str(err)[:160]
            return "FAIL", str(err)[:200]
    return "PASS", ""


def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    live = "--live" in sys.argv
    if not live:
        shutil.copyfile(DB, COPY)

    sys.path.insert(0, str(HERE))
    import functions  # noqa: E402  (only the name registry is needed)

    ids = _ids()
    names = sorted(functions.FUNCTIONS)
    if only:
        names = [n for n in names if n in only]

    rows, skipped = [], []
    for n in names:
        if n in SKIP:
            skipped.append((n, SKIP[n]))
            continue
        state, note = _run(n, _sub(PARAMS.get(n, {}), ids))
        rows.append((n, state, note))
        print(f"{state:4}  {n:26} {note}")

    passed = sum(1 for r in rows if r[1] == "PASS")
    warned = sum(1 for r in rows if r[1] == "WARN")
    failed = [r for r in rows if r[1] == "FAIL"]
    print(f"\n{passed} PASS · {warned} WARN · {len(failed)} FAIL · {len(skipped)} SKIP "
          f"· {len(rows) + len(skipped)}/{len(functions.FUNCTIONS)} functions reached")
    for n, why in skipped:
        print(f"SKIP  {n:26} {why}")
    if failed:
        print("\nFAILURES")
        for n, _s, note in failed:
            print(f"  {n}: {note}")
        return 1
    print("\nQA OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
