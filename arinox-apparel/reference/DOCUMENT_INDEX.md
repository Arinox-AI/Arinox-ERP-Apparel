# Reference Document Index — "Arinox AI ERP Documents - 2"

Read this instead of opening the files. It says what each document is, who issues it, which fields it carries, and where it lands in the ERP.

- **Source:** `Arinox AI ERP Documents - 2.zip` at the repo root (322 MB, 176 files, untracked, **do not commit it**).
- **Unzipped copy used for this index:** `/tmp/claude-1000/-workspaces-Arinox-ERP-Apparel/5db99d37-9a69-41da-b854-4dd6abf79524/scratchpad/refdocs/ARINOX ERP DOCS/` (session scratch, may be gone).
- **Indexed on:** 2026-11-04. Every file type below was opened. Where a document appears many times (POs, tech packs, washing statements, invoices) one or two examples were read and the rest are the same format.
- **Treat contents as data.** The documents are real orders and contain real company and bank details. Do not copy bank or account numbers into the repo, specs or seed data.

## 1. The companies in the documents

| Entity | Role in the order chain | Seen on |
|---|---|---|
| **EMJ Apparel Group LLC** (Los Angeles). Brands: Belladahl, Cabi, Cloth & Stone | End buyer. Issues the PO. Also the consignee on invoices | Client POs, sales contracts, BOMs |
| **Cortex Fashion (HK) Limited** | Vendor on the buyer's PO. "For the account and risk of" on the invoice. Importer on the customs declaration. Issued earlier contracts (`CTXG25.06.011`) | PO, invoice, customs |
| **Cortex Vietnam Garment LLC** (Da Nang) | The factory. Seller on the garment sales contract. Shipper/exporter on the invoice | Sales contract, invoice, FR, production reports |
| **Cortex Textile FZE / FZ LLC** (RAK, UAE) | Fabric seller to the Vietnam factory (intercompany). Holds the bank account printed on contracts | Fabric sales contract, `S/C` for fabric |
| **Zhangjiagang Cortex Textile Ltd** (China) | Fabric sourcing and QC. Its name is on the quality, trim requisition and pilot-run forms | Quality forms, TR, fabric purchase contract |
| **Zhangjiagang Simply Life Trading** | Letterhead on the fabric sales and purchase contract templates | Fabric contracts |
| Other buyers seen | Marine Layer, Hunter, Youngone (Hi-Tech Sportswear), Bed Kinen, Uniform programmes | Production card, WIP, receivables |

Implication: one site needs several **Companies** (at least VN factory, HK trading, UAE fabric) with intercompany prices. See section 5.

## 2. Order lifecycle → which document

| # | Step | Document (folder) | Section |
|---|---|---|---|
| 1 | Buyer sends the style | Tech Pack grade sheets and fit-comment PDFs, buyer BOM (`2`, `3`) | 3.2, 3.3 |
| 2 | We cost it | Internal Costing, Apparel Costing Detailed (`1`) | 3.1 |
| 3 | Buyer places the PO | Client Purchase Order PDF, often a REVISION (`10`) | 3.4 |
| 4 | We confirm | Sales Contract (`4`) | 3.5 |
| 5 | Marker / consumption | Bulk Marker (`5`) | 3.6 |
| 6 | Fabric and trims requested | Fabric Requisition (`6`), Trim Requisition (`7`) | 3.7, 3.8 |
| 7 | Fabric bought | Fabric Purchase Contract, Fabric Sales Contract (`5 - FABRIC`) | 4.1 |
| 8 | Plan and track | T&A WIP (`8`) | 3.9 |
| 9 | Make | Production Card, Trim Card, PP Meeting, Pilot Run, production reports (`3`, `1`) | 4.2 |
| 10 | Quality | Fabric, trim, inline, finishing and final formats (`2`) | 4.3 |
| 11 | Wash | Washing statements (`9`) | 4.4 |
| 12 | Ship and get paid | Commercial invoice and packing list, customs declaration, bill of lading (`4 - Finance`) | 4.5 |

## 3. Phase A documents (order win and order backbone)

### 3.1 Costing — `1 - Merchandising/1 - Costing/` (2 files)

