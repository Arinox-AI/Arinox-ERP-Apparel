# Hosted-site status

What has been **built and tested on a clean ERPNext-only site** (`hosted.localhost`: Frappe 16.33 + ERPNext 16.34.1, the app **not** installed, developer mode off, server scripts on), and what has not. Read `HOSTED_BUILD_GUIDE.md` (in `arinox-apparel/`) to continue the work, and `doctypes/HOSTED_CONSTRAINTS.md` sections 1 and 6 for the sandbox rules.

## How to use it

1. On the dev site: `bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '<dir>'}"` writes the bundle (`hosted_bundle/` in the repo is the last export).
2. Against a site, with an API key and secret of a user holding System Manager and Script Manager:
   `ARINOX_API_TOKEN=key:secret python3 api_load.py <dir> https://<site> [--only=group,group] [--dry-run] [--overwrite-seeds]`
   Standard library only. Re-running is safe. **Seed records and Apparel Settings are create-only**: an existing seed is skipped and only blank settings are filled, so a reload never removes a colour or size or overwrites a default people have set.
3. Tests: `arinox-apparel/hosted_tests.sh` (runs `portable/hosted_tests` on the ERPNext-only test site; the app is not installed there, so `bench execute` cannot be used). `hosted_sync.sh` re-exports and loads groups onto the test site.

## Loaded and verified

