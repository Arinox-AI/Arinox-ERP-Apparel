# Cortex Tower change prompt: ERP-native Server Scripts and custom ERP modules (2026-11-12)

> Paste everything below the line into the Cortex Tower builder (KOGO) chat. It is self-contained.

---

**Context.** Server Scripts are now **enabled on the live Arinox ERP** (`server_script_enabled = 1`), and the ERP-connected agent can create DocTypes, Server Scripts, Reports and similar records directly. Until now the Tower's Tower Script Runtime (TSR, `backend/tsr/`) executed the 253 vendored Arinox Server Scripts around every REST write, because the ERP could not run them. If both run now, **every rule runs twice**. Numbers skip (`arinox_naming_*`), ledger rows double (`arinox_engine*`), and gates throw twice. The kill switch (`tsr_kill_switch off`) does not prevent this, because `ALWAYS_ON_PREFIXES` keeps naming and engine scripts on. Custom modules built in the ERP also have to be visible to the Tower's roles and screens.

Make the following changes. Do not change any business rule, any vendored script text, or the approval and role model beyond what is written here.

### 1. A script-execution mode

- `config.py`: `ERP_SCRIPTS_MODE = env("ERP_SCRIPTS_MODE") or "auto"`. Values: `tower | native | auto`. A KV row `erp_scripts_mode` overrides the env value and is set through a new admin-only function `set_erp_scripts_mode(mode)`. Add that function to `guardrails.ADMIN_ONLY_FUNCTIONS`.
- `auto` resolves at runtime and caches for 10 minutes: call `GET /api/method/arinox_ping` on the ERP.
  - `200` with `{"message": {"native": true, …}}` → `native`
  - an error saying Server Scripts are disabled → `tower`
  - `404` / "not found" → `tower`, plus a health warning: "ERP has no arinox_ping script; set erp_scripts_mode explicitly"
  - **ERP unreachable → refuse writes** (do not guess)
- The ERP agent creates `arinox_ping` (API, allow_guest 0, read-only). It returns `{"native": True, "scripts": frappe.db.count("Server Script", {"disabled": 0}), "version": "2026-11-12"}`.

### 2. `pipeline.execute` in `native` mode

- **Preview** (`preview: true`): keep running the TSR in `record` mode exactly as today, so the user still sees the predicted operations and messages. Add `preview["engine"] = "erp-native"` and the note "Rules run in the ERP when this is saved; the preview is the Tower's prediction."
- **Execute**: do **not** call `_run_op` with a live sink. Send the operation straight to the ERP through the existing `tsr.backend` REST client, and let the ERP run its own scripts:
  - `insert` → `backend.insert({...data, doctype})`
  - `save` → `get_doc` + optimistic-lock check (the same `modified` comparison as today) + merge `data` + `backend.save`
  - `submit` / `cancel` → optimistic-lock check + `backend.submit` / `backend.cancel`
  - `delete` → `backend.delete`
  - `api` → `backend.call(<api_method>, params)` (the API method name, not the Server Script record name; reuse the name lookup the registry already has)
- A `frappe.throw` from the ERP comes back as an HTTP 417 or ValidationError. Map it to the same `TSRValidationError` → `{"ok": false, "blocked": true, "error": <ERP message>}` the UI already shows.
- Steps 1 (role), 3 (field guard), the mode gate, the rate limit, approvals, locks, idempotency, the journal entry, the audit row and the ERP trace comment all **stay exactly as they are**. Only the "8 execute through the TSR" step changes.
- Compensation: one REST call is one ERP transaction, so there is nothing to compensate after a single failed native call. Keep `compensate()` for multi-op functions and log "native single-op, nothing to undo".
- In `native` mode, `ScriptStateModel` run counters stay at zero for live writes. `tsr_status` must say so rather than show stale counters.

### 3. Module registry (custom ERP modules)

- New KV row `erp_modules` (JSON list). New functions:
  - `erp_module_register(registration)` (admin only, preview/confirm like other writes)
  - `erp_module_list()` (read, any role)
  - `erp_module_remove(slug)` (admin only)
