# Cortex Operations Control Tower — Architecture

## Active Sub-Skills
- core-builder: always

## Data Source
- **LIVE** from the client's KOGO ERP (Frappe / KOGO_SAS) via `backend/erp.py` — reads are GET-only; writes go through the opt-in, mode-gated `backend/writes.py` (drafts-only, reversible).
- No synthetic data. Local SQLite holds decision state only (`risk_state`, `action_state`, `audit_log`).
- Actions are previewed first; executing one performs a real ERP write and every action response carries `erp_write` + `mode`.
- Full contract: `LIVE_ERP_INTEGRATION_SPEC.md`.
- feature-module: NO — the analysis is deterministic over live ERP data; no live AI chat needed.
- chat-module: NO
- backend-tester: YES (Phase 6)

## Design Template: analytics-light (base structure/typography spacing), with brand colors overridden per explicit user design direction (navy/teal/amber/red).

## Entities (read live from KOGO ERP — see LIVE_ERP_INTEGRATION_SPEC.md)
- BuyerOrder   ← `Sales Order` (docstatus 1) + child `items`
- Risk         ← DERIVED live from ERP signals (BOM coverage, Delivery Notes, Fabric Quality,
                 Shipment variance, Work Orders, Trim MRs, Item Price, Payment Entries, Data Gaps)
- RecommendedAction ← DERIVED per risk (stable `action_key`)
- AuditLog     ← local SQLite (dashboard decisions only)

## Live ERP source
- Client's KOGO ERP (Frappe / KOGO_SAS) via `backend/erp.py`. Reads are **GET-only**; writes only through `writes.py` (opt-in, mode-gated `off|safe|draft|all`, drafts-only, reversible).
- Local SQLite holds decision state only (`risk_state`, `action_state`, `audit_log`).

## Base Functions
- get_dashboard (returns KPIs, risks, recommendations, audit log, chart data)
- get_buyer_orders, get_risks, get_recommendations, get_audit_log
- decide_action (approve/reject/execute)
- modify_action
- simulate_action (email / erp record preview + execution)
- ask_kogo (deterministic simulated analysis)
- get_email_preview, get_erp_preview
- run_action (executes approved action → updates risk status → audit log)

## Pages / Tabs
- Single full-width dashboard (state-based, no router)

## Step 0A Values (calibrated to THIS agent — 2026-09-29)
- API_BASE: https://agent.kogo.ai
- API_PATH: https://os.kogo.ai/api/v1/gateway
- TOOL_URL: https://preprod-tools.kogo.ai
- CHAT_API_PATH: https://os.kogo.ai/api/v1/chatai
- USER_ID: 6a97e9c5baf1f227d9ce4e03
- AGENT_ID: 6a97e9c6baf1f227d9ce4e33
- DEPLOYMENT_ID: 6a97e9c6baf1f227d9ce4e28
- SWARM_ID: 6a9e6b745b5ecf9923020aa0
- ORIGIN_ID: 6a9e6b745b5ecf9923020aa0  (= SWARM_ID, workspace context)
- PROJECT_SLUG: cortex_operations_control_tower
- PROJECT_DIR: artifacts/cortex-operations-control-tower
- SCRIPTS_DIR: skills/appster_skill/scripts
- DESIGNS_DIR: skills/appster_skill/designs

## Calibration History
- 2026-09-29 — Project imported from an uploaded `artifacts.zip` that had been built under a
  DIFFERENT agent (AGENT_ID 6a980dcbbaf1f227d9d187b4 / SWARM_ID 6a980f8bbaf1f227d9d1e195 /
  DEPLOYMENT_ID 6a980dcbbaf1f227d9d187bf). Recalibrated: moved to the canonical
  `artifacts/cortex-operations-control-tower/` location, rewrote `config.js` from this agent's live env
  (new AGENT_ID / DEPLOYMENT_ID / SWARM_ID / ORIGIN_ID), cleaned stale `__pycache__` + DB backup,
  the live ERP (Sales Order, BOM, Item, Fabric Roll, Trim Requisition Evidence, Material Request,
  Purchase Order/Receipt, Delivery Note, Sales Invoice, Payment Entry, Work Order, Fabric Quality
  Evidence, Garment Shipment Evidence, Production Daily Evidence, Migration Data Gap, Item Price). USER_ID was unchanged (same human). No frontend source change → no bundle rebuild needed
  (config.js is loaded at runtime; it is not inlined into index.html by the bundler).

