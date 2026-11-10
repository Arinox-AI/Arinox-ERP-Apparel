# Order to ship: handoff (2026-11-09, slice S11)

Plan: `arinox-apparel/ORDER_TO_SHIP_PLAN.md`. Build log with every gate output: `cortex-tower/ORDER_TO_SHIP_STATUS.md`. Nothing here is committed or pushed.
Everything was tested on `hosted.localhost:8001` only; the live KOGO ERP was never written to.

## 1. What exists

**Order page** (`#/orders/<Sales Order>`, ten steps, one page per Sales Order, follows amendments `-1`):
confirm, allocate (board), T&A (plan, lock, revise), samples and PP, materials, cut and sew, subcontract and finish, pack and inspect, ship, invoice-collect-close.
Also: order book (`#/orders`), Production board (`#/board`, replaces the old Cortex WIP screen), the Deal page's "Open the order" card (Deal step 6 and 7).

**Backend** (`cortex-tower/backend/`, plain functions, each `guarded`, role checked, `### name` entry in `document.md`):
`order_flow.py` (read model), `order_api.py` (get, list, allocation, T&A), `order_alloc.py` + `allocation.py` (suggester), `tna_plan.py` + `tna_engine/` (scheduler, golden plans),
`order_samples.py`, `order_materials.py`, `order_cutsew.py`, `order_subcontract.py`, `order_pack.py`, `order_ship.py`, `order_invoice.py`. Every ERP write goes `pipeline.execute -> TSR -> vendored Arinox scripts`, preview first;
the risky class (Stock Entry, Delivery Note, Sales Invoice, Purchase Receipt/Order, close) answers `needs_approval` until a manager approves.
**Frontend** (`frontend/src/app/`): `OrderPage`, `AllocationBoard`, `TnaPlan`, `SamplesPP`, `Materials`, `CutSew`, `Subcontract`, `Pack`, `Ship`, `Invoice`, `ProductionBoard`, shared `StepAct` (preview -> confirm).
**ERP side** (`arinox-apparel/`): doctype `Allocation Default`, Apparel Settings "Where to Produce", Server Scripts `arinox_tna_api_apply_plan`, `arinox_fabric_requisition_refresh_quantities`, the zero-quantity fix in `sales_contract_api_make_order`, and (S11) the packing-list style fix in `packing_list_validate`.

## 2. How to run and test

* Tower tests (need a venv with `sqlalchemy openpyxl requests`): `cd cortex-tower/backend && python3 tests/test_<name>.py` (all are plain scripts). Set `ARINOX_ERP_BASE` / `ARINOX_ERP_TOKEN` to the test site if a test could reach an ERP:
  the tower otherwise auto-discovers the sealed KOGO credentials. Order tests: `test_order_flow, _samples, _materials, _cutsew, _subcontract, _pack, _ship, _invoice`, plus `test_allocation, test_tna_engine, test_tna_plan, test_pipeline_guard, test_tsr_core, test_erp_links`.
* ERP tests: `cd arinox-apparel && sh hosted_tests.sh [group]` (needs `docker start apparel-mariadb apparel-redis` and `bench --site hosted.localhost serve --port 8001`; `bench worker --burst` if "too many queued jobs"). After a script change: `sh hosted_sync.sh server_scripts`, re-run, then `python3 tools/vendor_scripts.py` in `cortex-tower`.
* Frontend: `bash frontend/build.sh` (tsc, vite, one `index.html`; `config.js` stays the first script and is not inlined).
* Browser check: the S11 harness lives outside the repo (scratchpad of the S11 run): a small HTTP server that serves `index.html`, answers `POST /api` by calling the real `functions.FUNCTIONS[fn]` pinned to hosted.localhost (it prints the resolved base URL and logged user first and aborts if the base is not `http://hosted.localhost:8001`),
  plus Playwright + Chromium scripts (1440 and 390 px). Worth moving into `cortex-tower/tools/` (not done). `tools/ui_preview.py` is the older mock-API screenshot tool.
