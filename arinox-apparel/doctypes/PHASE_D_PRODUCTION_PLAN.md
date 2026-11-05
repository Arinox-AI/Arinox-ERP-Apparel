# Phase D — Production: Production Card → Pilot Run → Bulk Cutting → Bulk Sewing → Subcontracting (wash, embroidery, print, appliqué) → Finishing → Packing → Final Inspection → Order Reconciliation

**Status:** Plan written 2026-11-05. **Partly built (D0 to D4 on the dev site, D5 to D9 not started).** See [PHASE_D_BUILD_STATUS.md](PHASE_D_BUILD_STATUS.md) for what exists, what was verified, and where the build differs from this plan. (The user calls this "Phase 4"; it follows Phases A, B and C, so the folder and code call it Phase D.)
**Module:** Arinox Apparel
**Spec form:** one consolidated spec for the phase, same as Phases B and C.
**Written for:** the builder (Sonnet) who will implement it slice by slice. Everything a builder needs to decide is decided here or listed in section 14 with a default.

**Sources**
- Company documents opened for this plan (extracted from the zip to a scratchpad, read with the `xlsx` and `pdf` skills): `PRODUCTION CARD-SIZE BREAKUP 20445.xlsx` (both sheets), `TRIM CARD 20445-SP27.xlsx`, `PRODUCTION REPORT FORMAT MULTIPLE.xlsx` (5 sheets), `BELLADAHL OBS R&D.xlsx` (5 operation bulletins), `Cutting, sewing, finishing & packing detail report.xlsx`, `CORTEX VN PRODUCTION REPORT.xlsx`, `IN LINE AUDIT REPORT.xlsx`, `Finishing Inspection Report.xlsx`, `SPEC SHEET FOR BEFORE WASH.xlsx`, `Pilot Run.pdf`, `Final Inspection Report.pdf`, one packing list and its summary packing list (`C2027-S84`), and a wash payment request, a wash VAT invoice and the full 3-page **wash processing contract** (`Thanh toan Wash PPJ Hoa don 411`, scanned, read as images).
- Industry research notes saved in `../research_notes/Apparel production cutting to packing/` (untracked, not for commit): `cutting_and_pilot.md`, `sewing.md`, `finishing_and_packing.md`. Each separates sourced findings from the researcher's own inferences. Mostly practitioner sources (no public buyer manual or apparel-ERP field spec was found).
- **Research that did NOT finish:** the subcontracting study and the final-inspection / reconciliation study were stopped before they saved anything. This plan fills those two areas from the company's own wash contract, Final Inspection form and production reports, plus general ISO 2859-1 practice. **Gaps are listed in section 15.** Customs and tax rules for goods sent out for processing were not researched; the plan is jurisdiction-neutral (decision D14).
- The built app (Phases A to C) and ERPNext v16.34.1 source (paths cited inline).

---

## 0. Read this first (for the builder)

1. Read `../CLAUDE.md` (hard rules), then `../skills/frappe-doctype/SKILL.md`. Read the skill again before each new doctype.
2. Read `PHASE_B_PLAN_AND_APPROVE.md` and `PHASE_C_MATERIALS_PLAN.md` (status log at the end). Phase D reuses their patterns: rules in Python controllers, settings tables not hard-coded rules, a manager override with a reason, a whitelisted agent API, tests per slice, T&A auto-stamping that never raises.
3. **Nothing is tied to one company or buyer.** Cortex numbers (5 % extra cut, 1 % / 3 % wash thresholds, ±5 % wash quantity, AQL 2.5 / 4.0) are **seed data** in settings or terms. Code never names a buyer, a vendor, or a factory.
4. Never copy bank, tax, customs or contract identifiers from the reference files into code, seeds, tests or specs. Tests use made-up numbers; the golden numbers in section 12 are quantities only.
5. Build slice by slice (section 13). Each slice ends with `migrate`, tests passing, a status note at the end of this file, and a stop for user review.
6. Never commit or push. Never run anything against the hosted site. Never edit `erpnext/`.
7. **Prints are English only for now, and global.** The company's own forms are bilingual (English / Vietnamese), but the user decided on 2026-11-05 to build for any country and add languages later. Write every label through Frappe's translation function (`_()`), so a second language can be added with a `translations/<lang>.csv` once the user supplies the strings. Do not machine-translate and do not hard-code another language. Section 11.4 keeps the Vietnamese strings from the reference forms as a starter list for that later file only.

### Skills and tools to use

| When | Use |
|---|---|
| Before any doctype, controller, hook, fixture, patch | `frappe-doctype` (this repo: `arinox-apparel/skills/frappe-doctype/SKILL.md`) |
| Reading a reference workbook again, or building test fixtures from one | `xlsx` skill. Extract from the repo-root zip into your scratchpad, read-only, run Python with `-I` using the bench interpreter `/workspaces/frappe-bench/env/bin/python` (system Python has no openpyxl) |
| Reading a reference PDF (pilot run, final inspection, wash contract) | `pdf` skill. The wash PDFs are **scanned images**: extract the page images with `pypdf` and look at them with the Read tool |
| Any chart, colour, legend or stat tile (line efficiency, DHU, vendor scorecard, production board) | `dataviz` skill, **before** writing chart code |
| Looking up ERPNext or Frappe behaviour | Read the source and cite the path in your notes. ERPNext: `/workspaces/frappe-bench/apps/erpnext/erpnext/`. Frappe: `/workspaces/frappe-bench/apps/frappe/` |
| Seeding the AQL table (D7) | `WebSearch` for two independent published ISO 2859-1 Table 2-A sources and cross-check every number (section 10.3) |
| Checking a desk screen or print works | `run` skill: start the bench, open the form, take a screenshot. Phases B and C left JS untested in a browser; do not repeat that. Specifically open: Production Card, Lay Report, Daily Line Report, Subcontract Challan, Packing List, Final Inspection, and print the bundle ticket and carton label |
| End of every slice | `code-review` at `medium`, then `simplify` |
| Slice D9 (close-out) | `security-review` (whitelisted methods, permissions, the amounts on Subcontract Settlement) |
| If a pattern repeats in more than three doctypes (the movement ledger, the override-with-reason block) | Add a short section to `skills/frappe-doctype/SKILL.md`; do not copy-paste the pattern a fourth time |

Bench: `/workspaces/frappe-bench`, site `apparel.localhost`. Loop: edit → `bench --site apparel.localhost migrate` → `bench --site apparel.localhost run-tests --app arinox_apparel` → open in desk. After a Codespace restart: `docker start apparel-mariadb apparel-redis`.

### Glossary (new terms)

| Term | Meaning |
|---|---|
| Production card | The order sheet issued to cutting: colour × size breakup, extra cut, fabric required, packing requirements |
| Extra cut / cutting allowance | % cut above order quantity to cover losses (the sheet calls it "fabric allowance 5 %") |
| PCD | Planned cut date |
| Pilot run | A small bulk-line trial after the PP meeting, before bulk cutting: real fabric, real line, real wash |
| Marker | The cutting layout; **marker efficiency** = pattern area ÷ marker area |
| Lay / ply | A lay is the spread stack of fabric under one marker; a ply is one layer |
| Cut plan (lay plan) | The plan of which markers, size ratios and plies make up the cut quantity |
| End bit | Fabric left at the end of a ply or roll too short for a garment |
| Shade band | Rolls of one colour that match each other; never mixed within a garment |
| Stickering | Numbering every cut ply so all panels of one garment come from one ply |
| Bundle | A ticketed group of cut panels (one size, consecutive plies) that travels to the line |
| Challan | A delivery note for goods sent out to a subcontractor (and the matching return note) |
| OB / SAM | Operation bulletin (operation list per style) / standard allowed minutes per garment |
| DHU / RFT | Defects per hundred units / right first time (pieces passing first inspection ÷ checked) |
| B-grade | A sellable-at-discount second; **reject** is scrap |
| TOP sample | Top-of-production sample sent to the buyer before shipment |
| AQL | Acceptable quality limit; Ac / Re = accept / reject numbers for a sample size |
| SSCC | 18-digit unique carton ID in the GS1-128 carton barcode |
| CBM | Cubic metres of a carton (L × W × H) |

---

## 1. Research findings that shape the design

### 1.1 The standard flow (and how it maps)

```
Production Card issued ──► PP Meeting (Phase B) ──► Pilot Run ──► [bulk gate] ──► Bulk Cutting
        │                                                                              │
        │                                         panels: embroidery / print / appliqué (out and back)
        │                                                                              ▼
        │                                                                        Bulk Sewing (line input → output, inline + end-line QC)
        │                                                                              │
        │                                                      garments: wash / garment processes (out and back)
        │                                                                              ▼
        │                                                              Finishing (labels, press, tag, barcode, polybag, tissue; metal detect)
        │                                                                              ▼
        │                                                              Packing (cartons, SSCC, packing list) ──► Final Inspection (AQL)
        │                                                                              ▼
        └───── every stage writes the Production Movement ledger ─────► Delivery Note ──► Order reconciliation and close
```