## Detection engine (Phase 1 — 2026-10-05)
- Risks/recommendations are produced by `backend/rulebook.py` from `backend/rulebook.json` (thresholds).
- **Conditional, per-record** rules (per order/style/supplier/invoice/shipment) with **computed severity** and an **all-clear** state.
- Read-only over the live ERP; writes remain in the opt-in, mode-gated `writes.py`.
- See `backend/RULEBOOK.md`.

## Config discipline (appster core-builder) — 2026-10-05

`backend/config.py` is the **single source of truth**. No business module reads `os.environ` or
hardcodes an id/host/price-list. Integration constants are env-overridable with the current
production value as the default:

| Constant | Env var | Default |
|---|---|---|
| `ERP_APP_ID` | `ERP_APP_ID` | KOGO ERP app id (KOGO_SAS) |
| `ERP_WRITE_MODE` | `ERP_WRITE_MODE` | `draft` |
| `SELLING_PRICE_LIST` | `SELLING_PRICE_LIST` | `Standard Selling` |
| `DEFAULT_COMPANY` / `DEFAULT_CURRENCY` | `DEFAULT_COMPANY` / `DEFAULT_CURRENCY` | `Cortex Textile Limited` / `USD` |
| `MAIL_FROM_NAME`, `SMTP_HOST/PORT`, `IMAP_HOST/PORT` | same names | Gmail defaults |

Identity/URL values (`AGENT_ID`, `DEPLOYMENT_ID`, `SWARM_ID`, `USER_ID`, `KOGO_API_BASE`, `API_PATH`,
`CHAT_API_PATH`, `USER_JWT_TOKEN`) come from env only — never literal.

Guardrail: `backend/tests/test_engine.py` fails if any business module reintroduces `os.environ`.

## Write-path slug contract — 2026-10-05

`rulebook.py` emits action slugs (in each risk's `extra.slug`); `writes.py` must key its POLICY +
BUILDERS by the **same** slug, or Execute silently no-ops. The two are now covered by a test that
asserts `set(POLICY) == set(BUILDERS)` and that every rulebook-emitted writable slug resolves.
(Historical bug: `reinspection_s84` → `reinspection_fabric` mismatch, fixed.)

---

## 2026-10-08 — Cortex TnA Calendar merged into this app (single-tab consolidation)

The standalone **Cortex TnA Calendar** app was folded into the Control Tower so the user
opens **one app**, with the TnA planner as a single navigation tab.

### Backend
* New self-contained subpackage `backend/tna_app/` — the TnA backend verbatim (plan engine
  `tna.py`, live-ERP reader `erp.py`, overlay writer `writes.py`, own `models.py`,
  `database.py`, `bridge.py`, `config.py`) with **relative imports** (`from . import …`) so it
  cannot collide with the Tower's own `config` / `erp` / `models` / `database` / `writes`.
* Its SQLite overlay store lives at `backend/tna_app/data/cortex_tna_calendar.db` — **separate
  from the Tower DB** (both define an `audit_log` table). When the platform injects
  `DB_PATH_OVERRIDE`, the TnA store uses a distinct sibling file (`tna_app_<name>`).
* `backend/functions.py` imports the TnA registry and re-exposes every function through the
  Tower's `FUNCTIONS` dict. Each is wrapped so it runs against the **TnA** session (the Tower
  `db` is ignored). Three names collide with Tower functions, so the TnA variants publish under
  a `tna_` prefix: `tna_run_action`, `tna_rollback_action`, `tna_get_audit_log`.
