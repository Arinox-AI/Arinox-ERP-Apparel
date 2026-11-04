# Phase C — Materials: FR → TR → Purchase → Inspection → In-house, plus T&A / WIP

**Status:** Plan only. Nothing built. Written 2026-11-04 for a Sonnet build session.
**Module:** Arinox Apparel
**Spec form:** one consolidated spec for the phase, same as Phase B (`PHASE_B_PLAN_AND_APPROVE.md`).
**Sources (all read for this plan):**
- `../reference/DOCUMENT_INDEX.md` sections 3.7, 3.8, 3.9, 4.1, 4.2, 4.3
- Reference files opened directly: `FR Format Reference.xlsx`, `CTXGVN26.09.010-Bulk fabric-SU27.xlsx`, all 5 `TRIM REQUEST *.xlsx` (sheets `TR`, `T & A`, `FR`, `WASH`, `FILE MUST HAVE`), `23 OCT WIP DUMMY.xlsx`, `Belladahl_Warehouse_Report.xlsx`, `FABRIC PURCHASE CONTRACT.xlsx`, `2 - FABRIC INSPECTION FORMAT.pdf`, `3 - Trims Inspection Report.xlsx`, `Shrinkage report.pdf`
- ERPNext v16 source: `erpnext/stock/doctype/quality_inspection/`, `material_request/`, `batch/`, `controllers/stock_controller.py`, `stock_settings`
- Frappe source: `frappe/public/js/frappe/views/gantt/gantt_view.js`, `frappe/desk/form/meta.py` (calendar/gantt settings), `frappe/public/js/calendar.bundle.js`
- The built app: Phase A (Tech Pack, Cost Sheet, Sales Contract, Sales Order fields) and Phase B (Factory Allocation, Sample Approval, PP Meeting, bulk gate)

---

## 0. Read this first (for the builder)

1. Read `../CLAUDE.md` (hard rules), then `../skills/frappe-doctype/SKILL.md` (how to build and test a doctype in this app). Read the skill again before each new doctype.
2. Read `PHASE_B_PLAN_AND_APPROVE.md`. Phase C follows the same patterns: rules in Python controllers, settings tables instead of hard-coded rules, a whitelisted agent API, tests per slice.
3. **Nothing is tied to one company.** Cortex numbers (5 % allowance, 20 points, ±7 % bands, delay penalties) are **seed data** in settings or terms doctypes. Code never contains a buyer name or a supplier name.
4. Never copy bank, tax or customs identifiers from the reference files into code, seeds, tests or specs.
5. Build slice by slice (section 12). Each slice ends with `migrate`, tests passing, a status note at the end of this file, and a stop for user review.
6. Never commit or push. Never run anything against the hosted site.

### Skills and tools to use

| When | Use |
|---|---|
| Before any doctype, controller, hook, fixture | Read `arinox-apparel/skills/frappe-doctype/SKILL.md` |
| Reading a reference workbook (FR, TR, WIP, warehouse report) | `xlsx` skill. Copies are in the repo-root zip; extract to your scratchpad, open read-only, run Python with `-I` |
| Reading a quality PDF | `pdf` skill |
| Before writing any chart, colour, legend or grid on the WIP Board (slice C7) | `dataviz` skill (palette, status colours, light and dark) |
| Checking a desk screen works (every slice with a form or page) | `run` skill: start the bench, open the form or page, take a screenshot. Phase B was never opened in a browser; do it for Phase C |
| End of each slice | `code-review` at `medium`, then `simplify` |
| Before release (slice C8) | `security-review` (whitelisted methods and permission checks) |
| Looking something up in ERPNext or Frappe source | Read the file and cite its path in your notes. ERPNext source: `/workspaces/Arinox-ERP-Apparel/erpnext/`. Frappe: `/workspaces/frappe-bench/apps/frappe/` |

Bench: `/workspaces/frappe-bench`, site `apparel.localhost`. Loop: edit → `bench --site apparel.localhost migrate` → `bench --site apparel.localhost run-tests --app arinox_apparel` → open in desk.

### Glossary (apparel terms used below)

| Term | Meaning |
|---|---|
| FR | Fabric Requisition. The merchandiser's request to buy fabric for an order, per style × colour × fabric |
| TR | Trim Requisition. Same for trims: labels, thread, fusing, buttons, zips, tags, packaging |
| CW | Cuttable width. Usable fabric width; consumption depends on it |
| GSM | Grams per square metre (fabric weight). Needed to convert kg ↔ metres for knits |
| Consumption / YY | Fabric per garment (m, yd or kg), from the marker |
| Mini marker / bulk marker | Cutting layout that gives the real consumption. Mini marker comes first (used for the FR) |
| DTM | Dyed to match. Thread or trim colour that follows the garment colour |
| Lab dip | Colour approval of dyed fabric before bulk dyeing |
| Dye lot / shade band | Fabric dyed in one batch. Rolls from different lots can differ in shade and must not be mixed in one garment |
| 4-point system | Fabric inspection method: each defect gets 1–4 points by length; result is points per 100 yards |
| FPT / GPT | Fabric / Garment Physical Test (lab test report) |
| PI | Proforma Invoice from a supplier (trim PI date is a WIP column) |
| ETD / ETA | Estimated time of departure / arrival of a shipment |
| PCD | Planned cut date |
| T&A | Time and Action calendar: the milestone plan for an order |
| WIP | Work-in-progress tracker: one row per order line with every milestone date |

---

## 1. Research: do FR and TR run at the same time?

**Answer: they overlap. FR goes first, TR a few days later, and both are in procurement at the same time.** The two "ready" dates land on almost the same day, so neither waits for the other to finish.

Evidence from the company's own T&A template (sheet `T & A` inside every `TRIM REQUEST *.xlsx`). Offsets are days after the order is received:

| # | Milestone | Day |
|---|---|---|
| 1 | Mini marker | 3 |
| 2 | **FR raised** | **6** |
| 3 | **TR raised** | **9** |
| 4 | Fit approvals | 12 |
| 5 | Lab dip approvals | 13 |
| 6 | Trims approvals | 19 |
| 7 | **Bulk fabric ready** (at mill) | **28** |
| 8 | FPT (fabric test) | 29 |
| 9 | **Bulk trims ready** | **29** |
| 10 | Bulk fabric approved by buyer | 31 |
| 11 | PP sample approval + GPT | 36 |
| 12 | PP meeting | 39 |
| 13 | PCD | 41 |
| 14 | Pilot run | 44 |
| 15 | TOP / size set | 45 |
| 16 | Bulk finish | 45 + qty ÷ daily output (520 ÷ 300 = 1.7) |
| 17 | Washing finished | +3 |
| 18 | Packing finished | +3 |
| 19 | Final inspection | +2 |
| 20 | Freight booking | +3 |

Why this order is standard in garment sourcing:
- **Fabric is the critical path.** Bulk fabric takes 3–6 weeks (greige, dyeing or printing, finishing, testing). The FR is raised as soon as a mini marker gives a consumption, often before fit approval, because waiting would push PCD.
- **Trims are shorter but have more lines.** Labels, tags and packaging can be ordered from the buyer BOM straight away. Trims that need approval (buttons, zips, printed labels) are raised on the TR but held until the trim approval (day 19 here). That is why "TR raised" (day 9) is before "trims approvals" (day 19).
- **Both must be in-house and passed before PCD.** Fabric also needs inspection, relaxation and FPT before cutting, which is why fabric is due about 10 days before PCD.
- **Revisions are normal.** File names show `Revised Jan.30`. Buyer PO revisions after the FR/TR are raised produce delta requisitions, not new ones.

**Design consequence:** FR and TR are two separate documents with their own approval, both created from the Sales Order, both feeding Material Requests in parallel. Some TR lines can be put on hold until their trim approval; the FR never waits for the TR.

