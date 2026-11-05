# Handoff — Arinox Apparel

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
