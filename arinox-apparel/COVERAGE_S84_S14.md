# Does the model cover the real papers? Two orders entered end to end

**Run on 2026-11-05** on a clean ERPNext-only site (Frappe 16.33 + ERPNext 16.34.1, the `arinox_apparel` app **not** installed, developer mode off), after loading the hosted bundle. The papers are from `Arinox AI ERP Documents - 2.zip`. Re-run it with `arinox-apparel/hosted_ingest.sh "<unzipped ARINOX ERP DOCS folder>"`; the code is `arinox_apparel/arinox_apparel/portable/demo/ingest_orders.py`.

"Two companies" was read as the data of **two orders of the Cortex group**, because that is how the zip is organised:

| | Order **S84** | Order **S14** |
|---|---|---|
| Style / colour | C2027-S84-304 classic button-down shirt, Micro Tile Print | C7502-S14-304 (#5160) bias midi skirt, Moonflower Foliage |
| Buyer / brand | EMJ Apparel Group LLC (Belladahl) | EMJ Apparel Group LLC (Cabi) |
| Buyer PO | 69785 / EM92409, **1,462 pcs**, 5 sizes, $16.30 DDP | 70599 / 70601 / 70602, **5,087 pcs** on one contract, 6 sizes, $13.50 DDP |
| Entities | Cortex Vietnam Garment (factory) -> Cortex Fashion (HK) -> EMJ; Cortex Textile FZ (fabric) | same |
| Shipped | 1,520 pcs, 64 cartons, 344.6 kg, LCL, B/L BDN251200184, customs 308078021920 | 5,227 pcs on two POs, 219 cartons, invoice CTXGVN26.05.28 |

## 1. The short answer

The model **covers almost everything on the papers**. Of every value the ingest tried to store, only the items in section 3 had no field. Of the numbers it reconciled to the papers, **all matched except two**, and those two are logic that is not ported yet (section 2). Entering the papers also exposed **three real rule problems** and **one decision** (section 4). It also exposed **bugs in my own first parsers**, which the reconciliation caught (section 7).

Records created from the two orders, with 0 refusals by the site: 2 Tech Packs (190 + 90 measurements, 10 + 12 BOM lines), 2 Cost Sheets, 2 Sales Contracts, 2 Sales Orders (5 and 18 variant rows), 2 Trim Requisitions (5 + 9 lines), 2 Production Cards, 3 Packing Lists (8 + 10 + 9 carton runs), 2 Shipments, 2 Delivery Notes, 4 Sales Invoices (the two legs of each), plus the 3 group companies, the buyer, the HK internal customer, the fabric supplier, the forwarder, the style items and their variants.

## 2. Reconciliation against the papers

| Check | ERP | Paper | |
|---|---:|---:|---|
| S84 order quantity | 1,462 | 1,462 | ok |
| S84 order value | 23,830.60 | 23,830.60 | ok |
| S84 planned cut (each size +5%, rounded up: 284+458+443+235+118) | 1,538 | 1,538 | ok |
| S84 shipped in the ledger | 1,520 | 1,520 | ok |
| S84 packing list pieces / cartons (sum of the carton runs) | 1,520 / 64 | 1,520 / 64 | ok |
| S84 invoice, factory -> HK (1,520 x 6.56) | 9,971.20 | 9,971.20 | ok |
| S84 invoice, HK -> EMJ (1,520 x 16.85) | 25,612.00 | 25,612.00 | ok |
| S14 order quantity / value (3 POs) | 5,087 / 68,674.50 | 5,087 / 68,674.50 | ok |
| S14 shipped in the ledger (1,325 + 3,902) | 5,227 | 5,227 | ok |
| S14 PO 70599 / 70601 delivered | 1,325 / 3,902 | 1,325 / 3,902 | ok |
| S14 buyer invoice (the two S14 POs, 5,227 x 13.50) | 70,564.50 | 70,564.50 | ok |
| S14 contract number kept from the paper | CTXGVN26.01.003 | CTXGVN26.01.003 | ok |
| Tech pack measurements, every number under a size heading (S84 / S14) | 190 / 90 | 190 / 90 | ok |
| Buyer BOM lines (S84 / S14) | 10 / 12 | 10 / 12 | ok |
| **Packing list header: total cartons** | **0** | 64 | **DIFF** |
| **Packing list header: total pieces** | **0** | 1,520 | **DIFF** |

The two DIFF lines are not a model gap: the header totals (cartons, pieces, net/gross kg, CBM, size summary, over/short %) are computed by the Packing List controller, which is not ported. The carton **rows** are stored correctly (they sum to 64 and 1,520). Also not computed on the hosted site, for the same reason: the **Cost Sheet totals** (FOB, margin: the inputs are stored, the outputs stay 0), the shipment status (stays "Planned" although the cargo sailed), and the Delivery Note's T&A stamp.

## 3. Fields the papers carry that the model has no place for

| # | On the paper | Where it should go | Suggested fix |
|---|---|---|---|
| 1 | Tech pack grade sheet: **creation date** and **revised date** | Tech Pack keeps only "received on" | add `created_on_buyer`, `revised_on_buyer` (Date) |
| 2 | Grade sheet: a **section** (SHELL / LINING) that repeats the same POM codes (S14: B220, B325, B339 twice) | Tech Pack Measurement has no section | add `section` (Data); today the section is carried inside the point-of-measure text |
| 3 | Grade sheet: a **date on a row** marks that row as revised (S14: 2026-05-05) | no per-row revision date | add `revised_on` (Date) on the measurement row |
| 4 | Grade sheet: rows with **no POM code** (S84 sleeve cap height; S14 waist elastic, hip placement, sweep, side seam) | accepted (code is optional) | none; works |
| 5 | Trim request: **"HAVE STOCK SO NO NEED TO ORDER" / "NEED TO ORDER"** as words | Trim Requisition Item has `stock_used` (a quantity) and a warehouse, no yes/no | add a Select `stock_decision` (Order / Use stock) or fill `stock_used` with the quantity; decide with the merchants |
| 6 | One **commercial invoice covering several contracts and styles** (S14 invoice also carries EM92428 / C9360) | Sales Invoice has one `apparel_sales_contract` | decide: one invoice per contract, or a contract table on the invoice |
| 7 | PO terms **production lead time 45 days**, **claims within 5 days / cancellation 5 days** (the contract says 60 and 30 days) | no lead-time field; the PO and the contract conflict | add `production_lead_days`; decide which claim period wins (known from the earlier paper trace; not part of this run) |
| 8 | Packing instructions as yes/no flags (price ticket, barcode sticker) | text only | known; unchanged |
| 9 | Customs declaration: HS codes and per-line values on the Vietnamese customs list | Shipment Declaration holds the header only (number, type, channel, packages, gross kg, value, rate) | not entered in this run (the customs workbook was not parsed); add a lines table if you need them |

## 4. What the system did on the real data (rules at work)

1. **The over-ship gate caught a real over-shipment.** S14 PO 70599, size S: **355 shipped against 330 ordered; the 7.5% band allows 354**. The paper process let it through; the ERP stops the Delivery Note until a manager enters a reason. (S84's +3.97% overall and +2.2% to +6.25% by size were inside the band.)
2. **A contract line is style x colour x PO.** The real S14 contract has three lines with the same style and colour, one per PO. The first version of the rule ("one line per style and colour"), which is also what the **dev app enforces today**, refused the real contract. The hosted script now keys on style, colour and PO and has a test. **The app's `sales_contract.py` needs the same change.**
3. **The real S14 contract cannot be signed.** Its paper says *Shipping Marks on the carton: TBA* (and the address cell is `#REF!`). The rule "nothing may be left as a placeholder on a signed contract" refuses it, with the message *Shipping Marks: TBA*. **Decision for you:** keep the rule (and have merchants fill the marks first), or allow "TBA" for the marks until the booking.
4. **The group route works as the papers show it.** One invoice number on two invoices: the factory bills Cortex HK at 6.56, Cortex HK bills EMJ at 16.85 (S84), carried in `apparel_route_leg` 1 and 2. The papers give no exchange rate for the VND and HKD books, so the run **assumed** 25,000 VND and 7.8 HKD per USD (25,000 is the rate the costing sheet uses); a real rate must be entered. The *invoice price above the contract price* rule (16.85 vs 16.30) is **not ported**, so the hosted site currently lets it through.
5. **The measures are kept side by side** on the S84 shipment: packing list 1.597 CBM, booking 1.600, bill of lading 1.910 (the +19.6%).
6. **Per-material exchange rates** are needed: the S14 costing converts the main fabric at 7.3155 RMB per USD but the lining at 8.0. The model keeps a rate per row, so both are recorded as printed.
7. **A cost head was missing.** Every costing sheet charges *Depreciation 2.5%*; there was no such Cost Head. It is data: the ingest adds it. Add it to the app's seeds (`setup/install.py`).
8. **Both production cards show `pilot_required = 1`** (orders of 1,000 pieces or more). Neither order has a Pilot Run record in the sample set, so in the app bulk cutting would wait for a pilot or a manager's waiver. Not exercised on hosted (the pilot gate is not ported).

## 5. Things the site needed that are not model gaps

Fiscal years for 2025 and 2026; ERPNext's over-delivery allowance raised to at least the largest contract tolerance (15%); a USD receivable account per company that books in VND or HKD, set on the customer; an exchange rate on each invoice; the freight forwarder created as a Supplier; "RMB" is the currency code CNY; the three companies with their abbreviations; the sales order dated with the PO date (ERPNext dates a new order today, so a 2025 delivery looked like the past). Mode and trade term share a cell on the paper ("SEA DDP"); the model keeps them apart (mode *Sea*, term *DDP*; the shipment mode is *Sea LCL*).

## 6. Paper types this run did **not** exercise

The two orders do not come with these papers, or the papers in the zip are blank formats or belong to other styles. The model is built to carry them (Phases A to E were built against these formats and tested), but this run does not prove it:

- **Fabric Requisition:** the FR sheet in the trim workbook is a blank layout / another style (J35). No S84 or S14 FR in the zip.
- **T&A / WIP:** a dummy sheet. **Fabric and trim inspection, in-line and final inspection reports, pilot run, PP meeting:** blank formats in the zip, none filled for S84 or S14. So the Final Inspection gate was overridden with a stated reason on both delivery notes.
- **Washing contracts and statements** (folder 9): other orders. **Bulk marker**, **fabric purchase / sales contracts** (the S84 "sales contract" file is the fabric contract Cortex Textile FZ -> Cortex Vietnam), **customs workbooks**, **production card 20445 and trim card**, **production reports**, **operation bulletin R&D**, and the eight other orders' papers.
- **Price negotiation and quotation:** no offers or counters in the zip for these styles.
- **Sample requirements** from the PO (TOP $200 chargeback, customer samples 2 S + 1 L, PP only if asked): read, not entered.

## 7. Corrections to my own work, found by this check

The reconciliation is why these were caught; none is in the delivered app.
- My packing-list reader skipped every carton row (it split at the first size heading); the first run showed `0` carton rows while reporting "no failures". Fixed, and the packing check now sums the rows.
- My first tech-pack reader dropped the rows without a POM code and the lining section; it undercounted S84 by 10 values and S14 by 42, and its own check agreed with it. The check now counts every number under a size heading independently of the reader.
- My generated form scripts mangled the dynamic method names of the Shipment and Purchase Receipt buttons (`arinox_arinox_apparel_shipping`). Fixed, with a guard that refuses to export a mangled name.
- The generated form scripts expected a plain answer from an API script, but an API Server Script returns the whole `frappe.flags`. They now unwrap `frappe.flags.arinox_result`. All 30 pass `node --check`; **they have not been run in a browser.**
- The 12 ported script reports were first run on empty data only. They execute without error; their numbers on real rows are **not verified**.

## 8. Not verified

Nothing here was opened in a browser. Nothing was run against the real hosted site. The Cost Sheet, Packing List and shipment-status calculations are not ported, so their outputs were not checked. The ingest used the sample set's own figures for prices and quantities; bank and account numbers were not read.
