# T&A Calendar: production grade plan
### Cortex Tower, 9 November 2026. Planning document only. Nothing in this file has been built yet.

---

## 0. How to read this

This is the full plan for turning the T&A calendar from a working demo-grade screen into the tool the
merchandising, sourcing and production teams run the order book on: correct dates, dates that move when
reality moves, a plan that is agreed and then measured, alerts that reach a person, and a layer that
predicts trouble instead of reporting it after the fact.

It is written in seven parts:

1. What is true today, with evidence (section 2).
2. Every gap, numbered, with severity and impact (section 3).
3. The one architectural decision that everything else depends on, with a recommendation (section 4).
4. The target design: data model, scheduling rules, evidence, intelligence (sections 5 to 9).
5. How it is operated: alerts, screens, performance, security (sections 10 to 12).
6. How we prove it: test strategy and acceptance gates (section 13).
7. The build order, effort and risks (sections 14 and 15), and the decisions only you can make (16).

Read section 4 first if you read nothing else. Everything else hangs off it.

---

## 1. The short version

The T&A today is **two half-systems that do not talk to each other**:

* the **ERP** holds a genuinely production-shaped T&A model (per-order milestone rows, a baseline lock,
  feasibility flag, delay reason categories, sample requirement rules, automatic evidence stamping) with
  **zero records in it and its event scripts switched off**;
* the **Tower** holds a live, fast, well-presented calendar (61 milestones, dependency graph, critical
  path, alerts, program view) that **writes nothing back**, has **no baseline**, **no propagation**, and
  reads evidence from documents the factory has not started using.

Both are close to right. Neither is production grade alone. The plan is to make them one plan with one
scheduler, and to earn the right to the word "intelligent" by calibrating it against the factory's own
history.

Estimated effort: **48 to 64 development days** across six phases, with the first usable slice in
**10 days**.

---

## 2. What is true today (audit, verified live on 9 November 2026)

### 2.1 Two engines, described in different words

| | ERP (`Order TNA` + `TNA Milestone`) | Tower (`backend/tna_app/`) |
|---|---|---|
| Milestones | 33 `TNA Milestone Type` records | 61 milestone template, JSON file in the repo |
| Schedule base | `basis`: Order Received, PCD, After Milestone, Ex-Factory | `offset_days` from the ship date, on one of three calendars |
| Navigation | `after_milestone` (one predecessor) | `depends_on` (many predecessors) |
| Duration | `Fixed` or `Qty / Daily Output` | fixed days |
| Baseline | `baseline_locked`, `planned_date` vs `revised_date` | none (planned dates recomputed on every read) |
| Feasibility | `plan_feasible`, `feasibility_note` | not surfaced |
| Delay reason | `delay_reason_category` (Buyer, Supplier, Factory, Logistics, Other) | free text, 14 suggested causes |
| Applicability | `applies_when` (Always, Washed Only, Printed Only, Sample Type Required) | none |
| Sample rules | `Apparel Sample Rule` + `Sample Requirement` (gates, quantity, chargeback) | not used |
| Evidence | 23 server scripts that stamp actuals from documents | reads 8 document types, read only |
| Records today | **0 Order TNA, 0 TNA Milestone** | 2 orders read live, plan computed on the fly |
| Event scripts | **off on the site** (the platform flag is off, so hooks do not run) | n/a |

**Vocabulary overlap is 2 of 61 codes** (`PILOT_RUN`, `PP_MEETING`). The Tower says `ORD_CONF`, the ERP
says `ORDER_RECEIVED`; the Tower says `SEW_END`, the ERP says `BULK_FINISH`. Nothing can be written from
one to the other, which is why `cx_tna_push_milestone` answers `no_order_tna` today.

### 2.2 What the factory actually has in the ERP right now

| Record | Rows | Meaning |
|---|---|---|
| Sales Order | 2 | the two Bella Dahl orders from the deal flow |
| Sales Contract, Tech Pack | 4, 2 | from the same flow |
| Order TNA, TNA Milestone | **0, 0** | no plan has ever been created in the ERP |
| TNA Template | 1 | "Standard 60-Day (forward)", 30 rows, marked default |
| TNA Milestone Type | 33 | the vocabulary the ERP's own TNA screens use |
| Holiday List | 1 | "GGI Holidays 2026-27" |
| Sample Approval, PP Meeting, Fabric Inspection, Trim Inspection, Final Inspection, Cut Plan, Packing List, Quality Inspection, Work Order, Job Card, Production Card, Factory Allocation, Fabric Requisition, Trim Requisition, Pilot Run, Shipment, Purchase Order, Purchase Receipt, Delivery Note | **0 each** | every document the calendar would take evidence from is unused |

Three doctypes that the Tower's reader **asks for do not exist in the ERP at all**:

