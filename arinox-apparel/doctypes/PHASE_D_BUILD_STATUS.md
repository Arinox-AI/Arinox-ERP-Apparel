# Phase D (Production): build status

**Written:** 2026-11-05, at the point the user stopped the build and asked for this record.
**Plan this follows:** [PHASE_D_PRODUCTION_PLAN.md](PHASE_D_PRODUCTION_PLAN.md) (read that for the full design and the edge-case list).
**Dev site:** `apparel.localhost` (bench `/workspaces/frappe-bench`). Everything below is built and migrated on the dev site only. **Nothing has been installed on the hosted ERP.**

## 1. Summary

| Slice | Content | State |
|---|---|---|
| **D0** Foundations | Settings, masters and seeds, roles, custom fields, warehouses, **Production Movement ledger**, flow rules, Production Adjustment, shared bulk gate | **Built, migrated, tested** |
| **D1** Production Card | Card, size breakup, fabric rows, subcontract route, revisions, agent API, form script, two print formats | **Built, migrated, tested** (two buttons from the plan not built, see section 8) |
| **D2** Pilot Run | Pilot Run, checks, SAM validation, pilot part of the bulk gate | **Built, migrated, tested** |
| **D3** Bulk cutting | Cut Plan, Lay Report, Cut Bundle, Recut Request, fabric issue, remnant return, two reports, two print formats, form scripts | **Built, migrated, tested** |
| **D4** Bulk sewing | Operation Bulletin (with workbook import), Line Input, Daily Line Report, Line QC Report, four reports | **Built and migrated. Tests written but not verified after the last round of fixes** (section 9) |
| **D5** Subcontracting (wash, embroidery, print, appliqué) | Terms, Challan, Return, Settlement, debit note, scorecard | **Not started** |
| **D6** Finishing | Finishing Receipt, needle detector log, label control | **Not started** (the finishing quality form exists: it is the Line QC Report with audit type Finishing) |
| **D7** Packing | Packing Instruction, Packing List, cartons, SSCC, labels, Delivery Note button | **Not started** |
| **D8** Final inspection and reconciliation | AQL plan seeding, Final Inspection, ship gate, Production Summary, Order Close | **Not started** |
| **D9** Close-out | Production board tab, number cards, workspace, Sales Order buttons, security review, status log | **Not started** |

**Counts:** 42 new doctypes, 55 new Apparel Settings fields, 3 new roles, 6 new reports, 4 new print formats, about 20 new Python modules and controllers. Nothing under `erpnext/` was edited.

**Decisions the user gave on 2026-11-05 (already reflected in code):** build for any country (no country-specific customs or tax logic), no QR or barcode on bundle tickets for now (kept as a later idea), and the wash penalty applies to **all** vendor-damaged pieces once the threshold is exceeded.

## 2. How the pieces fit together

```
Production Card (issued, no gate)
   │                    PP Meeting (Phase B) ── Pilot Run ── approved ─┐
   ▼                                                                    ▼
Issue Fabric to Cutting ──► Cut Plan ──► Lay Report (bulk gate checked HERE) ──► Cut Bundles (numbered plies)
                                              │                                      │
                                              ▼                                      ▼
                                   Production Movement ledger  ◄──────────  Line Input ─► Daily Line Report ─► Line QC Report
                                   (CUT, CUT_REJECT, SEW_IN, SEW_OUT,                                     (rejects, B-grade, finishing A-grade)
                                    SEW_REJECT, ... SHIPPED)
```

**The ledger is the centre.** Every stage document writes its quantities to one table (`Production Movement`). Reports and the availability rules read only that table. A document posts on submit and removes its rows on cancel; `rebuild_movements(card)` recomputes a card's ledger from its submitted documents. A wrong count is corrected with a **Production Adjustment** (signed quantity and a reason), never by editing history.

**Availability rules** (`production/flow.py`): a stage can only post what the stage before it released. For one colour and size: sewing input is at most good cut (and, if the card has a before-sewing process such as embroidery, at most what came back from it); sewing output plus rejects is at most sewing input; a subcontract send is at most the output of the previous route step; finishing intake is at most the last route step's output; finishing A, B and reject are at most finishing intake; packed is at most A-grade less samples; shipped is at most packed. Cutting is capped at planned cut plus a few spare pieces (setting `cut_cap_extra_pcs`, mode Block, Warn or Off). A Production Manager can override with a reason.