---

## 2. The flow

```
Sales Order (Phase A, submitted)         Factory Allocation (Phase B) → PCD
        │                                          │ (PCD sets "required by")
        ├──────────────┬───────────────────────────┤
        ▼              ▼                           │
 Fabric Requisition  Trim Requisition              │
 (FR, approve=submit)(TR, approve=submit)          │
   │ lines held until lab dip   │ lines held until trim approval (Phase B Sample Approval)
   ▼                            ▼
 Material Request (Purchase) ── or Customer Provided (buyer-supplied trims)
   ▼
 Purchase Order (ERPNext) + Material Purchase Terms (qty bands, delay penalties)
   │  ETD / ETA / PI tracked on the PO
   ▼
 Purchase Receipt → Inspection warehouse (quarantine). Fabric rolls = Batches
   ▼
 Fabric Inspection (4-point, per roll)      Trim Inspection (visual, sample size)
   │ creates Quality Inspection (ERPNext)    │ creates Quality Inspection
   ▼                                         ▼
 Stock Entry: accepted → Fabric/Trim Store; rejected → Rejected warehouse → Purchase Return
   ▼
 "In-house and passed" ──► Material gate on Work Order (extends Phase B bulk gate)
                      └──► PP Meeting colour rows (fabric required / received) auto-filled

Every step stamps a milestone on the Order T&A ──► WIP Board (Gantt, calendar, WIP grid) and WIP Report
```

---

## 3. What ERPNext already has, and how it is used

| Need | ERPNext object | Decision |
|---|---|---|
| Purchase request | Material Request (type Purchase; type **Customer Provided** for buyer-supplied items) | **Reuse.** FR/TR create MRs on submit. MR Item already has `sales_order` |
| Supplier order | Purchase Order | **Reuse** + custom fields (terms, ETD/ETA, PI, contract no) |
| Goods in | Purchase Receipt | **Reuse** + validation (quantity bands) + delay penalty fields |
| Fabric roll | **Batch** (one batch per roll) + Serial and Batch Bundle | **Reuse** + custom fields (roll no, dye lot, shade band, width, points, status) |
| Incoming QC record | Quality Inspection (`reference_type` = Purchase Receipt, `inspection_type` = Incoming) + Quality Inspection Template | **Reuse** as the official record. The detail (4-point per roll, trims defects) lives in new doctypes that create the QI |
| Move accepted / rejected stock | Stock Entry (Material Transfer) | **Reuse** |
| Return to supplier | Purchase Receipt return (`is_return`) | **Reuse** |
| Freight, duty on imported fabric | Landed Cost Voucher | **Reuse**, configuration only |
| Buyer's item codes (LB030, BT088) | Item → `customer_items` (Item Customer Detail) | **Reuse** |
| Unit conversion yd ↔ m | UOM Conversion Factor + Item UOMs | **Reuse.** 1 yd = 0.9144 m exactly |
| Intercompany fabric (factory buys from group fabric company) | Internal Supplier / Internal Customer, inter-company PO → SO | **Reuse**, configuration only. Test once, no code |
| Holidays when planning dates | Holiday List on Company | **Reuse** in T&A date maths |
| Calendar and Gantt screens | Frappe Calendar view, Gantt view (`<doctype>_calendar.js`), `frappe-gantt` 0.6 and FullCalendar bundled with Frappe | **Reuse** (section 9) |
| Project / Task for T&A | Project, Task | **Not used.** Task has no style, colour, sales order, auto-stamp source or baseline vs revised date. A Task per milestone would also flood the Projects module |
| Production Plan for material planning | Production Plan | **Not used** (same reason as Phase B: no style × colour, consumption, allowance or stock-netting logic) |

---

## 4. Settings and master data (slice C0)

### 4.1 Apparel Settings: new section "Materials"

| Field | Type | Default | Notes |
|---|---|---|---|
| fr_material_types | Small Text | `Fabric`, `Lining`, `Contrast Fabric` | One per line. Tech Pack material types that go on the FR. Everything else goes on the TR (fusing/interlining is a trim, as on the TR form) |
| fr_qty_basis | Select Order Qty / Order Qty + Tolerance | Order Qty | Garment qty used for requirements |
| fabric_due_days_before_pcd | Int | 10 | FR "required by" = PCD − this |
| trim_due_days_before_pcd | Int | 7 | |
| auto_submit_material_request | Check | 1 | |
| inspection_warehouse_fabric / _trim | Link Warehouse | | Receipt (quarantine) warehouses |
| store_warehouse_fabric / _trim | Link Warehouse | | Released stock |
| rejected_warehouse | Link Warehouse | | |
| default_purchase_terms | Link Material Purchase Terms | seeded "Standard Fabric Terms" | |
| fabric_points_basis | Select Per 100 Linear Yards / Per 100 Square Yards | Per 100 Linear Yards | The fabric contract says 20 points / 100 linear yards |
| fabric_points_threshold | Float | 20 | Per-supplier override on the terms doctype |
| fabric_sampling_plan | Table **Fabric Sampling Band** (from_length_m, to_length_m, inspect_pct) | 0–1000: 50, 1001–2000: 30, 2001–3000: 20, 3001–5000: 15, above 5000: 10 | First four from the inspection format; the >5000 row is an assumption, flag it to the user |
| max_rejected_rolls_pct | Percent | 10 | Lot fails if more rolls fail than this |
| material_gate_fabric | Select Block / Warn / Off | Block | Work Order gate (section 8) |
| material_gate_trims | Select Block / Warn / Off | Warn | |
| material_gate_min_pct | Percent | 100 | Accepted qty ≥ this % of net requirement |
| hold_po_until_approval | Select Block / Warn / Off | Warn | PO for an FR/TR line whose lab dip or trim approval is not in |
| cost_overrun_warn_pct | Percent | 5 | PO rate vs Cost Sheet material rate |
| default_tna_template | Link T&A Template | seeded | |

Use the same `set_settings_defaults` fix as Phase B: never reset a Check the user turned off.

### 4.2 New master doctypes

