# ERP modules (built as data, not as a Frappe app)

One folder per custom module built inside the hosted Arinox ERP: DocTypes, Custom Fields, Server Scripts, Client Scripts, Reports, Print Formats and Workspaces, stored as an importable bundle. This folder is the **source of truth**. A record that is live but not here does not count as done.

The full process (intake → sign-off → test → git → go-live → Tower registration → rollback) is in
`skills/arinox-erp-tower/references/10-build-an-erp-module.md`. Copy-paste chat prompts are in `11-chat-prompts.md`.

```
erp-modules/<slug>/
  SPEC.md  CHANGELOG.md  TEST_LOG.md  rollback.json
  bundle/index.json + 01_module_def.json … (same format as arinox-apparel/hosted_bundle/)
  scripts/<server_script_name>.py
```

Apply a bundle (idempotent):

```
ARINOX_API_TOKEN="$(cat ~/.arinox_hosted_token)" \
python3 arinox-apparel/arinox_apparel/arinox_apparel/portable/api_load.py erp-modules/<slug>/bundle <site-url> [--only=group,…] [--dry-run]
```

Rules: prefix everything with the slug · server scripts load disabled and are enabled one by one · never edit an Arinox Apparel record from a module · no secrets or real commercial figures in git.

| Module | Slug | Status | Live since |
|---|---|---|---|
| — | — | — | — |
