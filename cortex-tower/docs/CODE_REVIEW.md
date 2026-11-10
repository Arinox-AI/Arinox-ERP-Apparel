# Cortex Operations Control Tower — Source Code Review

Reviewed: 2026-10-05 · Scope: `backend/` (16 Python modules, ~9,900 LOC) + `frontend/src/` (27 files) + `config.js`
Method: static read of every module, compile check, targeted greps for hardcoding/secrets/outbound calls.
No code was changed. No subagents used.

---

## 1. Verdict

| Aspect | Rating | One-line |
|---|---|---|
| Architecture | **GOOD** | Clean split between live-read layers (`erp`, `rulebook`, `forecast`), AI layers (`copilot`, `ai_nextsteps`), action layer (`writes`), and mail/inbox (`email_engine`, `mailer`, `inbound`). |
| Defensive design | **GOOD** | ERP layer never raises; every read degrades to an empty shape with `live:false`. TTL caches. |
| Maintainability | **WEAK** | `functions.py` is a 3,170-line, 86-function monolith; ~240 lines of dead code; no tests; no git. |
| Portability / reuse | **WEAK** | Several deployment- and client-specific constants are baked in (see §3). It runs for *this* workspace, not generically. |
| Security | **NEEDS ATTENTION** | ERP API key+secret cached in plaintext; SMTP password in plaintext SQLite (see §5). |
| Ask KOGO design | **GOOD** | Retrieval + grounding + validation + fallback is a sound pattern; routes to the KOGO agent stream (see §4). |

---

## 2. Four-part overview

### 2.1 The stack (source read)
- Frontend: single-file React/parcel bundle `index.html` (1.5 MB, prebuilt and committed). Calls the KOGO project API `https://agent.kogo.ai/api/agent/common_project_api_v1` (`config.js`).
- Backend: FastAPI-style function registry in `functions.py`, invoked by the platform middleware.
- Data: **all operational data live from KOGO ERP** via `erp.py` (Frappe REST). Local SQLite holds only decision state (risk/action/audit + mail + AI cache). `seed.py` is a deliberate no-op.
- Write path: `writes.py` — mode-gated (`off|safe|draft|all`, default `draft`), drafts-only for submittable doctypes, idempotent, reversible (`rollback_action`).

### 2.2 Strengths worth keeping
- Never-raise read layer: `erp.py` GET helpers return `[] / {} / 0` and record the last error for `connection.error`.
- Thresholds externalised to `rulebook.json` (the newer engine) — the top of the file explicitly says "thresholds live here, not in code".
- Write safety: idempotency checks against the ERP before every create; `MAX_PER_RUN` batch cap; rollback deletes (create) or cancels (submit).
- AI grounding: the copilot validates every ≥3-digit number in the answer against the retrieved evidence pack and flags `grounded:false` + `unsourced[]`. Reasoning-channel stripping and explicit UTF-8 decode are correctly handled.
- Docs: unusually complete (`ARCHITECTURE.md`, `SPEC.md`, `RULEBOOK.md`, `COPILOT.md`, `QA_REPORT.md`, `document.md`).

### 2.3 Weaknesses (ranked)
1. **`functions.py` monolith** — 3,170 lines, 86 top-level functions spanning snapshot, facts, risks, recs, KPIs, charts, fabric intel, email drafts, inbox, and function registry. Should be split by domain.
2. **Dead / shadowed code** (~240 lines + duplicates): `_build_risks` (L403) and `_build_recommendations` (L540) are shadowed by overrides at L3044/L3055; `ask_kogo` is defined twice (L1603 deterministic fallback kept live via `_orig_ask_kogo`, L3115 active). The L1603 body still contains client-specific templates and assumes USD.
3. **No tests** — only `backend/test_email_engine.py`. `rulebook.py` (807 LOC), `forecast.py`, `copilot.py`, `writes.py` have none.
4. **93 `except Exception` blocks** — mostly intentional for the never-raise policy, but there is no logging; failures vanish into `_last_error`.
5. **No version control** — no `.git`; recovery relies on manual `functions.py.bak-*` / `index.html.bak-*` files.
6. **Commit-time build fragility** — the 1.5 MB bundle must be rebuilt with a documented manual sequence (pnpm → tsc → parcel → html-inline → manual font base64 → prepend `config.js`). No CI.
7. **Duplicated threshold defaults** — `rulebook.json` **and** `rulebook._DEFAULTS` both define the same numbers (two sources of truth; the JSON wins but the fallback can drift).
8. Two severity decisions still hardcode `n < 10` (`rulebook.py` L531, L706) instead of reading `rulebook.json`.

---

## 3. Hardcoded values — full inventory

