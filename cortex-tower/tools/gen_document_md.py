#!/usr/bin/env python3
"""Append the Arinox-layer section to backend/document.md (idempotent: replaces a previous section).
Run from the repo with the backend's Python:  python3 tools/gen_document_md.py"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(os.path.join(ROOT, "backend"))
import cortex_api

D = {
"kogo_me": ("Who am I? The frontend calls this first.", "(none)", "`{authenticated, registered, email, name, role, is_admin, tower_roles, erp_user, via}`"),
"kogo_register_users": ("KOGO calls this at install / share. Idempotent. Never called by the frontend.", "`users: [{email, name, is_admin, role}]`", "`{ok, count}`"),
"kogo_login": ("Manual login for someone opening the app outside KOGO.", "`email, password`", "`{ok, token, name, role, is_admin}` or `{error}`"),
"kogo_logout": ("End the app session.", "`_app_token`", "`{ok}`"),
"kogo_set_password": ("Set your own password (min 10 characters).", "`new_password`", "`{ok}` or `{error}`"),
"kogo_admin_set_password": ("Administrator sets someone's password.", "`email, new_password`", "`{ok}` or `{error}`"),
"list_tower_users": ("Administrators: users, their tower roles and the roles available.", "(none)", "`{users, all_roles}`"),
"set_tower_user": ("Administrators: set a user's tower roles, ERP user, or active flag.", "`email, roles?, erp_user?, active?`", "`{ok}` or `{error}`"),
"cx_catalog": ("The process sidebar for the caller: only the screens their role may read.", "(none)", "`{ok, nav: [{key,label,items:[{key,label,kind,doctype?,report?}]}], me, write_mode}`"),
"cx_nav_counts": ("Open (draft) counts per document screen, for sidebar badges.", "(none)", "`{ok, counts: {key: n}}`"),
"cx_search": ("Global search across the main ERP documents the caller may read.", "`q`", "`{ok, results: [{doctype, name}]}`"),
"cx_doc_meta": ("Form definition of an ERP doctype (fields, child tables, required, read-only), filtered for the caller's role.", "`doctype`", "`{ok, fields, is_submittable, numbered}`"),
"cx_doc_list": ("A page of an ERP doctype's records with search and status filter.", "`doctype, search?, page?, page_size?, status?, order_by?`", "`{ok, columns, rows, total, page}`"),
"cx_doc_get": ("One ERP document with its child tables and the action buttons that apply to it.", "`doctype, name`", "`{ok, doc, actions, can_write, can_submit, can_cancel}`"),
"cx_link_search": ("Autocomplete for a Link field.", "`doctype, txt`", "`{ok, results: [{value, description}]}`"),
"cx_write": ("THE way a form writes to the ERP: insert | save | submit | cancel | delete. Runs the Arinox rule scripts, enforces roles, locks, approvals and undo. `preview: true` shows what would happen and writes nothing.", "`op, doctype, name?, data?, modified?, preview?, approval_id?, idem_key?`", "`{ok, doc?, preview?, needs_approval?, approval_id?, conflict?, run_id?, undone?, error?}`"),
"cx_run_script": ("Run one of the Arinox buttons (an API script) through the same guarded pipeline.", "`method, params?, doctype?, name?, preview?, approval_id?, idem_key?`", "same as `cx_write`, plus `result`"),
"cx_approvals": ("Pending (or all) approvals with the preview of what each would do.", "`status? = pending | approved | rejected | used | all`", "`{ok, can_decide, approvals}`"),
"cx_decide": ("A manager approves or rejects an approval. Nobody approves their own request.", "`approval_id, decision = approve | reject`", "`{ok, status}`"),
"cx_runs": ("Recent guarded writes (managers see all, others their own).", "`limit?`", "`{ok, runs}`"),
"cx_rollback_run": ("Managers: undo a finished run from its journal; what cannot be undone is listed.", "`run_id`", "`{ok, undone, irreversible, failed}`"),
"sync_changes": ("Poll the ERP for changes made outside the tower and reconcile them. Safe to call often; overlapping calls are skipped.", "(none)", "`{ok, poll, reconcile}`"),
"erp_event": ("Webhook receiver for the ERP. Authenticated by a shared secret; only enqueues.", "`secret, doctype, name, event?, modified?, docstatus?`", "`{ok, queued}`"),
"cx_sync_status": ("Sync health: queue depth, watermarks, open breaches.", "(none)", "`{ok, queue, doctypes, breaches_open, webhook_configured}`"),
"cx_breaches": ("ERP-side changes that break a rule the scripts enforce. Never auto-reverted.", "`state? = open | resolved | dismissed | all`", "`{ok, breaches}`"),
"cx_breach_decide": ("Managers: dismiss a breach, or start a (risky, approval-gated) cancel of the record.", "`breach_id, decision = dismiss | cancel, note?`", "`{ok}`"),
"cx_retry_change": ("Managers: retry a change whose reconcile failed.", "`change_id`", "`{ok}`"),
"tsr_status": ("Administrators: every rule script with runs, failures, average time, and vendor checksum status.", "(none)", "`{ok, rules_off, scripts, vendor}`"),
"tsr_set_script": ("Administrators: switch one rule script on or off.", "`name, enabled`", "`{ok}`"),
"tsr_kill_switch": ("Administrators: turn every RULE script off or on (numbering and the ledger engine stay on).", "`state = off | on | status`", "`{ok, rules_off}`"),
"cx_connection": ("Administrators: is the tower talking to the Arinox ERP? API user, Arinox doctypes present, ERP-side server scripts.", "(none)", "`{ok, base, api_user, arinox_doctypes, server_scripts_on_erp, missing_core_doctypes}`"),
"cx_reports": ("The Script Reports the caller may run.", "(none)", "`{ok, reports}`"),
"cx_report_run": ("Run one of the 17 Script Reports through the Tower Script Runtime. Cached 60 s.", "`name, filters?`", "`{ok, columns, rows, truncated, ms}`"),
"cx_today": ("My queue: approvals, breaches, failed syncs, inquiries waiting, overdue T&A milestones.", "(none)", "`{ok, approvals, breaches, sync_failed, inquiries_waiting, overdue_milestones, erp}`"),
"cx_inquiry_analyse": ("Read a stored mail and all its attachments (PDF, Excel, Word, zip, forwarded mail, images queued for a person), score its completeness and propose next steps.", "`mail_id, refresh?`", "`{ok, classification, fields, completeness, buyer, revision, links, parts, needs_reading, proposals}`"),
"cx_inquiry_queue": ("Mails that look like inquiries, with analysis state.", "(none)", "`{ok, mails}`"),
"cx_inquiry_step": ("Run one proposed step (create customer / Opportunity / Tech Pack) through the guarded pipeline. A later step uses the result of an earlier one.", "`mail_id, step_id, preview?, approval_id?`", "same as `cx_write`"),
"cx_inquiry_draft_reply": ("Store the 'please send us …' reply as a draft in Outbound Mail. Nothing is sent from here.", "`mail_id`", "`{ok, draft_id}`"),
}
MARK = "# Arinox layer (2026-11-06)"
missing = [n for n in cortex_api.FUNCTIONS if n not in D]
if missing:
    sys.exit(f"describe these first: {missing}")
head = ["", "---", "", MARK + " — identity, guarded ERP writes, Tower Script Runtime, sync, inquiries", "",
        "Every function except `kogo_login`, `kogo_register_users` and `erp_event` needs a signed-in caller (KOGO SSO or app login).",
        "A client-supplied `actor` is ignored: the audited actor is always the verified identity. Writes go through one pipeline",
        "(`pipeline.py`): role → mode gate → field guard → preview → approval → lock → optimistic lock → execute (rule scripts + journal)",
        "→ audit → ERP comment → event ledger. See `CORTEX_TOWER_PLAN.md`.", ""]
body = []
for n in cortex_api.FUNCTIONS:
    d, p, r = D[n]
    body += [f"### `{n}`", d, "", f"**Params:** {p}", "", f"**Returns:** {r}", ""]
path = "document.md"
text = open(path).read()
if MARK in text:
    text = text[:text.index(MARK)].rstrip().rstrip("-").rstrip() + "\n"
open(path, "w").write(text + "\n".join(head + body) + "\n")
print(len(cortex_api.FUNCTIONS), "functions documented")