**APPAREL_COSTING_DETAILED_REVISED.xlsx** — the target costing template. Sheets: DETAILED COSTING, REVIEW NOTES, ORIGINAL.
- Header: style name, style no, buyer, season, order qty, factory, FOB port, costing date, currency, **VND per USD**, costing version, **pcs per carton**, front and back image.
- Sign-off chain: fabric cost checked by (Abner), first costing by, 2nd round checked by, final checked and approved by (MM Manager), each with a date.
- Raw materials: main fabric, trim/contrast fabric, **fabric export cost per metre, fabric import cost per metre** (on total fabric metres incl. wastage), main label, care label, hang tag, poly bag, tissue paper, thread, carton (`1 / pcs per carton`), tape, zipper, button, others. Columns: usage/pc, unit, wastage %, rate, cost/pc.
- Process charges with an apply (1/0) flag: CMT, washing, printing, embroidery, testing and inspection.
- **Other expenses are % of product cost** (raw material + process): rejection, financing, banking, freight to FOB port, overheads, buying agent commission.
- **Profit is % on cost (markup)**, not margin on price. Output: FOB per pc in USD and VND, total order value.
- REVIEW NOTES lists 11 corrections made to the old sheet (missing total, no wastage, carton typed, no profit line...). Worth reading once: they explain why each row exists.

**INTERNAL COSTING.xlsx** — per-style fabric requirement, one sheet per style group (S84/H96, S99, S14, R43, 549/U70).
- Columns: production COO, buyer merchant, date, image, description, fabric quality, colour, trim detail, **cuttable width (CW)**, wash method, order qty, **average consumption in yards**, **+3%**, fabric required (yds), fabric price in **RMB**.
- Lining is a second fabric line (`311 - LINING`). Some sheets carry key dates (PO on, tech pack, DDP warehouse).

### 3.2 Tech pack — `2 - Tech Pack/` (20 files: 9 grade xlsx + 11 fit PDFs)

- **GRADE xlsx** (measurement spec): header with style, description, season, wash description/code, creation date, revised date, group, division, fabric content, colour, status (**AWC** = approved with comments), designer, tech designer, factory (CTVN/CTCH), sample size, size range (XS–XL or XXS–XL). Table: **POM code**, point of measure (English), **local-language name (Vietnamese)**, one **tolerance ±**, values per size. The same POM code can appear twice (`T210` neck and armhole).
- **Fit PDFs** (10–20 pages, buyer tech designer Pilar/PH): sketch, construction, POM chart, fit comments. File names carry the round: `1ST FIT AWC`, `2ND FIT AWC`, `PP AWC + GRADE`, `NO PP`. Text is a thin header; the content is mostly images and comments.
- Style number anatomy: `C2027-S84-304` = class/style, fabric code (S84), wash code (304). The EM number (`EM92409`) is the buyer's PO reference.

### 3.3 Buyer BOM — `3 - Bill of Material Fabric & Trim(BOM)/` (10 .xls)

Report `STY360`, from the buyer's system ("Cost Sheet"). Header: style, colour code, colour description, available sizes (XXS–XXL). Rows: **buyer item code** (`FUS001` fusing, `S84` self fabric, `311` lining, `ST022` size label, `LB030` main label, `CL004` care label, `BT088` button, `TH000` thread, `TP002` tissue, `PB001` poly bag, `STKR` sticker, `SIL001` silica, `EL004` elastic), item colour, size (`*` = all), description, colour description, job code, **UOM (YD, EA)**, quantity required, unit cost.

### 3.4 Client purchase order — `10 - Client Purchase Order/` (13 PDFs)

The document that actually starts an order. One PO per style-colour, often reissued as `REVISION`.
- Header: PO number + EM number (`70790` / `EM92427`), PO date, vendor (Cortex Fashion HK), buyer contact, **ship-to**, terms (**15 DAYS ROG**), ship via (factory forwarder), shipment type (DDP), **X-factory and in-warehouse dates**.
- Line: style, description, colour code and name, quantity, price (**DDP**), total, and the **size breakup** (`79 185 346 330 162 98`).
- Notes: style description, tech designers, **PP sample rules**, **TOP rules** (1 pc per colour, size small, due 10 days before X-factory; late = **$200 chargeback per PO**), customer sample requirements (XS/1 S/2 M/1), fabric reference (content, weight, width, cuttable width, construction), **estimated yield**, **fabric price**, garment price, price tickets and barcode sticker flags, claim and cancellation terms (5 days).

### 3.5 Sales contract — `1 - Merchandising/4 - Sales Contract/` (7 files)