* `Client Purchase Order` (the configured source for "Order Received", `TNA_ORDER_RECEIVED_SOURCE=client_po`)
* `Production Daily Evidence` (the factory's daily output record)
* `Buyer Tech Sheet Evidence`

So two milestones can never be dated automatically and progress can never be quantity-based, whatever the
screen says.

### 2.3 What is already good and must not be thrown away

Tower side:

* working-day arithmetic per calendar (`WorkingCalendar`: shift, between, holidays in range, special working
  days) with VN factory, CN supplier and HK office calendars, which is more correct than the ERP's own
  calendar-day offsets snapped to a working day;
* a real dependency graph, CPM forward and backward pass, float and critical path (`_compute_cpm`);
* a status vocabulary that a factory understands, including `Not recorded` (evidence missing) as distinct
  from `Overdue` (late);
* alerts with three escalation levels and a plain text digest; owner workload; KPI block with RAG;
* preview, commit, roll back and audit for every edit (`action_log`, `audit_log`), which is better governance
  than the ERP's own replan;
* 40 frontend components: Gantt, phase Gantt, month calendar, board, program, owner workload, dependency
  chain, exception rail, day detail, intake panel;
* an intake queue that starts a plan when an order arrives.

ERP side:

* the per-order `Order TNA` document with a **baseline lock**, **feasibility**, **critical delay days** and
  per-milestone `planned_start`, `planned_date`, `revised_date`, `revision_reason`, `delay_reason_category`,
  `actual_date`, `partial`, `status`, `not_applicable`, `owner_user`, `department`;
* `TNA Milestone Type` with `auto_source` (which document proves it) and `applies_when` (washed only,
  printed only, sample required), which is exactly how a real merchandiser thinks;
* sample requirement rules with gates, quantities, sample sizes and chargebacks, scoped by customer, order
  and style;
* `TNA Template` with `basis`, `after_milestone`, `duration_rule`, `daily_output`, `owner_role`, and template
  selection by customer, product type and shipment mode;
* a company `Holiday List`;
* 23 server scripts that know how to stamp milestones from documents (`arinox_tna` stamp/unstamp/refind/
  samples, milestone validate and after save, hooks on Sales Order, Tech Pack, Sample Approval, Shipment).

---

## 3. Every gap, numbered

Severity: **P0** blocks production use, **P1** makes it untrustworthy, **P2** makes it un-loved.

### Data and model

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G1 | Two vocabularies, 2 of 61 codes shared | P0 | code comparison above | no write path in either direction; the ERP's TNA screens stay empty |
| G2 | No `Order TNA` / `TNA Milestone` rows exist | P0 | 0 rows | the ERP has no plan, so the desk cannot see what the Tower shows |
| G3 | No baseline. Planned dates are recomputed on every read | P0 | `build_calendar` derives from template offsets | impossible to answer "are we slipping against the agreed plan", impossible to measure accuracy |
| G4 | Delay reason is free text, no party category, no analytics | P1 | `delay_reason` string; ERP field unused | no Pareto, no supplier scorecard, no learning |
| G5 | No plan version history, only overlay `updated_at` | P1 | `models.py` | cannot audit who changed a date in the plan itself, only in the overlay |
| G6 | Template is one JSON file in the repo, one product type | P1 | `tna_app/data/tna_template_woven_shirt.json` | every new product type is a code change; no per-customer or per-factory template |
| G7 | No capacity or resource model | P1 | program groups by ship month only | two orders can both plan cutting on the same line the same day |
| G8 | Company scoping silently degrades | P2 | `ORDER_COMPANY` default is a company the live ERP does not have, code falls back to the single company | works now, breaks the day a second company appears |

### Scheduling (the core of the problem)

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G9 | Planned dates are template offsets from the ship date, not schedule output | P0 | `p_finish = mcal.shift(ship, offset)` | a milestone finishing 6 days late moves **nothing** downstream |
| G10 | CPM is computed but only labels rows | P0 | `_compute_cpm` runs after dates are fixed | float is fiction: it compares hand-tuned offsets, not the dependency logic |
| G11 | Recording an actual does not change the forecast of successors | P0 | `forecast_finish` = actual or planned, per row | the plan cannot show consequences, which is the whole point of a T&A |
| G12 | Offsets are declared on different calendars but compared as one | P1 | per-milestone `calendar` | a CN supplier's 10 working days and a VN factory's 10 working days are not the same span |
| G13 | No feasibility gate at plan approval | P1 | ERP has one, Tower does not use it | plans that cannot make the ship date are accepted silently |
| G14 | No re-plan policy (who may move what, when, with what reason) | P1 | overlay accepts any date from any caller | the plan drifts without accountability |
| G15 | Order-level RAG is a rule of thumb | P2 | `kpis()` | no probability, no horizon, no weighting by criticality |

### Evidence and actuals

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G16 | 3 referenced doctypes do not exist (`Client Purchase Order`, `Production Daily Evidence`, `Buyer Tech Sheet Evidence`) | P0 | existence check | Order Received and quantity progress can never be derived |
| G17 | 18 evidence doctypes exist but are unused (0 rows) | P0 | row counts | every milestone reads "Not recorded"; the calendar is honest but empty |
| G18 | No conflict rule when several documents prove the same milestone | P1 | reader takes first/last per code | wrong actual can win, silently |
| G19 | No partial or quantity-aware actuals surfaced | P1 | `partial` exists in ERP, unused | a cut that is 60 percent done looks binary |
| G20 | No deep link from a milestone to the document that proves it | P1 | `evidence_value` is a string | a merchandiser cannot verify a date in two clicks |
| G21 | Manual confirmation has no proof attached | P2 | overlay only has a note | "I called the supplier" is unauditable |

### Operations

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G22 | Alerts are computed at read time only | P0 | `build_alerts` | nobody is told anything unless a person opens the screen |
| G23 | No persistence for ack, snooze, dismiss, owner of an alert | P0 | only `snooze_tna_order` for intake | the same alert is re-raised forever, and nobody can own it |
| G24 | No scheduled job (nightly snapshot, morning digest, escalation sweep) | P0 | none in the codebase | the app is pull-only |
| G25 | `TNA_SAMPLE_WHEN_EMPTY` defaults to on | P0 | `config.py` | a client-facing app can show a demo order as if it were real |
| G26 | No RBAC on milestone edits | P0 | `update_milestone` takes `actor` as a string | anyone with the app open can move any date |
| G27 | No immutability or approval on re-plan after baseline | P1 | overlay accepts anything | signed-off plans can be rewritten invisibly |
| G28 | Concurrency: two people editing the same milestone | P1 | no version check | last write wins, first person's judgement lost |
| G29 | Program view reads N orders live (or approximates from plan) | P1 | `get_tna_program` | with 150 orders it is slow, and the fast path is less accurate |
| G30 | No tests of any kind for TNA | P0 | no `test_tna*` file | nothing about the engine is protected against regression |
| G31 | No data quality gate on a plan (missing owner, missing dates, N/A abuse) | P1 | `data_quality` is read-only strings from the reader | a broken plan looks fine |

### Surfaces

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G32 | No baseline vs forecast vs actual view | P1 | single date column in the Gantt | the conversation the factory has with a buyer cannot be had |
| G33 | No printable or sharable T&A (PDF, Excel, ICS) | P1 | none | buyers ask for it; it is produced by hand today |
| G34 | No per-owner "my week" mobile flow | P1 | Board is order-centric | the person who records the date is not sitting at a desk |
| G35 | No drag reschedule with dependency validation | P2 | Gantt is read only | slow to correct a plan |
| G36 | No "why is this late" narrative | P2 | status is a label | managers rebuild the story by hand |

### Intelligence

| ID | Gap | Sev | Evidence | Impact |
|---|---|---|---|---|
| G37 | Offsets are static industry defaults, never calibrated | P1 | template values | the plan is as accurate in month 12 as on day 1 |
| G38 | No probability of missing the ship date | P1 | RAG only | no way to rank 40 orders by real risk |
| G39 | No what-if simulator | P2 | none | decisions (add a line, air freight, push a ship date) are made on instinct |
| G40 | No delay attribution analytics | P2 | free text | cannot say "supplier X costs us 9 days on average" |
| G41 | No reading of a buyer's own T&A or PO dates | P2 | none | every buyer sheet is retyped |
| G42 | Sample requirement gates and chargebacks not surfaced | P2 | ERP rules unused | cost and gate risk invisible |

Forty-two gaps. Sections 5 to 13 answer every one of them. Nothing here is a rewrite of the frontend: the
components are sound, the engine underneath them is what changes.

---

## 4. The architectural decision (read this twice)

### 4.1 The decision

**One plan. One scheduler. Two surfaces.**

* **The Tower is the scheduler and the work surface.** It computes the plan (working days per calendar,
  dependency graph, propagation from actuals, capacity) in Python, where it can be tested.
* **The ERP is the system of record and the evidence source.** It holds the `Order TNA` and `TNA Milestone`
  rows that the desk, the reports and the future buyer-facing views read. It also holds the documents that
  prove what actually happened.
* **One writer per field.** A field has exactly one owner. No field is written by both sides. This is what
  makes the two surfaces trustworthy instead of contradictory.

### 4.2 Why this way round

Four reasons, in order of weight:

1. **The ERP cannot schedule today.** Its planning runs inside event scripts, and the site's
   `server_script_enabled` flag is off, so the hooks on Sales Order, Sample Approval and Shipment do not
   run. Its scheduling code is 27 to 29 KB of sandbox Python with no imports, no tests and no way to unit
   test on a branch. The Tower's scheduler is ordinary Python with a test harness that already exists.
2. **The Tower's maths is already better.** Working-day arithmetic per calendar and a real dependency graph
   with a forward and backward pass. The ERP's `plan_dates` adds *calendar* days and then snaps to the
   nearest working day, and its replan moves only `revised_date` on the rows whose planned date changed, so
   a late predecessor never pushes a successor.
3. **The ERP's model is the right vocabulary** and it is data, not code: `TNA Milestone Type`,
   `TNA Template`, `TNA Milestone`, `Sample Requirement`, `Holiday List`. We can seed and extend it. We
   should not invent a parallel universe in SQLite.
4. **The factory already lives in the ERP.** Any plan they cannot see in the ERP will be duplicated in a
   spreadsheet within a month.

### 4.3 Field ownership matrix (the contract between the two halves)

| Field | Owner | Written by | Notes |
|---|---|---|---|
| `Order TNA` exists, `sales_order`, `style_item`, `colour`, `order_qty`, `customer` | ERP | Tower creates it, then never changes identity fields | idempotent on (sales order, style, colour, ex-factory) |
| `template`, `order_received_date`, `pcd`, `ex_factory_date` | ERP / shared | Tower on create; afterwards ERP when the factory allocation or contract changes | Tower adopts ERP value on next sync with an event on the timeline |
| `TNA Milestone` rows, `milestone_type`, `sequence`, `label`, `department`, `is_critical`, `not_applicable` | Tower | Tower | derived from the template and `applies_when` |
| `planned_start`, `planned_date` (baseline) | Tower, frozen at lock | Tower, until `baseline_locked`; after that, never | this is the number we are measured against |
| `revised_date`, `revision_reason` | Tower | Tower, on every re-plan, with a reason code | the living forecast after the lock |
| `actual_date`, `partial` | ERP evidence, or a person | ERP hooks / Tower's evidence reader / manual confirmation | never derived by the scheduler |
| `status`, `delay_days` | Tower | Tower, recomputed on every read and every write | a mirror of the engine, for the desk's benefit |
| `delay_reason_category` | person | Tower UI, one of the ERP's five values | enforced vocabulary, not free text |
| `owner_user` | person | Tower UI, defaulted from `owner_role` | assignment, not computation |
| `baseline_locked`, `lock_date`, `locked_by` | person (manager) | Tower with an approval step, mirrored to ERP | see 6.7 |
| `plan_feasible`, `feasibility_note`, `critical_delay_days` | Tower | Tower | mirrored for the desk |
| `Holiday List`, `TNA Milestone Type`, `TNA Template` | seeded data | Tower admin screens, seeded into ERP | see section 7 |

### 4.4 What we deliberately do not do

* We do not edit the ERP's `arinox_order_tna_replan` or planner scripts to become the master scheduler. They
  stay as the desk's fallback and are marked as such.
* We do not keep two copies of the plan. SQLite keeps the human layer (as today), the baseline snapshots, the
  alert state, the learned offsets and the audit. It does not keep a second `milestones` table that can
  disagree with the ERP.
* We do not write to the ERP from a read path. Reads stay GET only, as today.

### 4.5 The cost of getting this wrong

If the Tower writes planned dates and the ERP's replan also writes them, the two will fight and the factory
will stop trusting both. The ownership matrix in 4.3 is the guard. It goes into code as a single write
module with a per-field allowlist, and a test that fails if any other module writes a `TNA Milestone` field.

---

## 5. Target data model

### 5.1 ERP side (seeded and extended, no new doctypes except one)

| Change | Detail | Why |
|---|---|---|
| Extend `TNA Milestone Type` from 33 to the full vocabulary | add the 59 Tower codes not present, mapped in Appendix C. Keep the ERP's existing 33 codes unchanged so nothing breaks | one vocabulary for both apps |
| Add fields to `TNA Milestone Type` | `phase` (the Tower's 8 categories), `default_duration_days`, `auto_source_field` (which date on the document to read), `evidence_required` | makes the type record the single definition of a milestone |
| Seed `TNA Template` from the Tower's 61-milestone template | including `basis`, `after_milestone`, `offset_days`, `duration_rule`, `daily_output`, `owner_role`, `phase`, and a `depends_on` child table for multiple predecessors | the factory's own TNA screen shows the same plan |
| Add a `TNA Template Milestone` child field `depends_on` (Table MultiSelect or small child) | the ERP model allows one predecessor, the Tower needs many | without it the ERP cannot represent the graph |
| Add `plan_source`, `plan_synced_at`, `plan_version` to `Order TNA` | says who last computed the dates and when | trust and debugging |
| Add `TNA Capacity` (new doctype, small) | `department`, `plant floor`, `week`, `available_line_days`, `sam_per_unit` | the capacity model in 6.8 |
| Do **not** add a second plan table | n/a | one plan |

Creating one small doctype (`TNA Capacity`) plus custom fields is a metadata push of the kind already done
for this workspace (`apparel-modules/v2/hosted_bundle`), with a re-run safe loader.

### 5.2 Tower side (new tables in `tna_app/data/`)

| Table | Purpose | Key columns |
|---|---|---|
| `plan_baseline` | an immutable snapshot of planned dates at lock | `order_id`, `version`, `locked_at`, `locked_by`, `source`, `rows_json`, `feasible`, `note` |
| `plan_revision` | every re-plan after lock | `order_id`, `baseline_version`, `reason_code`, `reason_note`, `actor`, `approved_by`, `approved_at`, `moves_json` (old date, new date, milestone), `ship_impact_wd` |
| `milestone_state` (replaces most of `milestone_overlay`) | the human layer, one row per order and milestone, typed | adds `delay_reason_code`, `party` (buyer/supplier/factory/logistics), `confirmed_by`, `confirmed_at`, `evidence_doc`, `qty_done`, `qty_total`, `version` (optimistic lock) |
| `alert_state` | lifecycle of an alert | `alert_key` (stable hash), `order_id`, `code`, `level`, `raised_at`, `state` (open/ack/snoozed/resolved), `owner`, `ack_at`, `snooze_until`, `resolved_at`, `resolution`, `times_raised` |
| `evidence_link` | which documents prove which milestone, with the winner | `order_id`, `code`, `doctype`, `docname`, `doc_date`, `qty`, `confidence`, `is_winner` |
| `learned_offset` | calibrated lead times | `scope` (global/customer/factory/supplier/product type), `code`, `samples`, `median_wd`, `p90_wd`, `recent_trend`, `computed_at` |
| `plan_snapshot` | nightly materialised plan for fast program views | `as_of`, `order_id`, `ship_date`, `rag`, `progress`, `critical_delay`, `next_milestone`, `next_date`, `payload_json` |
| `notification_log` | what was sent, to whom, when, on which channel | `alert_key`, `channel`, `to`, `sent_at`, `result` |

Existing `action_log` and `audit_log` are kept as they are: they are good governance and the plan builds on
them rather than replacing them.

### 5.3 Vocabulary map

Appendix C carries the full 61 to 33 map. Rules:

* Where the ERP has the concept under a different name, the ERP code wins (`ORDER_RECEIVED`, not `ORD_CONF`;
  `BULK_FINISH`, not `SEW_END`).
* Where the Tower has a checkpoint the ERP lacks (for example `QC_INLINE`, `CARTON_AUDIT`, `COO_DOCS`), the
  Tower code is **seeded into** `TNA Milestone Type` so it becomes a first class milestone in both places.
* Aliases are kept in one table in code (`VOCAB_ALIASES`) so old overlay rows and old URLs keep working.

---

## 6. The scheduling engine (the heart of it)

This section is the specification. It replaces `build_calendar`'s offset maths with a real scheduler. Every
rule here is testable and gets a test.

### 6.1 Dates the plan is built from

| Name | Source | Used as |
|---|---|---|
| `order_received` | Sales Order date, or the Client PO date when that document exists | the forward anchor |
| `pcd` | factory allocation, or manual entry, or derived from the ship date | the pinned middle anchor |
| `ex_factory` | Sales Order `delivery_date`, or the contract's ex-factory date | the backward anchor |
| `ship` | Ex-Factory plus inland and cutoff buffer per calendar | the date the buyer sees |

### 6.2 Scheduling modes

| Mode | When | Algorithm |
|---|---|---|
| Backward (default) | no PCD pinned | start from Ex-Factory, run the backward pass |
| Forward | order received and no ship pressure, or a "how early can we be" question | start from Order Received, run the forward pass |
| PCD pinned | factory allocation gives a cut date | forward to PCD, backward from Ex-Factory, then resolve the join: if the two halves overlap, the plan is infeasible and says by how many working days |

### 6.3 Working days

* Every calendar is a `WorkingCalendar`: working weekdays, holidays, special working days, and a
  `half_day_dates` list (new, the factory works some Saturdays to 2 pm).
* `shift(day, n)` counts **working days**, not calendar days. This is already correct in the Tower and is
  what the ERP gets wrong.
* A date that falls on a non-working day is moved in the direction of travel to the nearest working day.
* Durations and lags are always expressed in **working days of the calendar the milestone belongs to**, and
  stored with the calendar id so a later holiday change cannot silently reinterpret history.

### 6.4 Links

| Link | Meaning | Use |
|---|---|---|
| FS (finish to start) with lag | successor starts `lag` working days after predecessor finishes | the default |
| FS with negative lag | overlap by `n` days (cutting and sewing overlap) | `SEW_START` after `CUT_START` |
| SS (start to start) with lag | successor starts `lag` days after predecessor starts | parallel workstreams (fabric and trims) |
| Milestone pinned to a date | a date that overrides the network (`pcd`, `ex_factory`, buyer-driven dates) | `PCD`, `EX_FACTORY`, `SHIP` |
| Soft link (warning only) | a relationship that informs but does not constrain | `FINAL_INSP` should precede `SHIP` but the planner may override |

Lags are typed: `wait` (drying, transit), `approval` (buyer turnaround), `transit`, `buffer`. The type is
what the intelligence layer calibrates.

### 6.5 The passes

1. **Forward pass.** For each milestone in topological order, earliest start is the maximum over
   predecessors of `finish + lag`, and never earlier than today for milestones that have not started.
   Pinned dates act as constraints that can only push later, never earlier, except for a deliberate pull-in
   which is a re-plan with approval.
2. **Backward pass.** From `ex_factory` (or the pinned date), latest finish per milestone. `float = latest
   start - earliest start`. `float = 0` on the critical path.
3. **Feasibility.** The plan is feasible if every milestone's earliest finish is on or before its latest
   finish, and if the last pre-ship milestone plus the ship buffer is on or before `ex_factory`. When it is
   not, the answer is a number, not a flag: "infeasible by 6 working days, driven by FABRIC_IN_HOUSE".
4. **Forecast.** The forward pass run again with actual and revised dates in place of planned dates. This is
   how a late sample becomes a late cut, and it is the single most important behaviour the calendar does not
   have today.
5. **Determinism.** Same inputs, byte-identical output. No `today` in the middle of the maths without being
   passed in explicitly, so tests and the snapshot job agree.

### 6.6 Propagation and re-plan

| Trigger | What happens automatically |
|---|---|
| An actual is recorded | forecast recomputed; downstream rows that now miss their planned date are marked `At risk` with the reason "upstream slip: <code> <n> wd"; an alert is raised if the ship date is affected |
| A revised date is entered | same as above, plus a `plan_revision` row |
| PCD or Ex-Factory changes in the ERP | full recompute; before lock, planned dates move; after lock, `revised_date` moves and the ship impact is shown |
| A template or holiday list changes | the plan is recomputed on next read, and the diff is listed on the timeline (never silently) |
| A milestone is marked not applicable | its lag is passed through as zero, and dependants are re-dated |

### 6.7 Baseline, lock, and who may move what

| State | Planned dates | Revised dates | Who |
|---|---|---|---|
| Draft (no lock) | free to recompute | not used | merchandiser |
| Locked (agreed with the factory and the buyer) | frozen, immutable | the working forecast | merchandiser may revise; moving the ship date needs merchandising manager approval |
| Re-locked (v2, v3) | a new baseline version is written; the old one is kept forever | reset | merchandising manager |

Rules that make this trustworthy:

* A baseline is a snapshot row, not a field, so version 1, 4 and 7 can be compared side by side.
* Any revision that moves the ship date needs `approved_by` before it is written, and the approval is a real
  row, not a checkbox.
* Past actuals cannot be edited by the person who recorded them after 7 days without a note, and never
  without leaving the old value in the audit.
* The lock is mirrored to `Order TNA.baseline_locked` so the ERP's own screens cannot be used to sidestep it
  without leaving a trace.

### 6.8 Capacity and leveling (phase 4, not day one)

* The unit is **line-days per department per week**. A milestone that consumes capacity says how much:
  cutting 1000 pieces at 900 per day per line is 1.1 line-days.
* `TNA Capacity` holds available line-days and SAM per unit per department per plant floor per week.
* Loading = sum over orders of the capacity each milestone consumes in that week. Over 100 percent is a
  hard flag, over 90 percent is amber.
* Leveling suggestions, in order of preference: move a milestone inside its float, split the order across
  two lines, shift the cut date and tell the buyer, add a shift. The engine proposes; a person decides.
* Before capacity exists as data, the program view keeps working on ship-month buckets as it does today, and
  says so plainly.

### 6.9 Edge cases the engine must name and handle

| Case | Rule |
|---|---|
| Ship date missing | the plan is not computed; the order shows "no ship date" with a one click fix |
| Order cancelled | the plan is closed, not deleted; alerts stop; the row stays for history |
| Split shipment (two ex-factory dates) | one `Order TNA` per style, colour and ex-factory date, as the ERP already assumes |
| Multi colour, same style | one `Order TNA` per colour when the cut dates differ, otherwise one with colour noted |
| Colour-specific gates (lab dip per colour) | applicability can depend on colour, evaluated per row |
| Washed or printed only milestones | `applies_when` decides, and the row is created as `not_applicable` rather than omitted, so the buyer sees the checklist |
| Partial quantity done | `partial` plus `qty_done`. Progress is quantity weighted, not binary |
| No template for a product type | the order is flagged, the plan is not invented, and the admin screen offers to clone a template |
| Holiday list gap for next year | a plan that reaches past the holiday list's end date raises a data quality warning |
| Two calendars in one link | the lag is interpreted on the successor's calendar, and the anchor date is converted explicitly |
| Timezone | all dates are factory-local dates. Timestamps are stored in UTC with the factory timezone recorded; no date arithmetic ever crosses a timezone boundary |
| Order already shipped | plan frozen read-only |

---

## 7. Milestone library and template governance

1. **One vocabulary, in the ERP.** `TNA Milestone Type` grows to the full set (Appendix C). Each type carries
   the phase, the department, `auto_source`, `applies_when`, default duration, whether evidence is required,
   and whether it is critical by default.
2. **Templates are data, and they are versioned.** `TNA Template` plus a `version` field. Publishing a
   template never changes an existing order's plan; a draft order can be repointed with a diff shown first.
3. **Template selection**, in this order: an order-level override, a customer-specific template, a product
   type template, the default. The ERP already has the first three fields; the Tower will honour them.
4. **Admin screens in the Tower** for the milestone library, templates, holidays, sample rules and capacity,
   each with preview, publish and roll back, so a merchandising manager can change a lead time without a
   release.
5. **Applicability conditions** are expressions over facts the order carries: washed (yes/no), printed,
   shipment mode, buyer sample requirements, colour specific gates. They are stored on the type record as a
   small, readable rule (for example `washed_only`, `sample:FIT`, `always`), not as code.
6. **Seeding.** The loader pushes the library and templates to the ERP and can be re-run; it never deletes a
   type that orders already use.

---

## 8. Evidence and automatic actuals

Today the calendar reads eight document types, three of which do not exist, and takes the first answer it
finds. That becomes a small, auditable subsystem.

### 8.1 The rule table

| Milestone | Evidence document | Field read | Completeness rule |
|---|---|---|---|
| ORDER_RECEIVED | Sales Order (or Client PO when it exists) | `transaction_date` / `po_date` | the order exists and is not draft, or draft with an explicit note |
| TECH_PACK_RECEIVED | Tech Pack | `creation` or `tech_pack_date` | submitted |
| BOM_RECEIVED | Tech Pack | buyer BOM table non-empty | at least one material row |
| MINI_MARKER | Cut Plan or Fabric Requisition | `creation` | exists |
| FR_RAISED | Fabric Requisition | `transaction_date` | submitted |
| FABRIC_BOOKED | Purchase Order | `transaction_date` | submitted, for this order's style |
| FABRIC_IN_HOUSE | Purchase Receipt | `posting_date` | submitted, quantity greater than zero |
| FABRIC_QC_PASSED | Fabric Inspection or Quality Inspection | `report_date`, verdict | verdict is pass |
| FABRIC_ETD | Purchase Order | `expected_delivery` / supplier ship date | from the supplier document, not guessed |
| PP_MEETING | PP Meeting | `meeting_date` | exists |
| PCD | Work Order or Factory Allocation | `planned_start_date` | exists |
| BULK_FINISH | Production Daily Evidence or Job Card completion | date of the last operation | if the doctype is missing, manual confirmation with a photo |
| PACK_FINISHED | Packing List | `posting_date` | submitted |
| FINAL_INSPECTION | Final Inspection or Quality Inspection | `report_date` | verdict recorded |
| ON_BOARD | Shipment | `sailing_date` / AWB date | exists |
| IN_WAREHOUSE | Shipment | `arrival_date` | exists |

Every other milestone is manual by design and says so on the row ("recorded by a person").

### 8.2 Rules that make evidence trustworthy

* **Winner rule.** When two documents could prove one milestone, the winner is the earliest *valid* document
  that meets the completeness rule, unless a person has pinned a different one. Both are recorded in
  `evidence_link` with `is_winner`, so the choice is visible and reversible.
* **Conflict alert.** A second document that contradicts the winner by more than a tolerance (default 2
  working days) raises a data quality alert instead of silently changing the past.
* **Nothing is derived from a draft** unless the document type has no draft state.
* **Every derived actual carries its proof**: doctype, name, date, and a link built by the ERP URL builder
  already in the tower, so one click opens the document.
* **Manual entries need a reason and, optionally, a file.** "Supplier confirmed by phone" with an attachment
  beats a bare date.
* **Unrecorded is a first class answer.** A milestone with no evidence and no manual entry stays `Not
  recorded`, is counted in the KPI block, and is what the completeness gate in 13.4 checks before a plan is
  called live.
* **Missing doctypes are a configuration error, not a silent skip.** The reader publishes a startup health
  check: which evidence sources are configured, which exist, which have zero rows.

### 8.3 Ramp for a factory that has never used these documents

Phase 2 includes a **thin evidence path**, because waiting for the whole ERP to be adopted means the
calendar stays empty for months:

1. Every milestone can be confirmed from the Tower itself in two taps (date, reason, optional photo).
2. Where a document type is unused, the plan says "evidence: manual" instead of pretending to read it.
3. A weekly adoption report shows, per document type, how many milestones were proved by a document versus a
   person. The target is 70 percent document-proved within two months; the report is how we get there.

---

## 9. The intelligence layer

Seven features, each with a clear input, output and acceptance test. All of them are explainable: no black
boxes in a factory.

### 9.1 Learned lead times (the foundation)

* **Input:** every completed order, actual working-day gap per milestone against its predecessor, by
  customer, factory, supplier, product type and season.
* **Output:** for each scope and code, sample count, median, p90, trend, and a proposed template offset.
* **Where it lands:** the template screen shows "your sheet says 45 days for LAB_DIP; the last 12 orders took
  a median of 51, p90 61" with one button to accept.
* **Acceptance:** replaying last season's orders through the learned template predicts at least 80 percent of
  first-cut dates within 3 working days, versus a baseline measured today on the static template.

### 9.2 Risk score with a horizon

* **Output:** probability that `SHIP` is missed, in three bands, with the two or three drivers named in words
  ("fabric not in house, 5 days behind, p90 for this supplier is 8 days").
* **Method:** start with a transparent scoring model (critical path slip in working days, remaining p90
  durations, open blocking gates, evidence gaps, capacity over 90 percent in the ship week), calibrate the
  weights on history, publish the weights on the page.
* **Acceptance:** the top decile by score contains at least 60 percent of the orders that actually shipped
  late, measured on the last two seasons.

### 9.3 Early warning on the material chain

* **Input:** purchase order dates, supplier confirmations, receipts, inspection outcomes.
* **Output:** "this order will miss FABRIC_IN_HOUSE by 4 working days unless the mill confirms by Friday",
  raised *before* the date passes.
* **Acceptance:** on a replay of real history, at least half of the material delays are flagged 5 or more
  working days before the planned date.

### 9.4 What-if simulator

* **Scenarios:** push the ship date by n days, add a second line for n weeks, single milestone slips by n
  days, a supplier slips by n days, air freight for the last leg.
* **Output:** the re-dated plan, the ship impact, the milestones that leave the critical path, the cost of the
  change where a cost is known (air freight per kg, overtime per line-day).
* **Rules:** a simulation never writes. It produces a diff that can be turned into a re-plan with approval.
* **Acceptance:** a simulation of a real past order reproduces the dates that actually happened within 2
  working days.

### 9.5 Delay attribution and Pareto

* Every late milestone carries a reason **code** and a **party** (buyer, supplier, factory, logistics in the
  ERP's own five-value vocabulary). Free text is allowed only as a note.
* **Outputs:** Pareto by cause, by party, by owner, by supplier, by customer, by product type; average days
  lost; trend; "the top three causes cost 41 percent of our slipped days last quarter".
* **Acceptance:** every late milestone has a code and a party (enforced at write time), and the report ties to
  the audit log to the day.

### 9.6 Reading the buyer's own sheet

* **Input:** a buyer's T&A, PO, critical path sheet or tech pack, as PDF, Excel or a photo, from the inbox.
* **Output (preview only):** the milestones it mentions, the dates it imposes, the conflicts with our plan,
  and a proposed set of plan changes with the reason "buyer schedule".
* **Method:** the model door already used elsewhere in the Tower (`deal_bom_ai` style: the model returns JSON
  that is validated before use, with a paste-in fallback for any model).
* **Acceptance:** on a corpus of the factory's real buyer sheets, at least 90 percent of the dates that exist
  are extracted, and no change is ever applied without a person confirming the diff.

### 9.7 Assistant on top of the plan

* Questions in plain language over the plan: "what is late this week", "why is Bella Dahl red", "who is
  blocking cutting", "draft the chase mail to the fabric supplier", "what does the buyer still owe us".
* Answers are computed from the engine (deterministic facts) and only then phrased. The model never invents a
  date. Every answer links to the rows it used.
* **Acceptance:** 20 scripted questions, each answered with the right order, date and owner, with no
  hallucinated milestone.

### 9.8 Sequence

9.1 first (it improves everything else), then 9.2 and 9.5 together (they share the reason codes), then 9.3,
then 9.4, then 9.6 and 9.7. Nothing in this section is allowed to ship before the baseline and propagation
work in phase 1, because a prediction on top of a plan that cannot be measured is noise.

---

## 10. Alerts, escalation and notification

The current alerts are good rules with no memory and no delivery. They become a small state machine with a
delivery path.

| Aspect | Design |
|---|---|
| Identity | `alert_key` = hash of order, code, rule, and the date bucket, so the same problem is one alert, not one per read |
| States | `open`, `acknowledged`, `snoozed` (until a date, with who), `resolved` (with how), `auto-resolved` (the condition went away) |
| Levels | L1 owner, L2 department manager, L3 merchandising manager, from the same working-day thresholds as today, and per rule override |
| Channels | in-app (always), email digest (uses the tower's existing mailer), and a WhatsApp or Telegram channel if we add a gateway; each channel switchable per role |
| Rhythm | a morning digest per role at the factory's start time, an escalation sweep at midday, a weekly program summary on Saturday |
| Deduplication | one notification per alert per day; a repeated alert increments `times_raised` and says "raised 4 times" |
| Ownership | every alert has an owner (from `owner_user` or `owner_role`) and a due-by time; an unowned critical alert escalates |
| Escalation proof | `notification_log` says what was sent, to whom, when, and whether it bounced |
| Quiet hours | no notifications outside the working window except L3 |

---

## 11. The surfaces

### 11.1 Screens and who they are for

| Role | First screen | Needs |
|---|---|---|
| Merchandiser | My orders, this week | their orders, what is due, one-tap record, the buyer-facing date |
| Sourcing (fabric, trims) | Material plan | every order's fabric and trim dates, supplier performance, chase list |
| Production | Cut and sew board | line loading, PCD, daily output entry, pilot run and inline QC |
| QA | Gates | samples, inspections, verdicts, fail and rework paths |
| Manager | Program and risk | RAG over the book, risk ranking, capacity conflicts, re-plan approvals |
| Buyer (optional) | Shared T&A | the agreed plan, progress, revised dates, documents owed |

### 11.2 Changes to what exists

* **Plan view**: three date lanes per milestone (baseline, forecast, actual) and a ship-date confidence band.
* **Drag to move a milestone** in the Gantt, with dependency validation and a reason prompt; the same rules as
  the form, so a drag can never do something the form would refuse.
* **My week**: a phone-first list for the owner, two taps to record, offline queue with a clear "not sent yet".
* **Print and share**: a one page T&A per order (PDF, the same layout as the buyer's own sheet), an Excel
  export, an ICS feed per owner so the plan lands in their calendar.
* **Every date has a source**: a small badge on each row saying ERP document, person, or engine, and a click
  to the document.
* **Nothing is a dead end**: empty states that say what to do, not just "no data".

### 11.3 Budgets

| Screen | Budget (p95, 150 orders) |
|---|---|
| Order calendar (one order) | 400 ms |
| Program view | 600 ms |
| My week | 300 ms |
| Write (record, revise) | 800 ms including the ERP write |
| First paint on a phone over 4G | 2 s |

---

## 12. Non functional

| Area | Requirement |
|---|---|
| Scale | 500 live orders, 61 milestones each, 12 seasons of history, one company growing to four plants |
| Performance | the program view reads the nightly snapshot, not 500 live ERP documents; a single order reads live with a 60 second cache and a stale-while-revalidate pattern |
| Reliability | an ERP outage degrades to the last snapshot with a visible banner and a timestamp; no write is ever half applied (preview, then single transaction, then verify by reading back) |
| Idempotency | every write carries an attempt key scoped to the attempt (the lesson from the contract work), so a retry cannot double-apply |
| Concurrency | optimistic locking on `milestone_state.version`; a stale edit is refused with "this changed while you were editing, here is what changed" |
| Security | identity from the platform only, never a parameter; role checks on every write; a per-field allowlist for ERP writes; secrets stay sealed as they are |
| Audit | append-only, 7 years, exportable; every date change has actor, time, before, after, reason code |
| Privacy | buyer names and prices in exports are role gated; the buyer-facing view never shows cost, margin or supplier names |
| Backup | nightly SQLite copy plus the ERP is the record for the plan; restore rehearsed once per phase |
| Observability | a health page: ERP reachable, evidence sources present, snapshot age, alert backlog, unsynced orders, template coverage |
| Localisation | dates in the factory's format, English first, Vietnamese and Chinese labels on the roadmap |

---

## 13. Testing and quality gates

Nothing in this plan is accepted without the tests below. The current TNA has **zero tests**, which is the
single largest reason it cannot be called production grade.

### 13.1 Unit

* Working-day maths with property based tests: `shift(shift(d, n), -n) == d` for working days, `between`
  inverse, holiday boundaries, special working days, half days, leap years.
* Scheduler: forward pass, backward pass, float, feasibility, circular dependency refusal, missing anchor,
  pinned date conflicts.
* Status derivation: a table of cases, one per status, including `Not recorded` versus `Overdue`.
* Capacity: loading arithmetic, overlap detection, leveling proposals.
* Evidence winner rule and conflict detection.

### 13.2 Golden plans

Six fixture orders with hand-computed expected dates, checked in as data:

1. washed woven shirt, sea freight, three colours, one colour specific lab dip
2. printed knit, air freight, tight ship date (infeasible, must say by how many days)
3. no wash, split shipment into two ex-factory dates
4. PCD pinned by factory allocation, plan joins in the middle
5. late supplier: a purchase receipt arrives 6 days late, forecast must move cutting and packing
6. a milestone marked not applicable, dependants re-dated

Any change to the engine must keep all six byte-identical or explain the diff in the pull request.

### 13.3 Contract tests against the ERP

The tower already has `tests/test_erp_contract.py` for this pattern: every field the code reads or writes is
checked against the live doctype meta, and every doctype the evidence map names is checked for existence. The
three missing doctypes would have been caught the day they were referenced.

### 13.4 Gates

| Gate | Check | When |
|---|---|---|
| Plan completeness | every applicable milestone has a date, an owner and a calendar; no milestone without a duration | before a plan can be locked |
| Evidence honesty | every derived actual has a document link; every manual actual has an actor and a reason | on every read |
| Vocabulary | no milestone code outside `TNA Milestone Type` exists in the plan | on every write |
| Snapshot freshness | the snapshot is under 26 hours old | health page and program view |
| No sample data | `TNA_SAMPLE_WHEN_EMPTY` must be off in production; the build fails if it is on | build |

### 13.5 End to end

Playwright flows on the built bundle: record an actual and watch the forecast move; snooze an alert and see it
come back; lock a baseline and be refused a planned-date edit; open a milestone and land on the evidence
document; print the buyer T&A. Mobile viewport included, as the last fix taught us.

### 13.6 Live smoke

A read-only nightly run against the ERP that exercises every read path and fails loudly on schema drift.

---

## 14. Build order, effort and acceptance

Effort is developer-days for one experienced developer, including tests and the documentation the tower
already keeps.

### Phase 0, foundations (6 to 8 days)

* Kill `TNA_SAMPLE_WHEN_EMPTY` in production and make the empty state useful.
* The vocabulary map and the seed of the missing milestone types into the ERP.
* Create `Order TNA` and `TNA Milestone` from the Tower, idempotently, through the pipeline, with a read back.
* The per-field write allowlist and the ownership matrix in code.
* RBAC on every TNA write, with the role table.
* Evidence health check at startup (doctypes present, rows, configuration).
* Test harness and the first two golden plans.
* **Acceptance:** for a real order, the ERP shows an `Order TNA` with 61 milestone rows whose dates match the
  Tower, and a person without the merchandiser role cannot change a date.

### Phase 1, real scheduling (10 to 13 days)

* The scheduler: links with typed lags, forward and backward passes, float, feasibility with a number.
* Propagation from actuals; forecast as a first class date.
* Baseline versions, lock, revision rows, approval for a ship-date move.
* Re-plan flows: PCD change, ship change, template change, with a diff shown before it is applied.
* Recompute on demand and on write; the plan becomes stable and explainable.
* **Acceptance:** all six golden plans reproduce exactly; recording a 6 day late receipt moves cutting and
  packing and says so; a locked plan refuses a planned-date edit and offers a revision instead.

### Phase 2, evidence (6 to 8 days)

* The evidence rule table with the winner rule, conflicts, partials, and deep links.
* The manual confirmation path with a reason and an optional file.
* Repoint the three non-existent doctypes to what exists, and publish what is missing.
* The adoption report (document proved versus person proved).
* **Acceptance:** on a seeded test order, 12 milestones are proved by documents with working links, 3 by
  people with reasons, and the rest honestly say "not recorded".

### Phase 3, alerts that reach people (5 to 7 days)

* `alert_state` lifecycle, dedupe, ownership, snooze, resolution.
* The morning digest and the escalation sweep, as a scheduled job with a kill switch.
* Email delivery through the existing mailer, with a test mode.
* **Acceptance:** a simulated slip produces one alert per problem, one digest per role per day, and an
  acknowledgement that survives a restart.

### Phase 4, capacity and the first intelligence (9 to 12 days)

* `TNA Capacity`, loading, over-capacity flags, leveling proposals.
* Learned lead times from history, with the template screen suggestion and accept flow.
* Risk score with named drivers, and the Pareto of delays.
* **Acceptance:** the program view shows line loading per week; the template screen shows a learned offset with
  its sample count and p90; the risk ranking is calibrated on history as in 9.2.

### Phase 5, surfaces (7 to 9 days)

* Three date lanes, ship confidence, drag with validation, My week on a phone with an offline queue.
* Printable buyer T&A, Excel export, ICS feed.
* **Acceptance:** a merchandiser can run their week from the phone; a buyer pack is produced in one click and
  matches the plan to the day.

### Phase 6, the reading and answering layer (5 to 7 days)

* Buyer sheet ingest with a validated diff.
* The assistant over the plan, 20 scripted questions green.
* **Acceptance:** as in 9.6 and 9.7.

### The first ten days, concretely

Phase 0 only, because everything else is wasted until the vocabulary and the write path exist. At the end of
day ten you can open any order in both the ERP and the Tower and see the same plan, with dates the engine
computed and nobody can quietly change. That is the moment the T&A stops being a screen and starts being the
record.

### Total

48 to 64 developer-days, so roughly 10 to 13 weeks for one developer, or 6 to 7 weeks for two working in
parallel from phase 2 onward (phase 1 is deliberately sequential, it is the brain).

---

## 15. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Two writers fight over dates | medium | high | the ownership matrix enforced in one module with a test |
| The factory keeps using its spreadsheet | high | high | phase 0 makes the ERP and Tower agree; the print view looks like the sheet they already use; adopt one pilot order with them, then a season |
| Evidence documents stay unused | high | high | the manual path plus the adoption report; do not wait for ERP adoption to have a calendar |
| The ERP's event scripts get switched on and duplicate the plan | medium | high | when that flag is turned on, we adopt the ERP's created rows and immediately restamp `plan_source`; the ERP scripts are documented as shell creators, not schedulers |
| Learned lead times overfit a small sample | medium | medium | minimum sample size, p90 not mean, seasonal split, a visible confidence, and a human accept step |
| Performance collapses at 300 orders | medium | medium | the snapshot store from phase 3, budgets in 11.3, a load test with 500 synthetic orders before phase 5 |
| Scope creep into a full MES | medium | high | this plan stops at the T&A. Daily output, line balancing and wage incentive are out of scope and named as such |
| Holiday calendar drifts (new year, Eid, Tet) | high | medium | a yearly task, a data quality warning when a plan reaches past the list, and the admin screen |

---

## 16. Decisions I need from you

Each has my recommendation so you can simply say "your recommendation".

| # | Decision | Options | My recommendation |
|---|---|---|---|
| 1 | Where the plan is stored | (a) ERP `Order TNA`, Tower computes (b) Tower only (c) ERP only | **(a)**. Both screens then agree and the desk keeps working |
| 2 | Milestone vocabulary | (a) the ERP's 33 (b) the Tower's 61 (c) merge: keep the ERP codes, seed the extra checkpoints | **(c)**, full map in Appendix C |
| 3 | Which calendars are real | VN factory, CN supplier, HK office, and is Saturday a working day at each | confirm per site, plus next year's Tet, National Day and any factory shutdown |
| 4 | Capacity | (a) ship month only, as today (b) department line-days per week | **(b)**, but it needs the factory to give available line-days and SAM per style |
| 5 | Who approves a re-plan that moves the ship date | merchandising manager, or the factory head, or both | merchandising manager, with the buyer informed by the digest |
| 6 | Evidence | which of the 18 documents will the factory actually use this season; the rest become manual | tell me the three they will use first, and we wire those properly |
| 7 | Alerts | email only, or add WhatsApp or Telegram | email first, WhatsApp if the merchandisers already live in it |
| 8 | Buyer visibility | private, a PDF pack, or a read only link | PDF pack in phase 5, a link later if a buyer asks |
| 9 | Sample gates and chargebacks | monitor them in the T&A, or leave them out | monitor the gates (they cost days), leave chargebacks to finance |

---

## Appendix A. The 17 TNA functions that exist today

`get_tna_calendar`, `get_tna_orders`, `get_tna_template`, `get_holidays`, `get_tna_kpis`,
`update_milestone`, `tna_run_action`, `tna_rollback_action`, `tna_get_audit_log`, `get_tna_alerts`,
`get_tna_owners`, `get_tna_program`, `get_tna_intake`, `approve_tna_order`, `reject_tna_order`,
`snooze_tna_order`, `get_bridge_status`, plus `cx_tna_push_milestone` in the tower itself.

All of them stay. What changes is the engine under them, the fields they return (three date lanes, sources,
conflicts, confidence) and the new ones this plan adds:

| New function | Purpose |
|---|---|
| `tna_plan_sync` | create or refresh the ERP `Order TNA` rows for an order, idempotent |
| `tna_baseline_lock` / `tna_baseline_unlock` | versioned baseline with approval |
| `tna_replan` | recompute with a diff, a reason code, and a dry run |
| `tna_whatif` | simulate a scenario, write nothing |
| `tna_evidence` | the evidence rules, winner, conflicts, links for one order |
| `tna_capacity` | loading and leveling per department per week |
| `tna_learned_offsets` | calibrated lead times, with samples and confidence |
| `tna_risk` | risk score with named drivers, for one order or the whole book |
| `tna_alert_state` | ack, snooze, resolve, assign |
| `tna_digest` | build and send the morning or weekly digest |
| `tna_read_buyer_sheet` | extract milestones and dates from a buyer document, preview only |
| `tna_admin_*` | milestone library, templates, holidays, sample rules, capacity |

Each gets a `### name` heading in `document.md` (the platform builds its allowlist from there) and a test.

## Appendix B. ERP records the plan depends on

`Sales Order`, `Sales Contract`, `Tech Pack`, `TNA Template`, `TNA Template Milestone`, `TNA Milestone Type`,
`Order TNA`, `TNA Milestone`, `Holiday List`, `Sample Approval`, `PP Meeting`, `Fabric Requisition`,
`Trim Requisition`, `Purchase Order`, `Purchase Receipt`, `Fabric Inspection`, `Trim Inspection`,
`Quality Inspection`, `Final Inspection`, `Cut Plan`, `Work Order`, `Factory Allocation`, `Production Card`,
`Job Card`, `Packing List`, `Shipment`, `Delivery Note`, `Plant Floor`, `Apparel Settings`,
`Apparel Sample Rule`, `Sample Requirement`, and the new `TNA Capacity`.

Present today and used by the plan: all except `TNA Capacity` (to be created) and the three doctypes in G16
that must be repointed or created.

## Appendix C. Vocabulary map (summary; the full table ships with phase 0)

ERP code kept, Tower code becomes an alias:

| ERP (33) | Tower alias |
|---|---|
| ORDER_RECEIVED | ORD_CONF |
| TECH_PACK_RECEIVED | TECH_PACK |
| BOM_RECEIVED | BOM_APPROVAL |
| BULK_STANDARD_RECEIVED | WASH_STD_APPROVAL |
| MINI_MARKER | MARKER_APP |
| FR_RAISED | FABRIC_BOOK |
| TR_RAISED | TRIMS_BOOK |
| FABRIC_BOOKED | FABRIC_PO |
| TRIM_PI | TRIM_CARD_APPROVAL |
| FIT | FIT_APPROVE |
| LAB_DIP | LABDIP_SUB, LABDIP_APP |
| TRIMS_APPROVED | TRIM_CARD_APPROVAL |
| BULK_FABRIC_READY_MILL | BULK_FABRIC_RELEASE |
| FABRIC_ETD | (tower had no equivalent, added) |
| FABRIC_IN_HOUSE | FABRIC_INHOUSE |
| FABRIC_QC_PASSED | FABRIC_INSPECT |
| FPT_PASSED | (added) |
| TRIMS_IN_HOUSE | TRIMS_INHOUSE |
| TRIMS_QC_PASSED | TRIMS_INSPECT |
| BULK_FABRIC_APPROVED | (added) |
| PP_GPT | PP_SAMPLE_APP |
| PP_MEETING | PP_MEETING |
| PCD | (pinned anchor, not a task) |
| PILOT_RUN | PILOT_RUN |
| TOP | SIZE_SET |
| BULK_FINISH | SEW_START, SEW_END, FINISH_END |
| WASH_FINISHED | WASH_SEND, WASH_RECV, WASH_TRIAL_APPROVAL |
| PACK_FINISHED | PACK_START, PACK_END |
| FINAL_INSPECTION | FINAL_INSP, (QC_ENDLINE maps here) |
| FREIGHT_BOOKING | FORWARDER |
| EX_FACTORY | SHIP_READY, SHIP |
| ON_BOARD | CARGO_HANDOVER, BL_AWB |
| IN_WAREHOUSE | DELIVERY |

New types seeded into the ERP for Tower checkpoints with no ERP parent: `SALES_CONTRACT`, `COST_APPROVAL`,
`CAPACITY_BOOK`, `PATTERN`, `PROTO_SAMPLE`, `PROTO_APPROVE`, `SHADE_BAND`, `OPS_BULLETIN`, `LINE_PLAN`,
`MAT_RELEASE`, `CUT_START`, `CUT_END`, `CUT_PANEL_QC`, `QC_INLINE`, `POST_WASH_MEAS`, `CARTON_AUDIT`,
`PACKLIST`, `COMM_INVOICE`, `COO_DOCS`, `SHIPPING_ADVICE`, `DOC_DISPATCH`, `ORDER_CLOSURE`.

## Appendix D. Phases at a glance

| Phase | Days | What you can do after it |
|---|---|---|
| 0 Foundations | 6 to 8 | the ERP and the Tower show the same plan for a real order, with role checks |
| 1 Scheduling | 10 to 13 | the plan moves when reality moves, and is agreed against a frozen baseline |
| 2 Evidence | 6 to 8 | dates are proved by documents, or by a person with a reason and a link |
| 3 Alerts | 5 to 7 | the right person is told, once, and can own it |
| 4 Capacity and learning | 9 to 12 | line loading, calibrated lead times, a ranked risk list, a delay Pareto |
| 5 Surfaces | 7 to 9 | phone-first recording, buyer pack, calendar feed |
| 6 Reading and answering | 5 to 7 | a buyer sheet becomes plan changes, and questions get answers with sources |
