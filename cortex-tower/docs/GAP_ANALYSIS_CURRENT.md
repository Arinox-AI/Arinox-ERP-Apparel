# Cortex Control Tower — Gap Analysis (CURRENT STATE)
## After Phase 1 · live · generic · 2026-10-05

**Scope:** all ERP data + the Tower. **Live write check:** re-run now.

---

## 0. Does the Tower change the ERP live? ✅ YES (re-verified just now)
- Executed `MDG_OPEN::assign_data_owners` → ERP `Task` count **0 → 1** (`TASK-2026-00001`)
- `rollback_action` → **1 → 0**
- Mode-gated (`off|safe|draft|all`), drafts-only, idempotent, reversible.

---

## 1. What is now DONE (Phase 1 — generic engine)
- **18 conditional, per-record rules** in `backend/rulebook.py`; thresholds in `rulebook.json`.
- **Severity computed** from magnitude + days-to-deadline + USD/%; **"all clear"** state (`risk_summary`).
- Live result: **56 risks (15 critical / 41 warning)** + 56 generic next-steps.
- **Generic** — proven: a synthetic brand-new style/order fired `BOM_MISSING_ORDER`, `WORK_ORDER_MISSING`, `NO_DELIVERY_NOTE`. **No tailored literals** in the active engine.

---

## 2. GAP A — Visibility for all types / danger / warnings

### 2.1 ERP entities with data that the engine still does **not** monitor
| ERP entity (rows) | What it would catch |
|---|---|
| **Job Card** (28) | schedule slippage, idle/overloaded capacity |
| **Stock Entry** (14) | material issue/receipt vs plan |
| **Batch** (15) | lot traceability gaps |
| **Fabric Inventory Variance** (10) | unexplained fabric loss |
| **Garment Production Progress** (10) | per-order progress vs plan |
| **Trim Requisition Evidence** (17) | requisition→order conversion |
| **Washing Service Evidence** (11) | wash yield / rejection |
| **Internal Costing Evidence** (5) | margin: contract price vs actual cost |
| **Sales Contract Evidence** (5) | contract terms vs Sales Order |
| **Client Purchase Order** (13, new link) | PO ↔ SO quantity/price reconciliation |
| **Customer** (3) / **Supplier** (10) | credit limit / supplier reliability score |
| **Item Price** (63) | pricing drift vs order rates |
| **Communication** (1) | unanswered buyer queries |
| **Shipment** (0) / **Payment Request** (0) | ETA/ETD vs promise; collections |

### 2.2 Danger classes still without a home
credit/customer risk · capacity & load · supplier reliability scoring · receivables/cash **aging** (only "overdue" today) · full logistics-document **compliance** · roll-level quality · order-amendment · **data freshness** (stale ERP data).

### 2.3 Behaviour gaps
- **No push / real-time** — the engine recomputes on read; there is no scheduled scan or alert yet.
- No threshold **UI** (config is a file), no per-rule **enable/disable**, no severity tuning in-app.
- Risk-type vocabulary is mapped onto the old 7 types (frontend not rebuilt) — cosmetic.

---

## 3. GAP B — Preventive measures

**Present:** fabric shortage vs received rolls · PO late · production shortfall · payables outstanding.

**Still missing:**
1. **Trim stock / reorder points** — Bin has trim stock; no demand-vs-stock trim rule yet.
2. **True lead-time** — `PO_LATE` is *retrospective* (already late). No *"will be late"* projection from supplier lead time.
3. **Capacity vs delivery window** — Job Cards exist but aren't used to detect overload.
4. **Safety stock / buffers** and **incoming quality gates** (schedule inspection before use).
5. **Scheduled monitoring** — no heartbeat/cron; nothing alerts you unprompted.
6. **Risk lifecycle** — no owner/assignee, due date, acknowledge, snooze, escalate.
7. **Threshold config surface** (edit thresholds without touching code).

---

## 4. GAP C — AI suggesting the next steps

- Recommendations are now **generated generically from rule metadata** (per record, evidence in the title) — far better than the old hard-coded table — but this is **not an LLM**.
- Missing: a **grounded LLM layer** over the live fact pack that gives free-form reasoning, **ranked alternatives**, **confidence**, and multi-step plans; plus a grounding guard (no invented numbers).
- Housekeeping: the **old tailored code is still in `functions.py`** (lines ~479 `"Da Nang sewing"`, ~573 `reinspection_s84`, ~1252 `"Standard Selling"`) — overridden/unused, but should be removed for cleanliness.

---

## 5. GAP D — Predictive measures

- **Present:** `PRODUCTION_SHORTFALL` (packed vs ordered + days left, escalates as the date nears).
- **Missing (data is already there):**
  1. **Delivery-date risk probability** (run-rate × days remaining vs ordered).
  2. **Stock-out forecast** (fabric/trim consumption vs stock + incoming).
  3. **Margin erosion** (contract/sell price vs costing).
  4. **Cash forecast** (receivables + payables aging).
  5. **Supplier-delay probability** (PO→PR lag history).
  6. **Capacity forecast** (load vs window). The **153-row Production Daily Evidence** + shipment history are the training signal and are currently unused for forecasting.

---