| Group | Records |
|---|---:|
| Module Def, roles | 1, 6 |
| DocTypes (130 from the app + `Arinox Number`) | 131 |
| Custom Fields on ERPNext doctypes, Property Setters | 189, 7 |
| Seeds (defect codes, processes, check items, T&A types and template, AQL plan, terms, categories, allowance rules, cost heads incl. Depreciation ...) | 195 |
| Apparel Settings defaults (ERPNext-master links left blank) | 1 |
| Print formats, Query Reports, Number Cards, Dashboard Charts, Dashboard | 10, 3, 29, 4, 1 |
| Workspaces, Workspace Sidebars, Desktop Icons | 4, 4, 4 |
| Script Reports (rewritten for the sandbox; the 5 added this round ran on real rows in tests) | 17 |
| Client Scripts (generated from the app's `.js`; all pass `node --check`; never run in a browser) | 30 |
| Server Scripts | 250 |

## Logic ported and tested (253 hosted tests pass)

| Piece | Scripts | Hosted tests |
|---|---|---:|
| Contract-based names for 12 doctypes (counter that never repeats) | `naming.py` (12 records), doctype `Arinox Number` | 3 |
| Production ledger and flow rules (post, unpost, check, totals, transfer on revision, card status) | `engine.py` (API `arinox_engine`) | 7 |
| Production Adjustment | 4 event scripts | 3 |
| Production Card + its helper buttons (card lines, order styles, summary, revise) | 5 event + 4 API scripts | 9 + 2 |
| Sales Contract (line key style x colour x PO, bands, price lock, sizes, signing list, placeholder scan with Shipping Marks allowed to stay TBA) + make-order and apply-template buttons | 5 event + 2 API scripts | 12 + 4 |
| Sales Order hooks (contract link, one live order, row fill of colour/size/PO/dates/tolerance) | 3 event scripts | 4 |
| Cost Sheet (materials, charges, FOB maths, margin, approval, sign-off chain, charges and margin buttons) | 2 event + 5 API scripts, `lib_costing.py` | 11 |
| Packing List (carton planning and ranges, contents, totals, needle gate, ledger, SSCC, finished-goods receipt, Generate Cartons) | 5 event + 1 API script, `lib_packing.py` | 11 |
| Final Inspection (lot, AQL sample, defects, re-inspection chain, result rules, seeded carton draw, Pick Cartons) | 4 event + 1 API script, `lib_inspection.py` | 9 |
| Delivery Note (ship gate with override, over-ship check, SHIPPED to the ledger, cancel) | 5 event scripts | 7 |
| Invoicing (direct route, group route with transfer price, same number on both legs, Prepare/Submit Invoices) | 2 API scripts | 4 |
| Payment follow-up (expected due date from the contract and shipment dates, daily status and reminders, Log Follow-up) and the shipment-date refresh | 1 scheduler + 1 API + 2 event scripts, `lib_followup.py` | 3 |
| Kill switch (turns every rule script off/on; keeps naming and the engine) | API `arinox_scripts_switch` | 1 |
| Tech Pack (sizes, measurements, fit rounds, accept/cancel) + Opportunity->Tech Pack, Tech Pack->Cost Sheet, Create Style Item buttons | 3 event + 3 API scripts | 10 |
| Price Negotiation (rounds, margin per offer, styles summary, status) + Quotation hook (margin floor, log round on submit) + Cost Sheet->Negotiation / Quotation and Negotiation->Quotation buttons, `lib_margin.py`, `lib_quotation.py` | 1+2 event + 3 API scripts | 9 |
| Factory Allocation (order check, tolerance cap, ship-to/PO narrowing, dates, status) + Get Order Lines, Save Allocation, Planning Context | 1 event + 3 API scripts, `lib_allocation.py` | 9 |
| Sample Approval (rules and overrides, rounds, process rules, readings, shrinkage, due date, chargeback, fit-approval clock) + Load Spec, Load Standard Tests, Sample Rules, Sampling Milestones, `lib_samples.py` | 2 event + 4 API scripts | 18 |
| PP Meeting (attendance, PP sample, buyer comments, actions after submit, comment sync, cancel) + 3 form buttons, `lib_pp.py` | 6 event + 3 API scripts | 11 |
| Bulk gate (G3): engine action `bulk_gate` (approvals, PP meeting, materials, pilot run), Work Order override and submit gate, Work Order gate indicator; `lib_materials.py` holds `material_gate` and `trim_readiness` from `materials/status.py` | 1 engine action, 2 event + 1 API scripts | 10 |
| Cost Head, Costing Parameter validation; Quotation -> Sales Contract button | 2 event + 1 API scripts | 5 |
| T&A: `arinox_tna` (stamp, unstamp, refresh, samples, refind), planner, Order TNA, TNA Milestone, TNA Template, board / update / agent endpoints, hooks from 9 documents | 22 scripts, `lib_tna.py`, `lib_tna_plan.py` | 16 |
| Materials: Fabric / Trim Requisition (+ 8 buttons), Purchase Order and Receipt hooks, roll import, Fabric and Trim Inspection (+ 3 buttons), `lib_mat.py`, `lib_purchasing.py`, `lib_items.py`, `lib_matinsp.py`, `lib_material_status.py` | 42 scripts | 13 + 9 + 9 |
| Production floor: Cut Plan, Lay Report, Recut Request, Cut Bundle, fabric issue, Operation Bulletin, Line Input, Daily Line Report, Line QC, Pilot Run, Finishing Receipt, Needle Detector Log | 34 scripts, `lib_cutting.py`, `lib_sewing.py` | 12 + 9 + 4 |
| Subcontract Challan / Return / Settlement (+ short close, make invoices), ledger rebuild | 13 scripts, `lib_subcontract.py` | 5 |
| Shipment hooks and buttons, freight, Buyer Claim, commercial close, EX_FACTORY stamp and shipment status on Delivery Notes | 22 scripts, `lib_shipment.py`, `lib_claim.py`, `lib_close.py` | 7 |
| Agent endpoints (production context / save / status, costing context / previous) | 5 API scripts | 2 |
| 5 script reports and 2 number cards (Report type) | `script_reports/`, `reports.CARD_QUERY_REPORTS` | 5 |
| Shipment checks, freight quote lines, sample invoice, Letter of Credit, LC reminder, T&A stamps, close production | the original 8 (`server_scripts/`) | in the dev suite (11) |

Shared helpers are written once in `hosted_scripts/lib_*.py` and copied into each script at export (`# include: lib_x.py`), because the sandbox cannot import.

Dev site, after all of this: the app's own suite is run again at the end of each round (407 tests, 2 skipped as of the last full run).

## Changes made to the app itself (the reference implementation)

- `sales_contract.py`: a contract line is style x colour x buyer PO; a size row finds its line by style, colour and PO; Shipping Marks may stay TBA.
- `shipping/invoicing.py`: links a contract to the invoice only when it exists (an order with no contract used to store its own name in the link and fail).
- New fields: Tech Pack `buyer_created_on`, `buyer_revised_on`; Tech Pack Measurement `section`, `revised_on`; Trim Requisition Item `stock_decision`; Sales Contract `production_lead_days`; Sales Invoice `apparel_all_contracts`.
- Cost Head *Depreciation* seeded. Permission tables of PP Meeting, Fabric Inspection and Trim Inspection corrected.

## Not ported

- `import_ob_workbook` (reads an uploaded .xlsx with `openpyxl`; no library in the sandbox). Enter the bulletin by hand, or add a CSV paste if it is wanted.
- The Order Desk and WIP Board pages, the WIP Report script report (`wip_report`), and Connections-tab dashboards: being built outside this app (section 9 of the guide).
- The demo / real-order ingest scripts (`hosted_ingest.sh`, `demo/`): held back from the public repo.

## Not verified

- Nothing was run against the real hosted site. The form scripts were never run in a browser (they pass `node --check`). The PP Meeting buttons return a count that the app's form shows in an alert; hosted, the alert shows an object instead of the number (data is correct).
- Tests run as Administrator, who holds every role. Role-restricted paths were tested with a second user only where ERPNext lets that user reach the document (override and waiver checks); a restricted user cannot even save a Purchase Order, so that branch is covered by ERPNext's own permission error.
- Group invoice route with a VND or HKD company (needs the USD receivable account and rate described in the guide).
- Server Script time limit on the real host (the ledger rebuild and carton plan loop over many rows).
- Pilot-run approval path of the bulk gate is covered (Pilot Run is ported); the T&A planner was tested with no Holiday List (Sundays off) only.