### 3.1 Infrastructure / deployment (highest reuse risk)
| What | Where | Note |
|---|---|---|
| KOGO ERP app id `6a84626b933cd6f2680eedac` | `erp.py:33` | Workspace-specific. App only reads *this* ERP. |
| Project/agent/deployment/swarm/origin/user ids + API base | `config.js` | Deployment-baked into the shipped bundle. |
| ERP API key + secret cached in plaintext | `backend/data/sas_creds.json` | `{BASE, AUTH:{Authorization: "token key:secret"}}`. |
| SMTP/IMAP host+port defaults | `functions.py:2204-2206`, `mailer.py:37`, `inbound.py:201`, `models.py:173` | `smtp.gmail.com:587`, `imap.gmail.com:993`. |
| Mail `from_name` default | `models.py:172`, `functions.py:2204` | `"Cortex Textile Limited"`. |

### 3.2 Business / client-specific
| What | Where | Note |
|---|---|---|
| `DEFAULT_COMPANY = "Cortex Textile Limited"` | `email_engine.py:55` | Falls back when ERP companies list is empty. |
| `DEFAULT_CURRENCY` / `_money(..., "USD")` | `email_engine.py:60,75` | Defaults USD. |
| `SELLING_PRICE_LIST = "Standard Selling"` | `writes.py:39`; also `functions.py:1261` | Assumed ERP price list name. |
| FG variant detection `item_group == "Finished Garments"` (fallback: any variant) | `functions.py:342` | Item-group-name coupling. |
| Quality status string `"not conclusively"` substring match | `functions.py:353` | Source-data wording coupling. |
| Item-code convention: style = first 3 `-`-parts, ≥5 parts required | `functions.py:86` (`_style_of_item`), `writes.py:_style` | Bakes in the `C2027-S84-304-MICTP-S` code shape. |
| Notify subject `"Cortex Tower - …"` | `functions.py:2738`, `monitor.py:136-137` | Also used as a self-ingest filter prefix. |
| Fabric warehouse heuristic (`"finished" in name`, else first) | `writes.py:_fg_warehouse` | Fragile for other naming schemes. |
| Margin plausibility gate `0.02·price ≤ cost ≤ 2.0·price` | `forecast.py:131` | Heuristic; documented but arbitrary. |
| Copilot keyword router `_ROUTES` | `copilot.py` | English keywords; wrong hit = narrow retrieval (fallback = broaden only when *no* hit). |

### 3.3 Legacy, now-unreachable literals (cosmetic risk only)
`functions.py` L479 `"Da Nang sewing"`, L573 slug `"reinspection_s84"`, L1218 slug branch, L1261 `"Standard Selling"` — all inside the shadowed `_build_*`/`_erp_record` code. Deleting the dead blocks removes these.

### 3.4 What is correctly NOT hardcoded
- Risk severity thresholds → `rulebook.json` (delivery/BOM/fabric/payment/shipment/production/supplier).
- Currency handling in the live layers → multi-currency, never summed across currencies (cash split USD/VND; `forecast.py:190`).
- No synthetic/demo data — `seed.py` no-op, `demo:false` everywhere.

---

## 4. How "Ask KOGO" is implemented, and where it routes

### 4.1 Call chain (source-verified)
```
AskPanel.tsx  →  App.runAsk()  →  callApi("ask_kogo",{question})
   → POST https://agent.kogo.ai/api/agent/common_project_api_v1   (KOGO project API, Bearer JWT)
      → functions.py:ask_kogo (L3115)  →  copilot.answer(db, question)
         → rulebook.live_facts() + forecast.build()   (live ERP read)
         → build_evidence()  (keyword router picks sections; always core snapshot)
         → ai_nextsteps._llm(db, prompt)
            → POST https://os.kogo.ai/api/v1/chatai/deployment_stream_kogo_os_stream   (SSE)
               payload {sender, thread_id, message, deployment_id, kogo_swarm_id}
               header  Authorization: <USER_JWT_TOKEN>
         → _clean() strips <think>…</think> + stream artefacts; UTF-8 decoded explicitly
         → _num_tokens() validates every ≥3-digit number against the evidence pack
      → {answer, grounded, unsourced[], evidence_sections[], related[]}
   → on model unavailable: falls back to deterministic _orig_ask_kogo (functions.py L1603)
```

### 4.2 Does it route to "this" KOGO chat, or something else?
**It routes to the same KOGO agent/chat backend that powers the KOGO assistant — the deployment stream.**
- Endpoint resolved at runtime: **`https://os.kogo.ai/api/v1/chatai/deployment_stream_kogo_os_stream`** (from `CHAT_API_PATH`, verified from the running process).
- It is **not** a separate service and **not** a direct external LLM provider: there is no OpenAI / Anthropic / Gemini SDK or API key anywhere in the project.
- Differences from *this* chat: the Tower opens **its own thread** (`app_kv.ai_thread_id`), reuses it for all questions, and injects a large grounded prompt as the "message" rather than sending the user's raw question. So: **same backend, separate thread, prompt-driven persona**, shared by all Tower users.
- I could not read the platform's server-side chat/agent source (that is outside this project and outside what I can access). What is verifiable is the exact request contract above — the Tower's half of the conversation.

