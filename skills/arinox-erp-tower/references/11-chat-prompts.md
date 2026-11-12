# 11 Copy-paste prompts (agent chat)

Each prompt is written for the agent named in the heading. Replace `<…>` and paste it. These prompts are for building or changing **modules**. For day-to-day order work, use the runbooks in `07-runbooks.md`.

---

## A. ERP agent — discovery (turn 1)

```
Read-only. I want a new capability in the ERP: <one paragraph: who does what, on which documents, what is calculated/tracked>.
1. List existing ERPNext and Arinox Apparel doctypes, custom fields and reports that already cover any part of this (name + one line).
2. List the questions you still need answered (max 7), using the module-brief checklist: workflow, records, links, rules, outputs, roles, volume/history.
Do not create or change anything.
```

## B. ERP agent — plan for sign-off (turn 2)

```
Draft the module plan using the arinox-erp-tower skill, references/10 §2 and assets/module-spec-template.md.
Module: <Name>, slug: <slug>. Prefix every record it creates with the slug.
Show: doctypes with field tables, custom fields on existing doctypes, server scripts (name · type · trigger · does · throws),
client scripts, reports, print formats, workspace, roles/permissions, test plan, rollback list.
Do not create anything. End with: "Approve this plan?"
```

## C. ERP agent — build and test (turn 3, after "approved")

```
Plan approved by <person> on <date>. Build module <slug> in this order: module_def, roles, doctypes, custom_fields,
property_setters, seeds, server_scripts (create ALL disabled), client_scripts, reports, print_formats, workspace.
Then create test rows named ZZTEST-<slug>-… , enable server scripts ONE AT A TIME, and run each test-plan row.
Reply with a table: rule · input · expected · actual · pass/fail. Leave any failing script disabled and tell me why it failed.
Do not touch any existing Arinox Apparel record or any non-test transaction.
```

## D. ERP agent — export to git (turn 4)

```
Export everything you created for module <slug> as the bundle in references/10 §4:
bundle/index.json and one JSON file per group (full records, fields=["*"], strip creation/modified/owner),
scripts/<name>.py for each server script, SPEC.md (the approved plan), TEST_LOG.md (the results table), rollback.json (reverse creation order).
One fenced code block per file, headed with its path under erp-modules/<slug>/.
```

## E. Coding agent (Claude Code) — commit and push

```
Save the files from the ERP agent's export under erp-modules/<slug>/ (paste below). Validate the bundle with
api_load.py --dry-run against hosted.localhost:8001 if it is up. Then add ONLY erp-modules/<slug> and commit
"feat(<slug>): <summary>" on branch apparel-app (or module/<slug>) and push. Do not add any other file.
<paste>
```

## F. ERP agent — go live (turn 5)

```
Go-live for <slug> approved by <person>. Delete the ZZTEST-<slug>- rows. Confirm all <n> server scripts are enabled and
report the final counts per group. Give me the CHANGELOG line and a one-screen "how to use it" note for users.
```

## G. Cortex Tower chat — register the module (turn 6)

```
Register this ERP module. Its server scripts run in the ERP (scripts_run_on: erp). Do not vendor or execute them in the TSR.
Map the doctypes to the role groups given, class "ledger": true doctypes' submit as risky, and show them in tsr_status.
Then run tsr_status and confirm erp_scripts_mode is "native".
<paste the registration JSON from references/10 §6>
```

## H. Any agent — change an existing module

```
Change to module <slug>: <what>. Read erp-modules/<slug>/SPEC.md and CHANGELOG.md first. Propose the diff
(which records, which fields/script lines) and the test rows. Do not change anything until I approve.
After approval: change git first, test on the test ERP (or ZZTEST rows), apply only the changed group live, append CHANGELOG, push.
```

## I. Any agent — emergency stop

```
Disable every Server Script whose name starts with <slug>_ (set disabled=1). Change nothing else. List what you disabled.
```

## J. ERP agent — create the native-mode probe (one time, before the Tower change goes live)

```
Create one Server Script, nothing else: name arinox_ping, script_type API, api_method arinox_ping, allow_guest 0, enabled.
Body (read-only):
frappe.response["message"] = {"native": True, "scripts": frappe.db.count("Server Script", {"disabled": 0}), "version": "2026-11-12"}
Then call /api/method/arinox_ping and show me the response. (The same record is in git at erp-modules/_platform/bundle/; it can also be loaded with api_load.py.)
```
