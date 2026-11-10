# Cortex Tower: from Sales Order to cash — build plan

**Written 2026-11-09. For the agent that builds it.** Read all of it before writing code. Every slice ends with a gate; do
not start the next slice until the gate passes, and quote real command output when you say it did.

Decisions already made by the user (2026-11-09) — do not re-open them:

| # | Decision |
|---|---|
| D1 | **The tower runs the Arinox Server Scripts** through its Tower Script Runtime (TSR) while `server_script_enabled` is off on the live ERP. Any *new* business rule is written as a Server Script in `arinox_apparel/portable/hosted_scripts/` (so it runs natively the day the flag is on), never as tower-only Python. |
| D2 | **One Order page per Sales Order**, same look and behaviour as the Deal page, with its own step bar. Opened from the Deal's "Sales order" step and from the order book. |
| D3 | **Where to produce: the tower suggests, the planner approves.** A deterministic, explainable suggester drafts the Factory Allocation; a person edits and saves it. |
| D4 | **T&A: build the whole of `TNA_PRODUCTION_GRADE_PLAN.md`** (in the tower zip, all six phases), with its section 16 recommendations taken as the answers unless the user says otherwise. |
| D5 | **(2026-11-09) Calendars:** every day is a working day, at every site (VN factory, CN supplier, HK office). No holiday list, no Saturday/Sunday rule, for now. The working-calendar code stays (so holidays can be added later as data) but the seeded calendars are 7-day with zero holidays. TNA plan section 16 item 3 is therefore answered. |
| D6 | **(2026-11-09) Evidence:** wire **all** the Arinox evidence documents (every row of the TNA plan section 8.1 rule table, i.e. Sample Approval, PP Meeting, requisitions, PO/PR, Fabric/Trim Inspection, Cut Plan, Daily Line Report, Line QC, Pilot Run, Packing List, Final Inspection, Shipment, Delivery Note, invoices) from the start. TNA plan section 16 item 6 is answered. |
| D8 | **(2026-11-09, supersedes D7's "use as seeds")** The company documents are **reference only**. The product is generic: no company value is ever a default in code, seeds or tests; fixtures are synthetic. See `AGENT_ARCHITECTURE.md` §8. |
| D9 | **(2026-11-09)** The tower is an **agent behind the ERP** (sense, understand, decide, approve, act, learn), with KOGO as its brain and clock, not a dashboard. Architecture and build order after T1: `AGENT_ARCHITECTURE.md`. |
| D7 (superseded by D8) | **(2026-11-09) Test data:** the company's own documents (`Arinox AI ERP Documents - 2.zip`, indexed in `reference/DOCUMENT_INDEX.md`) are the truth for seeds, templates and fixtures: the T&A WIP sheet (`8 - T&A WIP/23 OCT WIP DUMMY.xlsx`, the 61 milestones and their real offsets), the operation bulletin (`3 - Production/4 - BELLADAHL OBS R&D.xlsx`: 480 min, SAM, efficiency), the production reports, the sales contracts and POs, the packing lists and invoices. Learn lead times and defaults from them; do not invent. Real prices/PO numbers stay out of git. |

---

## 1. Why the post-order half is weak today (the diagnosis this plan fixes)

The inquiry → Sales Order half works because each step of `app/DealPage.tsx` is backed by `backend/deals.py`, and
every write goes `pipeline.execute → TSR → the real Arinox scripts → ERP REST`. After the Sales Order that pattern stops:

| Area | What the tower does now | Why it is wrong |
|---|---|---|
| Production WIP (`wip_plan.py`, `wip_actions.py`, `WipPlanView.tsx`) | reads the `Cortex WIP` doctype | an older Cortex "evidence" model, **not** on the Arinox site; Arinox has Production Card + Production Movement ledger |
| T&A calendar (`backend/tna_app/`, `frontend/src/tna/`) | own 61-code JSON template, own SQLite overlay, reads `Client Purchase Order`, `Production Daily Evidence` | those doctypes do not exist; the ERP's `Order TNA` has 0 rows; nothing propagates (see TNA plan §2–3) |
| Ship & track (`ship_track.py`, `TrackStep.tsx`) | dates derived from contract terms + Shipment read | good, but it is the only post-order screen; no packing, inspection, DN, invoice |
| Deal "Sales order" step | shows counts of follow-on docs and two buttons | no way to plan, allocate, produce, pack, ship, invoice from the tower |
| Everything else (Factory Allocation, Sample Approval, PP Meeting, requisitions, POs, inspections, Production Card, Cut Plan, line reports, subcontract, finishing, Packing List, Final Inspection, Shipment, invoicing, claims, close) | only the generic "ERP records" list | the 60 post-order API scripts that already exist are never offered as steps |

**The ERP layer is already complete** (Phases B–E, 242 hosted scripts, 82 API scripts, 253 hosted tests green). This
plan is ~90 % tower work. New ERP work is limited to gaps the suggester and T&A need (listed per slice, each a Server
Script + hosted test).

---

## 2. Sources to read first

| What | Where |
|---|---|
| The tower | zip `cortex-tower2/cortex-operations-control-tower (5).zip` → unpack per Slice 0. Read `HANDOFF.md`, `ARCHITECTURE.md` (last two sections), `FIXES_2026-11-09.md`, **`TNA_PRODUCTION_GRADE_PLAN.md` in full**, `backend/deals.py` (`erp_status`, `make_order`), `backend/deal_api.py`, `backend/cortex_api.py` (`cx_run_script`, `cx_write`), `backend/pipeline.py`, `backend/tsr/`, `frontend/src/app/DealPage.tsx`, `TrackStep.tsx`, `kit.tsx`, `Workspace.tsx` |
| The skill it is built with | `appster_skill_1792213975950.zip`: `SKILL.md`, `sub-skills/core-builder/SKILL.md` (hard rules), `backend-tester` |
| The Arinox ERP layer | `arinox-apparel/doctypes/PHASE_B_PLAN_AND_APPROVE.md`, `PHASE_C_MATERIALS_PLAN.md`, `PHASE_D_PRODUCTION_PLAN.md`, `PHASE_E_SHIP_AND_COLLECT_PLAN.md`, `HOSTED_BUILD_GUIDE.md` §3 (sandbox rules), §4 (port recipe), `portable/manifest_hosted.json`, `portable/HOSTED_STATUS.md` |
| The KOGO loader | `cortex-tower2/apparel-modules.zip` → `v2/README.md`, `v2/INTEGRATION.md` (how the bundle reaches the live site; scripts there are parked `disabled=1`) |

Appster hard rules that apply to every slice: frontend calls only the middleware (`call`/`callApi`); no servers; every
call is a fresh subprocess (~30 s budget, no in-memory state); `config.py` is the only env reader; every public
function has a `### \`name\`` heading in `backend/document.md`; KOGO SSO + permission checks on every function;
bundle with `frontend/build.sh`, `config.js` stays first and un-inlined.

---

## 3. Architecture of the new half

```
 DealPage ── step 6 "Sales order" ──► OrderPage(so)              Order book / Production board / T&A / Shipments
                                         │                              │
                                         ▼                              ▼
                           order_api.py (guarded fns) ──► order_flow.py (read model, one batched read per SO)
                                         │                       └─► step states, blockers, next action, by_step ERP pages
                                         ├─► allocation.py (suggester, pure)       ◄─ arinox_factory_allocation_get_planning_context
                                         ├─► tna_app/ (rebuilt per TNA plan)       ◄─► ERP Order TNA / TNA Milestone
                                         └─► pipeline.execute ──► TSR ──► arinox_* API + DocType Event scripts ──► ERP REST
```

Rules:

1. **One read model per order.** `order_flow.status(be, so)` reads every follow-on document of the Sales Order in batched
   `get_list` calls (filter by `sales_order` / link fields; chunk `in` lists by 100) and returns
   `{steps:[{key,state:"todo|doing|done|blocked|na", counts, docs:[{doctype,name,status,docstatus,url}], blockers:[text], next:{text,action}}], by_step, focus, kpis}`.
   Model it on `deals.erp_status`. Cache per request only. Target < 6 s for an order with 10 style×colour lines.
2. **Every write is a script call or a document write through the pipeline**: `cx_run_script(method, params)` or
   `cx_write(op, doctype, ...)`. No direct `erp.erp_create/update`. `test_pipeline_guard.py` already enforces this — extend
   its allowlist only for new modules, never weaken it.
3. **Preview first** for every action that creates or submits (the pipeline's preview mode); ledger-posting submits
   (Stock Entry, Delivery Note, Sales Invoice, Purchase Receipt) are `risky` class → explicit approval, as today.
4. **ERP links** only via `erp.url_for(doctype, name)` (FIXES_2026-11-09 §2). Never assemble a desk path.
5. **New rule needed? Server Script first.** Write it in `arinox-apparel/arinox_apparel/arinox_apparel/portable/hosted_scripts/`,
   register in `manifest_hosted.json`, add a hosted test, `hosted_sync.sh` + `hosted_tests.sh` green, then
   `tools/vendor_scripts.py` into the tower and regenerate `arinox-apparel/hosted_bundle/` (`portable/export_bundle.py`).
   Note in the slice log that the KOGO copy (`apparel-modules/v2/hosted_bundle/17_server_scripts.json`) needs the same
   change at the next load.
6. **Retire, do not delete, the old readers.** `wip_plan.py`, `wip_actions.py`, the `Cortex WIP` / `Client Purchase Order`
   / `Production Daily Evidence` reads: gate them behind `erp_profile` ("cortex_evidence" vs "arinox"); when the Arinox
   layer is present (it is on the live site) the new readers are used and the old screens leave the sidebar.

---

## 4. The Order page

Route `#/orders/<sales order>`; component `frontend/src/app/OrderPage.tsx`, split into one file per step like
`TrackStep.tsx`. Header: buyer, contract, style count, qty, value, ex-factory, days to ex-factory, overall RAG (from the
T&A). Under it: the "next" banner (same component as the Deal page), a **T&A strip** (this order's milestones, one row,
today marker, late in red — click opens the calendar on this order), then the step bar. Right column: "In the ERP"
document list (every follow-on doc, grouped by step, with ERP link) and the order timeline (ERP Comments + tower audit).

Each step screen has the same three blocks: **Status** (what is done, counts, blockers in plain sentences),
**Documents** (table: name, style/colour, status, owner, date, ERP link, open-in-tower drawer), **Actions** (buttons that
call the existing API scripts, each with preview → confirm). Data entry for floor documents uses the existing generic
`FormSheet`/`DocSheet` (cx/views/Docs.tsx), opened **pre-filled** from the step (sales order, style, colour, factory, line
already set). Bespoke widgets only where named below.

| # | Step | ERP documents | Existing scripts the step calls | Bespoke UI | Done when |
|---|---|---|---|---|---|
| 1 | **Confirm** | Sales Order | (submit stays an ERP action, as on the Deal page; tower shows docstatus and the link) | — | SO submitted |
| 2 | **Plan & allocate** (where to produce) | Factory Allocation (+Line), Plant Floor, Workstation, Operation Bulletin | `arinox_factory_allocation_get_planning_context`, `_get_lines_from_order`, `_save_allocation` | **Allocation board** (§5) | allocated qty = order qty (within tolerance) for every style×colour, PCD set |
| 3 | **T&A plan** | Order TNA, TNA Milestone, TNA Template | `arinox_planner_make_order_tnas`, `arinox_order_tna_lock_baseline/unlock/replan`, `arinox_api_get_tna`, `arinox_api_update_milestone` + new tower scheduler (TNA plan §6) | order Gantt (reuse `tna/components/GanttChart.tsx`) | plan exists, feasible, baseline locked |
| 4 | **Samples & PP** | Sample Approval (+rounds), PP Meeting, Work Order bulk gate | `arinox_sample_approval_get_sample_rules`, `_get_sampling_milestones`, `_load_spec_from_tech_pack`, `_load_standard_tests`, `arinox_pp_meeting_add_standard_participants`, `_load_from_requisitions`, `_get_buyer_comments`, `arinox_work_order_get_bulk_gate` | **Approval matrix** (sample type × style×colour, cell = status, click = rounds drawer); **bulk gate card** (green/red per style×colour with the missing items) | every required approval in, PP Meeting submitted, gate green |
| 5 | **Materials** | Fabric/Trim Requisition, Purchase Order, Purchase Receipt, Fabric/Trim Inspection, rolls | `arinox_fabric_requisition_get_lines_from_sales_orders`, `_save_`, `_revise_`, `_create_fabric_items`, `_get_requisition_context`, trim equivalents, `arinox_purchase_order_make_purchase_orders`, `arinox_rolls_import_roll_list`, `arinox_fabric_inspection_load_rolls`, `_make_inspection`, `_make_purchase_return`, `arinox_trim_inspection_make_inspection` | **Material status table** per material: required / ordered / received / passed / short, ETA vs PCD (from `lib_material_status.py` logic, through a report or API script) | all bulk material passed and in house before PCD |
| 6 | **Cut & sew** | Production Card, Work Order, Pilot Run, Cut Plan, Lay Report, Line Input, Daily Line Report, Line QC Report, Operation Bulletin | `arinox_production_card_get_production_context`, `_save_production_card`, `_get_card_lines`, `_get_summary`, `_get_production_status`, `_revise_`, `arinox_operation_bulletin_activate`, `arinox_cut_plan_suggest_rolls`, `_approve`, `_release`, `_reopen`, `arinox_cutting_get_issuable_rolls`, `_issue_fabric` | **Production matrix**: stage (cut, input, sewn, QC pass, finished, packed) × colour × size from `_get_summary`, with % of order and today's output | sewn ≥ order qty (± tolerance) |
| 7 | **Subcontract & finish** | Subcontract Challan / Return / Settlement, Finishing Receipt | `arinox_subcontract_challan_short_close`, `arinox_subcontract_settlement_make_invoices` | out/back balance per process (wash, print, embroidery) | nothing out at a subcontractor, finishing received |
| 8 | **Pack & inspect** | Packing List (+cartons, SSCC), Final Inspection, Needle Detector Log | `arinox_packing_list_generate_cartons`, `arinox_final_inspection_pick_cartons` | **Carton plan** (ratio/solid, cartons per size, totals vs order) | packing list submitted, final inspection passed |
| 9 | **Ship** | Shipment (+containers, docs), Delivery Note, Letter of Credit | `arinox_shipment_get_available_packing_lists`, `arinox_shipment_make_delivery_notes`, `arinox_freight_allocated_costs` | **Shipment wizard**: pick packing lists → create Shipment → make DNs (risky, approval) → booking/BL/tracking; **move today's `TrackStep` here** (clocks, papers, incoterm) and keep the Deal step 7 as a link to it | DN submitted, on board |
| 10 | **Invoice & collect & close** | Sales Invoice, Payment Entry, Buyer Claim, close | `arinox_invoicing_prepare_invoices`, `_submit_invoices` (risky), `arinox_followup_log_follow_up`, `arinox_buyer_claim_make_credit_note`, `arinox_close_get_checklist`, `arinox_close_commercial_close` | receivable card (due date, days overdue, follow-up log) and the close checklist | commercially closed |

Steps run in parallel in reality (samples and materials overlap): the step bar shows each step's own state, not a
single "current" position. The "next" banner picks the most urgent open item across steps, using the T&A (the
earliest late or due-soon critical milestone wins).

---

## 5. Where to produce: the allocation suggester (D3)

New pure module `backend/allocation.py` (no ERP calls; input is the planning context, output is a draft — fully unit
testable). Function `order_api.order_allocation_suggest(sales_order)` = planning context (existing API script) +
Operation Bulletins + working calendar → `allocation.suggest(ctx)` → draft lines + reasons. Saving is the existing
`arinox_factory_allocation_save_allocation` with `planned_by = "AI Agent"` and the reasoning in `agent_notes`
(both fields exist).

**Capacity per line per day** (pieces):
`operators × shift_minutes × efficiency ÷ SAM`
- operators: `Workstation.apparel_default_operators` (custom field, exists);
- SAM and efficiency: the style's active `Operation Bulletin` (`sewing_sam` / `total_sam`, `expected_efficiency_pct`);
  fallback a per-Product-Type default in Apparel Settings (**new settings fields**, seeded, editable); if neither exists the
  line is shown as "capacity unknown" and the suggester will not place work on it silently;
- shift minutes and working days: the factory's Holiday List + a shift length setting (**new**, Apparel Settings, default 480);
- learning curve: `Learning Curve Day` rows if present (day 1..n efficiency factors) applied to the first days of a new style
  on a line.

**Load already on the line**: `other_allocations_in_window` from the context, spread evenly over each allocation's
sewing window.

**Algorithm** (deterministic, so the same order gives the same suggestion):
1. Sewing window per style×colour: `sewing_end = ex_factory − finish_pack_days` (template value, per product type),
   `sewing_start = sewing_end − ceil(qty ÷ achievable daily output)`; `pcd = sewing_start − cut_lead_days`.
2. For each line of a factory whose `apparel_line_type` fits the product type: free capacity in the window = Σ day capacity
   − Σ existing load.
3. Score = fit (line type match) → slack (days between sewing_end and ex-factory) → keep one style×colour on one line
   (fewer changeovers) → same factory for all colours of a style → lowest load. Split a style×colour over lines only
   when no single line fits; never split below a minimum batch (setting, default 500 pcs).
4. Output per line: factory, line, qty, pcd, sewing_start, sewing_end, and a **reason sentence**
   ("Line 3 at Factory A: 1,200 free pcs in 14–29 Jan, same line type, 6 days slack"). Lines that cannot fit return a
   **shortfall** with the earliest feasible ex-factory, never a silent over-load.
5. Feed the T&A: the allocation's PCD/sewing dates become the scheduler's anchors (TNA plan §6.1).

**Allocation board UI**: rows = style×colour (qty, ex-factory); columns = lines grouped by factory with a 8-week load
strip; the suggestion pre-filled and editable (factory, line, qty, dates); live validation from the existing
`factory_allocation_validate` rules surfaced before save; "Why this?" shows the reason sentence.

**Setup step** (shown when no Plant Floor / Workstation / SAM exists): a short checklist with links to create factories,
lines (operators, line type) and the shift setting, plus an "import from sheet" for lines. Do not invent factories.

---

## 6. T&A (D4): the whole `TNA_PRODUCTION_GRADE_PLAN.md`

Build it as written, with these bindings to this plan:

- Its decisions table (§16) is taken at the recommendations: (1a) ERP `Order TNA` is the plan of record, the tower
  computes; (2c) ERP codes + seeded extra types (Appendix C); (4b) capacity per department line-days per week — **use the
  allocation's line capacity from §5** rather than a second capacity model; (5) merchandising manager approves a replan
  that moves ex-factory; (7) email alerts first; (8) PDF pack in its phase 5; (9) monitor sample gates. Items 3 (real
  calendars) and 6 (which evidence documents first) need the user — ask at the start of its Phase 0, do not guess.
- Its evidence rules (§8) read the **Arinox** documents the Order page steps create (Sample Approval, PP Meeting,
  requisitions, PO/PR, inspections, Cut Plan, Daily Line Report, Packing List, Final Inspection, Shipment, DN). No reader
  of `Client Purchase Order` / `Production Daily Evidence` / `Cortex WIP` survives.
- The calendar, board, program and owner views stay; the Order page's T&A strip and step 3 are thin views over the same
  engine. One scheduler, called from one place.
- Its phases slot into the slice order below (T0–T6).

---

## 7. The rest of the surface

- **Sidebar** (`Workspace.tsx`): replace the "Operations" group with **Orders**: Order book (Sales Orders with the
  `order_flow` step chips and T&A RAG per row, opens OrderPage), Production board (all orders' production matrices
  summarised; replaces "Production WIP"), T&A calendar, Shipments, Receivables. Remove `more/wip` once the board ships.
- **Deal page step 6**: keep "Make the Sales Order"; once it exists, the card shows the order's step chips and one
  button **Open the order** (→ OrderPage). Step 7 "Ship & track" becomes a link into OrderPage step 9.
- **Today / dashboard**: add my-queue items from `order_flow` blockers (allocation missing, gate red, material short
  vs PCD, inspection failed, invoice overdue) — role-filtered.
- **Reports**: the 17 script reports already run through the TSR; link the relevant ones from each step (material
  status, line efficiency/DHU, contract delivery schedule, receivables).

---

## 8. Slices (build order) and gates

Effort is for one experienced developer; the T&A numbers come from the TNA plan. Every slice: tests first or with the
code, `python3 tests/<new>.py` green, the whole existing suite re-run (`test_deals`, `test_pipeline_guard`,
`test_tsr_core`, `test_ship_track`, `test_erp_links`, `test_contract_amend`, `test_costing_sheet`), `bash build.sh`
(tsc clean), and a dated entry in `cortex-tower/ORDER_TO_SHIP_STATUS.md` (what was built, verified, not verified).

| Slice | Content | Gate |
|---|---|---|
| **S0 Setup** (1 d) | Unpack the tower zip into `/workspaces/Arinox-ERP-Apparel/cortex-tower/` **including** `backend/data/` (local only), add `cortex-tower/.gitignore`: `backend/data/`, `*.db`, `*.db.*`, `sas_creds.json`, `secret_key.bin`, `mail/`, `node_modules/`, `__pycache__/`, `dist/`. Start `docker start apparel-mariadb apparel-redis`, serve `hosted.localhost:8001` (RECORD_2026-11-06 "How to resume"). Baseline: run the tower suite and `hosted_tests.sh`; record results | `git status` shows no file under `cortex-tower/backend/data`; baseline recorded verbatim |
| **S1 Read model** (3 d) | `order_flow.py`, `order_api.py` (`order_get`, `order_list`), `document.md` headings, `erp_profile` switch; tests on FakeERP with a seeded order covering every step state | `tests/test_order_flow.py` green; `order_get` on `hosted.localhost` for a demo order < 6 s (measured) |
| **S2 Order page shell** (3 d) | `OrderPage.tsx` header, step bar, side panel, timeline, Status/Documents blocks for all 10 steps (read-only), Deal step 6 → "Open the order", sidebar Orders group, Order book | tsc clean; Playwright screenshot at 1440 and 390 px, no console errors |
| **S3 Allocation** (5 d) | `allocation.py` + Apparel Settings fields (Server Script / seed side per §3 rule 5) + allocation board + setup checklist | unit tests for the algorithm (fit, split, shortfall, learning curve, determinism); a save through TSR on `hosted.localhost` creates `FA-<SO>` and passes `factory_allocation_validate` |
| **T0 T&A foundations** (6–8 d) | TNA plan Phase 0 (ask the user items 3 and 6 first) | TNA plan §13.4 gate for Phase 0 |
| **T1 Scheduling** (10–13 d) | TNA plan Phase 1; anchors from the allocation | TNA plan gate; Order page step 3 + strip live |
| **S4 Samples & PP** (4 d) | step 4 actions + approval matrix + bulk gate card | create Sample Approvals from rules and a PP Meeting through TSR; gate turns green only when the hosted test's conditions hold |
| **S5 Materials** (5 d) | step 5 actions + material status table | requisition → PO → (PR in ERP) → inspection round trip on `hosted.localhost` through TSR |
| **T2 Evidence** (6–8 d) | TNA plan Phase 2, wired to the documents S4–S5 create | stamped actuals match the documents |
| **S6 Cut & sew** (6 d) | step 6 + production matrix; WIP board reader replaced | a Daily Line Report submitted through the tower posts Production Movement once; matrix totals = ledger |
| **S7 Subcontract & finish** (3 d) | step 7 | challan out → return → settlement balance correct |
| **S8 Pack & inspect** (4 d) | step 8 + carton plan | generate cartons, final inspection pick + AQL result through TSR |
| **S9 Ship** (5 d) | step 9 wizard; TrackStep moved in; DN creation as risky with approval | Shipment + DN created on `hosted.localhost`; `test_ship_track.py` still green |
| **S10 Invoice, collect, close** (4 d) | step 10 | invoice prepare/submit (approval), follow-up log, close checklist through TSR |
| **T3 Alerts** (5–7 d) | TNA plan Phase 3 + Order blockers in Today | TNA plan gate |
| **T4 Capacity & learning** (9–12 d) | TNA plan Phase 4 using §5 capacity | TNA plan gate |
| **T5 Surfaces** (7–9 d) | TNA plan Phase 5 | TNA plan gate |
| **T6 Reading & answering** (5–7 d) | TNA plan Phase 6 | TNA plan gate |
| **S11 End to end + bundle** (3 d) | one order from Sales Order to commercial close entirely in the tower on `hosted.localhost`; every ERP doc carries a tower Comment; bundle; handoff | the run's log quoted in the status file; `hosted_tests.sh` green; bundle URL check (`grep -oE 'https?://…' index.html`) shows only middleware URLs |

Total ≈ 46 d order flow + 48–64 d T&A ≈ **95–110 developer-days**. First usable thing for a planner: after S3
(order page + where to produce), about **12 days** in.

---

## 9. Edge cases each slice must test

- Sales Order **amended** (`-1`): the Order page follows `amended_from`; allocation, T&A and docs re-point; old ones shown as history.
- **Partial** quantities everywhere: split allocations, partial cuts, short shipment within tolerance, two shipments for one order, one invoice covering several contracts (existing rule).
- **Zero-qty sizes** (FIXES 2026-11-09 §1): never create a row with 0.
- A step done **in the ERP desk** instead of the tower: the read model shows it (sync), the T&A stamps it, nothing is duplicated.
- Desk submit that skipped a rule (scripts off on the site) → breach risk via the existing reconciler, never an auto-revert.
- No factories / lines / SAM set up → setup checklist, not an error. Capacity unknown → never silently placed.
- ERP down → read-only stale banner, writes refused.
- 30 s budget: anything heavier (carton generation on a 2,000-carton order, ledger rebuild) → measured; above ~20 s use the existing job pattern.
- Role filtering: QC sees inspections, Accounts sees step 10; every function checks permission server-side.

## 10. Working rules

- Never edit `erpnext/` core. Never fork a hosted script in the tower; change it at the source, keep `hosted_tests.sh` green, re-vendor.
- Never write to the **live** KOGO ERP. All testing on `hosted.localhost:8001`.
- No commits or pushes without asking the user. The repo is public: nothing under `cortex-tower/backend/data/`, no mail, creds, real prices or PO numbers, and none of the held-back files in `RECORD_2026-11-06.md`.
- Ask the user before changing a business rule. Mark anything not verified as **not verified**.