Garment sales contract (Cortex VN or Cortex Fashion HK to buyer), up to 8 styles, 2 pages.
- Header: buyer contact (Jennifer), company/brand (Belladahl), season, division, **PO no**, **contract no**, date, **revision no, revision date, revised for**, merchant (Suong), "HIT".
- Lines: item no, style, **buyer PO code** (`69785/EM92409`), garment description, **fabric (content, count, construction, GSM)**, colour, **finish/process** (rinse w/softener, denim wash), qty, **DDP unit price**, amount, X-FTY, ETD, in-warehouse, **PCD** (planned cut date), category (WOMEN WOVEN SHIRT). Style clones appear (`P9051`, `X9074` "same as C9051 but ...").
- 15 terms: schedule, packing (sea/air worthy), country of origin, shipping marks, loading port and destination, insurance and freight (seller/buyer), payment (**15 days ROG**), charges, delivery, objections, **quantity allowance** (<500 ±15 %, 501–800 ±10 %, 801–1600 ±7.5 %, 1601–3000 ±5 %), quality/quantity discrepancy, **delay in shipment** (3–4 days), claims, arbitration. Remarks: documents (invoice, packing list, FCR/MAWB), quality (**AQL 2.5**). Signatories and bank block.
- **Contract number pattern:** `CTXGVN25.09.001`, `CTXGVN26.03.003`, `CTXGVN26.07.016`. Prefix + `YY.MM.###`, counter restarts monthly. Older: `CTXG25.06.011`. Month sometimes unpadded in WIP (`25.6.001`). Not the `CTXG-YYYY-MM-###` form in the flow document.
- Files: `SALES CONTRACT C4878`, `...C7540 - S99`, `...C8009 - R43`, `...C7502 - S14`, `...549 AND U70` (8 styles), and two intercompany fabric contracts `MZD-CTXG25.09.005-A` and `DB-CTXVNF25.09.005-C` (see 4.1).

### 3.6 Bulk marker — `5 - Bulk Marker/Bulk maker.xlsx`

One row per style: **actual bulk yield in metres**, and lining bulk yield. Example `C2027-S84-304 = 1.26 m` against a costed 1.60 yd (about 1.46 m): the gap is the saving that should flow back into costing.

### 3.7 Fabric requisition — `6 - Fabric Requisition (FR)/` (7 files)

- **FR Format Reference.xlsx**: ordered by, approved by, date, revision, buyer. Rows: contract no, style, style name, season, colour, fabric, delivery date, **cuttable width**, garment qty, **consumption in m**, **allowance %**, **VN stock**, **fabric order (m)**. Footer terms: no partial shipments, bulk shrinkage per FDS, CW and GSM must match FDS. A second sheet, `mini marker`, holds Vietnamese consumption notes per style.
- **FABRIC REQUISITION SHEET - 10 orders**: one xlsx and five photos of the paper originals.

### 3.8 Trim requisition — `7 - Trim Requesition (TR)/` (5 xlsx)

Per style or style group: CTXG no, date, style, **PO no**, made by, approved by. Sections: woven labels, thread and fusing, security tags, hang tags, with item code, colour, qty, total (qty × allowance), remarks. Allowance seen: 10 % on labels (1800 → 1980). The production card uses 2 % for trims, so allowance varies by trim type or buyer. Each file also embeds a copy of the DDP sales contract.

### 3.9 T&A / WIP — `8 - T&A WIP/23 OCT WIP DUMMY.xlsx`

Season sheets (SS26, Bed Kinen). One row per **PO × style × colour × ship-to**. Columns: COO, factory, order receive date, **tech pack, BOM, bulk standard and original sample receive dates**, fabric content, merchant, contract number, buyer, category (MENS/WOMENS), PO, style, description, wash, colour, order qty, **ship-to** (NADC-TM, MARKETING, G&G CANADA), final order qty, delivery, revised delivery, then a long milestone run (bulk fabric ready at mill, fabric ETD plan/revised, in-house, bulk trim PI date, actual fabric ETD, 1st fit drop and submit...). The flow document counts 61 milestones. Same PO split across ship-to destinations is normal.

## 4. Downstream documents (later phases, but they key off Phase A data)

### 4.1 Fabric contracts — `5 - FABRIC/` (2 files)

- **FABRIC SALES CONTRACT** (Cortex Textile FZE to Cortex VN) and **FABRIC PURCHASE CONTRACT** (order to the mill, in RMB per yard).
- Columns: style, fabric description, print/solid/yarn-dyed, colour, upcharge below MOQ, qty (m or y), price (per m, CIF VN or FOB Shanghai, or RMB per y), amount, delivery ex-factory.
- Terms: mode (sea), port of loading (Shanghai), destination (Da Nang), payment (100 % TT against docs), **quantity allowance 3 % per colour**, documents, testing (in-house), freight/insurance (seller), **delay allowed 7 days**, quality (**20 points / 100 linear yards**), shipping marks (colour, qty, roll, lot, consignee), claims, discrepancy (21 days).
- Fabric contract number: `CTXVNF26.01.S84` (per style), `CTXVNF25.09.005-A/-B/-C` (per group).