### 4.3 Guardrails present
- Closed evidence pack; prompt instructs "use ONLY the FACTS".
- Numeric grounding validation → `grounded` / `unsourced`, surfaced as a UI badge.
- Reasoning/chain-of-thought stripping (`<think>…</think>`) + UTF-8 explicit decode (fixes the earlier mojibake/reasoning leak).
- Cache `ai_suggestion` keyed by `risk_key + evidence_hash`; deterministic fallback if the model is down.
- Router dependency map (`_DEPS`: materials → procurement) so "where do I get X" pulls suppliers too.

### 4.4 Observations / caveats
- **Cost & latency**: every question runs a full agent turn over a ~22–49 KB JSON evidence pack. The prompt is sent as a normal chat message.
- **Router is keyword-based**: an unusual phrasing that lands on the wrong keyword pulls a narrow section (the "include everything" fallback only triggers with *zero* keyword hits).
- **Same deployment, prompt-restricted**: the server-side agent answering the Tower is the same deployment agent; the "answer only from FACTS" constraint is prompt-enforced plus numeric validation, not a hard sandbox.
- **One shared thread**: all Tower users share `ai_thread_id`; conversation context is not per-user.

---

## 5. Security / hygiene notes

| Finding | Where | Severity |
|---|---|---|
| ERP API key+secret cached in plaintext inside the app folder | `backend/data/sas_creds.json` | HIGH — treat the folder as a secret. |
| SMTP password stored in plaintext SQLite (masked to the frontend via `password_set`, good) | `models.MailSettingsModel.password`, `backend/data/*.db` | HIGH — at-rest only. |
| SMTP defaults to Gmail + a shared app password | §3.1 | MEDIUM — single point of failure. |
| 93 broad `except Exception`, no logging | backend | MEDIUM — silent failures. |
| No VCS / no tests | project | MEDIUM. |
| `USER_JWT_TOKEN` passed as the `Authorization` header verbatim (no `Bearer ` prefix) to the chat stream | `ai_nextsteps._llm` | LOW — matches the platform's contract, but worth knowing. |

---

## 6. Recommended cleanups (no behaviour change)

| # | Action | Effort | Benefit |
|---|---|---|---|
| 1 | Delete dead `_build_risks`/`_build_recommendations` (L403–644); keep `_orig_ask_kogo`. | S | −240 LOC, removes stale client literals. |
| 2 | Move ERP `APP_ID`, SMTP host/port, `DEFAULT_COMPANY`, `SELLING_PRICE_LIST`, price-list/currency into config/env. | M | Reusable across workspaces. |
| 3 | Split `functions.py` into `snapshot.py`, `risks.py`, `charts.py`, `fabric.py`, `mail.py`, `inbox.py`. | M | Testability. |
| 4 | Collapse threshold defaults to `rulebook.json` only; move the two `n<10` rules into config. | S | One source of truth. |
| 5 | Add a `logs` sink (or at least count) for swallowed exceptions. | S | Observability. |
| 6 | Add unit tests for `rulebook`, `forecast`, `copilot._num_tokens`/`_clean`. | M | Regression safety. |
| 7 | `git init` + stop committing `.bak-*` files. | S | Recovery. |
| 8 | Encrypt or relocate `sas_creds.json` / mail password (env or keyring). | M | Security. |
| 9 | Make the copilot router fall back to "core + all relevant" on weak hits, and/or add a query-tool path. | M | Answer robustness. |

---

*Prepared read-only during the 2026-10-05 review session. No source files were modified.*

---

## Status update — 2026-10-05 (appster Edit-Flow cleanup applied)

| §6 item | Status | Note |
|---|---|---|
| 1 · Delete dead `_build_*` | **FIXED** | 242 lines removed; `ask_kogo` fallback intentionally kept. |
| 2 · Move constants to config | **FIXED** | `config.py` is now the single source; business code has zero `os.environ`. |
| 3 · Split `functions.py` | PARTIAL | Dead code removed (−242 lines); full module split still open. |
| 4 · One source of thresholds | **FIXED** | `_DEFAULTS` mirror completed + `trim` block added; `n<10` now config-driven. |
| 5 · Logging sink for swallowed errors | NOT DONE | Needs decision (observability, P2). |
| 6 · Unit tests | **FIXED** | `backend/tests/test_engine.py` — 71 checks incl. config-discipline + write-slug guards. |
| 7 · `git init` | NOT DONE | Out of scope for this edit; recommend separately. |
| 8 · Encrypt creds / password | NOT DONE | Needs your decision (security). |
| 9 · Copilot router robustness | NOT DONE | Documented; fallback already broadens on no-hit. |
| + NEW BUG | **FIXED** | rulebook `reinspection_fabric` vs writes `reinspection_s84` mismatch — Execute was dead for fabric-quality actions. |
