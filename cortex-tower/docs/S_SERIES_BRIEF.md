# S-series brief (S4 to S11) — shared by every agent that builds a step

Source of truth: `/workspaces/Arinox-ERP-Apparel/arinox-apparel/ORDER_TO_SHIP_PLAN.md` (sections 3, 4, 8, 9, 10). Read section 4's table row for your
step and section 3's rules. What S0 to S3, T0 and T1 built is logged in `cortex-tower/ORDER_TO_SHIP_STATUS.md` (read it, do not redo it).

## Rules (hard)
- Be economical: grep first, read only what you need, copy the pattern of an existing step (`OrderPage.tsx`, `AllocationBoard.tsx`, `TnaPlan.tsx`, `order_flow.py`, `order_alloc.py`, `order_api.py`). Final report under 40 lines.
- Every ERP write goes pipeline -> TSR -> the vendored Arinox scripts (`cx_run_script` / `cx_write`), preview first, risky class (ledger-posting submits: Stock Entry, Delivery Note, Sales Invoice, Purchase Receipt) needs approval. Never call erp create/update directly (test_pipeline_guard enforces it). Never edit `erpnext/` core. Never fork a hosted script inside the tower: a new rule is a Server Script in `arinox-apparel/arinox_apparel/arinox_apparel/portable/hosted_scripts/` + manifest + hosted test, `hosted_sync.sh` + `hosted_tests.sh` green, re-export the bundle, `tools/vendor_scripts.py` re-vendor.
- Each public function: `guarded`, role-checked, `### name` heading in `backend/document.md`.
- **Generic product (decision D8):** no company, buyer, factory, SAM, efficiency, lead-time, calendar or price value from the user's reference documents may be a default in code, seeds, settings or tests. Test data is synthetic (invented buyer "Acme Apparel Co", invented styles and numbers). Empty states guide setup. Never read the reference zip.
- Only `hosted.localhost:8001` for live checks (token `~/.arinox_hosted_token`; setup in `arinox-apparel/RECORD_2026-11-06.md` "How to resume": `docker start apparel-mariadb apparel-redis`, serve the site, `bench worker --burst` if "too many queued jobs"). Use a venv for the tower tests (sqlalchemy, openpyxl, requests; the earlier S0 run made one — find it with `ls /tmp/claude-1000/*/*/scratchpad` or recreate under your scratchpad). NEVER the live KOGO ERP; pin the base URL.
- No commits, no pushes. Known environmental failures (3 'ai door' in test_deals, test_chain 1, test_wip_edges 1, test_wip_plan) are not yours.
- Do not touch files of the other steps beyond the shared registration points (`functions.py`, `document.md`, `order_flow.py` step table, `OrderPage.tsx` step router, `theme.css`): append or edit only your step's block there.
- Stopped earlier runs may have left partial files: `cortex-tower/backend/agent/` (A2) and edits by A1 (seeds in `setup/production.py`, fixtures, `buyer_ref.py`). Do not build on or delete them; if one breaks the suite, say so in your report.

## Definition of done per step (from plan section 4 and 8)
1. `order_flow.py`: the step's state, counts, blockers (plain sentences), docs list, `next` action — already read-only from S1/S2; make it exact for your documents.
2. Actions: the existing API scripts named in the plan row, each as a tower function with preview -> confirm, through the pipeline. Forms for floor documents open the generic `FormSheet`/`DocSheet` pre-filled (sales order, style, colour, factory, line).
3. The bespoke widget named in the plan row (approval matrix, bulk-gate card, material status, production matrix, carton plan, shipment wizard, receivable card and close checklist, out/back balance).
4. Tests: a new `backend/tests/test_order_<step>.py` on synthetic data (state machine, blockers, every action's preview, role denial, zero-qty guard), plus one live run on hosted.localhost through the TSR for the step's round trip as written in plan section 8's gate column; quote the output. Re-run `test_order_flow`, `test_pipeline_guard`, `test_tsr_core`, `test_erp_links`, `test_deals`, `test_allocation` and `hosted_tests.sh`; quote counts.
5. `frontend/build.sh` (tsc clean) and a Playwright check at 1440 and 390 px of the step (no overflow, no console errors); if Playwright cannot run, say "not verified".
6. Append a dated section to `cortex-tower/ORDER_TO_SHIP_STATUS.md` (append only; re-read right before appending): what was built, gate output, what is not verified.

## Appster conformance (user instruction 2026-11-09: everything must be built on the appster skill)
Skill: `/workspaces/Arinox-ERP-Apparel/appster_skill_1792213975950.zip` (unzip into a NEW scratch dir; `SKILL.md`, `sub-skills/core-builder/SKILL.md`). Every function and screen you add must satisfy, and your report must state PASS/FAIL for each:
1. Frontend reaches the backend ONLY through `callApi`/`callApiWithFile` to `API_BASE` (grep your new frontend files: no `fetch(`/axios/URLs, no ERP or localhost address).
2. Backend = plain functions run as fresh subprocesses: no server, no threads, no sleeps, no in-memory state between calls; anything near 20 s is chunked (state in SQLite) like the existing job pattern.
3. `config.py` is the only reader of `os.environ` (test_engine enforces it); ids/URLs never literal.
4. Every public function is registered in `FUNCTIONS`, has a `### name` heading in `backend/document.md` (the middleware allowlist) and is `guarded` (KOGO SSO user + permission check, never role-name checks); `document.md` stays the KOGO agent's tool catalogue, so write each entry's purpose, params, return shape and side effects clearly (the KOGO agent calls these as tools: Pattern A).
4b. Responses use the two-layer envelope the skill defines (`callApi` -> `{success, data, message}`; functions return the payload or `{error}`); components read `res.success` and `res.data.error`.
5. External capabilities (OCR, web, etc.) only through `_call_agent_tool`, with `tools_used.json` kept in sync and `tool_unavailable` handled.
6. Bundle with `frontend/build.sh` (single `index.html`; `config.js` stays the first script and is not inlined); after your build run `grep -oE 'https?://[^"'"'"' ]+' index.html | sort -u` and confirm only fonts/middleware hosts appear.

## SAFETY CHECK before ANY script that touches an ERP (added after S6, where two early calls used the default connection = the live KOGO ERP)
The tower auto-discovers sealed KOGO credentials. In EVERY harness/script/test run: set the base URL and token for hosted.localhost explicitly, then FIRST call a read that proves where you are (e.g. print the resolved ERP base URL and `frappe.auth.get_logged_user`), and abort if the base URL is not `http://hosted.localhost:8001`. Never run a write before that check has printed. If you cannot pin it, do not run the script.