**The bulk gate moved.** Phase B checked it when a Work Order was submitted. The PP meeting needs an issued production card, and the gate needs the PP meeting, so the card cannot wait for the gate. Now the card is issued with no gate and the gate is checked at the **Lay Report** (first bulk lay): Phase B buyer approvals, PP meeting held with cutting actions closed, the Phase C material gate, and (for bulk lays) an approved Pilot Run when the card requires one. The Work Order hook still works and calls the same function (`production/gate.py: bulk_gate_for`).

## 3. What was built, by area

### 3.1 Foundations (D0)

**Python modules** in `arinox_apparel/production/`:

| File | Purpose |
|---|---|
| `maths.py` | Pure functions, no database: planned cut (rounded **up** per size), max ship qty, required fabric, lay and actual consumption, weighted marker efficiency, day and hour targets, pieces per machine, operation target, efficiency %, learning factor, DHU, RFT, traffic-light colour, wash penalty (all-damaged or excess-only), working-day arithmetic that skips Sundays and holidays, carton CBM, cartons needed, ratio-pack maths, carton selection, over/short %, GS1 check digit and validation |
| `flow.py` | The availability rules above (`Flow` class) |
| `ledger.py` | `post`, `unpost`, `totals`, `stage_total`, `rebuild_movements`, `transfer_card` (moves history to a revised card), `refresh_card_status` (status follows the furthest stage) |
| `gate.py` | `bulk_gate_for(sales_order, style, colour, stage)` with `pilot` and `bulk` stages, plus `pilot_blockers` and `active_card` |
| `stock.py` | The Stock Entries Phase D makes: fabric issue to Cutting WIP, remnant return, `moved()` totals, `refresh_issued()` |
| `cutting.py` | Roll suggestion for a cut plan, ply numbering, bundle creation, kit (lining / pocketing) check, form entry points for issuing rolls |
| `sewing.py` | Active operation bulletin of a style, learning-curve day on a line, OB workbook parser and importer |
| `measurements.py` | Garment measurement tolerance rule shared with Phase B |
| `summary.py` | Stage quantities read back from the ledger for reports |

**Apparel Settings: new "Production" sections** (55 fields): extra cut default 5 % (warn above 8 %), bundle size 20, cut-above-plan mode Block with 3 spare pieces, marker variance 5 %, width spread 1 cm, shrinkage spread 3 %, remnant minimum 5 m, kit check Warn, pilot required from 1,000 pieces and 30 pilot pieces, wash-before-pilot Warn, 480 working minutes and 65 % planned efficiency, learning curve table, bundle requirements, traffic-light rules (Yellow from 1 defect, Red from 2), DHU alert 5, wash threshold default 1 % and penalty settings (**All Damaged**, Cost Sheet FOB, 3-day quantity window), needle detector settings, controlled-trim tolerance, carton max gross 22.7 kg, GS1 company prefix (blank = SSCC off), final inspection plan, carton pick rule, ship gate and over/short basis, stock posting switches, and five production warehouses.

**Masters and seeds** (inserted only when missing, edits are never overwritten; `setup/production.py`):
- **Apparel Defect Code**: 43 codes from the company's end-line audit and final inspection forms, the daily report's loss categories and cutting practice, with severity and usual fault source. *Wrong Size Label* and *Metal or Needle Found* are seeded **Critical**; QA must confirm all severities.
- **Subcontract Process**: Wash, Embroidery, Print, Appliqué, Heat Transfer, Garment Dye (position, item state, billing unit).
- **Production Check Item**: 13 checks (pilot run, line setting, pre-pack) from the company's pilot-run form.
- **Carton Type**: one example from the packing list (54 × 33 × 20 cm).
- **Learning Curve Day** rows: **53.85, 69.23, 84.62, 92.31, 100 % of the final target on days 1 to 5.** This is sourced: the company's OB sheets plan 35, 45, 55, 60 then 65 % efficiency on days 1 to 5 against a 65 % final efficiency.
- **Traffic Light Rule**: Yellow 1, Red 2 (configurable).
- **AQL Plan** and **AQL Plan Row**: structure only. **No AQL numbers are seeded yet** (planned for D8, to be checked against ISO 2859-1).

**Roles** (created by a pre-sync patch so doctype permissions can name them): Apparel Production Manager, Apparel Production User, Apparel QA.

**Custom fields**: Company `apparel_pc_prefix`; Workstation `apparel_line_type`, `apparel_default_operators`, `apparel_default_helpers`; Stock Entry `apparel_production_card`, `apparel_issue_kind`; Supplier type gains Embroidery, Printing, Appliqué, Garment Dye.

**Warehouses** created if missing and linked in settings: Cutting WIP, Line WIP, Finished Goods (existing setting reused), Seconds (B-Grade), Scrap.

