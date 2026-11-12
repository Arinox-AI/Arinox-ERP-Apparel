# 08 Known gaps and gotchas

Status as of the 2026-11-09 handoff (`HANDOFF_ORDER_TO_SHIP.md`, `ORDER_TO_SHIP_STATUS.md`). Check the dated handoff files before relying on any "built" claim older than a few days.

## What was verified, and where

Everything in the order flow was tested on the **test ERP (`hosted.localhost:8001`) only**. The live KOGO ERP was never written to by the order-to-ship build. Hosted tests: 261 pass (`hosted_tests.sh`). Tower tests are plain scripts; a few fail only because the machine has no live ERP (`test_chain`, `test_wip_edges`, `test_wip_plan`, `test_register_replay`, `test_mail_documents`, and 3 AI-door assertions in `test_deals` that need the signed-in KOGO session).

## Not built

- **The agent layer (A0-A6)**: no `backend/agent/` exists. No signals/proposals/playbooks, no `agent_tick`, no autonomy matrix, no learning of lead times. Today you are the agent, supervised by humans. `AGENT_ARCHITECTURE.md` is the design.
- **No scheduler**: KOGO has none (answered by the user, 2026-11-09). The heartbeat is page open, a 60 s timer in an open tab, ERP webhook, "Sync now", chat. Never imply you run unattended.
- **Team Tasks** (assigning work to people as KOGO tasks) need a workspace (`SWARM_ID`). Without one there is no such function; fall back to a drafted message.
- T&A **re-plan after a PCD/ex-factory/template change**: the diff exists internally (`scheduler.moves`) but there is no function or UI; **re-lock (baseline v2)** has no function; the forecast is not mirrored into `Order TNA.status`.
- Payments are not a Tower function (made in the ERP).
- Chatbot-made proposals; resumable long jobs (`cx_job` table exists, no runner); attachment upload/download; per-field `permlevel` beyond hide/show.
- ERP-side webhooks, regenerated Client Scripts ("Open in Cortex Tower" buttons) and a permission profile: not installed; each writes to the client ERP and needs the owner's approval.

## Built but not verified