* Both the ERP Server Scripts and the tower's own rules exist on hosted.localhost, so ledger/stock submits run twice there (second run fails or double posts). For a live run on that site, disable the `After Submit` scripts of the document you submit
  (Fabric/Trim Inspection, Lay Report, Line Input, Daily Line Report, Subcontract Challan/Return, Finishing Receipt, Line QC Report, Packing List, Final Inspection, Delivery Note), then re-enable them (`hosted_sync.sh server_scripts` re-enables everything). A site without the scripts (the real target) does not have this.

## 3. ERP-side setup a real site needs

1. **Property Setters** from `cortex-tower/erp_setup/allow_on_submit.json` (57 fields: what the Arinox scripts `db_set` on submitted documents, e.g. Fabric Inspection quality_inspection/stock_entry, requisition item quantities, Subcontract Settlement invoices, Buyer Claim credit_note). Load with `portable/api_load.py` or create by hand; clear the cache. Regenerate with `tools/gen_allow_on_submit.py` after any new script.
2. **Apparel Settings** (all of them must be filled for the suggester and gates): "Where to Produce" (`alloc_finish_pack_days`, `alloc_cut_lead_days`, `alloc_min_batch_qty`, table `alloc_defaults` = SAM and efficiency per Product Type), `work_minutes_per_day`, `planned_efficiency_pct`, `learning_curve`;
   the five warehouses (fabric and trim inspection, fabric and trim store, rejected) plus Cutting WIP and Finished Goods; `enforce_bulk_gate`, `require_pp_meeting`, `ship_gate_final_inspection`, `ship_tolerance_basis`, `final_inspection_plan` (an AQL Plan); Stock Settings: Serial and Batch No on, ERPNext over-delivery allowance at least the largest contract tolerance.
3. **Masters**: factories (Plant Floor), lines (Workstation: type Sewing, default operators and helpers), Product Types (with an item group or a Tech Pack naming the type), Subcontract Processes, suppliers (mill, trims, wash house), a Tech Pack per style (materials with consumption), customers. Empty states in the tower say what is missing ("No SAM for ...", "Capacity is unknown ...").
4. **Vocabulary seeds**: the 33 `TNA Milestone Type` checkpoints (`tna/seed.py`), TNA calendars, reason codes, sample type rules, Product Type list. They are seeded by `setup/install.py` / `setup/production.py`, and exported into `hosted_bundle/06_seeds.json`.
5. **New ERP scripts** (Server Scripts in `portable/hosted_scripts/`, manifest, hosted tests): `arinox_tna_api_apply_plan`, `arinox_fabric_requisition_refresh_quantities` (called after a real inspection submit), `arinox_sales_contract_api_make_order` (skips zero-quantity sizes), `packing_list_validate` (S11: a carton row is tied to the order line of its own style).
6. **KOGO loader bundle (`apparel-modules/v2/hosted_bundle`) needs the same additions** and was NOT touched: doctype `Allocation Default`, the Apparel Settings fields, the seeds, the Property Setters above, and the four scripts. Without them the Order page degrades (allocation save, T&A apply, inspection refresh, packing refuse or no-op).

## 4. Known gaps (all "not verified" or not built)

* Trim requisition and trim inspection: unit tested only, never run live. Trim step of materials not exercised in the S11 order.
* Multi-style orders: found and fixed in S11 (packing list to order line; header style count). Other ERP scripts that match order lines by colour and size only (`delivery_*`, invoicing, ledger rebuild read `so_detail`, so they are right once the packing list is right) were not audited one by one.
* The tower's T&A re-plan after a PCD, ex-factory or template change: the diff exists (`scheduler.moves`), no API/UI; re-lock (baseline v2) has no function; the forecast is not mirrored into `Order TNA.status`.
* Payments are not a tower function (made in the ERP). Shipment can be submitted by the ERP while its delivery note is still a draft (the wizard orders the steps; a desk user can skip them).
* Partial-failure rollback cannot delete a Shipment already linked to a Packing List (ERP 417); noted S8.
* The preview modal of a risky action does not say "needs approval" up front (only on Confirm). The Confirm click now carries the approval id after the manager approves (fixed in S11).
* Playwright scripts are not in the repo. Carton generation was measured on tiny orders only (the 20 s job pattern for a 2,000-carton order is not tested).
* Two tower tests not in the known-failure list fail in this environment without a configured ERP URL: `test_register_replay` (2: ERP page url empty) and `test_mail_documents` (KeyError `documents`). Not caused by S11 changes (they touch `erp.url_for`); not checked against an earlier baseline.
* Agent layer A0-A6 (`AGENT_ARCHITECTURE.md`): not built. `cortex-tower/backend/agent/` does not exist in this tree.