Evidence summary (details and sources in the research notes):
- **Cut quantity** = order quantity × (1 + extra cut %); 2 to 5 % is typical, higher with more processes such as wash (one trade source; no authoritative standard). The company sheet uses 5 % fabric allowance as the extra cut, and 2 % for trims.
- **Pilot run** happens after the PP sample is approved and the PP meeting is held, before bulk cutting, on the real line with real bulk fabric. Reported quantity is 25 to 30 pieces minimum up to 100 to 200 per style (sources conflict, so it is a setting). Small orders (one source: under about 1,000 pieces) often skip it. Washed styles are approved after wash.
- **Cutting** is a controlled chain: group rolls by shade, shrinkage and width → cut order plan (markers, ratios, plies) → spread (one shade per lay) → cut → sticker every ply → bundle and ticket → inspect panels (often 100 %) → re-cut from the same roll or the same dye lot with approval → reconcile fabric.
- **Sewing**: line capacity = operators × working minutes × efficiency; loading = order qty × SAM; a new style follows a learning curve of rising efficiency over its first days (no sourced percentages; each factory builds its own). Quality is tracked as DHU, defect % and RFT; inline checks use a traffic-light system (5 or 7 pieces per operator per round; thresholds vary); the end-line audit checks 100 % hourly. Damaged panels are replaced by re-cutting.
- **Finishing**: trim threads, check, attach, spot clean, press, final check, fold and tag, **metal detection** (calibrate with a 1.2 mm test piece at start-up and at intervals; keep records at least 1 year; if a check fails, re-scan everything passed since the last good check), pack. Output is split into A-grade, rework, B-grade and reject. Neck, size and care labels are sewn in at finishing on washed garments (the researcher's inference: wash can fade or shrink labels; no source stated why).
- **Packing**: solid (one colour, one size per carton), ratio/assorted (sizes in a set ratio), mixed; a unique **SSCC-18** per carton in a GS1-128 barcode that must match the shipping notice exactly and is never reused; every style-colour-size has its own GTIN; polybag suffocation warnings are required by several US states for film under 1 mil above size triggers (aggregator source, not the statutes); Canada needs fibre content in English and French. CBM = L × W × H; net weight on the packing list must match the bill of lading. Cartons are usually capped at about 50 lb (22.7 kg).
- **Final inspection** uses ISO 2859-1 / MIL-STD-105E General Level II, single sampling, normal inspection, AQL 0 critical / 2.5 major / 4.0 minor (it is on the company's own form).
- **ERPNext fit:** Packing Slip can only be made from a **draft** Delivery Note and has no carton master, ratio, CBM or SSCC (`erpnext/stock/doctype/packing_slip/packing_slip.py` line 82). Subcontracting Order / Receipt need a finished-good item distinct from the raw material and a Subcontracting BOM, and know nothing of size × colour breakups or vendor rejection thresholds. Work Order is per SKU and BOM-backflushed.

### 1.2 What the company's own documents show (findings the first design would have missed)

1. **Circular gate in Phase B.** PP Meeting submit requires "production card issued on or before the meeting date" (Phase B rules), and the bulk gate requires the PP Meeting. So the Production Card **must be issuable before the PP meeting and before the gate**. Phase D therefore moves the bulk gate from "Work Order submit" to **"first bulk lay"** and issues the card with no gate (section 5.4).
2. **Order grain.** The sheet is per style, colours as rows, sizes as columns. Phase D's Production Card key is Sales Order × style × ex-factory date (the same grain as Order TNA), with one line per colour × size.
3. **Typed fractions.** The reference card shows a cut quantity of 1894.2 pieces (a size shows 163.8, 454.65 …). A cut quantity must be a whole number per size: round **up** per size. The reference order of 1,804 pieces at 5 % becomes **1,897** pieces cut, not 1,894.2 (section 12).
4. **Sizes have typos** in the reference (`Marge`, `Larger`). Importers and the agent API must map or reject unknown size names, never store them (same rule as Phase C case 7).
5. **Roll list shows short rolls** (46 m, 37.8 m, 50.7 m, 94.6 m among rolls of about 145 m, 26 rolls, 3,285.5 m). Short rolls produce end bits and "fabric shortage in the roll" (the daily cutting report has a `FABRIC SHORTAGE IN ROLL` line).
6. **The daily production report reconciles exactly** and is the template for the ledger (section 12): `cut = packed + B-grade + rejects` and `packed = shipped + A-grade stock`. Its loss categories are: washing rejection, stain garments, factory rejection, fabric rejection, spec issue, damage, returned to warehouse, missing.
7. **The OB sheet has a formula bug.** `PCS / HR` divides the daily output by **9.5 hours even when the sheet's working time is 480 minutes** (C2027: 358.03 ÷ 9.5 = 37.69; correct is 358.03 ÷ 8 = 44.75). The expected output per day (358.03 = 28 operators × 480 × 0.65 ÷ 24.4) is correct. The ERP must compute from the stored working minutes.
8. **Packing list oversells the buyer's per-size 3 % line**: shipped 1,520 vs PO 1,462 is +3.97 % in total, and individual sizes are +2.2 % to +6.25 %, against a "3 % over/short" check printed on the sheet. The contract tolerance bands (Phase A) allow ±7.5 % at this quantity. The ERP needs both a total check and a per-size check and must say which rule applies (decision D10).
9. **Carton height varies** (14, 18, 20, 22 cm; L and W fixed at 54 × 33): CBM is per carton, not per carton type. 54 × 33 × 14 cm = 0.024948 m³ (matches the sheet). Gross weight is per carton row (5.1 to 5.9 kg). The tail carton is a mixed carton (12 + 6 pieces).
10. **Buyer packing instruction (from the production card):** hang tag on the size label, polybag sticker bottom right, regular fold, tissue paper, **solid colour solid size, tail carton mixed colour mixed size**. These belong on a Packing Instruction, not in free text.
11. **The wash contract is the subcontracting rule book** (section 8.1): ±5 % quantity tolerance; vendor-damaged pieces are **not paid**; **FOB penalty if wash damage exceeds 1 % per colour** (normal and enzyme wash) or **3 %** (dye, bleach, acid wash), measured per style per colour; vendor checks 10 % of each incoming lot before washing and must report over-limit defects, and if it washes without written confirmation it carries the responsibility; both sides confirm quantities within **3 days** of each delivery or later complaints are not accepted; turnaround 1 day (normal), 3 days (enzyme, light bleach), 5 to 7 days (dye, acid, hard wash), excluding Sundays and holidays; batches of at least 2,000 pieces (one delivery if the order is under 1,000); first a sample with 6 legs for a test run, then size set and pilot, then a first lot of at least 200 pieces approved before bulk; payment 30 days after the order is closed, against a VAT invoice plus a settlement statement the vendor stamps; price in USD converted to VND at a fixed bank rate on the contract date; VAT 8 % on the invoice.
12. **Reconciling the paperwork has real gaps.** The wash contract is for 6,656 pieces and the vendor invoiced 6,909 (+3.80 %, inside ±5 %); the factory's own detail sheet shows 6,992 sent to wash for the style. The grains differ (one colour vs style) so this is not proof of loss, but it shows why sent, returned, rejected, short and invoiced quantities must sit on one reconciliation (ask the user to check this one pair).
13. **Payment is requested per vendor invoice** on an internal "Payment Request" (applicant, department, invoice number, amount in VND and in words, signatures). The Subcontract Settlement prints that form.
14. **The company's end-line audit and finishing inspection forms are the same form** (hourly grid 7:30 to 18:00, passed pieces, defect analysis by code, total checked, DHU = defects × 100 ÷ checked). One doctype with an `audit_type`.
15. **The Final Inspection form** has: report type (In Line, Final, Re-inspection, 2nd Re-inspection, Other), Level II, AQL critical 0 / major 2.5 / minor 4.0, PO quantity, offered quantity, cartons inspected, sample size, defect lists (sewing, fabric, general), measurements, test status (FPT, GPT, Azo, wash care, fibre content as per test report), conformity to sealer sample (style, material, colour), result (Accepted, On Hold, Rejected), re-inspection date, three signatures.
16. **Daily reports are bilingual** (English and Vietnamese) and list per line: line loading (style, quantity loaded today, cumulative), cut qty by size by day, fabric shortage in roll, sent today / total / received / balance for wash, packed, shipped.

---

## 2. What ERPNext already has, and how it is used

| Need | ERPNext object | Decision |
|---|---|---|
| Fabric and trim stock, rolls | Stock Entry (Material Transfer), Batch (one per roll, Phase C fields) | **Reuse** for fabric and trim issue to the floor, remnant return, finished goods in. Entries are created by buttons and tested |
| Sewing line, factory | Workstation (`plant_floor`), Plant Floor (Phase B) | **Reuse** + custom fields (section 4.4) |
| Production order | Work Order / BOM / Job Card | **Not used for tracking.** Work Order is per SKU (size × colour variant), consumes a BOM by backflush, and has no size matrix, lay, bundle, or subcontract steps. The Phase B Work Order gate stays in place for anyone who still creates one, but the Production Card runs the same gate function itself (section 5.4) |
| Outsourced processing | Subcontracting Order / Receipt | **Not used.** Needs a distinct finished item and Subcontracting BOM per process, supplied-items stock moves, no size / colour matrix, no per-style threshold, no debit logic. Replaced by **Subcontract Challan / Return / Settlement** |
| Vendor order and invoice | **Purchase Order** with a service item, **Purchase Invoice**, Purchase Invoice with `is_return` (debit note) | **Reuse.** The PO is the subcontract order (ordered qty, rate, ±5 % check); Settlement creates a draft PI and a draft debit note |
| Barcodes | Item `barcodes` child (barcode, type EAN / UPC-A) | **Reuse** for one GTIN per size × colour variant |
| Delivery | Delivery Note (from Sales Order) | **Reuse** + custom fields. Created from the Packing List |
| Packing | Packing Slip | **Not used** (draft Delivery Note only; no carton master, ratio, CBM, SSCC). Replaced by **Packing List** |
| Final QC | Quality Inspection | **Not used** for the final inspection (its model is per-item parameter readings; the final inspection is lot + AQL + defect classes). Phase C's Quality Inspection use for receiving is unchanged |
| Holidays | Holiday List on Company | **Reuse** (wash turnaround dates, T&A) |
| Planning | Production Plan | **Not used** (same reason as Phases B and C) |

---

## 3. Architecture: one ledger, many documents

Every stage document writes quantities into a single append-only table, so reports and reconciliation are one query and the stages cannot drift apart.

### 3.1 Production Movement (plain doctype, written only by code)

| Field | Type | Notes |
|---|---|---|
| production_card | Link Production Card | reqd, indexed |
| sales_order, style_item, colour, size | Link / Data | denormalised for fast reports; indexed on (production_card, stage) |
| stage | Select | `CUT`, `CUT_REJECT`, `SEW_IN`, `SEW_OUT`, `SEW_REJECT`, `SC_OUT`, `SC_BACK_GOOD`, `SC_BACK_REJECT_VENDOR`, `SC_BACK_REJECT_FACTORY`, `FIN_IN`, `FIN_A`, `FIN_B`, `FIN_REJECT`, `SAMPLE_OUT`, `PACKED`, `SHIPPED` |
| purpose | Select Bulk / Pilot / Re-cut / Sample | pilot pieces are tracked but listed apart |
| process | Link Subcontract Process | for `SC_*` stages |
| qty | Float | positive from documents; **negative only from Production Adjustment** |
| posting_date | Date | |
| line | Link Workstation | sewing and finishing |
| supplier | Link Supplier | `SC_*` |
| shade_band | Data | |
| fault_source | Select | Factory Sewing / Fabric / Cutting / Subcontractor / Trims / Spec or Pattern / Handling / Unknown |
| source_doctype, source_name, source_row | Dynamic Link / Data | |

- Written by `on_submit` of the source document, removed by `on_cancel` (delete the rows whose `source_doctype + source_name` match; the source document is the truth). `rebuild_movements(production_card)` recomputes everything from the submitted documents; a test must show rebuild equals the incremental result.
- Helpers in `arinox_apparel/production/ledger.py`: `post(rows)`, `unpost(source_doctype, source_name)`, `totals(production_card, by=("colour","size"), purpose=None)` (one SQL `group by`), `available(production_card, stage, colour, size)`.
- Read-only for everyone except System Manager; list view hidden from the menu (reports and the card summary are the screens).

### 3.2 Flow rules (the "availability" rule each document enforces on submit)

Per production card × colour × size, using ledger totals `T(stage)`:

| Stage being posted | Maximum allowed |
|---|---|
| `CUT` (bulk, pilot, re-cut) | Bulk: `planned_cut_qty + cut_cap_extra_pcs` less already cut (excluding re-cut). Re-cut has its own cap: pieces rejected so far less re-cuts already made |
| `SEW_IN` | `T(CUT) − T(CUT_REJECT) − T(SEW_IN)`; when the card route has a **before-sewing** process, also `≤ T(SC_BACK_GOOD for that process)` |
| `SEW_OUT` + `SEW_REJECT` | `T(SEW_IN) − T(SEW_OUT) − T(SEW_REJECT)` |
| `SC_OUT` | the output of the previous route step (`SEW_OUT` for the first after-sewing process; the previous process's `SC_BACK_GOOD` for a chained one; `CUT − CUT_REJECT` for a before-sewing process) less already sent for that process |
| `SC_BACK_*` | `T(SC_OUT of the challan row) − already returned on that row` (a vendor cannot return more than was sent on that challan row) |
| `FIN_IN` | the output of the last route step before finishing (`SEW_OUT` if no garment process; otherwise the last process's `SC_BACK_GOOD` plus any factory-fault rejects accepted for repair, see 9.4) less `FIN_IN` so far |
| `FIN_A + FIN_B + FIN_REJECT` | `T(FIN_IN) − already classified` |
| `SAMPLE_OUT` | `T(FIN_A) − T(SAMPLE_OUT) − T(PACKED)` |
| `PACKED` | `T(FIN_A) − T(SAMPLE_OUT) − T(PACKED)` |
| `SHIPPED` | `T(PACKED) − T(SHIPPED)` |

Exceeding a limit throws, naming the stage, size and shortfall. A Production Manager can submit with **Flow Override** + reason (same pattern as the Phase B gate override). A **Production Adjustment** (submittable, manager only: stage, colour, size, signed qty, reason) corrects counting errors without editing history.

### 3.3 Stock postings (decision D5; the Material Request / receipt patterns of Phase C apply)

Production tracking is **quantity-based**. Only these ERPNext Stock Entries are created, each by a named button and linked back:

| Posting | When | Default |
|---|---|---|
| Fabric issue: Material Transfer, fabric store → **Cutting WIP** warehouse, by Batch (roll) | "Issue Fabric to Cutting" on Production Card | **Submitted** (a transfer, no profit and loss effect; same as Phase C inspection transfers) |
| Remnant return: Material Transfer, Cutting WIP → fabric store, with a remnant Batch per roll that has leftover | Lay Report submit (end bits above `remnant_min_m`) or "Return Remnants" | Submitted |
| Trim issue: Material Transfer, trim store → **Line WIP** warehouse, from the Trim Requisition lines | "Issue Trims" on Production Card | Submitted |
| Finished goods in: Material Receipt of packed pieces into the **Finished Goods** warehouse at the Cost Sheet cost per piece | Packing List submit | **Draft** (hits the accounts; the accountant submits). A Delivery Note cannot submit until it is submitted unless negative stock is allowed |
| Fabric and trim consumption: Material Issue of what is left in Cutting WIP / Line WIP (issued − returned) | "Close Production" | **Draft** |

`auto_submit_stock_entries` (Apparel Settings) switches the two Draft rows to submitted. Warehouses (Cutting WIP, Line WIP, Finished Goods, Seconds, Scrap) are created in `after_install` if missing, as in Phase C.

---

## 4. Settings, masters and custom fields (slice D0)

### 4.1 Apparel Settings: new section "Production"

| Field | Type | Default | Notes |
|---|---|---|---|
| default_extra_cut_pct | Percent | 5 | Sheet shows 5 % fabric allowance used as extra cut |
| max_extra_cut_pct | Percent | 8 | Warn above (hard stop for non-managers) |
| trim_allowance_pct | Percent | 2 | Printed on the card; trims themselves are requested in Phase C |
| pilot_min_order_qty | Int | 1000 | Pilot required at or above this order qty (one source; confirm D2) |
| pilot_default_qty | Int | 30 | Per style; lines = all sizes or jump sizes |
| pilot_waiver_role | Link Role | Apparel Production Manager | |
| bundle_size | Int | 20 | Research range 10 to 20 |
| cut_cap_mode | Select Block / Warn / Off | Block | cutting above `planned_cut_qty + cut_cap_extra_pcs` |
| cut_cap_extra_pcs | Int | 3 | Per colour × size, covers ratio rounding |
| marker_variance_pct | Percent | 5 | Marker consumption vs FR or costed: above this the cut plan needs manager approval |
| shade_one_per_lay | Check | 1 | Always on; shown for transparency |
| max_width_spread_cm | Float | 1.0 | Rolls in one lay must be within this width |
| max_shrinkage_spread_pct | Float | 3 | Rolls in one lay must be within this warp/weft shrinkage spread (denim and washed styles) |
| panel_inspection_pct | Percent | 100 | % of cut panels checked |
| remnant_min_m | Float | 5 | End bits shorter than this are waste, not a remnant roll |
| work_minutes_per_day | Int | 480 | Default; the OB and line override it (the company's other OBs use 570) |
| planned_efficiency_pct | Percent | 65 | From the OB sheets |
| learning_curve | Table Learning Curve Day (day_no, pct_of_target) | 1: 50, 2: 75, 3: 90, 4: 100 | **Assumption**, not sourced; flag to the user |
| inline_check_pieces | Int | 5 | Pieces per operator per round (5 or 7) |
| traffic_light_rules | Table (colour, defects_from) | Yellow 1, Red 2 | Configurable; the stricter variant is red on any defect |
| gate_for_inline_red | Select Warn / Off | Warn | A red operator raises an alert on the line report |
| dhu_alert_threshold | Float | 5 | Highlight in reports; no blocking |
| require_bundle_on_input | Check | 1 | Line Input must list bundles |
| require_bundle_on_output | Check | 0 | Output may be by quantity |
| kit_check | Select Block / Warn / Off | Warn | Secondary-component bundles must exist before the shell bundle is issued |
| subcontract_default_threshold_pct | Percent | 1 | Fallback when a vendor has no terms row |
| subcontract_penalty_scope | Select All Damaged / Excess Only | All Damaged | Decided with the user (D6); `Excess Only` kept as an option |
| subcontract_penalty_basis | Select Cost Sheet FOB / Sales Order Rate / Fixed Per Piece | Cost Sheet FOB | |
| subcontract_reconcile_days | Int | 3 | Quantity confirmation window |
| require_pilot_before_bulk_wash | Select Block / Warn / Off | Warn | |
| needle_check_required | Select Block / Warn / Off | Warn | Metal detector check logged that day before finishing is submitted |
| needle_test_piece_mm | Float | 1.2 | |
| needle_recheck_hours | Float | 2 | Policy: re-check about every 2 hours |
| final_inspection_plan | Link AQL Plan | seeded | |
| ship_gate_final_inspection | Select Block / Warn / Off | Block | Delivery Note needs a passed final inspection |
| ship_tolerance_basis | Select Total / Each Size / Both | Both | Over-ship check (D10) |
| carton_max_gross_kg | Float | 22.7 | About 50 lb |
| gs1_company_prefix | Data | blank | Needed for SSCC; blank = SSCC off |
| carton_pick_rule | Select Square Root / Fixed Pct | Square Root | Final inspection carton selection (D12) |
| auto_submit_stock_entries | Check | 0 | Section 3.3 |
| post_fg_receipt | Check | 1 | Drafts the finished goods receipt at Packing List submit |
| controlled_trim_tolerance | Int | 0 | Branded labels, hang tags, barcode stickers must reconcile to this many pieces |

Use the Phase B `set_settings_defaults` approach: never reset a Check the user switched off.

### 4.2 New master doctypes

| Doctype | Fields | Seed |
|---|---|---|
| **Apparel Defect Code** | code, defect_name, stage (Select: Cutting / Sewing / Washing / Finishing / Final, multi via `applies_to` child or Small Text), severity (Critical / Major / Minor), fault_source (as the ledger list) | **Sewing** from the end-line form: Broken or loose stitch, Open seam or raw edge, Puckering, Joint stitch visible, Bar tack / button / buttonhole (insecure, missing), Alignment, Label (wrong size label, incorrect placement, crossed label), Poor ironing, Shine or crease marks. **Fabric**: stains, holes, shade variation, weaving. **Final form**: open seams, weak seams, broken stitches, overlock quality, balancing, needle marks, wavy stitching, neck shape, snagging, uncut or loose threads, raw edges, inside finishing, elastic quality, embroidery placement, embroidery fraying, snaps / studs / zipper, pilling, hand feel, print defects, measurements. **Loss categories** from the daily report: washing rejection, stain garment, factory rejection, fabric rejection, spec issue, damage. Wrong size label and any needle or metal finding are seeded **Critical** (a wrong size label is a recall risk; user to confirm severities) |
| **Subcontract Process** | process_name, default_position (Before Sewing / After Sewing), item_state (Cut Panels / Garments), billing_uom (Pcs / Kg), requires_approved_standard (Check) | Wash (After Sewing, Garments, Pcs, approved standard), Embroidery (Before Sewing, Cut Panels), Print (Before Sewing, Cut Panels), Appliqué (Before Sewing, Cut Panels), Heat Transfer, Garment Dye |
| **AQL Plan** (+ child **AQL Plan Row**) | plan_name, level, rows: lot_from, lot_to, code_letter, sample_size, major_ac, major_re, minor_ac, minor_re, critical_ac (0), critical_re (1) | "General II – 0 / 2.5 / 4.0". **Numbers in section 10.3; QA must confirm** |
| **Carton Type** | type_name, length_cm, width_cm, height_cm, tare_kg, max_gross_kg, ply_note, customer (optional) | One example type from the packing list (54 × 33 cm, heights 14 / 18 / 20 / 22) |
| **Production Check Item** | check_name, applies_to (Pilot Run / Pre-pack / Line Setting) | From the pilot-run form (section 6.1) |

### 4.3 New roles (fixture, as in Phase A)

`Apparel Production Manager` (all production documents, overrides, adjustments, close), `Apparel Production User` (floor data entry: lay, line, finishing, packing, challan, return), `Apparel QA` (pilot approval, inspections, AQL, final inspection). Existing roles (`Apparel Merchandiser`, `Apparel Merchandising Manager`) read all production documents and create Production Card, Subcontract Terms and Settlement drafts. Costing amounts (Subcontract Settlement, Terms rates) are visible only to Production Manager, Merchandising Manager, Accounts.

### 4.4 Custom fields (in `setup/install.py` `get_custom_fields`)

| Doctype | Fields |
|---|---|
| Company | `apparel_pc_prefix` (default PC) |
| Supplier | `apparel_supplier_type` gains options **Embroidery, Printing, Appliqué, Garment Dye** (existing field from Phase C: extend, do not recreate) |
| Workstation | `apparel_line_type` (Cutting / Sewing / Finishing / Packing), `apparel_default_operators` (Int), `apparel_default_helpers` (Int) |
| Trim Category | `apparel_controlled_trim` (Check: labels, hang tags, barcode stickers, branded tissue reconcile to zero) |
| Purchase Order | `apparel_production_card`, `apparel_subcontract_process` (Link), `apparel_style_no`, `apparel_colour` (on the item), `apparel_contract_no` (Data). Item-level `apparel_ordered_pcs` is the PO qty |
| Purchase Invoice / Item | `apparel_settlement` (Link Subcontract Settlement), `apparel_challan` on the item row |
| Delivery Note | `apparel_packing_list` (Link), `apparel_over_ship_override` (Check, manager only) + `apparel_over_ship_reason`, `apparel_final_inspection` (Link, ro) |
| Work Order | none new. `overrides/work_order.py` is refactored so the gate is a plain function `bulk_gate_for(sales_order, style, colour, stage)` that both the Work Order hook and the Production Card use (section 5.4) |
| PP Meeting (own doctype, edit the controller) | on `validate`, if `production_card_ref` is blank and a submitted Production Card exists for the order and style, fill `production_card_ref` and `production_card_issued_on` |

---

## 5. Production Card (slice D1)

Submittable. **Submit = issue.** Naming: `apparel_pc_prefix` + `YY.MM.###`, monthly counter, same helper as Phase A contract numbers and Phase C FR numbers. Key: **Sales Order × style × ex-factory date**, one active card per key (a revision chain shares a key).

### 5.1 Fields

**Header:** company, customer, sales_order (reqd, submitted), style_item, style_no, style_name, season, sales_contract (ro), buyer_pos (Small Text, ro, from SO items), ex_factory_date (reqd, from SO items), pcd (from Factory Allocation, else contract line), factory, line (from Factory Allocation), `local_contract_no` (Data), `declaration_no` (Data); optional reference fields that the reference card carries, with no customs logic behind them; **never seed values**, top_sample_size (Data), top_sample_qty_per_colour (Int, default 2), top_sample_eta (Date), packing_instruction (Link Packing Instruction), packing_requirements (Small Text, fetched), is_washed (from the PP Meeting, else Tech Pack finish), pilot_required (Check, computed, see 6.3) + pilot_waiver + reason, bundle_size (default from settings), default_extra_cut_pct, trim_allowance_pct (info), status (Draft / Issued / In Cutting / In Sewing / At Subcontractor / In Finishing / Packed / Shipped / Closed / Cancelled, computed from the ledger), revision_no, previous_card, revision_reason (reqd when revising), made_by, checked_by, qc_assigned, remarks, action_plan_for_fabric (the sheet's "plan of action how to manage this fabric, cutting and sewing").

**Child Production Card Line** (one per colour × size): colour, size, order_qty (sum of SO items over ship-tos and POs), max_qty (order × (1 + SO item `apparel_qty_tolerance_pct`)), extra_cut_pct (default from header), planned_cut_qty (ro), planned_sample_qty (TOP + pilot pieces, info), remarks.

**Child Production Card Fabric** (one per colour × fabric item): fabric_requisition_item (Data), fabric_item, material_role, `material_code_ref` (Data, optional reference code), consumption, consumption_uom, consumption_source (FR / Cost Sheet / Marker), required_m (ro), fr_net_m (ro), accepted_m (ro, from the FR line), issued_m (ro, from Stock Entry), shortage_m (ro), allowance_note.

**Child Production Card Process** (the route): process (Link Subcontract Process), position (Before Sewing / After Sewing), sequence, item_state, supplier (default vendor), colour (blank = all), purchase_order (Link, ro), approved_standard (Link Sample Approval, optional), notes.

### 5.2 Maths and rules (Python, so the agent API cannot skip them)

1. `planned_cut_qty = ceil(order_qty × (1 + extra_cut_pct / 100))` **per colour × size**. Never trust a typed total.
2. `required_m = Σ planned_cut_qty over the colour × consumption`. Compare with the FR line: warn when `required_m` exceeds the FR `net_qty` by more than 1 %; show `shortage_m = required_m − accepted_m`. **The card never creates purchase requests** (Phase C owns that). The reference 5 % "fabric allowance" and the FR allowance are the same 5 %: do not apply it twice.
3. Every colour and size must exist on the Sales Order. Unknown size names (`Marge`) are rejected.
4. `extra_cut_pct ≥ 0`; above `max_extra_cut_pct` needs the manager role and a reason.
5. One active card per key. Cancel is blocked once the ledger has any movement for the card.
6. **No bulk gate on issue** (section 1.2 item 1). Issue warns, and lists, anything missing: no Factory Allocation, no Tech Pack, no FR or TR, no Packing Instruction, no approved BOM.
7. **Revise** (button on an issued card, same pattern as FR): new draft with `previous_card`, `revision_no + 1`, quantities refreshed from the current Sales Order. On submit the previous card becomes Superseded. If a revised `planned_cut_qty` is lower than what is already cut for a colour × size, keep the cut and write a red flag "cut exceeds revised plan by N" (do not block).
8. On submit: fill `production_card_ref` and `production_card_issued_on` on any draft PP Meeting for the same order and style (section 4.4 also does this when the meeting is saved later), and set `issue_date` on the card.
9. **Create Subcontract POs** button: one Purchase Order per vendor × process (service item), lines per colour with qty = `planned_cut_qty` sum for that colour, rate from Subcontractor Terms, `apparel_production_card` set. Draft only.
10. **Issue Fabric to Cutting** and **Issue Trims** buttons: section 3.3. Fabric can only be issued from Batches whose `apparel_inspection_status` is Accepted or Accepted by Lot; Rejected and Hold rolls are refused. Trim issue lists only trim categories that need cutting or sewing; packing trims are issued at finishing.

### 5.3 Print formats

- **Production Card** laid out like the reference sheet (header, colour × size matrix with totals, extra cut, fabric required, packing requirements, signatures), labels through the translation function (section 11.4).
- **Trim Card** (one row per colour, columns per trim category: thread, main label, item or PO label, interlining, button, logo label, polybag, hang tag and hanger, polybag sticker, hang tag sticker), generated from the Trim Requisition lines. Not a doctype.

### 5.4 The bulk gate moves to the first lay

`overrides/work_order.py` becomes a thin wrapper over `production/gate.py: bulk_gate_for(sales_order, style, colour, stage)` returning `{blockers, warnings}`. `stage` is `"pilot"` or `"bulk"`:
- `pilot`: Phase B approvals, PP meeting held with cutting actions closed, material gate. No pilot approval needed (it is the pilot).
- `bulk`: everything in `pilot`, plus **Pilot Run approved** (or waived) when `pilot_required`.

The Work Order hook keeps working (calls the same function with `bulk`). Lay Reports call it (section 7.3). The manager override and reason fields already exist on Work Order; the Lay Report carries its own override pair.

### 5.5 Agent API (whitelisted; check `frappe.has_permission` inside each)

`get_production_context(sales_order)` (SO lines by colour × size, Factory Allocation, FR and TR status, Packing Instruction, ledger totals), `save_production_card(data)` (create or update a draft; validation runs; never submits), `get_production_status(sales_order)` (stage totals per colour × size).

---

## 6. Pilot Run (slice D2)

### 6.1 Documents

The existing **PP Meeting** with `meeting_type = Pilot Run` (Phase B) stays as the review meeting. Phase D adds **Pilot Run** (submittable) as the production record that approves bulk.

**Pilot Run** fields: production_card, sales_order, style_item, line, factory, colours (Table Pilot Run Colour: colour, sizes_run (Data), qty_planned), pilot_pp_meeting (Link PP Meeting, optional), run_date, line_supervisor, line_qc, cutting_supervisor, cad_incharge (Users), status (Draft / Submitted / Approved / Approved with Comments / Rejected / Re-run), result_notes, approved_by, approved_on.
- **Quantities** are not typed here. They come from the ledger (`purpose = Pilot`): cut, sewn, washed, rejected, per colour and size. The pilot is cut by a Lay Report with purpose Pilot and sewn through a Line Input and Daily Line Report with purpose Pilot (section 7 and 8). Pilot pieces that **conform** count toward the order (they ship with it, per the research); rejected pilot pieces are written off against the extra cut. A pilot garment going to the wash vendor travels on a challan of type Pilot (section 9).
- **Check table** (child Pilot Run Check): check_item (Link Production Check Item), result (Yes / No / N/A), comment, action_taken, responsible, where. Items from the company's form: fit and measurements, construction, wash result vs the approved wash standard, trims and labels, line setting, needle and thread, packing, shade. The form also asks QC and supervisor comments **relevant to pattern and cutting**, and the cutting supervisor and CAD in-charge; carry those as `pattern_cutting_qc_comment`, `pattern_cutting_supervisor_comment` (Small Text).
- **SAM validation** (child Pilot Run Operation): operation (from the Operation Bulletin), planned_sam, actual_sam, bottleneck (Check), note. `achieved_efficiency_pct` and `bottleneck_count` are computed.
- **Measurements after wash:** reuse the Phase B child doctype **Sample Measurement** as a Table field if its shape fits (read it first; if not, add a small child). Out-of-tolerance readings default the result to Re-run unless the approver writes a reason. This mirrors Phase B's rule that washed garments are approved only after wash.
- **Defects found** (child with Apparel Defect Code, qty).
- Participants table (name, designation) as the form shows.

### 6.2 Rules

1. A Pilot Run can only be created for an issued Production Card whose PP Meeting is held (stage `pilot` gate passes).
2. To approve: all pilot pieces for the colour are washed (if the style is washed), measurements in tolerance or reasoned, every check item answered, every Fail has an action. The approver needs the `Apparel QA` or manager role.
3. **Rejected** or **Re-run**: bulk cutting stays blocked; a Re-run creates a new Pilot Run for the next trial (the first stays as history). Open pattern or cutting actions raised here are added to the PP Meeting actions table (Phase B) so the existing gate still sees them.
4. On Approve: stamp `PILOT_RUN` actual (already stamped by a Pilot Run PP Meeting; the first of the two wins, the other does nothing), refresh the Order TNA.

### 6.3 When a pilot is required

`pilot_required = order_qty ≥ pilot_min_order_qty` OR a Sample Requirement rule says so (Phase B rule table: add sample type **Pilot Run** with gate If Raised, seeded, per style). Waiver: manager role + reason (`pilot_waiver`, stored on the card). Orders under the threshold skip it. The rule is data; the default 1,000 is one source's cutoff (decision D2).

---

## 7. Bulk cutting (slice D3)

### 7.1 Documents

**Cut Plan** (plain; status Draft / Pending Approval / Released / Superseded). One per production card × colour × fabric item.
- Header: production_card, colour, fabric_item, pattern_version (Data), costed_consumption (ro), fr_consumption (ro), marker_consumption (ro, computed), variance_pct (ro), approved_by (manager), notes.
- **Child Cut Plan Lay**: lay_no, marker_ref (Data), marker_length_m, marker_width_cm, marker_efficiency_pct, planned_plies, shade_band, width_group_cm, shrinkage_group, pieces_per_ply (ro).
- **Child Cut Plan Ratio** (keyed by `lay_no`, Frappe has no nested tables): lay_no, size, ratio (pieces per ply).
- Computed per colour × size: planned output `Σ plies × ratio` vs `planned_cut_qty`, with the variance shown in the plan and a warning when a size in `planned_cut_qty` has no ratio in any lay ("size missing from the lays") or when a lay overshoots a size by more than `cut_cap_extra_pcs`.
- **Suggest Rolls** action: take the Batches available in the Cutting WIP warehouse (inspection status Accepted / Accepted by Lot), group by shade band, then width within `max_width_spread_cm`, then shrinkage within `max_shrinkage_spread_pct`, and allocate to lays, longest roll first, so a lay's rolls cover `planned_plies × marker_length`. Short rolls (the 46 m, 37.8 m, 50.7 m rolls) fill the tail of a lay or become end-bit stock; show the unallocated metres and any lay left short. Nothing is posted until the plan is released.
- **Release rule:** `|variance_pct| ≤ marker_variance_pct`, else status Pending Approval and a manager must approve (the research: a consumption variation must be approved before bulk). Marker consumption = `Σ(marker_length × plies) ÷ pieces cut` (lay consumption).

**Lay Report** (submittable; one per lay per table per day). Purpose Select Bulk / Pilot / Re-cut / Sample.
- Header: production_card, cut_plan, lay_no, colour, fabric_item, purpose, lay_date, table_no, line (the line it feeds), marker_ref, marker_length_m, marker_width_cm, marker_efficiency_pct, shade_band (ro, from rolls), cutting_supervisor, spreading_operator, cutting_operator, remarks, gate_override + reason (manager).
- **Child Lay Roll:** batch (Link Batch, filtered to the cutting warehouse), roll_no (ro), dye_lot (ro), shade_band (ro), width_cm (ro), roll_length_m (ro, available), plies (Int), length_laid_m (computed = plies × marker_length + splice allowance), end_bit_m (the leftover at the end of a ply or roll), end_loss_m (computed), damage_m (fabric damaged and cut out), balance_returned_m (computed: roll length less laid, end bit and damage; goes back to store as a remnant if ≥ `remnant_min_m`), splices (Int), remarks.
- **Child Lay Size:** size, ratio (ro, from the plan), pieces_cut (computed = total plies × ratio), panels_checked, panels_rejected.
- **Child Lay Panel Reject:** size, qty, defect_code (Apparel Defect Code), fault_source, replace (Check: needs a re-cut), remarks.
- Totals: total_plies, laid_m, pieces_cut, rejected_pieces, lay_consumption (laid_m ÷ pieces_cut), cad_consumption (marker length ÷ pieces per ply), difference.

**Cut Bundle** (plain, auto-created on Lay Report submit; name `BDL-.#######`; never edited by hand except status via actions):
production_card, lay_report, colour, size, component (Body / Lining / Pocketing / Contrast / Other), bundle_no (per card), ply_from, ply_to, qty (= ply_to − ply_from + 1; per body when a marker holds several bodies of one size), shade_band, roll_nos (Small Text), kit_key (cut_no + size + ply range; secondary components share it), status (Cut / Issued / At Subcontractor / Back / Complete / Closed / Voided), sewn_qty, rejected_qty, line (when issued), `barcode` (the bundle name, printed as text; no QR or barcode image for now).

**Recut Request** (submittable, manager approval): production_card, size, qty, reason (defect code), replaces (Lay Report or Cut Bundle), source_roll (Link Batch, "same roll"), same_dye_lot_approved (Check) + approved_by when a different roll is used, shade_band (must match the original panels), status. Submit creates nothing in the ledger; the re-cut itself is a Lay Report with purpose Re-cut that links the request. The cap in section 3.2 uses the sum of rejected panels and sewing rejects.

### 7.2 Bundle generation (`production/cutting.py: make_bundles(lay_report)`)

For each lay, size and body index, ply numbers continue from the card's running ply counter (so sticker numbers are unique per cut). Bundles are consecutive plies of one size, up to `bundle_size` plies each; the last bundle is the remainder (a short bundle is allowed and marked). Panels of all components of one garment carry the same ply number (stickering rule). Ply numbers and bundle numbers never repeat on a card; a voided bundle's numbers are not reused.

### 7.3 Rules on Lay Report submit

1. The Production Card must be Issued (not Superseded or Cancelled).
2. **Gate:** `bulk_gate_for(..., stage = "pilot" if purpose is Pilot else "bulk")` per colour. Block with every blocker listed, or pass with a manager override + reason (Lay Report `gate_override` pair, same pattern as Work Order). Purpose Re-cut and Sample use the pilot-stage gate only.
3. Every roll: Batch inspection status must be Accepted or Accepted by Lot (Phase C); a Rejected or Hold roll is refused. Shade band must equal the plan lay's shade band (one shade per lay: block). Width within `max_width_spread_cm` of the plan (warn), shrinkage group within the spread (block when the style is washed, else warn).
4. Roll length available in the Cutting WIP warehouse ≥ length laid + end bit + damage. A roll cannot be used twice beyond its balance.
5. Cut cap per section 3.2 (`cut_cap_mode`).
6. `Σ ply count` per size must match the plan ratios (a lay cannot cut a size that is not in its ratios).
7. On submit: post ledger `CUT` (purpose from the report) and `CUT_REJECT` per size, create bundles, create the remnant Stock Entry (section 3.3) for each roll with balance ≥ `remnant_min_m` (a new remnant Batch keeps `apparel_shade_band`, `apparel_dye_lot` and width), update the Running Fabric Stock columns (section 7.6), stamp `PCD` actual on the first bulk lay (replaces the Work Order trigger; the Work Order hook stays as a fallback; an existing actual is never overwritten).
8. Cancel: blocked if any bundle from the report was issued to a line; otherwise voids the bundles, removes the ledger rows, and reverses the remnant Stock Entry.

### 7.4 Cutting reconciliation (per production card × fabric × colour)

A section on the card (computed, not typed) and the report "Fabric Consumption" (section 7.6). Pin these definitions in the code and the print:
- `issued_m` = Stock Entry fabric issued; `returned_m` = remnants returned; `laid_m` = Σ(length_laid); `end_bit_m`, `damage_m`, `splice waste` as entered.
- `good_cut_garments = Σ(CUT − CUT_REJECT)` (garment sets on the shell fabric).
- `lay_consumption = laid_m ÷ pieces cut`; `actual_consumption = (issued_m − returned_m) ÷ good_cut_garments`.
- `marker_efficiency` = weighted by plies.
- Variances: actual vs costed, vs FR, vs marker. Flag above `marker_variance_pct`.
- **Fabric shortage**: when remaining planned cut needs more than the fabric left (after remnants) the card shows a red flag with the metres short (the daily report has a line for this).

### 7.5 Print formats

- **Lay Report** (like the reference: date, table, width, order quantity, buyer, style, contract, colour, fabric received, layers, balance, remarks, size, total, bundle numbers, CAD consumption, actual consumption, difference, signatures).
- **Bundle ticket**: label-size print of one bundle (style, colour, size, bundle no printed large, ply range, qty, shade, line). **No QR or barcode for now** (kept as an idea, section 16); scanning is not part of this phase.

### 7.6 Reports

- **Daily Cutting Report** (matrix by day, per card × colour × size: cut, balance to cut, fabric shortage in roll), matching the company's `DAILY CUTTING REPORT` and `CUTTING REPORT` sheets (order qty, cut qty, balance, issued to line, issued balance, order consumption vs actual consumption, fabric used vs received).
- **Fabric Consumption** (the reconciliation above).
- Fill the empty columns in **Running Fabric Stock** (`cut_qty`, `used_consumption`) and **WIP Report** (`cut_qty`) from the ledger and the lay totals. The columns exist and are labelled "(cutting phase)"; remove those suffixes.

### 7.7 Edge cases (cutting)

Partial fabric arrival (cut the colours or shade lots whose rolls are accepted; release lays by shade); fabric short before the order is fully cut (re-plan sizes, short-cut approval with reason, claim against the mill using Phase C inspection data); mixed shade bands in one colour (separate lays; shade band travels on the bundle, the line input and the packing line); roll width variation (group by width); shrinkage groups on denim (separate pattern version per group); a size missing from the lay; ratio rounding overshoot (cap with `cut_cap_extra_pcs`); excess cut (blocked, or manager override with reason); several ship-tos (cut by colour × size, allocation to ship-to at packing); shell + lining + pocketing (lays per component; shell drives the garment count; `kit_check` ensures lining and pocketing bundles exist before issue); directional or checked fabric (note on the plan: `nap_direction`, `match_pattern` Check, which raises `splices` and widens the end allowance); very short rolls (end bits, remnant rule); roll with a defect cut out (damage_m, panel replacement via Re-cut); re-cut from the same roll or the same dye lot with an approver (never from a different shade); duplicate ply numbers (blocked); the order revised after cutting (card revision keeps the cut); the lay cancelled after bundles were issued (blocked).

---

## 8. Bulk sewing (slice D4)

### 8.1 Documents

**Operation Bulletin** (plain, versioned; one active per style). Header: style_item, version, buyer, description, colour (info), operators (Int), working_minutes (default from settings), expected_efficiency_pct (default 65), total_sam (computed), sewing_sam (machine), manual_sam, status. **Child OB Operation:** seq, part_group (Collar, Cuff, Sleeve, Front, Back, Assembly …), operation, machine_type (Data from the sheets: SNLS, SNUBT, 5TO/L, EC, IRON, TABLE), machine_sam, manual_sam, operators_needed (computed = line target per hr ÷ operation target per hr), target_per_hr (computed = 60 × efficiency ÷ sam), pitch_flag (computed: above or below the ±15 % band). Computed at the top: `target_per_day = operators × working_minutes × efficiency ÷ total_sam`, `target_per_hour = target_per_day ÷ (working_minutes ÷ 60)`, `pitch_time = total basic minutes ÷ number of operations`, `balancing_loss`. **Do not copy the sheet's 9.5-hour divisor.** Import from the existing OB workbooks (xlsx skill, forgiving of the sheet's quirks: section rows with only a heading, a part name repeated, an `OPRN NUM` that is sometimes a heading).
Note for the user: the research found two textbook definitions of pitch time; the OB stores basic time and the allowance % per operation so either can be computed. Pick one in review.

**Line Input** (submittable): date, production_card, line (Workstation), purpose, bundles (Table: bundle, colour, size, qty, component, shade_band), loaded_by. Rules: bundles must be Cut and not already issued; for a multi-component style `kit_check` finds the matching secondary bundles by `kit_key`; the card must be Issued and the ledger's sewing availability rule (3.2) passes; trims for the colour were issued (Warn; the sewing trims in the Trim Card). On submit: ledger `SEW_IN`, bundle status Issued with `line`, stamp the first-input milestone. **Line Allocation check:** warn when the line is not the one in the Factory Allocation for this style and colour.

**Daily Line Report** (submittable; one per line per day):
- Header: report_date, line, production_card (default from the day's inputs; several allowed through rows), shift_minutes (default from the OB or the settings), operators_present, helpers_present, overtime_minutes, downtime_minutes + downtime_reason (Select: no work, machine, power, material, absence, other), notes.
- **Child Output rows:** production_card, colour, size, purpose, qty (passed end-line), bundle (optional, required if `require_bundle_on_output`).
- **Child Hourly rows:** hour_slot (7:30–8:30 … as on the sheet), target_qty, output_qty.
- Computed: `produced_minutes = Σ(qty × OB total SAM)` for each card in the report; `available_minutes = operators_present × (shift_minutes + overtime − downtime)`; `efficiency_pct = produced ÷ available × 100`; `target_qty` from the OB with the learning-curve factor for the style's day on the line (day count from the first Line Input on that line for that style); `variance_to_target`.
- On submit: ledger `SEW_OUT`, bundle `sewn_qty` (if bundles listed).

**Line QC Report** (submittable): `audit_type` Select **Inline (traffic light) / End-line / Finishing**, report_date, line, production_card, inspected_by (User), line_qa.
- **Hour rows:** hour_slot, checked, passed.
- **Defect rows** (the form's "defect analysis"): hour_slot, defect_code (Apparel Defect Code), qty, operation (Link OB Operation, optional).
- **Disposition rows:** colour, size, disposition (Rework / Reject / B-Grade), qty, defect_code, fault_source. **Reject** at sewing and finishing posts the ledger (`SEW_REJECT` / `FIN_REJECT`); **B-Grade** is allowed only for Finishing and Final; **Rework** posts nothing (the piece is fixed and re-counted).
- **Traffic light** rows (Inline only): operator, round, pieces_checked, defects, colour (computed from `traffic_light_rules`). A red raises a message on the Daily Line Report.
- Computed: `total_checked`, `total_passed`, `total_defects`, **DHU = defects × 100 ÷ checked**, `defect_pct = defective pieces ÷ checked × 100`, **RFT = pieces passed first time ÷ total × 100** (a repaired piece never counts toward RFT; a lot's pass rate is not RFT).
- Panel replacement: a Reject disposition with `replace` creates a draft Recut Request.

### 8.2 Rules

1. All output and input quantities obey section 3.2.
2. **Sewing WIP** = `SEW_IN − SEW_OUT − SEW_REJECT`, per line and per colour × size, never negative.
3. A line cannot run two styles in one Line Input; one Daily Line Report can list several (changeover), with `changeover_minutes` counted in downtime.
4. An order can be split across lines or factories: allocation is in Phase B; the ledger is by line, so totals add up.
5. Output reported by size must not exceed what was loaded by size. Mixed sizes in one bundle are impossible (a bundle is one size).
6. Overtime and absenteeism change `available_minutes` only; efficiency is always recomputed, never typed.

### 8.3 Reports and screens

- **Line Loading** (the company's `LINE LOADING REPORT`: line, style, quantity loaded today, cumulative, note), **Line Efficiency and DHU** (per line per day: output, efficiency, target, DHU, RFT), **Sewing WIP** (per line and card). Use the `dataviz` skill for any chart and take screenshots.
- Number cards: Lines Behind Target, High-DHU Lines (today).
- **Daily Production Report** (matches `DAILY PROD REPORT`: order received date, buyer, style, colour, line, order qty, cut today, cut qty, balance, pilot run, sew today, sew total, wash factory, sent today, sent total, received today, received total, balance to receive, packed, shipped …) generated from the ledger by date: one screen replaces the several spreadsheets.

### 8.4 Edge cases (sewing)

New style learning curve (first days target scaled; short runs may never reach peak); line changeover; operator count differs from the OB (the OB target uses planned operators; the report uses present); helpers counted separately; output reported by colour and size; a bundle missing panels (blocked at input by `kit_check`); shade mixed within a bundle (impossible by construction; checked at input for mixed-shade bundles issued together when the buyer requires one shade per carton: Warn); damaged panel (Recut Request); rework loop (not counted twice, not toward RFT); CMT sewing at another factory (out of scope; the data model allows a process "Sewing" later); late trims (warn); line stops (downtime with reason); two production cards on one line in one day; output after the card is Closed (blocked).

---

## 9. Subcontracting: wash, embroidery, print, appliqué (slice D5)

### 9.1 What the wash contract fixes (seed and design from it)

| Contract clause | Where it lives |
|---|---|
| Quantity tolerance ±5 % of the contract quantity | Terms `qty_tolerance_pct`; checked on the PO line vs challans and invoiced qty |
| Vendor-damaged pieces not paid | Terms `no_pay_vendor_damage`; Settlement deducts |
| FOB penalty if wash damage > 1 % per colour (normal, enzyme) or > 3 % (dye, bleach, acid), per style per colour | Terms class rows `reject_threshold_pct`; Settlement evaluates per style × colour |
| 10 % pre-wash check on every incoming lot; vendor reports over-limit defects; washing without written confirmation moves responsibility to the vendor | Challan fields `vendor_precheck_*`, `proceed_authorised_by` |
| Quantities confirmed within 3 days of each delivery, later complaints refused; appearance defects on goods past finishing not the vendor's responsibility unless reported within 3 days | `reconcile_within_days`; Return `dispute_deadline` |
| Turnaround 1 / 3 / 5–7 days by wash class, excluding Sundays and holidays | Terms class rows `turnaround_days`; Challan `expected_return_date` using the Company Holiday List |
| Batches at least 2,000 pieces (one delivery if the order is under 1,000) | Terms `min_batch_qty` (Warn) |
| Sample with 6 legs, test run, size set and pilot, first lot ≥ 200 pieces approved before bulk | Challan types Sample / Test / Size Set / Pilot / Bulk; bulk wash gate (9.3) |
| Payment 30 days after order closing against VAT invoice + vendor-stamped settlement statement | Terms `payment_days`; Settlement |
| USD price converted at a fixed bank rate at contract date; VAT 8 % | Terms `currency`, Settlement `exchange_rate`, `vat_pct` |
| Re-process: items needing re-wash are the vendor's to redo; returned to the factory if re-wash fails | Return row disposition **Re-process**, no new charge |

### 9.2 Doctypes

**Subcontractor Terms** (plain; one per supplier × process, with `valid_from` / `valid_to`): supplier, process, currency, rate_basis (Pcs / Kg), qty_tolerance_pct (5), no_pay_vendor_damage (1), penalty_basis, penalty_scope (default from settings), reconcile_within_days (3), min_batch_qty, vat_pct (8), payment_days (30), turnaround excludes holidays (Check), terms_text; **child Subcontractor Terms Class**: class_name, rate, rate_uom, reject_threshold_pct, turnaround_days. Seed class rows for a wash vendor: **Normal / Enzyme Wash** (1 %, 1 day), **Light Bleach** (1 %, 3 days), **Dye / Bleach / Acid / Hard Wash** (3 %, 5 to 7 days). Rates are not seeded (money belongs to the user). Most specific valid terms row wins (supplier + process + date).

**Subcontract Challan** (submittable; the "sent" note): challan_type (Sample / Test / Size Set / Pilot / Bulk), supplier, process, purchase_order (Link, warn if blank), production_card, challan_date, service_class (Link row of the terms), item_state (Panels / Garments), uom (Pcs / Kg), expected_return_date (computed), vehicle_no, gate_pass_no, wash_recipe_ref (Sample Approval or Data), approved_standard, vendor_precheck_pct, vendor_precheck_defects, proceed_authorised_by + proceed_authorised_on, status (Open / Part Returned / Returned / Reconciled / Disputed / Cancelled), remarks; **Child Challan Row:** colour, size, qty_sent, kg_sent (when billed by weight), bundle (optional), lot / shade_band, production_card_line; summary computed per colour × size (sent, returned good, rejected, short, at vendor, % rejected).
- Production Card must be Issued; **before-sewing** challans send Cut Bundles (status At Subcontractor, panels), **after-sewing** challans send garments by colour × size.
- Over-send beyond the PO line `qty × (1 + qty_tolerance)` blocks (manager override with reason).
- Posts ledger `SC_OUT` (process, supplier).
- Stamps `WASH_FINISHED` only when the challans for the order are Reconciled.

**Subcontract Return** (submittable; the "came back" note; one per vendor delivery, may cover several challans): supplier, return_date, vendor_delivery_note_no, dispute_deadline (= return_date + `reconcile_within_days`), rows: challan, challan_row (Data), colour, size, qty_good, qty_reject, reject_fault (Select Vendor / Factory (sewing or fabric) / Disputed), defect_code, qty_reprocess (to go back to the vendor), kg_returned, remarks.
- Posts `SC_BACK_GOOD`, `SC_BACK_REJECT_VENDOR`, `SC_BACK_REJECT_FACTORY` (a Disputed reject posts nothing until resolved, shows as "Disputed"); re-process quantity posts nothing (it stays at the vendor).
- A return exceeding what was sent on that challan row blocks (the vendor cannot return pieces from another order).
- Returned pieces are checked against `reconcile_within_days`: after the deadline the Return can still be saved but is marked Late and cannot change the vendor-fault split without a manager override (the contract refuses later complaints).

**Reconcile** (action on the Challan): when every sent piece is accounted for or the user declares the remainder **Short**, the challan becomes Reconciled with `short_qty = sent − good − rejected(all faults) − re-process pending`. Short pieces stay on the ledger as "not returned" and flag on the Order Close.

**Subcontract Settlement** (submittable; one per vendor invoice, prints the company's Payment Request): supplier, process, purchase_order, challans (Table), vendor_invoice_no, vendor_invoice_date, invoiced_qty, rate, currency, exchange_rate, vat_pct, settlement_date, status.
Computed per style × colour (aggregated over the listed challans):
- `sent`, `returned_good`, `reject_vendor`, `reject_factory`, `disputed`, `short`, `invoiced`.
- **Payable qty** = `returned_good + reject_factory` (washed correctly). **Unpaid** = `reject_vendor + short`. Invoice qty above payable is flagged and the excess is the deduction.
- `reject_pct = reject_vendor ÷ sent` for the style × colour; compare with the class threshold; if above, **penalty = penalty_qty × FOB per piece** where `penalty_qty` is all vendor-damaged pieces (`penalty_scope = All Damaged`) or only the excess over the threshold (`Excess Only`), FOB from the Cost Sheet (default) or the Sales Order rate. Decided with the user (D6): All Damaged; `Excess Only` stays selectable.
- Invoice qty vs PO qty ±5 %: outside it is flagged.
- `Create Purchase Invoice`: a **draft** Purchase Invoice (service item) for the payable qty × rate; `Create Debit Note`: a **draft** Purchase Invoice with `is_return = 1` for the penalty amount (and any deduction for unpaid pieces not already excluded from the invoice). **Never submitted by the app.** Disputed pieces are excluded from both until resolved; the Settlement cannot be submitted while disputed quantity remains unless the user marks it "settled without those pieces" with a reason.

**Vendor Scorecard** (script report): per supplier × process × period: pieces sent, returned, rejected % (vendor fault), short %, average turnaround vs promised days, on-time return %, invoices, penalties and deductions in money, disputed count. Chart with the `dataviz` skill; the threshold line comes from the terms.

### 9.3 Gates and approvals

- A **bulk** wash challan requires: the Pilot Run approved (when pilot is required; `require_pilot_before_bulk_wash` Warn), an approved wash standard for the process (`requires_approved_standard`), a `service_class` set.
- A challan of type Sample, Test, Size Set or Pilot is allowed before the gate.
- Before-sewing process (embroidery, print, appliqué): the bundles must be Cut; their status becomes At Subcontractor; the Line Input refuses them until the return is posted (`SC_BACK_GOOD ≥` the bundle qty).

### 9.4 What counts as returned for the next stage

For a garment process, finishing can receive `SC_BACK_GOOD` plus any factory-fault rejects the factory decides to repair (**accepted for repair**, a Return row flag `accept_for_repair`; they then re-enter `FIN_IN` and are counted again by finishing). Vendor-fault rejects never re-enter. The availability rule in section 3.2 uses `SC_BACK_GOOD + accepted_for_repair`.

### 9.5 Edge cases (subcontracting)

One challan with several styles and colours (rows carry them); one style split to two vendors; partial returns over weeks (many Returns per challan); a vendor returns more than sent (blocked) or mixes in another order's pieces (blocked: the row must match); wrong size returned (Return row size differs from the sent row: blocked, record as Disputed with a note); damaged panels at embroidery replaced by Re-cut panels (the re-cut panels go on a new challan); sample, test and pilot challans before bulk; wash by weight (`kg_sent`, billing in kg; the ledger still counts pieces, conversion kept as an average piece weight on the challan); vendor holds goods for an unpaid invoice (note field; an overdue Settlement shows in the scorecard and on the Order Close); the factory fault found at the vendor's 10 % pre-wash check (not the vendor's responsibility if the vendor reported and was told to proceed); proceed authorisation missing when the pre-check exceeded the limit (vendor takes the responsibility; shown on the Settlement); invoice qty above sent; contract qty ±5 %; USD rate changes (the Settlement stores the rate used); a second wash of failed pieces (Re-process, no new charge); order cancelled while goods are at the vendor (challans stay Open and are listed on the Order Close); customs or tax formalities for processing outside the factory are outside this plan (decision D14): the challan has a free-text `reference_no` for whatever a jurisdiction needs.

---

## 10. Finishing, packing and final inspection

### 10.1 Finishing (slice D6)

**Finishing Receipt** (submittable): receipt_date, production_card, source (Sewing / Wash / Embroidery or other garment process), supplier (when from a vendor), challan / return refs, rows: colour, size, qty, shade_band / wash lot. Posts `FIN_IN`. The availability rule uses the route (3.2, 9.4): a washed style cannot receive more than came back.

**Finishing quality** uses the Line QC Report with `audit_type = Finishing` (section 8.1): hourly passed and defects, dispositions (Rework / Reject / B-Grade), DHU. On submit: ledger `FIN_A` (passed), `FIN_B`, `FIN_REJECT`. B-grade goes to the Seconds warehouse only if the user later sells it; no stock posting by default.

**Finishing route and label control.** The Production Card route (from settings) lists the finishing steps in order: trim threads, check, label sewing, button, spot clean, repair, press, final check, fold, tag, barcode sticker, polybag, tissue, carton. Steps are a checklist on the card (done / not required). Only the three quantities `FIN_IN`, `FIN_A/B/Reject`, `PACKED` are counted. **Label sewing** carries a per-size count in the Line QC rows (`labels_sewn`); the system warns when labels sewn for a size exceed size labels issued (Trim Issue) and, at Order Close, reconciles **controlled trims** (Trim Category `apparel_controlled_trim`: main, size and care labels, hang tags, barcode stickers, branded tissue) issued, used, returned, destroyed. `controlled_trim_tolerance` is 0 pieces by default.

**Needle Detector Log** (plain): date, machine, line, test_piece_mm (default 1.2), check_time, result (Pass / Fail), checked_by, garments_rescanned (when Fail: everything passed since the last good check), action. Rules: when `needle_check_required` ≠ Off, a Finishing Line QC Report for a date needs a passing check that day for the line (Warn or Block); a Fail with no rescan entry blocks packing for that line until the rescan is logged; a garment that trips the detector is held (a Disposition Reject with defect code "Metal / needle found", Critical) and is never packed. Records are kept; no deletion.

**Finishing inspection print**: the company's finishing form (hourly grid, defect analysis, DHU, quality in-charge and line QA signatures).

### 10.2 Packing (slice D7)

**Packing Instruction** (plain; per customer × style, with revision): customer, style_item, pack_type (Solid Colour Solid Size / Solid Colour Assorted Size (ratio) / Assorted), `tail_carton_rule` (Select Mixed Colour and Size / Mixed Size Only / Own Carton), pcs_per_carton, carton_type (Link Carton Type), max_gross_kg (default from settings), fold_method (Data), hanger (Data), tissue (Check), polybag (Data: size, thickness), `suffocation_warning` (Check), `warning_languages` (Data), hang_tag_position, polybag_sticker_position, barcode_required (Check), `price_ticket` (Check), special_requirements (Small Text), revision_no; **child Ratio rows:** colour (blank = any), size, pieces_per_pack; **child Ship-To overrides:** ship_to, language_override (e.g. bilingual French / English for Canada), label_template, extra_requirements, pcs_per_carton_override. The Production Card copies the instruction at issue and shows it; a later change creates a new revision and the card shows "instruction changed after issue".

**Packing List** (submittable): production_card, sales_order, ship_to, buyer_po, ship_via, packing_date, instruction (Link), status. **Child Carton:** carton_from, carton_to (a range of identical cartons, like `1~11` on the sheet), carton_count (computed), carton_type, length_cm, width_cm, height_cm (editable per row: heights differ), shade, net_weight_kg, gross_weight_kg (per carton, editable), cbm_per_carton (computed = L × W × H ÷ 1,000,000), total_cbm (computed), sscc (Data; per carton, generated one per carton number, not per range: see below), `tail` (Check). **Child Carton Content:** carton_row, colour, size, qty_per_carton, sales_order_item (carries ship-to and PO), pieces_total (computed).
- **Generate Cartons** action: from the instruction and the chosen quantities, produce solid cartons `floor(qty ÷ pcs_per_carton)` plus the tail carton by `tail_carton_rule`; ratio packs: with ratio vector `R`, pack size `P = ΣR`, full packs per size `min over sizes of floor(qty_s ÷ R_s)`, the leftovers form the tail carton(s). Carton count `ceil(qty ÷ pcs_per_carton)`.
- Totals: cartons, pieces by colour × size, net, gross, CBM, **summary by size with over / short vs the Sales Order** (total and per size, `ship_tolerance_basis`), matching the sheet's `OVERAGES / SHORTAGES` and `PERCENTAGE` lines.
- **SSCC** (only when `gs1_company_prefix` is set): 17 digits (extension digit + prefix + serial) + GS1 check digit, one per carton number, drawn from a counter that never reuses a number, even after cancel (use `frappe.model.naming.getseries` with a fixed key). A cancelled Packing List keeps its used numbers. The barcode label must carry the SSCC in the (00) application identifier. Placement rules conflict between GS1 bodies (50 mm vs 19 mm from the vertical edge, bottom edge 32 mm above the base): **confirm per retailer** and keep the layout in the label template.
- GTIN check digit helper and a validator for the Item barcodes of the variants (UPC-A / EAN-13) in `production/gs1.py`, with tests for known check digits.

Rules on submit:
1. Every carton row's total pieces equals Σ contents; every content row matches a Sales Order item (colour, size, ship-to).
2. Packed qty obeys the ledger (`PACKED ≤ FIN_A − SAMPLE_OUT − PACKED so far`).
3. Gross weight ≤ `max_gross_kg` per carton (warn), net ≤ gross, gross > 0 on every row.
4. Over / short vs Sales Order per `ship_tolerance_basis` and `apparel_qty_tolerance_pct`: outside the allowance blocks unless the order has an approved over-ship override on the Delivery Note (a Warn here, the hard stop is at the Delivery Note).
5. Finishing needle check logged for the line and day (`needle_check_required`).
6. On submit: ledger `PACKED`, draft FG Material Receipt (3.3), stamp `PACK_FINISHED` (when packed ≥ the order's A-grade planned qty), refresh T&A.
7. Cancel: blocked if a Delivery Note references it; otherwise removes ledger rows and cancels the draft Stock Entry.

**Make Delivery Note:** a button on the Packing List calling ERPNext's `make_delivery_note` for the Sales Order and then setting item quantities to the packed quantities per Sales Order item (grouped by ship-to). The Delivery Note carries `apparel_packing_list`.

**Print formats**
- **Packing List** like the reference (header, carton ranges, shade, colour, units per carton by size, total pieces, gross weight, summary by size with order, overages, percent, over and short ship limits, CBM), orange / black header.
- **Carton Label** (4 × 6 inch): ship-to, buyer PO, style, colour, size or ratio, qty, carton number of total, SSCC and GS1-128 barcode (human-readable (00) line), country of origin, Canada bilingual variant from the ship-to override. **The barcode cannot be scan-tested from here; the user must scan a printed label before use.** Check what barcode support Frappe v16 ships (`grep -ri jsbarcode /workspaces/frappe-bench/apps/frappe/frappe/public`) and use it; add no dependency without asking.
- **Hang tag / polybag / tissue** are trims issued from stock, not printed by the ERP.

### 10.3 Final Inspection (slice D8)

**AQL Plan** seed, **General Inspection Level II, single sampling, normal inspection** (lot size → code letter, sample size):

| Lot size | Code | Sample size |
|---|---|---|
| 2–8 | A | 2 |
| 9–15 | B | 3 |
| 16–25 | C | 5 |
| 26–50 | D | 8 |
| 51–90 | E | 13 |
| 91–150 | F | 20 |
| 151–280 | G | 32 |
| 281–500 | H | 50 |
| 501–1,200 | J | 80 |
| 1,201–3,200 | K | 125 |
| 3,201–10,000 | L | 200 |
| 10,001–35,000 | M | 315 |
| 35,001–150,000 | N | 500 |
| 150,001–500,000 | P | 800 |
| 500,001 and over | Q | 1,250 |

Accept / reject numbers the plan seeds (the ones the builder and QA must **cross-check against ISO 2859-1 Table 2-A from two public sources before trusting**; the lot ranges at or above 51 are consistent with the trim table in Phase C and with widely quoted garment tables, but they were not re-verified from a standard here):

| Sample size | Major AQL 2.5 Ac / Re | Minor AQL 4.0 Ac / Re |
|---|---|---|
| 13 | 1 / 2 | 1 / 2 |
| 20 | 1 / 2 | 2 / 3 |
| 32 | 2 / 3 | 3 / 4 |
| 50 | 3 / 4 | 5 / 6 |
| 80 | 5 / 6 | 7 / 8 |
| 125 | 7 / 8 | 10 / 11 |
| 200 | 10 / 11 | 14 / 15 |
| 315 | 14 / 15 | 21 / 22 |
| 500 and over | 21 / 22 | 21 / 22 |

Critical: always Ac 0 / Re 1 (any critical defect fails). **Small lots (up to 50) and the large-lot arrow rows (above 35,000) are left for QA to fill from the standard; the seed marks them "inspect 100 % or QA to confirm" rather than guessing.** Where the standard's arrows change the sample size, store that row's real sample size, not the code letter's.

**Final Inspection** (submittable; follows the company form):
- Header: inspection_type (In Line / Pre-Final / Final / Re-inspection / 2nd Re-inspection / Other), report_no, production_card, sales_order, style_item, style_no, colour(s), buyer, supplier / factory, season, buyer_code, description, po_no, material, construction, size_range, fibre_content_per_test_report, country_of_origin, po_qty, offered_qty, packed_qty (ro, from the ledger), total_cartons, inspected_cartons (computed from `carton_pick_rule`: `ceil(sqrt(total_cartons))` by default, **common practice, confirm D12**), plan (Link AQL Plan), sample_size (computed from offered qty), inspection_level, inspector, inspection_date, inspected_by_party (Factory QA / Buyer QA / Third Party) + third_party_name, shipment_approved_by.
- **Test and conformity checks** (Yes / No): FPT, GPT, Azo, wash care per test report, fibre content per test report, conformity to the **sealer sample** (style, material, colour). Link to the approved sample in Phase B (`Sample Approval`). Metal detection proof (Needle Detector Log for the dates), carton drop test, barcode scan check, measurement check (a Table of measurements per size against the tech pack POM tolerances), packing check (carton, label, polybag warning).
- **Defect table:** defect_code, severity (from the code), qty, carton_ref, remarks. The form's three groups (sewing, fabric, general) are just filters on the code.
- Computed: `critical_found`, `major_found`, `minor_found` against Ac / Re → `result` (Accepted / Rejected / On Hold). Any critical fails. `On Hold` is set manually (waiting for a test result or the buyer).
- Re-inspection: a new Final Inspection with `previous_inspection`; the Re-inspection has its own sample drawn after rework; the first stays as history. The ship gate looks at the latest one per card and colour.
- **Pre-final / inline (DUPRO)** uses the same document at 20 to 50 % packed; `offered_qty` is the finished quantity at that time, and a Pass here never opens the ship gate.
- On submit: stamp `FINAL_INSPECTION` actual when Accepted and inspection type is Final or Re-inspection; refresh the Order TNA. On Rejected: a message listing the defect classes; the Packing List stays open for repack and rework; any rework posts through Line QC (Finishing) and `PACKED` adjustments (a repack is a Production Adjustment with reason, not a negative packing).

**Ship gate (Delivery Note hook):** `ship_gate_final_inspection` (Block / Warn / Off). A Delivery Note with `apparel_packing_list` cannot submit unless every colour on it has a latest Final Inspection of type Final or Re-inspection that is Accepted. Manager override + reason (Delivery Note `apparel_over_ship_override` pair is for quantity; add a separate `apparel_gate_override` pair for inspection). Also checks over-ship per `ship_tolerance_basis` against the Sales Order and **posts `SHIPPED`** on submit, **stamps `EX_FACTORY`**, removes on cancel.

---

## 11. Order reconciliation, Order Close, and screens (slice D8 continued, D9)

### 11.1 Production Summary (script report and a section on the card)

One row per card × colour × size, columns in this order (so it can be checked line by line against the company's daily report):

`Order qty · Planned cut · Cut · Cut reject · Good cut · Sewing in · Sewn out · Sewing reject · Sent (per process) · Back good · Back reject (vendor) · Back reject (factory) · Short · Finishing in · A-grade · B-grade · Finishing reject · Samples · Packed · Shipped · A-grade stock · B-grade stock · Unaccounted`

and the headline ratios:
- `rejection_pct = (all rejects) ÷ good cut`; `cut_to_ship = shipped ÷ cut` (the reference's 0.9726); `order_to_ship = shipped ÷ order qty` (1.0167); `short_or_excess_pct = (shipped − order) ÷ order`.
- **Unaccounted (missing)** = `good cut − (shipped + A-grade stock + B-grade + all rejects + samples + WIP at every stage)`. A non-zero value is a red flag with a number.
- Check identities from the company's report (they must hold for the golden data): `cut = packed + B + rejects`, `packed = shipped + A-grade stock` (section 12).
- Loss categories shown as in the daily report: washing rejection, stain, factory rejection, fabric rejection, spec issue, damage, returned to warehouse, missing, by `fault_source`.
- Fills the **WIP Report** columns `cut_qty`, `sew_qty`, `wash_qty`, `pack_qty`, `ship_qty` and removes the "(production phase)" suffixes.

### 11.2 Production Movement screens

- **Production Board** (extend the Phase C WIP Board page `apparel_wip_board` with a new tab "Production", do not build a second page): one row per card × colour, columns the stages with a quantity and a percent bar and a status symbol (not colour only); click a cell to open the Production Summary filtered; uses `dataviz` rules, light and dark, 200 cards per load, one query for all cells.
- Number cards: Orders Behind (cut or sew behind plan), Unaccounted Pieces, Challans Overdue, Open Disputes, Final Inspections Rejected (30 days).
- Workspace: add a "Production" block (links: Production Card, Pilot Run, Cut Plan, Lay Report, Line Input, Daily Line Report, Line QC Report, Subcontract Challan / Return / Settlement, Packing List, Final Inspection, reports) and Sales Order buttons: **Production** (open the card or make one) and **Packing** (open the Packing List).

### 11.3 Order Close

"Close Production" on the Production Card (Production Manager only) succeeds only when: no draft stage documents remain; every challan is Reconciled or explicitly Short; every Settlement is submitted or marked Not Required; Final Inspection accepted (if the gate is on); shipped ≥ the lower tolerance or a shortfall approval is recorded. It then: writes the closing numbers, creates the **draft** fabric and trim consumption Stock Entries (3.3), runs the controlled-trim reconciliation (any mismatch above `controlled_trim_tolerance` blocks the close until a reason is written), and stamps nothing new. Status becomes Closed; further movements for the card are blocked. A reversal is a Production Manager action with reason (reopen).

### 11.4 Starter list for a later Vietnamese translation file

Not used in this phase (decision D9). If the user later adds Vietnamese, these strings come straight from the reference forms: `SỐ LƯỢNG CẮT` (cutting qty), `MÀU` (colour), `SIZE`, `CHUYỀN` (line), `MÃ HÀNG` (style), `TỔNG CỘNG` (total), `SỐ LƯỢNG GIAO LOADING QTY` (loading qty), `LŨY KẾ` (cumulative), `GHI CHÚ` (note), `BÁO CÁO SẢN LƯỢNG HẰNG NGÀY` (daily production report), `BÁO CÁO SẢN LƯỢNG CẮT VÀ SỬ DỤNG VẢI HẰNG NGÀY` (daily cutting report and fabric utilisation), `NGÀY` (date), `BÀN SỐ` (table no), `ĐỘ RỘNG` (width), `SỐ LƯỢNG ĐƠN` (order qty), `KHÁCH HÀNG` (buyer), `CHIỀU DÀI TRẢI` (lay length), `SỐ HỢP ĐỒNG` (contract no), `SỐ LỚP VẢI` (no. of layers), `CÂN ĐỐI THỰC TẾ` (actual balance), `SỐ BÓC TẬP` (bundle numbers), `ĐỊNH MỨC CAD` / `ĐỊNH MỨC THỰC TẾ` / `CHÊNH LỆCH` (CAD / actual consumption / difference), `CUỘN SỐ` (roll no), `CÔNG NHÂN TRẢI VẢI` / `QUẢN LÝ CẮT` / `CÔNG NHÂN CẮT` (spreading operator / cutting supervisor / cutting operator), `SỐ LƯỢNG CẮT` and the headers of the daily production report (order received date, cut qty, balance, pilot run, sewing total, washing factory, sent, received, balance to receive, packed, shipped). Anything else needs a Vietnamese speaker.

---

## 12. Golden numbers (put these in tests; quantities only)

| # | Case | Input | Expected |
|---|---|---|---|
| 1 | Planned cut with 5 % extra, per size, rounded up | Sizes 156, 433, 313, 458, 171, 221, 52 (total 1,804) | 164, 455, 329, 481, 180, 233, 55 = **1,897** |
| 2 | Required fabric | 1,897 × 1.72 m | **3,262.84 m** (the sheet's unrounded 1,894.2 × 1.72 = 3,258.024; received 3,285 m so the surplus is 22.16 m with rounding, 26.976 m on the sheet) |
| 3 | Roll list | 26 rolls, 3,285.5 m, rolls of 46, 37.8, 50.7, 94.6 m among about 145 m | total 3,285.5; four short rolls flagged for end-bit handling |
| 4 | Order reconciliation, row 3 of the daily report | Order 1,350; cut 1,362; wash rejection 11, stain 20, factory 5, damage 2 (total rejects 38); B-grade 2; packed 1,322; shipped 1,291; A-grade stock 31 | `cut = packed + B + rejects` (1,362 = 1,322 + 2 + 38); `packed = shipped + A stock` (1,322 = 1,291 + 31); rejection % = 38 ÷ 1,362 = **0.0279**; cut-to-ship = 1,291 ÷ 1,362 = **0.9479**; order-to-ship = 1,291 ÷ 1,350 = **0.9563** |
| 5 | Same, row 1 | Order 1,500; cut 1,568; rejects 20 (stain 11, damage 9); B-grade 4; packed 1,544; shipped 1,525; A stock 19 | `1,568 = 1,544 + 4 + 20`; `1,544 = 1,525 + 19`; rejection **0.012755**; cut-to-ship **0.97258**; order-to-ship **1.01667** |
| 6 | OB targets | 28 operators, 480 min, 65 %, total SAM 24.4 | per machine **12.7869**/day; output **358.03**/day; **44.75**/hr (not 37.69) |
| 7 | OB operation target | SAM 0.5 min at 65 % | **78**/hr (`60 × 0.65 ÷ 0.5`) |
| 8 | Packing list CBM | 54 × 33 × 14 cm; 64 cartons | **0.024948** m³ for the first row; sheet total 1.596672 (heights vary per row) |
| 9 | Packing list over / short | Shipped by size XS 276, S 456, M 438, L 231, XL 119 (1,520) vs PO 270, 436, 421, 223, 112 (1,462) | +6, +20, +17, +8, +7 = +58; per size +2.22 %, +4.59 %, +4.04 %, +3.59 %, +6.25 %; total **+3.97 %**. With `Both` and a 3 % buyer line: warn on four sizes; with contract band ±7.5 %: all within. |
| 10 | Wash invoice | 6,909 pcs × 4,703 VND | **32,493,027** VND; VAT 8 % = **2,599,442**; total **35,092,469**; contract 6,656 pcs: 6,909 is **+3.80 %** (inside ±5 %) |
| 11 | Wash contract amount | 6,656 × 4,703 | **31,303,168** VND; rate from USD 0.18 × 26,125 = 4,702.5, rounded to 4,703 |
| 12 | Settlement penalty (invented numbers) | Sent 2,000; returned good 1,950; vendor-fault rejects 30 (1.5 %); short 20; class threshold 1 % | rejects 1.5 % > 1 % → penalty applies; `All Damaged` penalty qty = 30; `Excess Only` penalty qty = 10 (30 − 1 % × 2,000); payable 1,950; unpaid 50 |
| 13 | Wash turnaround | Received Friday, class 3 days, Sunday and one holiday on Monday | return date Wednesday |
| 14 | AQL | Lot 1,500 → code K, sample 125; major found 7 → accept, 8 → reject; minor found 10 → accept, 11 → reject | per the seeded rows |
| 15 | Carton pick | 64 cartons | `ceil(sqrt(64)) = 8` cartons inspected |
| 16 | Ratio pack | Ratio 1:2:2:1, quantities XS 276, S 456, M 438, L 231 | full packs `min(276, 228, 219, 231) = 219` |
| 17 | GTIN check digit | UPC-A body 03600029145 | check digit **2** (standard worked example; add two more known values from GS1) |

Row 6 and 7 come from the OB sheet; 4, 5, 9, 10, 11 from the reports and invoice; 1, 2, 3 from the production card; 12, 13, 15, 16 are invented to test rules; 14 depends on the table verified in D8.

---

## 13. Slices (build in this order; stop for review after each)

| Slice | Content | Exit check |
|---|---|---|
| **D0 Foundations** | Settings section, masters and seeds (defect codes, subcontract processes, carton type, production check items, empty AQL plan), roles, custom fields, warehouses, **Production Movement** and `ledger.py`, `gate.py` refactor of the Work Order gate, flow-rule helpers, Production Adjustment, `rebuild_movements` | `migrate` clean; seeds present; the 195 existing tests still pass; ledger post / unpost / rebuild tests pass |
| **D1 Production Card** | Card, lines, fabric rows, process route, revisions, Create Subcontract POs, Issue Fabric / Trims, PP Meeting auto-fill, print formats (card, trim card), agent API | Card from a demo SO; golden numbers 1 and 2; issue works before the PP Meeting; form opened with the `run` skill |
| **D2 Pilot Run** | Pilot Run, checks, SAM validation, approval, pilot rule, Sample Requirement type | Approve and reject paths; bulk gate blocked until approved or waived |
| **D3 Bulk Cutting** | Cut Plan, Lay Report, bundles, Recut Request, Suggest Rolls, reconciliation, cutting reports, bundle ticket, gate at first lay, Running Fabric Stock columns | A demo order cut in two lays; bundles numbered; remnants returned; reconciliation matches by hand; cancel rules; screenshots |
| **D4 Bulk Sewing** | Operation Bulletin (+ import), Line Input, Daily Line Report, Line QC Report, learning curve, traffic light, line reports, Daily Production Report | Golden numbers 6 and 7; efficiency and DHU by hand; WIP never negative |
| **D5 Subcontracting** | Terms, Challan, Return, Settlement, Reconcile, PO link, debit note draft, scorecard, gates | Golden numbers 10 to 13; a full wash round trip with partial returns; debit note draft created and not submitted |
| **D6 Finishing** | Finishing Receipt, finishing QC, needle log, label control, finishing print | A washed style flows wash → finishing; availability rule holds; needle rules |
| **D7 Packing** | Packing Instruction, Packing List, Generate Cartons, SSCC, GTIN check, labels, packing list print, Delivery Note button | Golden numbers 8, 9, 16, 17; a PO split over two ship-tos; carton label printed and **scanned by the user** |
| **D8 Final inspection and reconciliation** | AQL Plan (verified), Final Inspection, ship gate, Delivery Note hooks, Production Summary, Order Close, T&A stamps, WIP Report columns | Golden numbers 4, 5, 14, 15; a rejected then re-inspected lot; an order closed with a zero Unaccounted |
| **D9 Close-out** | Production Board tab, number cards, workspace and Sales Order buttons, print review, `security-review`, full test run, update this file's status, add Phase D to `CLAUDE.md` folder map and `HANDOFF.md` | All tests pass; review with the user |

### 13.1 T&A stamps (extend `tna/events.py`; the same never-raise wrapper)

| Event | Milestone |
|---|---|
| Pilot Run approved | `PILOT_RUN` (if not already stamped) |
| First bulk Lay Report submit | `PCD` actual |
| Cumulative good sewn ≥ planned good cut | `BULK_FINISH` (partial earlier) |
| Every challan Reconciled | `WASH_FINISHED` |
| Packed ≥ planned A-grade | `PACK_FINISHED` |
| Final Inspection Accepted (Final or Re-inspection) | `FINAL_INSPECTION` |
| Delivery Note submit | `EX_FACTORY` |
| Cancels | `unstamp(source_doctype, source_name)` |

No new milestone types. `FREIGHT_BOOKING` stays manual.

### 13.2 Tests (files `tests/test_production_card.py`, `test_cutting.py`, `test_sewing.py`, `test_subcontract.py`, `test_packing.py`, `test_final_inspection.py`, `test_ledger.py`)

Reuse `tests/utils.py` from Phases A and B to make a customer, style, tech pack, contract, submitted SO, a fabric Batch with Phase C fields. Every flow rule in section 3.2 has a pass and a fail test. Every override has a manager test and a non-manager test. Every ledger-writing document has a cancel test and an `unpost` test. Seed idempotence: running install twice creates no duplicate seeds. Pure functions (planned cut, consumption, efficiency, DHU, RFT, CBM, GTIN and SSCC check digits, carton and ratio maths, AQL lookup, penalty, turnaround date) are tested directly with the golden numbers.

---

## 14. Open decisions (defaults were used in the plan; the user confirms)

| # | Question | Default |
|---|---|---|
| D1 | Who installs the app on the hosted site (still open from Phases A to C; production screens need the same install) | As before |
| D2 | When is a pilot run required, and how many pieces? | Required at 1,000 pieces or more, or when the sample rule says so; 30 pieces; waiver by Production Manager with a reason |
| D3 | Bundle size and the cut cap tolerance | 20 pieces per bundle; 3 spare pieces per colour × size over plan |
| D4 | Learning curve percentages | 50 %, 75 %, 90 %, 100 % of target on days 1 to 4 (assumption, not sourced) |
| D5 | Stock postings | Fabric and trim issue submitted; finished goods receipt and consumption drafted for the accountant (section 3.3) |
| D6 | Wash penalty: all damaged pieces once the threshold is exceeded, or only the excess? Basis FOB or something else? | **Decided 2026-11-05: all damaged pieces**, Cost Sheet FOB. The `Excess Only` option stays in the setting in case it is needed later |
| D7 | Which defects are Critical | Wrong size label and any needle or metal finding; the user's QA confirms |
| D8 | AQL table | The rows in 10.3, to be verified against ISO 2859-1 by two sources and by QA; plan rows for lots up to 50 and above 35,000 left to QA |
| D9 | Languages | English only; other languages added later through translation files when the user supplies the strings (**decided 2026-11-05**) |
| D10 | Over-ship rule: contract band (Phase A ±7.5 % at 1,462 pieces) or the buyer's per-size 3 %? | Check **both**; Delivery Note blocks only on the contract band, warns on the 3 % |
| D11 | Is the packing instruction taken from the buyer's PO text or keyed by the merchant? | Keyed by the merchant (Packing Instruction), copied to the card; the agent can draft it |
| D12 | Carton selection for the final inspection | `ceil(sqrt(total cartons))` (common practice; confirm) |
| D13 | Is a Pre-final inspection recorded in the ERP, and who may close an order with a shortfall? | Recorded; Production Manager with a reason |
| D14 | Customs and tax rules for goods sent out for processing, per country | Out of scope; the plan is global. Add when the user supplies the data |

---

## 15. Research gaps and things not verified

- **Subcontracting and final-inspection research did not finish.** The wash rules, the Payment Request, the Final Inspection form and the AQL structure come from the company's own documents and general knowledge. Customs and tax rules for goods sent out for processing are not researched; the design is jurisdiction-neutral and the user will supply country data later (D14).
- **AQL numbers** are from memory and consistency with Phase C; they are not verified from ISO 2859-1 text. Rows for lot sizes up to 50 and for lots above 35,000 are deliberately not seeded.
- **GS1 label layout** conflicts between sources (50 mm vs 19 mm from the vertical edge). Retailer routing guides were not reachable.
- **Polybag warning rules** are from an aggregator, not the statutes.
- **Pilot quantity** (25 to 30 vs 100 to 200) and **extra cut** (2 to 5 %) are from single practitioner sources. No public US buyer manual was found for either, nor for inline or end-line pass criteria, DHU / RFT targets, ply-height limits, bundle sizes or shipment tolerances.
- **Browser and barcode checks:** none of the production screens, the GS1-128 carton label have been scanned or opened yet; the build must do the former and the user must do the latter.
- Reports built on SQL are not filtered by User Permissions (Phase C item 6); decide in D9 whether to close that gap for production reports (recommended).

---

## 16. Out of scope (later)

QR or barcode bundle tickets and scan-based tracking (idea only, not now), piece-rate pay and bonuses, barcode scanner hardware and a mobile app for the floor, RFID, EDI 856 and 810 generation (the carton SSCC and GTIN fields exist so a later phase can build them), commercial invoice, customs declaration, bill of lading and freight booking, landed cost, actual consumption feeding back into the Cost Sheet, supplier scorecards for fabric mills and trim suppliers, outsourced whole-garment sewing (CMT) to another factory, automatic debit-note submission and payment, buyer claims after shipment.

---

## Status log

_(To be filled by the builder after each slice: what was built, what was verified in a browser, what was not, differences from this plan, decisions taken.)_
