# Hosted-site status (written 2026-11-05)

What has been **built and tested on a clean ERPNext-only site** (`hosted.localhost`, Frappe 16.33 + ERPNext 16.34.1, the app **not** installed, developer mode off, server scripts on), and what has not. Read `doctypes/HOSTED_CONSTRAINTS.md` sections 1 and 6 for the sandbox rules this work found.

## How to use it

1. On the dev site: `bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '<dir>'}"` writes the bundle (`hosted_bundle/` in the repo is the last export).
2. Against the hosted site, with an API key and secret of a user that has System Manager and Script Manager:
   `ARINOX_API_TOKEN=key:secret python3 api_load.py <dir> https://<site> [--only=group,group] [--dry-run]`
   Standard library only. Re-running is safe (records are updated, not duplicated). It prints one line per group and every failure with the server's message.
3. Tests: `hosted_tests.sh` (runs `portable/hosted_tests` on the ERPNext-only test site; the app is not installed there, so `bench execute` cannot be used).

## Loaded and verified (0 failures, re-run creates nothing new)

| Group | Records |
|---|---:|
| Module Def, roles | 1, 6 |
| DocTypes (130 from the app + `Arinox Number`) | 131 |
| Custom Fields on ERPNext doctypes, Property Setters | 188, 7 |
| Seeds (defect codes, processes, check items, T&A types and template, AQL plan, terms, categories, allowance rules ...) | 194 |
| Apparel Settings defaults (ERPNext-master links left blank) | 1 |
| Print formats, Query Report, Number Cards, Dashboard Charts, Dashboard | 10, 1, 27, 4, 1 |
| Workspaces, Workspace Sidebars, Desktop Icons | 4, 4, 4 |
| Script Reports (rewritten for the sandbox; run on empty data) | 12 |
| Client Scripts (generated from the app's `.js`) | 30 |
| Server Scripts | 40 |

## Logic ported and tested (39 hosted tests pass on the ERPNext-only site)

| Piece | Scripts | Tests |
|---|---|---:|
| Contract-based names for 12 doctypes (a counter that never repeats) | `naming.py` (12 records) + doctype `Arinox Number` | 3 |
| Production flow rules and ledger (post, unpost, check, transfer on revision, card status) | `engine.py` (API `arinox_engine`) | 7 |
| Production Adjustment (validate, negative check, post on submit, unpost on cancel) | 4 small event scripts | 3 |
| **Production Card** (order check, header fill, planned cut with extra %, max ship qty, one live card per order/style/date, fabric need, route rules, pilot rule, issue, cancel block, revision takes over history) | 5 event scripts | 9 |
| **Delivery Note** (card copied from packing list, final-inspection ship gate with manager override, over-ship check per size and in total, SHIPPED posted to the ledger, cancel reverses it) | 5 event scripts | 7 |
| **Sales Contract** (template terms, tolerance bands and overlap check, one line per style/colour, SKU limit, dates from terms, price lock to the quotation, size rows, totals, ready-to-sign list, placeholder scan, cancel guard) | 5 event scripts (line rule: style x colour x PO) | 10 |
| Shipment checks, freight quote lines, sample invoice, Letter of Credit, LC reminder, T&A stamps, close production | the original 8 (`server_scripts/`) | in the dev suite (11) |

Shared helpers are written once in `hosted_scripts/lib_*.py` and copied into each script at export (`# include: lib_x.py`), because the sandbox cannot import.

Dev site, after all of this was added: **407 tests, OK, 2 skipped** (same as before).

## Real-data check (two orders)

`demo/ingest_orders.py` enters two real orders (S84 and S14) into the ERPNext-only site and reconciles them with the papers: 23 documents created with 0 refusals, 16 of 18 figures match the papers, the other 2 are the unported Packing List header totals. The report (`COVERAGE_S84_S14.md`) and the script are held back from the public repo because they carry real commercial figures; ask the owner. How to finish the port is in `arinox-apparel/HOSTED_BUILD_GUIDE.md`.

Also built since the first version of this file: the include mechanism for shared helpers (`# include: lib_x.py`), the `Arinox Number` series doctype, `convert_reports.py` (12 script reports), client scripts that unwrap `frappe.flags.arinox_result` (all 30 pass `node --check`; never run in a browser), the helper scripts `hosted_sync.sh`, `hosted_tests.sh`, `hosted_exec.sh`, `hosted_ingest.sh`.

## Not ported (the logic of these documents does not run on the hosted site yet)

All other controllers and hooks: Cost Sheet, Fabric/Trim Requisition, Sample Approval, Fabric/Trim Inspection, Lay Report (needs the bulk gate, roll stock and bundle numbering), Cut Plan, Pilot Run, Line Input/QC, Daily Line Report, Subcontract Challan/Return/Settlement, Finishing Receipt, Needle Detector, Packing List (carton planning, SSCC), Final Inspection (AQL sampling, random draw, re-inspection chain), the Shipment hooks, invoicing, the daily follow-up, Buyer Claim, Price Negotiation, Tech Pack, T&A planner and event stamping, Purchase Order/Receipt/Work Order hooks. Without them, those documents save and submit but none of their rules run. The 29 button methods (make a sales order from a contract, make a cost sheet, etc.) have no API scripts, so the Client Scripts that call them will report a missing method.

Also not ported: five script reports that call app code (Fabric Consumption, Material Status, Freight Allocation, Running Fabric Stock, Sample Approval Tracker); two number cards that call app Python (Fabric Overdue, TR Lines On Hold); Order Desk and WIP Board pages and the WIP Report (being built separately).

## Defects found in the app while doing this

- PP Meeting: *Sales User* may submit, cancel and amend but not write (a custom DocType refuses this). In the bundle those three rights are removed.
- Fabric Inspection and Trim Inspection: *Quality Manager*, *Stock User* and *Stock Manager* each appear twice in the permission table (merged in the bundle).