| Doctype | Kind | Fields | Seed |
|---|---|---|---|
| **Material Allowance Rule** | Plain | material_type (Select: same options as Tech Pack material), trim_category (Link Trim Category, optional), customer (optional), item_group (optional), allowance_pct, pack_size (round order qty up to a multiple), min_order_qty, remarks | Fabric 5 %, Lining 5 %, Contrast 5 %, Label 10 %, Trim 2 %, Packaging 2 %. Resolve most specific first: customer + category, customer + type, category, type. Same pattern as Phase B Sample Requirement |
| **Trim Category** | Plain | category_name, calc_basis default (section 5.2), needed_for (Select Cutting / Sewing / Finishing / Packing), sequence | Woven Label, Size Label, Care Label, Thread, Fusing / Interlining, Security Tag, Hang Tag, Button, Branding, Zipper / Hooks / Fasteners, Elastic / Tape, Packaging, Others. These are the section headings on the TR form |
| **Material Purchase Terms** (+ child **Purchase Qty Band**, **Delay Penalty Band**) | Plain | terms_name; qty bands (from_qty, to_qty, uom, tolerance_pct); delay bands (from_days, to_days, penalty_pct, action Select Discount / Cancel or Discount); claim_window_days; points_threshold; extra_qty_policy (Select Reject / Accept Unpaid / Accept Paid); terms_text (Text Editor, printed on the PO) | "Standard Fabric Terms" from `FABRIC PURCHASE CONTRACT.xlsx`: qty 0–1000 m ±7 %, 1001–3000 ±5 %, 3001–10000 ±3 %; delay 1–3 days 0 %, 4–11 days 10 %, 12–21 days 25 %, >21 days cancel or 50 %; claim window 45 days; 20 points; extra qty Accept Unpaid. "Standard Trim Terms": one band 0–∞ ±5 %, no delay penalty |
| **Fabric Defect Code** | Plain | code, defect_name, always_four_points (Check), category (Weaving / Dyeing / Printing / Finishing / Other) | From the inspection format: A double pick, B broken pick, C colour bar, D dye streak, E dye mistake, F foreign yarn, G dye patch, H hole (always 4), I stain mark, J crack, K knot, L loose weave, M double end, N broken end, O oil mark, P printing mistake, Q folding mark, R crease mark, S stop mark, T tiny dot, U slub, V pull yarn, W weaving defect, X shine mark, Y press mark, Z shift print, `△` mill mark, `a` slack/tight end. Code `X` appears twice in the format (shine mark and "defect was taken"); seed only shine mark and tell the user |
| **Trim Defect Type** | Plain | defect_name, severity (Major / Minor) | From the trims format: letter missing, print missing, shape out, stains, fusing problem, scratch, needle hole missing, damaged button/label, colour variation, size variation, size mix-up, unmatching thread |
| **Trim Sampling Plan** (+ child rows) | Plain | method (Percent / AQL table), inspect_pct, rows: lot_from, lot_to, sample_size, accept_max, reject_min | Default "Trims 10 %". Optional AQL rows for General Level II, AQL 2.5: 51–90 → 13 (1/2), 91–150 → 20 (1/2), 151–280 → 32 (2/3), 281–500 → 50 (3/4), 501–1200 → 80 (5/6), 1201–3200 → 125 (7/8), 3201–10000 → 200 (10/11), 10001–35000 → 315 (14/15), 35001–150000 → 500 (21/22). **The user's QA must confirm these against ISO 2859-1 before use.** Lots ≤ 50: inspect 100 % |

### 4.3 Custom fields on ERPNext doctypes (in `setup/install.py` `get_custom_fields`)