- Registration shape:
  `{"module": str, "slug": str, "doctypes": {name: {"group": str, "write_roles": [..], "submit_roles": [..], "ledger": bool}}, "api_methods": [{"name": str, "risky": bool, "doctype": str}], "scripts_run_on": "erp", "spec": str}`
- On register, validate the following and refuse with a clear sentence if any check fails:
  1. every doctype exists on the ERP (`backend.meta`)
  2. `scripts_run_on == "erp"`
  3. the slug does not collide with an existing group in `guardrails.GROUP`
  4. no doctype is already owned by Arinox Apparel
- `guardrails`: at import time and after every register or remove, merge the registry into `GROUP`, the WRITE/SUBMIT role tables (via the existing `_override` path or an equivalent in-memory merge), `LEDGER_DOCTYPES` (when `ledger: true`), and `RISKY_API` (exact api_method names with `risky: true`). Unknown doctypes keep today's behaviour: readable by all, writable only by Management and Admin.
- Never vendor or run a registered module's Server Scripts in the TSR, in any mode. In `tower` mode an op on a module doctype goes straight to REST, as in native mode.
- Order and Deal screens are unchanged. Add a simple **"ERP modules"** admin card that lists each module, its doctypes with live row counts, and a link to the ERP workspace.

### 4. Drift guard

In `native` mode the live scripts are the source of truth, and the ERP agent can edit them. Extend `tsr_status` with `drift`: compare each live Arinox Server Script (`name`, `modified`, a sha1 of `script`) with `tsr/vendor/CHECKSUMS.json`. Report `same | changed_on_erp | missing_on_erp | extra_on_erp` counts and the first 20 names. This is only a warning, never a block. `previews` built from a drifted script carry `"preview_may_differ": true`.

### 5. `tsr_status` / health

Add `erp_scripts_mode` (the resolved mode and its source: env / kv / auto-probe at <time>), `native_probe` (the last probe result), `modules` (count + slugs) and `drift`. The health card shows "Rules run in: ERP (native)" or "Rules run in: Tower (TSR)". It shows a red warning whenever the probe says the ERP runs scripts but the resolved mode is `tower`. That is the double-run state.

### 6. Tests (add to `backend/tests/`, all against the existing fake backend)

1. `native` insert → the fake backend receives exactly one insert, and the TSR `LiveSink` records zero script runs. A naming series advances by one, not two.
2. `native` api → `backend.call` receives the API method name, and the params pass through unchanged.
3. An ERP-side throw → `{"ok": false, "blocked": true}` with the ERP's message.
4. Preview in `native` → the operations list is present and `engine == "erp-native"`.
5. `auto` with the probe returning native, disabled, missing and unreachable → `native`, `tower`, `tower` + warning, and writes refused.
6. Module register: an unknown doctype is refused; a valid registration makes `group_of` return the slug, and a `ledger: true` submit classifies as `risky`; remove restores the old behaviour.
7. Drift: one changed vendored script → `changed_on_erp: 1`.
8. All existing tests still pass (`tests/test_pipeline_guard.py`, `test_tsr_core.py`, the order-flow tests).

### 7. Docs

- Update `backend/document.md` for the new functions (`gen_document_md.py`) and `ARCHITECTURE.md` §write path with the two modes.
- Change the comment on `INTAKE_WRITE_PATH` in `config.py` ("needed while ERP server scripts are OFF") to describe both modes.

**Rollout order:**
1. The ERP agent creates `arinox_ping`.
2. Deploy this change with `ERP_SCRIPTS_MODE=native` set explicitly.
3. Run `tsr_status` and confirm `erp_scripts_mode: native`, no red warning, and the drift counts as expected.
4. Make one low-risk write (a Comment, or a draft on a `ZZTEST-` record) and confirm the ERP numbered it exactly once.
5. Only then switch to `auto` if wanted.

**Acceptance:** report the test results, the `tsr_status` output, and the document name from step 4 of the rollout.