## 6. Generality (future orders, not tailored) — status
- Active engine: **config- + entity-driven, no style/order literals** ✅ (synthetic new order proved it).
- Remaining: delete the **dead tailored code** in `functions.py`; consider rebuilding the frontend so new risk types (supplier/cash/compliance/logistics) show natively instead of being mapped.
- Real **data** limitations (not code): per-size BOM consumption not supplied; no OCR (deferred).

---

## 7. What to do next (priority order)
1. **Phase 3 — grounded AI next-step layer** (LLM over the live fact pack, evidence-cited, generic).
2. **Phase 4 — forecasting** (delivery risk, stock-out, margin, cash, supplier delay) from the production/shipment history.
3. **Phase 2 extras — scheduled monitoring** (heartbeat/cron → push alerts) + **risk lifecycle** (owner/ack/escalate) + **threshold UI**.
4. **Coverage** — add the §2.1 entities (Job Card, Stock Entry, Batch, variances, costing, Client PO reconciliation).
5. **Cleanup** — remove dead tailored code; optionally rebuild frontend for native new risk types.

## Bottom line
Phase 1 turned a hard-coded dashboard into a **generic, live, per-record detection engine** — and the writes are confirmed live on the ERP. What remains is the **forward-looking brain**: grounded AI next-steps (Phase 3), forecasting (Phase 4), and autonomous monitoring/prevention + lifecycle (Phase 2 extras), plus a few unmonitored entities.

---

# UPDATE — Phase 3 (grounded AI next-step layer) — ✅ BUILT (2026-10-05)

- New `backend/ai_nextsteps.py` + cache models (`ai_suggestion`, `app_kv`).
- **Grounded LLM** (KOGO agent stream): each live risk → reasoning + 1-3 actions with
  owner/priority/confidence + predicted impact + watch-outs.
- **Validation:** every narrative number checked against the closed evidence pack;
  unsourced numbers recorded and the suggestion flagged. (Live: 12/12 grounded.)
- **Cache + fallback:** one row per risk, invalidated when live facts change; falls back
  to the deterministic action if the model is unavailable. Never blocks the dashboard.
- **Wired in:** `get_dashboard` attaches cached `risk["ai"]`; the Tower **risk drawer**
  now renders the "AI next steps" card (bundle rebuilt, `config.js` first script).
- **Generic:** evidence pack + prompt are built from rule metadata → new risks get AI
  next-steps automatically.
- Live sample: `PAYMENT_OVERDUE#ACC-SINV-2026-00001` → grounded plan citing the USD 25,612.00
  outstanding / 289-day ageing, with dunning + credit-hold actions owned by Finance/Credit Control.
- Operational: generation is out-of-band (already run for the top 12); a scheduled task can
  refresh it. `get_ai_next_steps` is registered for the next project publish.

**Remaining:** Phase 4 (forecasting), Phase 2 extras (scheduled monitoring, risk lifecycle,
threshold UI), coverage of the §2.1 entities, dead-code cleanup.

---

# UPDATE — Phase 2 (proactive monitor + push alerts) — ✅ BUILT (2026-10-05)

- New `backend/monitor.py`: scans the live engine and **pushes an email alert** when a
  **new critical** appears (or a warning escalates to critical).
- **Baseline-safe** (first run seeds state + one "armed" summary; then alerts only on change),
  **throttled** (`maybe_run`, 25-min cooldown), **best-effort** notify (reuses SMTP),
  **read-only** on the ERP. State in `app_kv`; every run audited.
- Wired: `get_dashboard` calls the throttled scan; `run_monitor` registered in `FUNCTIONS`.
- **Scheduled:** KOGO agent heartbeat "Cortex Tower — live monitor" (Operations, every 25 min)
  runs it out-of-band → alerts fire whether or not anyone opens the Tower.
- **Verified live:** first run sent "Cortex Tower — monitor armed (critical baseline)"
  (confirmed in Gmail); second run was silent (no change).
- Docs: `backend/MONITOR.md`.

**Remaining roadmap:** Phase 4 forecasting; copilot chat; risk lifecycle + threshold UI;
§2.1 entity coverage; dead-code cleanup.

---

# UPDATE — Phase 4 + copilot + UI (2026-10-05)

- **Scheduler PAUSED** per request — the "Cortex Tower — live monitor" heartbeat was removed.
  (The monitor code + `run_monitor` remain; re-enable the heartbeat anytime.)
- **Phase 4 `backend/forecast.py`** — delivery risk, stock-out cover, margin (scale-guarded),
  **cash per currency**, supplier performance. Served on the dashboard as `forecast`.
  Data-integrity fixes: VND vs USD never summed; margin suppressed when costing currency differs.
- **Copilot** — `ask_kogo` upgraded to a grounded LLM over a live fact digest (fallback to the
  deterministic answerer; every number validated against the digest, `grounded`/`unsourced`).
- **Dashboard** now also exposes `migration_gaps` (17) for a future gap view.
- **Frontend** — new **Forecast** view (Analyse group); bundle rebuilt.
- Docs: `backend/FORECAST.md`.

**Remaining:** track-and-trace per order; Migration-Gap UI; threshold/rule config UI;
§2.1 entity coverage; dead-code cleanup; publish the project so the new functions
(`get_ai_next_steps`, `run_monitor`) become callable via the API.