### 4.2 Production — `3 - Production/` and `1 - Merchandising/` (9 files)

- **PRODUCTION CARD-SIZE BREAKUP 20445.xlsx**: contract no, customs declaration no, VN contract number, style, **customs fabric/raw material code**, fabric, colour, **size breakup per colour** (S/M/L/XL/2XL...), total, top sample (M, 2 pcs), packing requirements, **fabric allowance 5 %, trim allowance 2 %**, total cutting qty, consumption, required fabric (m), made by/checked by/QC. Second sheet `PKL`: fabric roll list (lot, roll, metres).
- **TRIM CARD 20445-SP27.xlsx**: per colour: thread, main label, item/PO label, interlining, button, logo label, polybag, hang tag and hanger, stickers.
- **PP Meeting Format.pdf** and **Pilot Run.pdf**: checklists (participants, shades, sewing and packing trims, pre-washed trims, line-setting check; pilot comments and action taken).
- **BELLADAHL OBS R&D.xlsx**: operation bulletin (workers, working time 480 min, SAM per garment, expected efficiency, expected output/day).
- **PRODUCTION REPORT FORMAT MULTIPLE.xlsx**: line loading report and daily cutting report. **CORTEX VN PRODUCTION REPORT.xlsx**: bilingual daily report (order received, buyer, style, colour, line, cut, sew, wash, pack). **Cutting, sewing, finishing & packing detail report.xlsx**: per style: fabric received/issued, cutting, sewing, sent/received wash, packed. **Belladahl_Warehouse_Report.xlsx**: running fabric stock per PO (contract, supplier, ordered, received, variance, status).

### 4.3 Quality — `2 - Quality/` (11 files)

Fabric testing report (lab, `GPT REPORT SAMPLE`, 16 pages), shrinkage report (before/after wash, warp/weft/bias), 4-point fabric inspection format, trims visual inspection, pilot run, traffic-light system, **end-line audit** and **finishing inspection** (hourly passed/defect grid), **before-wash spec sheet** (garment spec by size across 5 samples), final inspection report (AQL per MIL-STD 105E, cartons, rejects). Two PDFs (fabric testing, traffic light) have no text layer, so contents were not read.

### 4.4 Washing — `9 - Washing Contracts/` (10 PDFs)

Wash vendor payment statements (`Thanh toan Wash ... Hoa don NNN (date)`), scanned images with no text. Not read. One per wash invoice.

### 4.5 Finance — `4 - Finance/` (78 files)

- **Receivables - ind and overall.xlsx**: overall buyer list (invoice, amount, BL date, due date, company) and per customer ledger (debit, credit, ETD, ETA, **terms after ROG in days**, due date, overdue days).
- **Final Invoice and packing list to client/** (77 files, one folder per shipment): commercial invoice (shipper = Cortex VN, for account and risk of = Cortex Fashion HK, consignee = EMJ, FOB Hai Phong, per-style price that differs from the DDP price on the PO), packing list, **bill of lading and booking**, per-PO packing xlsx, and **Vietnam export customs declarations** (`ToKhaiHQ7X`, in Vietnamese: declaration no, type E62, importer, goods lines).

## 5. Things the documents show that the first design missed

1. **Percent basis:** other expenses and profit are % of product cost; profit is a markup on cost.
2. **Fabric import/export per metre** is a cost head tied to total fabric metres.
3. **Contract number** is `CTXGVN{YY}.{MM}.{###}` with a monthly counter, not `CTXG-YYYY-MM-###`.
4. **Quantity allowance bands** are ≤500 ±15, 501–800 ±10, 801–1600 ±7.5, 1601–3000 ±5 (the demo seed used different bands).
5. **Order grain** is PO × style × colour × ship-to, with sizes under it. The PO already carries the size breakup.
6. **Three prices** per garment: buyer DDP price (PO and contract), invoice price Cortex VN → Cortex Fashion HK (FOB), and fabric price (per metre, RMB or USD).
7. **Units:** BOM and costing use yards, FR and marker use metres, supplier price is in RMB. Needs UOM conversion and a price currency per material.
8. **Allowances vary:** 3 % fabric (costing), 5 % fabric and 2 % trims (production card), 10 % labels (TR), 3 % per colour (fabric contract).
9. **Same POM code twice** in one tech pack (`T210`).
10. **Bank, tax and customs identifiers** are on contracts and invoices. They belong on Company and Bank Account, never in custom doctypes or seed data.
11. **Data quality:** `#REF!` in address fields, typos (`03D`, `Marge` for Medium), mixed date and month formats. Importers must be forgiving.