* `backend/document.md` documents all 18 TnA functions (the middleware derives its callable
  allowlist from `### \`name\`` headings, so they are live immediately — no republish).
* Bundled data (`tna_template_woven_shirt.json`, `holidays_2026.json`,
  `tna_test_snapshot.json`) copied into `backend/tna_app/data/`.

### Frontend
* The whole TnA React app copied to `frontend/src/tna/` (pages Plan · Board · Calendar ·
  Program, OrderRail, StatusBand, NeedsAttentionRail, MilestoneDetailDrawer, IntakePanel …).
* `frontend/src/tna/index.css` is **auto-scoped under `.tna-root`** (every selector prefixed,
  `:root`/`html`/`body`/`#root` → `.tna-root`) so the two design systems cannot collide when
  bundled together.
* `frontend/src/views/TnaView.tsx` mounts `<TnaApp/>` inside `.tna-root`.
* New nav entry **TnA Calendar** (group **Plan**), `View` type `"tna"`, topbar title, and a
  full-bleed render branch in `App.tsx` (Tower beta banner + topbar are hidden on the TnA tab
  because the TnA app brings its own header).
* The embedded TnA UI calls the **same** middleware project (`cortex_operations_control_tower`)
  via its own `services/api.ts` — no cross-project hop.
* Rebuilt: `frontend/build.sh` → `index.html` (~1.67 MB, single self-contained file).

### Not changed
* `config.js` is unchanged (still `PROJECT: "cortex_operations_control_tower"`).
* The standalone `artifacts/cortex-tna-calendar/` project is left intact as a fallback; it can
  be archived once the user confirms the merged tab.

### 2026-10-08 — UX fixes (sidebar order, date anchoring, notice, collapsible panels)
* **Sidebar groups re-ordered** to Monitor → Plan → Analyse → Act → Audit (was Plan-first).
* **Collapsible main sidebar**: a chevron in the brand row collapses it to a 72px icon rail
  (`.sidebar.is-collapsed`); labels/counts become icons + dots.
* **TnA side rails are collapsible**: a `PanelLeftClose/Open` button in the TnA top bar toggles the
  left OrderRail and the right NeedsAttentionRail (`railsOpen` state in `src/tna/App.tsx`).
* **Calendar is anchored on today**: `monthsInWindow()` now always includes the as-of month, the view
  opens on the current month, the "Today" button always works, and an explanatory note states whether
  today is inside the order's plan window (with "Go to plan start"). An empty-month hint replaces a
  blank calendar.
* **Data-quality notice is compact + dismissible**: detail list collapsed behind a *Details* toggle,
  one-line summary, an ✕ dismiss (remembered for the session, re-appears only if the issue set changes),
  capped/scrollable list, `padding-right` so it never dominates the view.
* Note: the extra scoped rules live at the END of `src/tna/index.css` (which is otherwise
  auto-generated from the standalone TnA stylesheet) — keep them when regenerating.

### 2026-10-08 — TnA calendar now FOLLOWS today (self-rolling, no rebuild)
* `src/tna/App.tsx`: `as_of` is live — unless the user **pins** a date (`asOfPinned`), it rolls
  forward to the current date via a 60 s timer plus `focus`/`visibilitychange` checks.
