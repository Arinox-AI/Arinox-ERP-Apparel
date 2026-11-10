# Cortex Tower — handoff

## 2026-11-07 — Workspace release (read this first)
* **What changed:** one inbox as conversations (inquiries flagged, replies sent and captured in the same thread), deals
  that follow the ERP's own flow (Opportunity + Tech Pack → Cost Sheet → Price Negotiation → Quotation → Sales Contract →
  Sales Order), add-a-customer in one step, a dashboard, and a new shell (Professional Slate). Details: ARCHITECTURE.md
  (last section), SPEC.md (last section), QA_REPORT.md (last section).
* **Platform steps:** upload the project; nothing to configure. On first open the stored mail is re-labelled once with
  the new classifier and grouped into threads.
* **ERP setup the flow needs:** an Item Group on each Product Type (or Apparel Settings → Style Item Group), so the tower
  can make each style's Item; a FG warehouse in Apparel Settings (for the Sales Order); Cost Heads and, ideally, a
  Costing Parameter with your rates (otherwise rates are typed per costing).
* **Write mode:** the default `draft` allows everything the deal flow does (submitting Cost Sheet / Quotation / Sales
  Contract is the "draft" class); ledger documents still need approval.

# Cortex Tower × Arinox ERP — handoff (2026-11-06)

Read `CORTEX_TOWER_PLAN.md` first (the plan this was built against). This file says what is DONE and VERIFIED, what is BUILT BUT NOT VERIFIED, and what is NOT DONE. Nothing here was committed or pushed.

## Verified (commands I ran, results as seen)
| What | Command (from `backend/`) | Result |
|---|---|---|
| Runtime + pipeline + sync, on an in-memory ERP | `python3 tests/test_tsr_core.py` | 95 assertions pass |
| Inquiry intake, 19 synthetic mails/edge cases | `python3 tests/test_inquiry_v2.py` | 55 pass |
| Structural guards (single write path, no os.environ, no direct frontend URLs, document.md complete, vendored scripts = repo bundle) | `python3 tests/test_pipeline_guard.py` | 96 pass |
| Tower's own pre-existing tests | `tests/test_engine.py`, `test_buyer_ref`, `test_erp_contract`, `test_intake`, `test_intake_replay`, `test_inquiry`, `test_email_engine.py` | pass. `test_chain`, `test_wip_edges`, `test_wip_plan` fail only because this machine has no live ERP / pack builder (same before my changes) |
| Frontend typecheck + build | `cd frontend && bash build.sh` | tsc clean; 1.9 MB single `index.html` (Vite; Parcel's native compiler would not load here) |
| Naming scripts through REST on the real ERPNext test site (`hosted.localhost:8001`, server scripts OFF) | `python3 tools/conformance.py --only naming` | 3/3 pass |

## Built but NOT verified
* **Conformance of the real Arinox scripts through the runtime** (`tools/conformance.py` runs the repo's 261 hosted tests with `frappe` replaced by the TSR). The full run was never completed. Interim run (old code, partial): 52 ok / 62 fail. I fixed the causes found (date typing/serialisation in query filters, sandbox `json`, `doc.meta.fields`, deep attribute-dict results, cancelled-doc writes) but did NOT re-run to confirm. Known not-runnable: tests that `import erpnext` in-process (gate group, some button tests), raw-SQL-write tests, `frappe.desk.query_report`. **First job: `bench --site hosted.localhost set-config server_script_enabled 0`, run `tools/conformance.py`, fix what fails, set it back to 1.** The site needs `bench worker --burst` every few tests (503 "too many queued jobs"); the runner does this.
* **Frontend look/feel.** The new iOS-style shell (`frontend/src/cx/`) builds and typechecks, but I never saw a rendered screenshot (the preview script `tools/ui_preview.py` had a wait bug I fixed last; not re-run). Expect layout polish. Legacy screens (overview, orders, risks, WIP, TnA, intake, inbox, mail …) are shown inside the new shell, restyled only lightly.
* Webhook intake, poller/reconciler, breach detection: unit-tested on the fake ERP only, never against a real ERP.
* `cx_connection` (is the tower pointed at the Arinox site?) never run for real. Phase 0 questions S1–S8 of the plan are unanswered, except REST behaviour (S8) which I measured.

## Not done
* ERP-side: no webhooks installed, Client Scripts not regenerated ("Open in Cortex Tower" buttons), no permission profile. All need the owner's approval (they write to the client ERP).
* Chatbot (plan Phase 6): not extended; the existing `ask_kogo` is unchanged. Proposals-from-chat not built.
* Resumable long jobs (`cx_job` table exists, no runner). Heavy scripts (ledger rebuild, carton plan) are untimed.
* T&A calendar still reads its own overlay, not ERP `Order TNA` (plan §5.4). Bespoke screens (Tech Pack grid, Packing carton plan) not built; the generic record screen covers them.
* Document attachments upload/download, per-field `permlevel` beyond hide/show.
* `docs/` specs (ARCHITECTURE/SPEC/REQUIREMENTS/DESIGN/QA_REPORT) NOT updated for this work.

## Things you must know (findings)
1. **REST cannot do raw `db_set` on submitted documents.** 27 (doctype, field) pairs the scripts write (mostly `status`) need `allow_on_submit`. `erp_setup/allow_on_submit.json` = Property Setters for them (`tools/gen_allow_on_submit.py --base <site> [--apply]`). I APPLIED them to the local test site only. The runtime raises a clear `TSRNeedsSchemaFix` if one is missing. Writes to cancelled docs are skipped and reported (`skipped_writes`).
2. **Default write mode is `draft`**, which blocks risky ops (cancel, ledger submits) outright, before approval. For real use set `ERP_WRITE_MODE=all` (approvals then gate them).
3. ERP `owner`/`modified_by` become the API user; the real person is in the audit log and the ERP comment the tower leaves.
4. Numbered doctypes (name from `arinox_name`) cannot be created in the ERP desk without server scripts: create them in the tower.
5. The 15 legacy action functions now require sign-in + role and ignore the client's `actor` (`functions.py`, bottom). Without KOGO SSO env (`KOGO_AUTH_VERIFIED=1`) or a password login, the whole app is locked — intended, per the skill.
6. Test site state I changed: `server_script_enabled` was toggled and restored to 1; 27 Property Setters added; many test records created/removed by the runner.

## Where things are
`backend/tsr/` runtime (shim, sql, journal, runner, reports, backend, fake, compat, vendor/) · `backend/pipeline.py` · `changefeed.py` · `guardrails.py` · `cx_users.py` · `cortex_api.py` (38 functions, documented in `document.md`) · `inquiry_v2.py` · `docs.py` · `catalog.py` · `frontend/src/cx/` · `tools/` (vendor_scripts, conformance, gen_allow_on_submit, gen_document_md, ui_preview). The real mail corpus, DB and ERP credentials were deliberately NOT included (`backend/data/` is excluded); the repo is public.
