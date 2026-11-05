# Handoff — Arinox Apparel

> **Update 2026-11-05 (hosted limits):** the hosted site takes only DocTypes, data and Server Scripts. Read `doctypes/HOSTED_CONSTRAINTS.md` first: about 93 doctypes and all prints, reports (SQL), decks and cards import as data; about 9,000 lines of controller and hook code (103 files) must be rewritten as Server Scripts before the hosted site can run Phases A to E, and the two Page screens cannot exist there. Eight Server Scripts already exist and are tested (`arinox_apparel/portable`). The dev bench now has `server_script_enabled` on in `common_site_config.json`. `DEPLOY.md` (install the app with `bench get-app`) does **not** apply to that site.

> **Update 2026-11-05 (Phase E, latest):** the subcontract round trip, finishing, packing, final inspection, shipment and freight, invoicing, payment follow-up and claims are built on the dev site. Read the **Status log at the end of `doctypes/PHASE_E_SHIP_AND_COLLECT_PLAN.md`** first. It is reuse-first (ERPNext Shipment, Supplier Quotation, Sales Invoice and Customer are extended with custom fields) and every new document is named `<contract no>-<code>-<nn>`. Not done: nothing was opened in a browser, the two-company invoice route was not run end to end, AQL accept/reject numbers are confirmed only for codes K, L, M, and the Phase D order close, Production Summary and board are still to build. `bench migrate` output must be read for "Orphaned DocType" (see the skill file). The hosted site still has none of Phases A to E.

> **Update 2026-11-05 (Phase D):** Production slices D0 to D4 (foundations and ledger, Production Card, Pilot Run, bulk cutting, bulk sewing) are built on the dev site. D5 to D9 (subcontracting, finishing, packing, final inspection, order close) are not started. Read `doctypes/PHASE_D_BUILD_STATUS.md` first for the state, the deviations from the plan and what is unverified (the sewing tests were not re-run after the last fixes; nothing from Phase D has been opened in a browser). The plan is `doctypes/PHASE_D_PRODUCTION_PLAN.md`. Decisions from the user: build for any country, no QR for now, wash penalty on all damaged pieces.

> **Update 2026-11-05:** Phases A, B and C are built on the local dev site (bench at `/workspaces/frappe-bench`, site `apparel.localhost`). 195 tests pass. The "Where we are" section below is from the first session and is out of date. See `doctypes/PHASE1_ORDER_BACKBONE_PLAN.md`, `PHASE_B_PLAN_AND_APPROVE.md` and `PHASE_C_MATERIALS_PLAN.md` (status log at the end) for what exists. After a Codespace restart, start the database first: `docker start apparel-mariadb apparel-redis`. The hosted site still has none of this: someone with shell access must run `bench get-app`, `install-app` and `migrate` (see `DEPLOY.md`).

Read this first in any new session, then `CLAUDE.md`.

## Where we are

- **Phase 0 (dev environment): not started.** No bench yet. Docker 29.9.2 and Compose v5.6.1 are installed and the daemon runs. Resources: 2 CPUs, 7.8 GB RAM, 15 GB free disk.
- **App skeleton: done** at `arinox-apparel/arinox_apparel/`. Commit `997a733136` on local branch `apparel-app`.
- **App-root branch: built, not pushed.** `apparel-app-root` (`27495f6930`) holds only the app tree, with no repo history.
- **Doctypes: none yet.** Specs are not written. Only `doctypes/_TEMPLATE.md` exists.

## Decisions still open (need the user)

1. **Repo visibility.** `Arinox-AI/Arinox-ERP-Apparel` is PUBLIC. Options: make it private, push to a new private repo such as `Arinox-AI/arinox_apparel`, or keep local.
2. **Hosting target.** Self-hosted server. The hosted AI agent is API-only, so a human must run `bench get-app`, `install-app`, `migrate`, and `restart`.
3. **Git read access for the server.** If the repo is private, the server needs a read token or deploy key.
4. **First doctype slice.** Proposed: Style, Size Chart, Colorway.

## Hard rules (from CLAUDE.md, repeated here)

- Never edit ERPNext core code.
- Never push, tag, or commit without user approval.
- No destructive commands on the hosted site.
- Every doctype needs a reviewed spec before code.

## Known facts about the hosted site

- API user `cortex@gmail.com`, System Manager role. The agent can read and write records via API. It cannot run bench, install apps, or read the server filesystem.
- Server Scripts are disabled at bench level.
- The last migrate on the hosted site was 2026-09-07 (from Patch Log).
- Live-site probes already ran: a test ToDo was created and deleted, and a disabled Server Script was created and deleted. Frappe has no trash, so deletions are permanent.

## Next step

Phase 0: bring up the Docker bench with ERPNext v16.34.1, create a dev site, install `arinox_apparel` from the local branch, and confirm `migrate` runs clean.