- Trim requisition and trim inspection: unit tested only, never run live.
- Multi-style orders: found and fixed in S11 (packing list tied to its own style's order line). Other scripts that match order lines by colour and size only (delivery_*, invoicing, ledger rebuild read `so_detail`, so they are right once the packing list is right) were not audited one by one.
- Carton generation measured on tiny orders; a 2,000-carton order (20 s job pattern) is untested.
- The two-company invoice route (factory leg, then trading leg) was not run end to end.
- AQL accept/reject numbers are confirmed only for sample size codes K, L, M.
- `cx_connection` against the real ERP, webhook intake, poller/reconciler and breach detection: unit tests on a fake ERP only.
- Frontend look at 1440/390 px was checked in S11 with a harness that lives outside the repo.

## Traps

1. **REST cannot `db_set` on submitted documents** unless the field is `allow_on_submit`. Hence the Property Setters (06). A fresh site without them fails on the first status write.
2. **Duplicate rules on the test site.** `hosted.localhost` has both the ERP Server Scripts and the Tower's rules, so ledger/stock submits run twice (second run fails or double posts). For a live run on that site, disable the `After Submit` scripts of the document you submit (Fabric/Trim Inspection, Lay Report, Line Input, Daily Line Report, Subcontract Challan/Return, Finishing Receipt, Line QC Report, Packing List, Final Inspection, Delivery Note), then re-enable (`hosted_sync.sh server_scripts` re-enables all). A site without the scripts (the real target) does not have this.
3. **Default `draft` mode blocks risky ops entirely**; for real use `ERP_WRITE_MODE=all`.
4. **Numbered doctypes** (names built by `arinox_name`) cannot be created from the ERP desk without server scripts; create them through the Tower.
5. **Amendments**: Sales Order `-1` is the same order; `order_get` follows the chain. Do not treat it as a new order.
6. **Template offsets under 7-day weeks (D5)**: the T&A template was written for a six-day week; with every day working, cut-to-ship is one day in seven shorter. A late-as-possible PCD from the suggester once produced a plan the lock refused ("Ship is forecast 11 working days after ex-factory"). Open decision: rescale (× 7/6) or let learned offsets correct. If a lock is refused, report the working-day shortfall and the options.
7. **Planning efficiency default is 65 %**; the one style measured ran near 47 % of target on median days. Do not present a 65 % plan as reliable without saying so.
8. **Shipment can be submitted in the ERP while its delivery note is still a draft** (the wizard orders steps; a desk user can skip them).
9. **Rollback cannot delete a Shipment already linked to a Packing List** (ERP 417).
10. **The preview modal of a risky action did not say "needs approval" up front** (only on Confirm). Say it yourself.
11. **Two tests currently fail without a configured ERP URL** (`test_register_replay`, `test_mail_documents`); not caused by recent changes.
12. **Legacy T&A overlay** (`tna_app/`, own SQLite) still runs beside the ERP's `Order TNA`; the ERP is the single source of truth for new work. Do not write both.
13. **Hosted Server Script limits** (06) are the reason some ERPNext features are absent; do not propose a Python controller, an `import`, or a bench command for the hosted site.
14. **Frappe has no trash.** A deletion is permanent. Live-site probes in the past created and deleted a ToDo and a disabled Server Script; do not repeat probes on the live site.

## Open decisions (ask the user, do not decide)

1. Template offsets under 7-day weeks: rescale or learn.
2. Planning efficiency source: keep 65 %, or a per-product default in Apparel Settings.
3. Genericity clean-up (A1) not finished: company-derived values remain in some seeds (`LEARNING_CURVE` percentages, two exported Apparel Settings rows with SAMs), some real-order fixtures (anonymised style/colour/buyer/PO but real quantities and dates), and buyer-like strings in several modules and tests. **The repo is public. Do not commit or publish any file containing real buyer, factory, company, PO or customs numbers, or bank details.** Real data belongs only in git-ignored `cortex-tower/backend/data/`.
4. Retiring the legacy T&A calendar.
5. When to build the agent layer.
6. When to roll the doctype, settings, seeds, Property Setters and four scripts into the KOGO loader bundle (`v2`).
7. Allocated = ordered tolerance; material-ready input to the suggester; finish-pack days from template or medians; SAM averages per Product Type; a garment-type notion on lines.

## Secrets and data you must never copy

- API key/secret live only in `~/.arinox_hosted_token` (chmod 600), `sas_creds.json` and `secret_key.bin` under `cortex-tower/backend/data/` (git-ignored). Never print them, commit them, or put them in a function argument.
- The reference documents zip (`Arinox AI ERP Documents - 2.zip`, 322 MB, untracked) holds real orders and bank details. Read `arinox-apparel/reference/DOCUMENT_INDEX.md` instead of opening it; never copy account numbers into specs, seeds or tests.
- `COVERAGE_S84_S14.md` and `portable/demo/` were held back from the public repo on purpose.


## Added 2026-11-12 (native Server Scripts)

- **Double execution.** The ERP runs scripts natively now. A Tower still in TSR mode runs them a second time. Symptoms: a naming series jumps by 2, duplicate Production Ledger rows, the same throw shown twice. Fix: set the Tower to `erp_scripts_mode: native` (Tower prompt 2026-11-12). Until that is deployed, treat Tower writes as unsafe.
- **Live edits drift from git.** The ERP agent can edit a Server Script live. The Tower's vendored copy and `hosted_bundle/17_server_scripts.json` then disagree. Copy every live edit back to git the same day, and re-vendor (`tools/vendor_scripts.py`).
- **No Script Reports, no .py, no hooks.** Custom modules use Report Builder or Query Reports (select-only SQL) and Server Scripts. A Desk page is replaced by a Tower screen or a Workspace.
