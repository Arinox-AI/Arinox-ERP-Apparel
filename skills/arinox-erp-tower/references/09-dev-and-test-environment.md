# 09 Dev and test environment

Use this only when asked to run, test or change something on the development machine. **Everything here targets local sites. Never point a test, a loader or a write at the live ERP.**

## Bring it up (Codespace)

```
docker start apparel-mariadb apparel-redis          # after every Codespace restart
cd /workspaces/frappe-bench
bench --site apparel.localhost ...                  # dev site: arinox_apparel installed (reference)
bench --site hosted.localhost serve --port 8001 &   # hosted-like site: ERPNext only + the loaded bundle (the test ERP)
bench worker --burst                                # if a site says "Too many queued background jobs (600)"
```

Versions: ERPNext/Frappe v16.x (target v16.34.1), Python 3.11+, Node 20+, MariaDB 10.6+, Redis. The `hosted.localhost` site is **not** in developer mode and has `server_script_enabled` on. The dev bench's `common_site_config.json` also has `server_script_enabled` on.

Credentials for the test site: an API key for Administrator in `~/.arinox_hosted_token` (`key:secret`, chmod 600), passed as `ARINOX_API_TOKEN`. The Tower otherwise auto-discovers the sealed KOGO credentials, which is why test runs must pin the base explicitly: set `ARINOX_ERP_BASE` (and `ARINOX_ERP_TOKEN`) to the test site. A run must abort if the resolved base is not `http://hosted.localhost:8001`.

## ERP-side scripts (in `arinox-apparel/`)

| Script | Does |
|---|---|
| `hosted_sync.sh [group,group]` | Exports the bundle from the dev site and loads the named groups (default `server_scripts`) onto the hosted-like site via REST. Run after every script change. |
| `hosted_tests.sh [group_or_test]` | Runs the hosted tests; prints `ok` / `FAIL` per test and `RESULT passed N failed M` (baseline 261 / 0). |
| `hosted_exec.sh file.py [grep]` | Runs a Python file in the hosted-like site's console (`bench execute` refuses a module from an app not installed on the site). |
| `hosted_ingest.sh "<docs folder>"` | Enters the two sample orders and reconciles against the papers. **Not in the repo**; ask the owner. |

Dev app tests: `bench --site apparel.localhost run-tests --app arinox_apparel` (195 passed at last count; the suite has grown). Read `bench migrate` output for "Orphaned DocType".

Loading onto a real hosted site (only on the owner's instruction):
`ARINOX_API_TOKEN=key:secret python3 arinox_apparel/arinox_apparel/portable/api_load.py hosted_bundle https://<site> [--only=group,group] [--dry-run]`. Always `--dry-run` first. Take a backup first. Regenerate the bundle from the app with `bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '<dir>'}"`.

## Tower (in `cortex-tower/`)

```
# needs a venv with: sqlalchemy openpyxl requests
cd cortex-tower/backend && python3 tests/test_<name>.py         # plain scripts; exit 0 = pass
#   order flow: test_order_flow, _samples, _materials, _cutsew, _subcontract, _pack, _ship, _invoice
#   plus: test_allocation, test_tna_engine, test_tna_plan, test_pipeline_guard, test_tsr_core, test_erp_links
cd cortex-tower/frontend && npm install && bash build.sh          # tsc, vite, one index.html; config.js stays first, un-inlined
python3 tools/vendor_scripts.py                                   # re-vendor Arinox scripts after an ERP script change
python3 tools/conformance.py --only naming                        # real scripts through the runtime against a site
python3 tools/gen_allow_on_submit.py --base <site> [--apply]      # Property Setters for db_set on submitted docs
python3 tools/gen_document_md.py                                  # keep document.md complete
```

Structural guards in `test_pipeline_guard.py`: single write path (no module but `pipeline` calls the ERP write primitives), no `os.environ` outside `config.py`, no direct frontend URLs, `document.md` lists every registered function, vendored scripts equal the repo bundle. **Extend its allowlist only for new modules; never weaken it.**

## Rules when you change code

- A new public function needs: a `guarded` wrapper, a role check, a `### \`name\`` entry in `document.md`, registration in `functions.py`, a test. A function without a heading is invisible to the middleware and to you.
- Every ERP write goes `pipeline.execute`. No direct `erp.erp_create/update`.
- `config.py` is the only env reader. Identity/URL values come from env only, never literal.
- Write new business rules as Server Scripts + hosted tests first (so they run natively when `server_script_enabled` goes on); the Tower runs them via TSR.
- No company/buyer/factory/SAM/lead-time default anywhere; fixtures are synthetic (invented buyer, styles, numbers).
- Report test output faithfully. If you skipped a step, say so. Do not commit or push without being asked; commit messages and PRs follow the attribution instructions the user gave.

## Where the history is

`cortex-tower/ORDER_TO_SHIP_STATUS.md` (slice-by-slice build log with gate output) · `cortex-tower/HANDOFF.md` · `cortex-tower/QA_REPORT.md` · `cortex-tower/FIXES_2026-11-09.md` · `arinox-apparel/RECORD_2026-11-05.md`, `RECORD_2026-11-06.md` · `arinox-apparel/doctypes/PHASE_*_*.md` (status logs at the end) · `arinox-apparel/HOSTED_BUILD_GUIDE.md` (full port guide).