## 5. Decisions still open for the user

1. **Template offsets under 7-day weeks (D5).** The template was written for a six-day week; every day is now a working day, so cut-to-ship is one day in seven shorter. Rescale (x 7/6) or let learned offsets (T4) correct it? S11 order: the suggester's late-as-possible PCD gave a plan the lock refused ("Ship is forecast 11 working days after ex-factory"), the planner had to move the PCD 3 weeks earlier. That conflict is the template/allocation disagreement showing up.
2. **Planning efficiency source.** The default is 65 %; the one style measured ran near 47 % of target on median days. Keep 65 %, or set a per-product default in Apparel Settings?
3. **Genericity clean-up A1 is not finished (D8).** Still holding company-derived values:
   * Seeds: `arinox_apparel/setup/production.py` no longer seeds `Allocation Default` rows, but `LEARNING_CURVE` (35/45/55/60/65 % = 53.85/69.23/84.62/92.31/100) is the company's own; `hosted_bundle/07_apparel_settings.json` still exports two rows (Knit Top 17.2 SAM, Woven Top 24.4 SAM, 65 %, source strings "Company operation bulletin ...") and the dev/test sites still hold them.
   * Real-order fixtures: `cortex-tower/backend/tests/fixtures/real_order_a.json` (anonymised style/colour/buyer/PO but real quantities and dates) used by `tests/test_real_order.py`; `tests/fixtures/` also holds `BOM_C9043-U70-629.xls`, `PO_AO-5644_AsterOak_new_style.pdf`, `t2_bom.xls`, `t3_bom.xls`, `t3_techpack.txt`, `deal_meta.json`, `sales_contract_signed_payload.json`; `backend/tna_app/data/tna_test_snapshot.json`.
   * Real-order strings (buyer names, `EM9xxxx` / `PO70xxx`-like references, style codes) in: `backend/seed_intake_demo.py`, `functions.py`, `inquiry.py`, `intake.py`, `erp_model.py`, `buyer_ref.py`, `tests/test_{costing_sheet,erp_links,xls,register_replay,write_payload,tech_pack_read,buyer_ref,deals,cost_save,po_form,mail_documents,cost_autofill,inquiry}.py`, `tests/deal_harness.py`, `QA_REPORT.md`, `docs/{LIVE_ERP_INTEGRATION_SPEC,EMAIL_AUTOMATION_PLAN,INTAKE_PLAN_EMAIL_TO_PROCESS}.md`;
     on the ERP side `arinox_apparel/tests/test_sewing.py`, `doctype/sales_contract_item/sales_contract_item.json`, `portable/demo/ingest_orders.py`, `hosted_bundle/03_doctypes.json`. The test site (hosted.localhost) also holds real-looking demo orders and customers (copies of a demo order) made by earlier slices.
   * Several files are pre-existing in the tower zip, not written by this build; check all of the above before any commit (the repo is public).
4. **Legacy T&A calendar retirement.** `tna_app/` (own SQLite overlay, `cx_tna_push_milestone`) is unchanged and still runs next to the ERP's `Order TNA`; confirm before it is switched off and the single writer (`order_tna_*`, `arinox_tna_api_apply_plan`) becomes the only one.
5. **Agent layer A0-A6 not built.** Decide when (and whether) the tower becomes the agent behind the ERP (KOGO as brain and clock); order and acceptance criteria are in `AGENT_ARCHITECTURE.md`.
6. Roll the doctype, settings, seeds, Property Setters and the four scripts into the KOGO loader bundle (`apparel-modules/v2`): when.
7. Other open questions from the status file ("Open questions for the user" 1, 4, 5, 6, 9): tolerance for "allocated = ordered", material-ready input to the suggester, finish-pack days from template or from medians, SAM averages per Product Type, a garment-type notion on lines.