* `src/tna/components/TopBar.tsx`: the advanced popover shows the mode ("Following today — rolls
  forward automatically" / "Pinned") with a **Follow today** reset button.
* `src/tna/pages/CalendarPage.tsx`: the month window already includes the live as-of month; a new
  effect **follows** the roll-over if the user was parked on the "today" month (otherwise their
  view is left untouched and only the "← today" marker moves).
* No backend change needed — `get_tna_calendar` already defaults `as_of` to today.
* Verified with a faked clock: open on 2027‑03‑15 → list extends to **March 2027 ← today**
  (selected); session open across Oct→Dec 2026 → auto-follows to **December 2026 ← today**.

### 2026-10-08 — Per-rail open/close (Orders · Needs attention)
* `src/tna/App.tsx`: the single `railsOpen` flag was split into **`leftRail`** and **`rightRail`**
  (both default open). Each rail now has its **own close control**, and when closed it renders a slim
  vertical **edge handle** (`.rail-handle--left/--right`) that reopens just that rail. The TnA top-bar
  button remains as a "toggle both" shortcut.
* `OrderRail.tsx` / `NeedsAttentionRail.tsx`: accept `onClose` and render a `rail-close` button in the
  panel header (`.rail-head-right`).
* `src/tna/index.css`: added `.rail-handle`, `.rail-close`, `.rail-head-right` (scoped under `.tna-root`).

### 2026-10-08 — Collapsible main sidebar + TnA rails
* Main Tower sidebar collapses to a 72px icon rail (`navCollapsed` in the Tower `App.tsx`,
  `.sidebar.is-collapsed`); TnA rails have per-rail controls (above).

## Order intake (2026-11-03) — mail → understanding → ERP drafts
- `backend/docread.py` reads a PDF (text layer), XLSX, CSV or text attachment with **no third-party
  library** (zlib + zipfile + ASCII85). A scan is flagged `needs_ocr`, never guessed.
- `backend/intake.py` turns the paper into facts: deterministic extraction merged with an LLM pass,
  **confidence per field**, arithmetic gates (`Σ lines = total`, `rate × qty = value`, `ship > PO date`),
  then matching (buyer, PO duplicate/revision, style, fabric via `Item Mapping`, FX) and routing.
- `backend/intake_exec.py` builds the ordered plan and executes it: **drafts only**, stops dependants on
  failure, records every created ref for one-click rollback, and composes the grounded acknowledgement.
- Storage: `mail_attachment` (bytes + extracted text), `intake_run` (one document = one decision,
  `source_key` unique), `intake_edit` (operator corrections).
- UI: **Order intake** tab — queue · "what it read" (each field editable, confidence chip) ·
  "what it will create" (ready/blocked with the reason) · the document · the reply.
- Nothing writes until `approve_intake`; nothing sends until the operator approves in Outbound Mail.

---

## 2026-11-07 — Workspace: one inbox, deals from inquiry to Sales Order

```
 IMAP (inbox + Gmail Sent) ─► sync_inbox (stores, classifies) ─► mailbox.assign_threads (X-GM-THRID / References)
                                                                   │
 UI (src/app) ──callApi──► deal_api.py ──► mailbox.py  (threads, reply in thread via mailer.send_via_smtp)
                                      └──► deals.py    (deal record; every ERP write → pipeline.execute → TSR runs the
                                                        Arinox scripts → ERP REST)
```

* **Modules added:** `bom_reader.py` (BOM sheets + style tables, pure), `mailbox.py` (threads), `deals.py` (flow),
  `deal_api.py` (guarded functions), `models_deal.py` (`deal`). Registered at the bottom of `functions.py` and bridged.
* **Changed:** `inbound.classify` (inquiry class, scoring, quoted text ignored, PO document decisive; `fetch_sent`,
  `X-GM-THRID`), `mailer` (Cc), `sync_inbox` (stores thread headers; reads the order book only when mail arrived),
  `pipeline` (previews return the computed document), `tsr/shim.py` (`doc.set` makes child rows, rows numbered,
  `run_method` for the two ERPNext totals methods), `tsr/journal.py` (`create_variant` is read-only).
* **Runtime bugs fixed on the way (they blocked the flow on the real ERP too):** `doc.set("charges", [dicts])` stored
  dicts, so `arinox_cost_sheet_validate` crashed and no Cost Sheet could be saved; new child rows had no `idx`, so
  `arinox_price_negotiation_validate` crashed on every round; `doc.run_method` did not exist, so no Quotation could be
  built; `create_variant` returned None in preview, so no Sales Order could be made.
* **Frontend:** a new shell (`src/app/Workspace.tsx`) replaces `cx/Shell.tsx` (kept, unused). The heavy `get_dashboard`
  read now runs only when a legacy analysis screen opens.