**Existing files changed:** `overrides/work_order.py` (gate moved out, same public functions), `setup/install.py` and `setup/materials.py` (roles, fields, supplier types, production setup call), `patches.txt`, `apparel_sample_rule.json` (sample type **Pilot Run** added to the Select), `apparel_settings.json`, and the Running Fabric Stock and WIP reports (now read the ledger).

### 3.2 Production Card (D1)

- **Production Card** (submittable, numbered by company prefix + `YY.MM.###`). Key: sales order × style × ex-factory date, one live card per key. One line per colour × size; the Sales Order supplies order quantity and contract tolerance.
- **Planned cut** per size = order × (1 + extra cut %), rounded **up** (the company's sheet showed fractions such as 163.8; the reference order of 1,804 pieces becomes **1,897**). Extra cut above the limit needs a manager and is flagged.
- **Fabric rows** compute required metres from planned cut and consumption (yard and kg conversions reuse Phase C), compare with the Fabric Requisition (warn above 1 % over), show accepted and issued metres and the shortage. The card never raises purchase requests.
- **Route** of subcontract processes (before or after sewing, panels or garments); impossible combinations are rejected.
- **Pilot required** when order quantity reaches the setting, or a sample rule says **Required**; a manager can waive with a reason.
- **Revise** makes a new draft with the quantities refreshed. On issue the old card is Superseded and its ledger rows and stage documents are **moved to the live card**, so history and cut caps carry over; cut already above the revised plan is flagged, not blocked.
- Issuing lists what is still missing (allocation, tech pack, requisitions, packing instruction) as a warning only. It fills the PP Meeting's production card reference.
- **Agent API** (whitelisted, permission-checked): `get_production_context`, `save_production_card` (drafts only), `get_production_status`, `get_card_lines`, `get_order_styles`.
- **Form script**: get lines from the Sales Order, Revise, Production Summary dialog, **Issue Fabric to Cutting** dialog.
- **Print formats**: *Production Card Form* (colour × size matrix, fabric, route, packing, signatures) and *Trim Card* (from the approved Trim Requisition lines).
- **Production Adjustment** (manager only) and status that follows the ledger.

### 3.3 Pilot Run (D2)

Pilot Run (submittable): pieces cut, sewn, washed and rejected come **from the ledger** (purpose Pilot), not from typing. Checklist (answers, action for every "No"), pattern and cutting comments, SAM validation per operation, measurements after wash (reuses Phase B's Sample Measurement and its tolerance rule), defects found, participants. Approval needs QA or manager role, an answered checklist, sewn pieces, washed pieces for washed styles, and a reason for out-of-tolerance readings. Rejected or Re-run needs notes. An approved run opens the bulk gate **for its colours only**; cancelling it closes the gate again. Stamps the `PILOT_RUN` milestone on the T&A.

### 3.4 Bulk cutting (D3)

- **Issue Fabric to Cutting**: Material Transfer from the fabric store to Cutting WIP by roll (batch); only accepted rolls of the card's fabrics can be issued. Issued metres are written onto the card's fabric rows.
- **Cut Plan**: lays with marker length, plies and ratios per size (ratios are a second table keyed by lay number because Frappe has no nested tables). Computes marker consumption, variance against the card, planned output per size against planned cut, and red flags (size in no lay, overshoot, shortfall). **Release** sends a variance above the limit to **Pending Approval**; a manager approves with a reason. **Suggest Rolls** groups available rolls by shade, then width, longest first, and reports short lays and unallocated rolls (nothing is saved).
- **Lay Report** (submittable): rolls laid with plies, end bits, damage and splices. Enforces: accepted rolls only, **one shade band per lay**, width spread, marker not wider than the roll, shrinkage spread (a block for washed styles), enough metres in Cutting WIP after earlier lays, ratios equal to the plan, re-cut rules, panel rejects. A balance below the remnant minimum becomes end bit. Lining and pocketing lays must be **paired with the shell lay** (same plies and ratios) so every component shares ply numbers. On submit: posts CUT and CUT_REJECT (shell only), creates bundles, returns remnants to the store, stamps `PCD`, moves the card to In Cutting. Cancel voids the bundles (numbers never reused), removes the ledger rows and cancels the remnant entry; blocked once a bundle has left the cutting room.
- **Cut Bundle**: one size, one body, consecutive plies, up to the bundle size; the last bundle may be short. Ply numbers run on across lays of a card.
- **Recut Request** (submittable): limited by rejects not yet replaced; a different roll or shade needs a manager's approval. A re-cut lay names the request and closes it.
- **Reports**: *Daily Cutting Report* (a column per day), *Fabric Consumption* (issued, returned, laid, end bits, damage, good garments, lay and actual consumption, variance, weighted marker efficiency, shortage). *Running Fabric Stock* and *WIP Report* now fill their cut and used-consumption columns from the ledger.
- **Print formats**: *Lay Report Form*, *Bundle Ticket* (bundle number printed as text; no QR, by decision).
- **Form scripts** for Cut Plan (Release, Approve, Reopen, Suggest Rolls) and Lay Report.

### 3.5 Bulk sewing (D4)

- **Operation Bulletin** (versioned, one Active per style): operations with machine and manual minutes. Computes total SAM, sewing and manual SAM, target per day and hour, pieces per machine, pitch time, each operation's target per hour, operators needed and a balance flag (±15 % of pitch). **Import** parses the company's OB workbook layout (heading rows, repeated names, missing numbers, a TOTAL row) and **warns when the operation rows do not add up to the sheet's own total**.
- **Line Input** (submittable): bundles loaded on a line; checks bundle status, purpose, before-sewing process returned, kit completeness (setting), the allocated line (warning). Posts SEW_IN, marks bundles Issued. Cancel restores them unless output was already reported.
- **Daily Line Report** (submittable): output by colour and size (optionally by bundle), manpower, overtime, downtime with reason, hourly table. Computes produced minutes (output × SAM), available minutes (**operators + helpers** × (shift + overtime − downtime)), **efficiency**, the day's **target scaled by the learning curve** (day counted from the style's first input on the line) and variance. Posts SEW_OUT; bundle sewn quantities and completion follow.
- **Line QC Report** (submittable): one hourly form for **Inline (traffic light)**, **End-line** and **Finishing**: hours checked and passed, defects by code, dispositions (rework, reject, B-grade), traffic-light rounds. Computes **DHU**, defective %, **RFT**. Rejects post SEW_REJECT (or FIN_REJECT at finishing); B-grade only at finishing; finishing posts FIN_A from a passed-by-colour-and-size table that must equal the hourly passes. A reject marked "needs re-cut" raises a **draft** Recut Request.
- **Reports**: *Line Loading*, *Line Efficiency and DHU*, *Sewing WIP* (loaded − sewn − rejected), *Daily Production Report* (the company's daily sheet from the ledger: cut, sewn, sent, received, finished, packed, shipped, today and total, rejects, cut-to-ship).

## 4. Findings from the company's documents (new in this build)

1. **The OB sheet has day-by-day planned efficiency** (35, 45, 55, 60, 65 %, days 1 to 5). It is now the seeded learning curve, replacing my earlier assumption.
2. **The sheet's worker count is operators plus helpers** (21 + 7 = 28), so capacity counts helpers; the bulletin's total SAM includes helper (manual) time.
3. **Formula bugs in the sheet:** pieces per hour divides by 9.5 hours although the working time is 480 minutes (37.69 shown, 44.75 correct), and the daily targets in the day table use 570 minutes. The ERP computes from the stored working minutes.
4. **The C2027 sheet's operation rows add up to 27.0 minutes (20.1 machine + 6.9 manual), but its header and TOTAL row say 24.4 (18.8 + 5.6).** The importer warns about such differences.
5. The daily production report reconciles exactly (`cut = packed + B-grade + rejects`, `packed = shipped + A-grade stock`); these identities are in the tests.
6. The wash contract, packing list and invoice findings recorded in the plan (section 1.2) are unchanged.

## 5. Differences from the plan

| Plan said | What was built | Why |
|---|---|---|
| Field `process` on movements and the route | `subcontract_process` | `process` collides with a method on Frappe's Meta class and breaks doctype sync |
| New remnant Batch per leftover roll | The same batch's balance is transferred back to the store | Keeps shade, dye lot and width on one record; simpler and exact |
| A revised card starts empty | History moves to the live card on issue | Otherwise cut caps and flow rules would restart at zero |
| Pilot required by "Required" or "If Raised" rule | Only an explicit **Required** rule | "If Raised" means the buyer must ask; it would have forced a pilot on every card |
| Learning curve is an assumption | Sourced from the OB sheets | Found in the reference workbook |
| Efficiency from operators | Operators **plus helpers** | Matches the sheet and the SAM definition |
| Line QC dispositions carry the card | The report carries it; a "passed A-grade" table was added for finishing | Hourly form has no colour or size |
| Packing Instruction link on the card | Plain text field until D7 | The doctype does not exist yet |

## 6. Files

New or changed under `arinox-apparel/arinox_apparel/arinox_apparel/` (the Python package):

- `production/` (9 modules above), `setup/production.py`, `patches/make_production_roles.py`
- `arinox_apparel/doctype/`: 42 new folders (JSON, controller, form script where one exists)
- `arinox_apparel/report/`: `daily_cutting_report`, `fabric_consumption`, `line_loading`, `line_efficiency_and_dhu`, `sewing_wip`, `daily_production_report`
- `arinox_apparel/print_format/`: `production_card_form`, `trim_card`, `lay_report_form`, `bundle_ticket`
- `arinox_apparel/tests/`: `production_base.py`, `test_ledger.py`, `test_production_card.py`, `test_pilot_run.py`, `test_cutting.py`, `test_sewing.py`
- Changed: `overrides/work_order.py`, `setup/install.py`, `setup/materials.py`, `patches.txt`, the two Phase C reports, `apparel_settings.json`, `apparel_sample_rule.json`
- Docs: `doctypes/PHASE_D_PRODUCTION_PLAN.md`, this file, `HANDOFF.md`, `CLAUDE.md`

The doctype JSON files were produced with a throwaway generator kept outside the repo; the JSON in the repo is the source of truth.

## 7. Tests

| Run | Result |
|---|---|
| Whole app, after D0 and D1 | **242 passed, 1 skipped** (the 195 from Phases A to C plus 47 new) |
| `test_pilot_run` | 14 passed |
| `test_production_card` (after the revision change) | 22 passed |
| `test_cutting` | **38 passed** |
| `test_ledger` | 25 passed (earlier run) |
| `test_sewing` | 31 written. The last completed run had 3 failures and 5 errors, almost all faults in the tests (they looked up bundles by a status they no longer had). Fixes were applied and **the rerun was interrupted, so this file is unverified** |
| Whole app after D2 to D4 | **Not run** |
| Browser | **Nothing from Phase D has been opened in a browser.** Form scripts, dialogs and print formats are untested visually (print formats are rendered to HTML in tests for the card, the lay and the bundle only) |

Golden numbers from the company's sheets are in the tests: 1,897 pieces cut and 3,262.84 m of fabric; 358.03 pieces a day and 44.75 an hour; 12.7869 pieces per machine; the daily-report identities; the wash penalty (30 pieces all-damaged, 10 excess-only); a Wednesday wash return across a Sunday and a holiday; the GS1 check digit for 03600029145; 219 full ratio packs; 8 cartons inspected of 64.

## 8. Not built

- **D5 to D9** in full (subcontracting, finishing, packing, final inspection, order close, production board, number cards, workspace and Sales Order buttons, security review).
- From D1: the **Create Subcontract POs** and **Issue Trims** buttons.
- From D4: print formats and form scripts for the sewing documents (Line Input, Daily Line Report, Line QC Report, Operation Bulletin import button) and the Operation Bulletin print.
- T&A stamps for sewing finished, wash finished, packing finished and final inspection (only `PCD` and `PILOT_RUN` are stamped so far).
- The ledger's rebuild list names doctypes that do not exist yet; it skips them until they are built.
- Bilingual or translated prints, by decision.

## 9. Known risks and things to check first

1. **Run the whole suite** before anything else; `test_sewing` in particular.
2. **Open the new forms in a browser** with the `run` skill: Production Card (Issue Fabric dialog), Cut Plan, Lay Report, Operation Bulletin, Line Input, Daily Line Report, Line QC Report.
3. Dev-site data: tests create records prefixed `_AT` and some leave stock behind in the test company's warehouses. They only delete their own order's production records.
4. A production user with only the floor role cannot read Sales Orders, so cards are created by merchandising or managers; this is intended but untested end to end.
5. Reports use SQL and are not filtered by User Permissions (same limitation as Phase C).
6. The AQL table is not seeded; the numbers in the plan are from memory and must be verified against ISO 2859-1 before use.
7. The hosted ERP still has none of Phases A to D. Someone with server access must install the app (see `DEPLOY.md`).

## 10. How to continue

1. `docker start apparel-mariadb apparel-redis`, then `cd /workspaces/frappe-bench && bench --site apparel.localhost run-tests --app arinox_apparel`. Fix whatever `test_sewing` still reports.
2. Build D5 next (the plan's sections 9 and the wash-contract table are the spec), reusing the ledger helpers (`ledger.post`, `Flow`) and registering new doctypes in `LEDGER_SOURCES`.
3. Update the status table at the top of this file after each slice, and add Phase D to the folder map in `CLAUDE.md` when it is complete.