| Doctype | Fields |
|---|---|
| Company | `apparel_fr_prefix` (default FR), `apparel_tr_prefix` (default TR) |
| Supplier | `apparel_purchase_terms` (Link Material Purchase Terms), `apparel_supplier_type` (Select Mill / Converter / Trim Supplier / Washing / Other) |
| Item | `apparel_material_type` (Select, as Tech Pack), `apparel_trim_category` (Link), `apparel_fabric_gsm` (Float), `apparel_fabric_width_cm` (Float), `apparel_fabric_content` (Data), `apparel_construction` (Data) |
| Material Request Item | `apparel_requisition_type` (Select FR / TR), `apparel_requisition` (Dynamic Link), `apparel_requisition_item` (Data, child row name), `apparel_style_no`, `apparel_colour`, `apparel_hold_reason` (Small Text, ro) |
| Purchase Order | `apparel_purchase_terms`, `apparel_supplier_contract_no` (Data; e.g. the mill's contract no), `apparel_shipment_mode` (Select Sea / Air / Road / Courier), `apparel_port_of_loading`, `apparel_destination`, `apparel_pi_no`, `apparel_pi_date`, `apparel_mill_ready_date`, `apparel_etd_planned`, `apparel_etd_revised`, `apparel_etd_actual`, `apparel_eta`, `apparel_bl_awb_no`, `apparel_approval_override` (Check, manager only) + `apparel_approval_override_reason` |
| Purchase Order Item | `apparel_requisition_type`, `apparel_requisition`, `apparel_requisition_item`, `apparel_style_no`, `apparel_colour` (fetched from the MR item when the PO is made from the MR; also set by a `validate` hook if missing) |
| Purchase Receipt | `apparel_delay_days` (Int, ro), `apparel_penalty_pct` (ro), `apparel_penalty_amount` (ro), `apparel_qty_band_note` (Small Text, ro) |
| Batch | `apparel_roll_no`, `apparel_dye_lot`, `apparel_ticket_length`, `apparel_actual_length`, `apparel_width_cm`, `apparel_shade_band`, `apparel_points_per_100`, `apparel_inspection_status` (Select Uninspected / Accepted / Accepted by Lot / Rejected / Hold), `apparel_fabric_inspection` (Link), `apparel_shrinkage_warp_pct`, `apparel_shrinkage_weft_pct` |

Item setup rules (documented in the slice C0 notes, enforced by a helper `ensure_fabric_item` used by FR):
- Fabric item = **template per fabric quality** (e.g. `CTX-C06011`) with the Colour attribute; **variant per colour**. Stock UOM = metre. Purchase UOM can be yard or kg. `has_batch_no = 1`, batch naming by series.
- Knits bought in kg: add kg as an Item UOM. The conversion is per item and depends on GSM and width: `metres = kg × 1000 ÷ (GSM × width_m)`. Compute it from `apparel_fabric_gsm` and `apparel_fabric_width_cm` and refuse a kg line when either is missing.
- Trims: one item per trim code. Variants by Size (size labels) or Colour (DTM thread) where needed. Buyer code in `customer_items`.
- Buyer-supplied trims are separate items with `is_customer_provided_item = 1` (check `erpnext/stock/doctype/item/item.py` for what that flag forces before relying on it).

---

## 5. Requisitions (slices C1 and C2)

### 5.1 Fabric Requisition (FR)

Submittable. Submit = approved. Naming: Company `apparel_fr_prefix` + `YY.MM.###`, monthly counter. Reuse the Phase A contract-number helper; the reference FR number is `CTXVNF 26.09.008`.

**Header**

| Field | Type | Notes |
|---|---|---|
| company | Link Company | reqd |
| customer | Link Customer | reqd. One buyer per FR (the form has one BUYER) |
| season | Data | |
| fr_date | Date | default today |
| ordered_by | Link User | default session user |
| approved_by, approved_on | Link User, Datetime | set on submit |
| previous_fr | Link Fabric Requisition | set by **Revise** (section 5.3) |
| revision_no, revision_reason | Int, Small Text | reason reqd when revision_no > 0 |
| status | Select Draft / Approved / Partly Ordered / Ordered / Partly Received / Received / Superseded / Cancelled | computed |
| items | Table Fabric Requisition Item | |
| summary | Table Fabric Requisition Summary (ro) | grouped by fabric item + supplier: total order qty, uom, earliest required date. This is what the supplier sees |
| terms | Text Editor | from settings; the FR form's 7 terms |
| red_flags | Small Text (ro) | computed warnings (section 5.4) + manual notes |

**Fabric Requisition Item**

| Field | Type | Notes |
|---|---|---|
| sales_order | Link Sales Order | reqd, submitted |
| sales_contract, buyer_po | fetched / Data | `CTXG NO` on the form |
| style_item, style_no, style_name | | from the SO line |
| colour | Data | garment colour |
| material_role | Select Shell / Lining / Pocketing / Contrast / Other | |
| tech_pack_material | Data | row name on the Tech Pack, for traceability |
| fabric_item | Link Item | the colour variant. "Create Fabric Item" action if missing |
| fabric_description | Small Text | quality code, content, construction, GSM, width as printed |
| fabric_colour | Data | can differ from garment colour (`DTM-Shadow`, a print name) |
| supplier | Link Supplier | default from Tech Pack nominated supplier |
| nominated_by_buyer | Check | |
| cuttable_width_cm | Float | reqd. Parse "132CM", `57"` (× 2.54) on import |
| gsm | Float | |
| lab_dip_status | Data (ro) | from the Phase B Lab Dip Sample Approval for style × colour × material |
| garment_qty | Int | from the SO (sum over sizes and ship-tos for style × colour), editable down, warn when it differs from the SO |
| consumption | Float | per garment |
| consumption_uom | Link UOM | m / yd / kg |
| consumption_source | Select Mini Marker / Bulk Marker / Cost Sheet / Tech Pack / Manual | reqd |
| costed_consumption | Float (ro) | from the Cost Sheet material row, converted to the same UOM |
| allowance_pct | Percent | from Material Allowance Rule, editable; reason reqd when changed |
| allowance_reason | Data | |
| gross_qty | Float (ro) | garment_qty × consumption × (1 + allowance) |
| stock_warehouse | Link Warehouse | where leftover stock is taken from |
| stock_used | Float | leftover stock used (the "VN STOCK" column) |
| net_qty | Float (ro) | gross − stock_used, never below 0 |
| order_uom | Link UOM | purchase UOM (yd for many mills) |
| order_qty | Float (ro) | net_qty converted to order_uom, rounded up by the rule's pack_size |
| required_by | Date | default PCD (Factory Allocation, else contract line) − fabric_due_days_before_pcd |
| hold | Check (ro) | lab dip not approved and settings say hold |
| material_request, material_request_item | (ro) | |
| ordered_qty, received_qty, accepted_qty, rejected_qty | Float (ro) | rolled up from PO / PR / inspections, in stock UOM |
| remarks | Small Text | |

**Actions**
- **Get Lines from Sales Order:** one row per style × colour × FR material on the style's Tech Pack. Fills consumption from the Cost Sheet (source Cost Sheet) when no marker value exists.
- **Create Fabric Item:** makes the template (if needed) and the colour variant from description, GSM, width.
- **Revise:** section 5.3.

**Rules (Python, so the agent API cannot skip them)**
1. Each SO must be submitted and belong to the FR's customer and company.
2. No duplicate key `sales_order + style_item + colour + material_role + fabric_item`.
3. consumption > 0, cuttable width > 0, source set.
4. `gross_qty` is always computed. Never trust a typed total (the reference FR shows 3 % in the % column but the total was computed with 5 %: 553 × 1.97 × 1.05 = 1143.8805).
5. stock_used ≤ free stock = actual qty of fabric_item in stock_warehouse − stock_used on other **approved, not superseded** FRs not yet issued. Two FRs cannot both claim the same leftover roll.
6. kg lines need GSM and width.
7. Warn when consumption differs from costed_consumption by more than 5 % either way (both the saving and the overrun matter to costing).
8. Warn when the CW in the description and the CW field disagree (the reference FR row 12 says "CW 152CM" but the CW column says 142CM).
9. **On submit:** create Material Requests (type Purchase) **grouped by supplier**, one MR item per FR line (keeps the link to the SO). Lines with `hold` get `apparel_hold_reason`. Submit the MRs when auto_submit is on. Stamp T&A milestone `FR_RAISED`.
10. **On cancel:** cancel linked MRs that have no PO. If any MR item is ordered, block and say which PO.
11. Status and the rolled-up quantities update from hooks on PO, PR, Fabric Inspection and Stock Entry (submit and cancel).

### 5.2 Trim Requisition (TR)

Submittable, same numbering pattern with `apparel_tr_prefix`. A TR can cover several styles (the reference TR covers `C9307-C9360-C9043-...`). Header as FR plus `shipment_mode` (Sea / Air; the files are split `SEA DDP` / `AIR DDP`).

**Trim Requisition Item**

| Field | Type | Notes |
|---|---|---|
| sales_order, buyer_po, style_item, style_no | | |
| colour | Data | blank = all colours ("ALL COMBO") |
| size | Data | blank = all sizes |
| trim_category | Link Trim Category | reqd; groups the print like the paper form |
| trim_item | Link Item | |
| buyer_item_code | Data | from Item Customer Detail or Tech Pack |
| description | Data | |
| trim_colour | Data | `DTM` resolves to the garment colour on validate |
| calc_basis | Select Per Garment / Per Size / Per Colour / Per Carton / By Length / Fixed Qty | default from the category |
| garment_qty | Int | for Per Size: qty of that size from the SO; for Per Colour: that colour |
| qty_per_garment | Float | e.g. 10 buttons |
| spare_per_garment | Float | e.g. 1 spare button ("10+1=11pcs") |
| pcs_per_carton | Int | Per Carton basis; default from the Cost Sheet |
| consumption, consumption_uom | Float, Link UOM | By Length (tape, elastic, thread) |
| allowance_pct, allowance_reason | | from Material Allowance Rule |
| gross_qty | Float (ro) | section 5.2.1 |
| stock_warehouse, stock_used, net_qty | | as FR |
| pack_size | Float | e.g. thread cone length, labels per roll |
| order_uom, order_qty | | net rounded up to pack_size |
| supplier, nominated_by_buyer | | |
| customer_provided | Check | buyer supplies it: MR type Customer Provided, no PO |
| approval_status | Data (ro) | Phase B Bulk Trim Sample Approval for this style (and colour) |
| hold | Check (ro) | approval missing and settings say hold |
| required_by | Date | |
| material_request, material_request_item, ordered_qty, received_qty, accepted_qty | (ro) | |

#### 5.2.1 Trim quantity maths

| Basis | gross_qty |
|---|---|
| Per Garment | garment_qty × (qty_per_garment + spare_per_garment) × (1 + allowance) |
| Per Size | size_qty × qty_per_garment × (1 + allowance), one row per size |
| Per Colour | colour_qty × qty_per_garment × (1 + allowance), one row per colour |
| Per Carton | ceil(garment_qty ÷ pcs_per_carton) × qty_per_carton × (1 + allowance) |
| By Length | garment_qty × consumption × (1 + allowance), in consumption_uom |
| Fixed Qty | qty as entered |

Then `order_qty = ceil(net_qty ÷ pack_size) × pack_size` when pack_size is set. Thread example: 1800 garments × 150 m per garment × 1.02 = 275,400 m; cone 5,000 m → 56 cones.

Golden numbers from the reference TR (`TRIM REQUEST 02.05.26 #C8009-R43-304`): labels 1800 × 1.10 = **1980**; buttons 1800 × (10 + 1) × 1.10 = **21,780**.

**Actions:** **Get Lines from Tech Pack**: explodes Tech Pack materials whose type is not an FR type. Size labels become one row per size using the SO size quantities (SO items carry `apparel_size` and `apparel_colour`). DTM thread becomes one row per colour.

**Rules:** as FR (duplicates, computed totals, stock claims, cancel), plus:
- customer_provided rows need no supplier and create an MR of type Customer Provided.
- A row on hold creates its MR item with `apparel_hold_reason`. The PO hook (section 6) blocks or warns.
- On submit stamp `TR_RAISED`.

### 5.3 Revisions (both FR and TR)

Buyer PO revisions arrive after the FR/TR is approved (the reference TR is "Revised Jan.30"). Do **not** use cancel-and-amend (it would cancel MRs that may already be on a PO).

- **Revise** (button on an approved FR/TR) makes a new draft with `previous_fr` / `previous_tr` set, `revision_no + 1`, the same lines, quantities refreshed from the current SO.
- On submit, for each line key, compare `net_qty` with the total already requested by the whole revision chain:
  - **Increase:** create an MR item for the difference only.
  - **Decrease:** no MR. Add a red flag "Reduce X on PO Y with supplier Z" and show it on the Material Status report. If the PO is already received, the excess becomes leftover stock.
  - **Line removed** (style or colour cancelled): same as decrease to zero.
- The previous document becomes **Superseded**. Its MRs stay.

### 5.4 Red flags (computed on validate, shown on the form and printed in the "RED FLAGS & ALERTS" block)

- Consumption differs from costing by more than 5 %.
- Required-by date is after PCD − due days, or the supplier's lead time cannot meet it.
- Lab dip (FR) or trim approval (TR) not approved.
- CW mismatch between description and field.
- Garment qty differs from the SO.
- Stock claimed by another FR.
- A revision reduced quantity on an ordered line.

### 5.5 Agent API (whitelisted, same style as Phase B `save_allocation`)

- `get_requisition_context(sales_order)`: SO lines with sizes, Tech Pack materials, Cost Sheet consumption, allowance rules, leftover stock per fabric item, Factory Allocation PCD, lab dip and trim approval status.
- `save_fabric_requisition(data)` / `save_trim_requisition(data)`: create or update a draft; validation runs. Never submits.
- `get_material_status(sales_order)`: the Material Status report rows (section 8).

Check `frappe.has_permission` inside every whitelisted method.

### 5.6 Print formats

FR and TR print formats laid out like the paper forms (header, line table grouped by style for FR and by trim category for TR, terms, red flags, ordered-by and approved-by signatures). Arinox orange `#e8590c` and black header (CLAUDE.md branding).

---

## 6. Purchase Order and Purchase Receipt extensions (slice C3)

Hooks in `hooks.py` `doc_events`, code in `overrides/purchase_order.py` and `overrides/purchase_receipt.py`.

**Purchase Order `validate`**
1. Copy the requisition link, style and colour from the MR item when missing.
2. Default `apparel_purchase_terms` from the Supplier, else from settings.
3. Hold check: for rows whose MR item has `apparel_hold_reason`, re-check the approval now. If still missing: Block / Warn per `hold_po_until_approval`. Override with `apparel_approval_override` + reason (Apparel Merchandising Manager or System Manager only, like the Phase B gate override).
4. Cost check: PO rate (converted to the Cost Sheet UOM and currency) vs the Cost Sheet material rate. Warn above `cost_overrun_warn_pct`.
5. `apparel_etd_planned ≤ apparel_eta`; `apparel_etd_actual` not in the future.

**Purchase Order `on_submit` / `on_update_after_submit`:** stamp T&A (`FABRIC_BOOKED`, `TRIM_PI` from `apparel_pi_date`, `FABRIC_ETD` from ETD fields). Make the ETD/ETA/BL fields `allow_on_submit` so the merchant can update them after submit.

**Purchase Receipt `validate`**
1. Default `set_warehouse` to the inspection warehouse for rows that came from an FR/TR.
2. **Quantity band:** for each PO row, cumulative received vs ordered. The band comes from the PO's terms, picked by ordered qty in the band UOM. Over the band: act on `extra_qty_policy` (Reject = block; Accept Unpaid = allow and write a note that the excess must not be invoiced; Accept Paid = allow). Under the band after the PO is closed or fully received: write a shortage note. Notes go in `apparel_qty_band_note`.
3. Fabric rows must have batches (rolls). See section 7.1.

**Purchase Receipt `on_submit`**
1. **Delay penalty:** delay days = (`apparel_etd_actual` on the PO if set, else PR posting date) − PO row `schedule_date`. Penalty % from the delay bands; amount = penalty % × received value. Store on the PR. Show it; **do not post accounting**. A "Make Debit Note" button can come later.
2. Update FR/TR received qty. Stamp `FABRIC_IN_HOUSE` / `TRIMS_IN_HOUSE` when cumulative received ≥ required (partial receipt sets the milestone In Progress).

**Cancel** of PO or PR reverses roll-ups and clears milestone actuals that came from that document.

---

## 7. Receiving and quality inspection (slices C4 and C5)

### 7.1 Receiving fabric rolls

- Purchase Receipt into the fabric inspection warehouse. Stock moves at this point, so "fabric in-house" is true on the receipt date even though QC is pending.
- **Import Roll List** button on the PR row (client JS dialog): paste or upload the supplier packing list (roll no, dye lot, length, width, length UOM). The reference `PRODUCTION CARD` sheet `PKL` has this shape (lot, roll, metres).
- Server method creates one **Batch** per roll (batch_id `<PR>-<roll no>`, fields from section 4.3) and the row's Serial and Batch Bundle. Row qty = sum of roll lengths in stock UOM. Read `erpnext/stock/serial_batch_bundle.py` and `stock_controller.py` (the bundle code around line 405) for the supported way to build a bundle in v16 before writing this.
- Edge cases to handle: yard roll lists for a metre item (convert), duplicate roll numbers in one receipt (block), a roll list total that differs from the PR qty (block until fixed), a roll list arriving after the goods (allow saving the PR as draft without rolls; block submit).

### 7.2 Fabric Inspection (4-point)

Submittable. One per Purchase Receipt × fabric item (colour). Naming `FI-.YYYY.-.#####`.

**Header:** purchase_receipt, purchase_receipt_item, supplier, purchase_order, fabric_requisition, sales_orders (Small Text, ro), style_nos (ro), customer, fabric_item, colour, inspection_date, inspected_by (User), inspection_machine (Data), light_source (Select D65 / TL84 / CWF / Daylight), points_basis and points_threshold (from terms, else settings), total_rolls, total_received_m, sampling_pct (from plan, by total_received_m), required_inspect_m, inspected_m (computed), inspected_pct, avg_points, rejected_rolls, shade_bands_found, lot_result (Select Pass / Fail / Re-inspect 100% / Hold), result_override + reason (QA manager), fpt_sample_approval (Link Sample Approval), remarks.

**Child Fabric Inspection Roll:** batch (Link Batch, filtered to the PR row), roll_no, dye_lot, ticket_length, actual_length, length_variance (computed), width_required_cm, width_start/middle/end_cm, width_ok, total_points (computed), points_per_100 (computed), shade_band (Data, e.g. A/B/C), csv_ok (centre-selvedge variation), bowing_skew_pct, face_side_marked (Check), roll_result (Select Accept / Reject / Hold), remarks.

**Child Fabric Inspection Defect:** roll_no (Select from the roll rows), yard_position (Int), defect_code (Link Fabric Defect Code), defect_length_in (Float), points (Int 1–4, computed), remarks. (Frappe has no nested child tables, so defects are a second table keyed by roll_no.)

**Child Shrinkage:** reuse the Phase B child doctype **Sample Shrinkage Reading** as a Table field here. A child doctype can sit in more than one parent.

**Maths (put each in a small pure function and test it)**
- Points by defect length: ≤ 3 in = 1; > 3 to 6 in = 2; > 6 to 9 in = 3; > 9 in = 4. Holes and any defect code with `always_four_points` = 4.
- Cap: no more than 4 points in one linear yard per roll (sum by `roll_no + yard_position`, cap at 4).
- Per 100 linear yards: `total_points × 100 ÷ inspected_yards`.
- Per 100 square yards: `total_points × 3600 ÷ (inspected_yards × cuttable_width_inches)`.
- Lengths in metres convert to yards (÷ 0.9144) for the points formula.
- Example to use in tests: 30 points over 150 yd at 57 in width → 20.0 per 100 linear yards; 12.63 per 100 square yards.
- Sampling: 1,500 m of one colour → 30 % → at least 450 m must be inspected. Pick whole rolls; inspected_m ≥ required_inspect_m or submit is blocked (override with reason).
- Width impact: when the average actual width < required CW, estimated new consumption = FR consumption × required CW ÷ actual CW. Show the shortfall in metres for the FR line and add a red flag to the FR.
- Shrinkage: % from before/after readings as in Phase B; warn above `max_shrinkage_pct`.

**Lot result**
- Pass: average points ≤ threshold **and** rejected rolls ≤ `max_rejected_rolls_pct` of inspected rolls.
- A single roll above the threshold is rejected even when the lot passes.
- Fail on the sample: set **Re-inspect 100%**. Submit is blocked until every roll is inspected (standard practice), unless overridden.
- More than one shade band: allowed, but write `apparel_shade_band` on every batch and flag "Cut by shade band" on the FR line and the PP Meeting.

**On submit**
1. Write roll results to each Batch (`apparel_inspection_status`: inspected rolls Accepted / Rejected; uninspected rolls in a passed lot become **Accepted by Lot**; in a failed or held lot they become **Hold**).
2. Create an ERPNext **Quality Inspection** (Incoming, reference the PR, item, status Accepted if the lot passes else Rejected, readings from a seeded template "Fabric 4-Point": avg points, worst roll, width, shrinkage warp, shrinkage weft). Set Stock Settings `allow_to_make_quality_inspection_after_purchase_or_delivery` in `after_install` and say so in the notes.
3. Create a **Stock Entry** (Material Transfer) moving accepted rolls to the fabric store and rejected rolls to the rejected warehouse. Draft or submitted per a setting (default submitted).
4. Update the FR line accepted and rejected qty. Stamp `FABRIC_QC_PASSED` when the accepted total ≥ required.
5. Claim deadline: PR posting date + terms `claim_window_days`. Show on the inspection and on the Material Status report (45 days in the reference terms).

**Rejected fabric:** a **Make Purchase Return** button creates a PR return for the rejected batches from the rejected warehouse. A replacement is a new PR on the same PO.

**FPT (fabric lab test):** add sample type **Fabric Test (FPT)** to the Phase B Sample Approval Select and seed an Apparel Sample Rule (gate If Raised, per colour, PCD − 21). It reuses the Sample Test Result table. Fabric Inspection shows its status. Release to store does not wait for FPT; the bulk gate does (Phase B logic already handles it once the rule exists).

### 7.3 Trim Inspection

Submittable. One per Purchase Receipt × trim item. Fields from the trims format: received_date, supplier, customer, style_nos, material_description, colour, invoice_no, received_qty, sampling plan (Link Trim Sampling Plan), sample_size (computed), inspected_qty, defects table (Trim Defect Type, count), defective_qty (computed), accepted_qty, rejected_qty, rejected_pct, original_sample (Attach Image), defective_sample (Attach Image), approved_trim_ref (Link Sample Approval, Bulk Trim), result (Pass / Fail / Hold), warehouse_incharge (User), trim_sourcing_manager (User).

Rules: inspected_qty ≥ sample_size; with an AQL plan, Fail when defective ≥ reject number. Size labels: a size mix-up is always Fail for that lot. On submit: Quality Inspection + Stock Entry (accepted → trim store, rejected → rejected warehouse) + TR roll-up + `TRIMS_QC_PASSED`.

---

## 8. Material status and the material gate (slice C6)

**Script Report "Material Status"** (the merchandiser's main screen). One row per SO × style × colour × FR/TR line: material, supplier, required by, net qty, ordered (PO, PO date), ETD planned / revised / actual, ETA, received, in inspection, accepted, rejected, balance to receive, claim deadline, status (Not Requested / Requested / On Hold / Ordered / In Transit / In House – QC Pending / Accepted / Short / Rejected), days late. Filters: customer, SO, supplier, status, material type.

**Script Report "Running Fabric Stock"** (replaces `Belladahl_Warehouse_Report.xlsx`). One row per fabric PO row: PO date, buyer, merchant, style, supplier, supplier contract no, fabric spec, colour, ordered, unit, price, value, delivery date, delay days, received date and qty, over/short qty and ratio, location (warehouse), issued (Stock Entry out; Phase D adds cutting), balance, % of order, % of received, stock value, garment order qty. Leave **cut qty** and **actual used consumption** columns empty until the cutting phase exists, and label them so.

**Bulk gate extension (Phase B G3).** In `overrides/work_order.py` `before_submit`, add material blockers for the Work Order's style × colour:
- Fabric (if `material_gate_fabric` ≠ Off): for every FR line of this SO × style × colour, accepted qty ≥ net qty × `material_gate_min_pct`. Block or warn per setting.
- Trims (if `material_gate_trims` ≠ Off): same, only for trim categories with `needed_for` = Cutting or Sewing (packaging must not stop cutting).
- The existing override field and reason cover these blockers too. List every blocker in one message, as Phase B does.

**PP Meeting (Phase B) integration.** "Load from Requisitions" fills the colour rows' `fabric_required_m` and `fabric_received_m` from FR lines (accepted qty) and suggests `sewing_trims` / `packing_trims` (Available / Partial / Not Available) from TR status. Shade bands found go into the colour row `no_of_shades`.

**Number cards:** Fabric Overdue, In Inspection, Rejected Lots (30 days), TR Lines On Hold.

---

## 9. T&A and WIP chart (slice C7)

### 9.1 About server access

**Calendar and Gantt screens need no extra server access beyond installing the app**, and the app has to be installed anyway: every Phase A and B doctype is already in it.
- The Gantt view and Calendar view come with Frappe. An app turns them on for a doctype by shipping a `<doctype>_calendar.js` file in the doctype folder (`frappe/desk/form/meta.py` loads it as `__calendar_js`), or for an ERPNext doctype via the `doctype_calendar_js` hook.
- `frappe-gantt` 0.6 and FullCalendar are bundled with Frappe, so the custom WIP Board page loads them from `/assets/frappe/...` with no new dependency (see how `frappe/public/js/frappe/views/gantt/gantt_view.js` loads them).
- **Do not depend on the scheduler for correctness.** If the hosted site has the scheduler off, statuses (Late, At Risk) must still be right. Compute them at read time in reports and the page. The daily job only sends reminders.
- The real blocker is the open question in `HANDOFF.md`: someone with shell access (or Frappe Cloud's dashboard) must run `bench get-app`, `install-app`, `migrate` for **any** phase to reach the hosted site. If nobody can, see decision D1 for the fallback.

### 9.2 Doctypes

**T&A Milestone Type** (master): code (unique, e.g. `FR_RAISED`), label, department (Merchandising / Sampling / Purchasing / Quality / Production / Washing / Shipping), auto_source (Select from the event list in 9.3, or Manual), is_critical, applies_when (Select Always / Washed Only / Printed Only / Sample Type Required), sample_type (for "Sample Type Required"), sequence.

Seed these milestone types (union of the T&A sheet and the WIP sheet columns): Order Received, Tech Pack Received, BOM Received, Bulk Standard Received, Mini Marker, FR Raised, TR Raised, Lab Dip Approved, Fit Approved, Trims Approved, Fabric Booked (PO), Trim PI Received, Bulk Fabric Ready at Mill, Fabric ETD, Fabric In-house, Fabric QC Passed, FPT Passed, Trims In-house, Trims QC Passed, Bulk Fabric Approved by Buyer, PP Sample + GPT Approved, PP Meeting, PCD, Pilot Run, TOP / Size Set, Bulk Finish (sewing), Washing Finished, Packing Finished, Final Inspection, Freight Booking, Ex-Factory.

**T&A Template** (+ child **T&A Template Milestone**): template_name, customer (optional), product_type (optional), shipment_mode (optional), is_default. Rows: milestone_type, basis (Select Order Received / Ex-Factory / PCD / After Milestone), after_milestone (code), offset_days (negative allowed for Ex-Factory basis), duration_rule (Select Fixed / Qty ÷ Daily Output), daily_output (Int, used with Qty ÷ Daily Output), owner_role. Most specific template wins (customer + product type, customer, product type, default).

Seed **"Standard 60-Day (forward)"** from the T&A sheet offsets in section 1 (Order Received basis for rows 1–13; Pilot Run = PCD + 3; TOP = PCD + 4; Bulk Finish = TOP + qty ÷ 300; then +3, +3, +2, +3). Also seed Fabric Booked (FR + 2), Fabric ETD (Bulk Fabric Ready + 2), Fabric In-house, Fabric QC Passed (In-house + 3), Trims In-house and Trims QC Passed so the materials flow shows.

**Order T&A** (plain): one per Sales Order × style × colour × ex-factory date (a ship-to with a different ex-factory date gets its own T&A; the WIP sheet splits the same PO by ship-to). Fields: sales_order, customer, merchant (User), factory (from Factory Allocation), style_item, style_no, colour, order_qty, ship_tos (Small Text), order_received_date (Buyer PO date, else SO date), ex_factory_date, pcd, template, baseline_locked (Check), status (On Track / At Risk / Late / Completed / Cancelled, computed), critical_delay_days, plan_feasible (Check, computed), feasibility_note.

**T&A Milestone** (plain, **not a child table**, so Calendar, Gantt, Kanban and Report views work on it): order_tna, sales_order, customer, style_no, colour, factory, milestone_type, label, sequence, department, owner (User), planned_start, planned_date (baseline), revised_date, revision_reason, delay_reason_category (Select Buyer / Supplier / Factory / Logistics / Other), actual_date, status (Not Started / In Progress / Done / Late / Not Applicable, computed), delay_days (computed), source_doctype, source_name (Dynamic Link), is_critical, `depends_on_tasks` (Data: name of the predecessor milestone; the Gantt view draws dependency arrows from this exact fieldname), color (Data hex, computed from status), progress (Int, 0 or 100), remarks. Turn on `track_changes`.

### 9.3 Planning and auto-stamping

**Make T&A** (button on Sales Order, and automatically on SO submit when a default template exists): one Order T&A per grain, milestones from the template.
- Forward pass from Order Received; PCD-based and Ex-Factory-based rows use those dates; After Milestone rows chain. Qty ÷ Daily Output rounds up to whole days.
- Shift dates off holidays using the Company Holiday List.
- Use Factory Allocation `pcd`, `sewing_start`, `sewing_end` when present; they override the template for PCD and Bulk Finish.
- **Feasibility:** if the last milestone before Ex-Factory lands after the ex-factory date, set `plan_feasible = 0` and write "Plan is N days late against ex-factory" (the T&A sheet's DAYS LEFT column).
- Milestones whose `applies_when` fails become Not Applicable: no wash → Washing Finished N/A; Phase B Sample Requirement says Fit = No or the style is a carry-over with an approved fit → Fit Approved N/A (the WIP sheet shows "CARRY OVER").
- `planned_date` is the baseline. **Lock Baseline** freezes it; afterwards only `revised_date` changes (reason required). Delay = (actual, or today when not done) − planned.

**Auto-stamp events.** One module `arinox_apparel/tna/events.py` with `stamp(sales_order, style_item, colour, code, date, source_doc, partial=False)` and `unstamp(source_doc)`. Wire it with `doc_events`:

| Event | Milestone(s) |
|---|---|
| Tech Pack received / accepted | Tech Pack Received, BOM Received (when buyer_bom_file set) |
| Fabric Requisition submit | FR Raised (+ Mini Marker when source is Mini Marker) |
| Trim Requisition submit | TR Raised |
| Sample Approval status change (Phase B) | Lab Dip, Fit, Trims, Bulk Fabric Approved by Buyer, PP + GPT, FPT, TOP / Size Set. Per-colour types count only when every colour of the T&A grain is approved |
| Purchase Order submit / ETD update | Fabric Booked, Trim PI Received, Fabric ETD, Bulk Fabric Ready at Mill |
| Purchase Receipt submit | Fabric In-house, Trims In-house (In Progress when partial) |
| Fabric Inspection / Trim Inspection submit | Fabric QC Passed, Trims QC Passed |
| PP Meeting submit (Phase B) | PP Meeting, or Pilot Run when meeting_type is Pilot Run |
| Factory Allocation save (Phase B) | revises PCD and dependent planned dates (revised_date, not baseline) |
| Work Order actual start | PCD actual |
| Sales Order cancel | Order T&A Cancelled |

Rules: an actual date is never overwritten by a later event; it is cleared only when its source document is cancelled. Manual actual dates are allowed (source "Manual"). Stamping must never raise: wrap each hook, log failures with `frappe.log_error`, so a T&A problem cannot block a purchase or a receipt.

The fit columns in the WIP sheet (drop date, submit date and comment date for the 1st to 4th fit) come from Sample Approval **rounds**, not from fixed milestones. The WIP report reads them from the rounds (Phase B `get_sampling_milestones`).

### 9.4 Screens

1. **Built-in views on T&A Milestone.** Ship `t_and_a_milestone_calendar.js` with `field_map` {start: planned_start, end: revised_date or planned_date, id: name, title: label, allDay: 1, progress}, `gantt: true`, `order_by: "planned_start"`, and a `get_events_method` that colours by status. That gives **Calendar** and **Gantt** list views with no custom page. Also a Kanban by status.
2. **WIP Board** page (`apparel_wip_board`). Load the `dataviz` skill before writing it. Filters: customer, merchant, factory, season, ex-factory range, "late only". Three tabs:
   - **WIP grid** (the screen merchandisers will use most): rows = Order T&A, columns = milestone types in sequence, each cell shows the date with a status colour (done on time, done late, due within 7 days, overdue, not applicable). Click a cell to open the milestone and set revised or actual dates. Status needs text or an icon as well as colour.
   - **Gantt:** frappe-gantt, one bar per milestone grouped by order, baseline vs revised, today marker, dependency arrows, click → form.
   - **Calendar:** FullCalendar month and week of milestones due, filtered.
3. **Script Report "WIP Report":** one row per SO × style × colour × ship-to, columns in the order of `23 OCT WIP DUMMY.xlsx` (COO, factory, order receive, tech pack, BOM, bulk standard, original sample, fabric content, merchant, contract, buyer, category, PO, style, description, wash, colour, order qty, ship to, final qty, delivery, revised delivery, fabric ready at mill, fabric ETD plan / revised / actual, fabric in-house, trim PI date, fit rounds 1–4, PP approval, plan PCD, TOP, PCD, ACD, cut / sew / wash / pack / ship qty (empty until the production phase), shipment mode, fabric YY, fabric ordered, fabric received, ratios, FOB, price). Excel export comes with Frappe.
4. **Number cards and chart:** Late Milestones, Due in 7 Days, Orders At Risk, Infeasible Plans; a chart of milestones by status per week.
5. **Daily job** (`scheduler_events` daily): email owners of milestones due tomorrow and overdue. Optional; never needed for status.

**Agent API:** `get_tna(sales_order)`, `update_milestone(name, revised_date=None, actual_date=None, reason=None)` with the same rules as the form.

---

## 10. Edge cases (each needs a test or an explicit note)

**Requirements**
1. Same style twice on one FR with different seasons or colours (reference FR rows 2 and 3: style 20445 SU27 and FA27).
2. One style, several fabrics (shell + pocketing + lining). Fusing goes on the TR.
3. Same fabric used by several styles. One summary line for the supplier, separate FR lines for traceability.
4. Fabric colour ≠ garment colour (DTM, print names).
5. Units: consumption in yd, FR in m, mill price per yd in RMB, knits in kg. Conversions are exact (0.9144) and kg needs GSM and width.
6. Typed allowance ≠ computed (reference row 1). The system computes; importers flag the mismatch.
7. `#REF!`, `MISSING`, `03D`, mixed date formats in imported sheets: the agent import must reject or flag, never store.
8. Leftover stock claimed twice by two FRs.
9. Garment qty on FR differs from SO (partial FR) or the SO is revised after the FR.
10. Ship-to splits: requirements aggregate across ship-to; T&A splits by ex-factory date.
11. Buyer-supplied trims (Customer Provided MR, no PO, still inspected).
12. Nominated suppliers and buyer-negotiated prices: the supplier comes from the Tech Pack, the PO rate is checked against costing.
13. Size labels per size, thread per colour, buttons with spares, cartons rounded up, pack-size rounding.
14. Contract quantity tolerance (±5–15 %) vs the requisition basis (decision D5).

**Purchasing and receiving**
15. Over-delivery beyond band ("extra fabric will not be taken/paid"), under-delivery, multiple partial receipts against "partial shipments not allowed".
16. Delay penalty on the band edges: 3 days = 0 %, 4 days = 10 %, 11 days = 10 %, 12 days = 25 %, 21 days = 25 %, 22 days = cancel or 50 %.
17. Lab dip or trim approval still pending when the PO is raised (hold, override with reason).
18. Order cancelled after fabric is booked: FR cancel is blocked; a revision to zero flags the liability.
19. Roll list missing, wrong total, duplicate roll numbers, yards vs metres.
20. Intercompany purchase (group fabric company → factory): standard ERPNext; one manual check on the dev site.
21. Currency: RMB PO, USD costing, VND company. Cost check converts with the PO exchange rate.

**Inspection**
22. Lot passes but one roll fails; lot fails on the sample → 100 % re-inspection.
23. Several defects in the same yard (cap 4); holes always 4.
24. Width narrower than CW → consumption impact and FR red flag.
25. Several shade bands in one colour → cut by shade, flag the PP Meeting.
26. Shrinkage above the limit → warn, link to the Bulk Fabric approval (Phase B), do not auto-reject.
27. Ticket length vs actual length (supplier shortage claim).
28. Claim window (45 days) running out.
29. Trims size mix-up is always a fail; trim colour vs approved trim card.

**T&A / WIP**
30. Order received date missing (WIP shows MISSING): fall back to the SO date and flag it.
31. Carry-over style: fit milestones N/A.
32. No wash or no print: those milestones N/A.
33. Plan infeasible on day one.
34. PCD moved by the Factory Allocation after baseline lock: revised dates move, the baseline does not.
35. A source document is cancelled after stamping: actual cleared and recomputed from the remaining documents.
36. Holidays and Sundays.
37. Hosted site with the scheduler off: statuses still correct.
38. Many orders: the WIP Board must page (limit 200 Order T&As per load) and must not run one query per cell. Fetch milestones in one query and group in Python.

---

## 11. Tests (`tests/test_materials.py`, `tests/test_inspection.py`, `tests/test_tna.py`)

Reuse `tests/utils.py` helpers from Phase A/B to make a customer, style, tech pack, contract and submitted SO.

- **FR:** lines from SO; golden 553 × 1.97 × 1.05 = 1143.8805; stock claim cannot exceed free stock across two FRs; kg line without GSM rejected; yd ↔ m conversion; MRs grouped by supplier with the SO link; cancel blocked once ordered; revision raises only the delta and flags a decrease.
- **TR:** labels 1980 and buttons 21,780 golden; per-size rows from SO sizes; DTM resolves to the colour; carton rounding; pack-size rounding; customer-provided makes a Customer Provided MR; hold flag set when the Bulk Trim approval is missing.
- **PO / PR:** hold blocks the PO; manager override passes; quantity bands at 1000 / 1001 / 3000 / 3001 m; extra-qty policies; delay penalty band edges (case 16); cancel reverses roll-ups.
- **Inspection:** points by length; holes = 4; cap of 4 per yard; linear and square formulas (20.0 and 12.63); sampling 1500 m → 450 m; lot pass with one roll rejected; lot fail → re-inspect; batches updated; QI created with the right status; Stock Entry splits accepted and rejected; width-impact maths; trims AQL accept / reject numbers; size mix-up fail.
- **Gate:** Work Order blocked while fabric is not accepted; trims warn only; packaging trims never block; override passes.
- **T&A:** template pick (most specific); forward pass with the seeded offsets; Qty ÷ Daily Output; holiday shift; infeasible flag; N/A rules; each auto-stamp event; cancel clears the actual; baseline lock keeps planned dates; status computed without the scheduler.

---

## 12. Slices (build in this order; stop for review after each)

| Slice | Content | Exit check |
|---|---|---|
| **C0 Foundations** | Settings section, the 7 masters and seeds, custom fields, item setup helper, warehouses created in `after_install` if missing, stock setting for QI after receipt | migrate clean; seeds present; existing 72 tests still pass |
| **C1 Fabric Requisition** | FR, summary, MR creation, revisions, red flags, agent API, print format | FR from a demo SO creates MRs; tests pass; form opened with the `run` skill |
| **C2 Trim Requisition** | TR, quantity maths, Tech Pack explode, customer-provided, hold | same |
| **C3 PO / PR extensions** | Terms on PO, hold check, cost check, ETD fields, quantity bands, delay penalty | PO from MR, PR with over-delivery blocked |
| **C4 Receiving rolls** | Roll list import, batches, bundle | PR with 10 rolls submits; batches carry the roll fields |
| **C5 Inspection** | Fabric Inspection, Trim Inspection, QI, Stock Entry, purchase return, FPT sample type | full path PR → inspection → store; rejected path → return |
| **C6 Status and gate** | Material Status, Running Fabric Stock, gate extension, PP Meeting load, number cards | Work Order blocked then released |
| **C7 T&A / WIP** | 4 doctypes, seeds, planner, auto-stamp hooks, calendar js, WIP Board page, WIP Report, cards, daily job, agent API | an SO walked from FR to QC shows stamped actuals in the grid, Gantt and calendar; screenshots taken |
| **C8 Close-out** | Workspace "Materials" and "WIP" cards, Sales Order Create buttons and Connections (FR, TR, T&A), dashboards, `security-review`, full test run, update this file's status, add Phase C to `CLAUDE.md` folder map and `HANDOFF.md` | all tests pass; review with the user |

C7 does not depend on C3–C6 code except for the stamp hooks. If the user wants the WIP chart sooner, build C7 after C2 and add the purchase and inspection stamps when C3–C5 land.

---

## 13. Decisions for the user (the builder proceeds with the default and records it)

| # | Question | Default |
|---|---|---|
| D1 | Who runs `bench get-app / install-app / migrate` on the hosted site? Without it no phase (A, B or C) reaches it. Fallback if nobody can: move the site to Frappe Cloud (dashboard deploy, no shell), or publish a read-only WIP page outside ERPNext that reads the REST API | Build as an app (no change) |
| D2 | Receive into a quarantine warehouse, then inspect (stock is visible as "in-house, QC pending") vs inspect before the receipt is submitted | Quarantine warehouse |
| D3 | Track every fabric roll as a Batch | Yes |
| D4 | Material gate: fabric Block, trims Warn | As stated |
| D5 | Requisition qty from order qty or from order qty + contract tolerance | Order qty (allowance covers cutting loss) |
| D6 | 4-point basis and threshold | Per 100 linear yards, 20 points (from the fabric contract), per-supplier override |
| D7 | T&A planned forward from order receipt (the company's sheet) or backward from ex-factory | Forward, with an infeasibility flag; template rows can use the Ex-Factory basis |
| D8 | Fabric inspection sampling above 5,000 m (not on the form) | 10 % |
| D9 | AQL values for trims | Percent plan (10 %) until QA confirms the AQL rows |

---

## 14. Out of scope (later phases)

Cutting (bulk marker doctype, lay plans, roll-to-lay allocation by shade band, actual consumption), sewing and line output, washing job orders (the `WASH` sheet), production card and trim card print, packing, final inspection, invoices, customs, receivables, supplier scorecards, debit-note posting for delay penalties.

---

## Status log

(Builder: add one dated entry per slice: what was built, migrate and test output, what was not verified.)
