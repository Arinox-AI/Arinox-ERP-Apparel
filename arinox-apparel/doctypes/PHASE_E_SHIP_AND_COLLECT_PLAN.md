# Phase E — Ship and Collect: Packing → Final Quality Inspection → Export Shipment and Freight → Invoicing → Payment Follow-up → Claims and Commercial Close

**Status:** Plan written 2026-11-05, then **built the same day on the dev site (E0 to E7 in a reduced, reuse-first form; E8 close-out only partly)**. Read the **Status log at the end** first: it lists what was built, what differs from this plan, and what is not built or not verified. Where this plan and the status log disagree, the status log is right.
**Module:** Arinox Apparel
**Spec form:** one consolidated spec for the phase, same as Phases B, C and D.
**Written for:** the builder who implements it slice by slice, and the user who reviews it. Everything the builder must decide is decided here or listed in section 15 with a default.

**Relation to Phase D.** Phase D's plan already designed Packing (slice D7, section 10.2) and Final Inspection (slice D8, section 10.3). **This plan adopts those designs unchanged unless a section below says otherwise**, and adds what Phase D left out of scope (section 16 of that plan): commercial invoice, customs declaration record, bill of lading, freight booking, freight cost, payment follow-up and buyer claims. D9 (close-out) is merged into E8. D5 (subcontracting) and D6 (finishing) are **prerequisites** (section 2).

**Sources**
- Company documents opened for this plan (zip extracted to the session scratchpad, read with the `xlsx` and `pdf` skills, nothing copied into the repo):
  - `4 - Finance/1 - Final Invoice and packing list to client/`: shipments `C2027-S84` (sea LCL), `C4878-H96` (sea, 4 POs on one invoice), `C9307 - C9051` (one shipment split over two export invoices and two declarations), `C8009-R43` (air), `C7502-C4825-C9307` (two competing forwarder quotes). In each: the commercial invoices (`INV`), packing summaries (`PS`), per-PO packing lists (`PL`), the customs-format invoice and packing list (`INV_PKL`), booking notes, bills of lading, the air waybill, the forwarder warehouse entry order, the export customs declaration (`ToKhaiHQ7X`), the customs release list (`DS`), the port fee notice (`Mau_01_TBNP`), and the sea DDP, air DDP and second forwarder quotations.
  - `4 - Finance/Receivables - ind and overall.xlsx` (overall list and per-customer ledger).
  - `1 - Merchandising/4 - Sales Contract/SALES CONTRACT C4878.xlsx` (payment, claims, quantity allowance, documents).
  - `2 - Quality/8 - Final Inspection Report.pdf`.
- ERPNext v16.34.1 source (paths cited inline) and the built app (Phases A to D4).
- Web checks (secondary sources, cross-checked; the builder re-verifies anything marked *verify*): US Importer Security Filing is due 24 hours before loading at the foreign port (19 CFR 149); UCP 600 art. 14: presentation within 21 calendar days after shipment if the credit is silent, bank examination up to 5 banking days; US MPF is 0.3464 % with yearly min/max (FY2026 $33.58 / $651.50, **FY2027 from 2026-10-01 $34.58 / $670.86**), which is why no fee number goes into code.

---

## 0. Read this first (for the builder)

1. Read `../CLAUDE.md`, then `../skills/frappe-doctype/SKILL.md` (again before each doctype), then `PHASE_D_PRODUCTION_PLAN.md` sections 3, 10, 11 and 12 and `PHASE_D_BUILD_STATUS.md`. Phase E reuses Phase D's patterns: the Production Movement ledger and `Flow`, settings not hard-coded rules, manager override with a reason, whitelisted agent API with permission checks, T&A stamps that never raise, tests per slice.
2. **Nothing is tied to one company, buyer, forwarder or country.** Group structure (factory company, trading company), price layers, payment bases, document lists, filing rules and fees are **configuration** (masters and settings). Code never names a company, buyer, forwarder, port, bank or country.
3. **Never copy bank, tax, customs, B/L, container or contract identifiers** from the reference files into code, seeds, tests or specs. Tests use invented identifiers. Quantities, prices and amounts from section 13 may be used as golden numbers.
4. **Money is computed on the server.** Invoice amounts, freight amounts, deductions and claim caps are recalculated in Python; the client only displays.
5. **ERPNext owns the books.** Phase E creates ERPNext Sales Invoices, Purchase Invoices, Payment Entries, Journal Entries and Credit Notes. It never writes GL or Payment Ledger rows itself and never edits a submitted accounting document with `db.set_value`. Anything that hits the accounts is created **as a draft** unless a setting says otherwise; the accountant submits.
6. Build slice by slice (section 14). Each slice ends with `migrate`, tests passing, a browser check with the `run` skill, `code-review` at medium, `simplify`, a status note at the end of this file, and a stop for user review. Never commit or push. Never touch the hosted site. Never edit `erpnext/`.
7. Prints are English, global, labels through `_()` (Phase D decision D9). Arinox prints use the orange (`#e8590c`) and black header.

### Skills and tools

| When | Use |
|---|---|
| Before any doctype, controller, hook, fixture, patch | `frappe-doctype` (`arinox-apparel/skills/frappe-doctype/SKILL.md`) |
| Re-reading an invoice, packing list, quote or receivables workbook, or building test data from one | `xlsx` skill; extract the zip into your scratchpad, run Python with `-I` using `/workspaces/frappe-bench/env/bin/python` (it has `openpyxl`, `xlrd`, `pdfplumber`, `pypdf`) |
| B/L, booking, AWB, quotes, final inspection form | `pdf` skill (`pdfplumber`); page 2 of the AWB has no text layer: render it and look at it |
| AQL table (E2) | `WebSearch` two independent ISO 2859-1 Table 2-A sources; every seeded number must match both |
| Any chart, stat tile or board (collections ageing, shipment board, freight variance) | `dataviz` skill **before** chart code |
| Every desk form, dialog and print | `run` skill: open the form, use the buttons, take a screenshot. Specifically: Packing List (Generate Cartons), Final Inspection (Pick Cartons), Export Shipment (Prepare Documents, Make Delivery Note), Commercial Invoice print, Receivable Follow-up, Buyer Claim |
| End of every slice | `code-review` (medium), then `simplify` |
| E8 | `security-review` (whitelisted methods, permissions, every amount field) |
| Pattern used a fourth time (override-with-reason block, ledger posting) | Add it to `skills/frappe-doctype/SKILL.md` instead of copying it again |

Bench: `/workspaces/frappe-bench`, site `apparel.localhost`. After a Codespace restart: `docker start apparel-mariadb apparel-redis`.

### Glossary (new terms)

| Term | Meaning |
|---|---|
| Invoice route / leg | The chain of sellers between the factory and the buyer. A *direct* route has one leg (factory → buyer). A *trading* route has two (factory → group trading company at a transfer price, trading company → buyer at the order price) |
| Transfer price | Price on the intercompany leg (here FOB port of loading) |
| Commercial invoice number | The number printed on the invoice. In the reference documents **every leg prints the same number**, so it is stored as a field, not as the ERPNext document name |
| Export Shipment | One physical movement booked with one forwarder: one house B/L or house AWB, one or more packing lists, POs and invoices |
| Booking / cut-off | Forwarder space confirmation; the last time cargo can reach the CFS or airport warehouse |
| CFS / LCL / FCL | Container freight station / less than container load (shared container) / full container load |
| HBL / MBL, HAWB / MAWB | House (forwarder) and master (carrier) bill of lading or air waybill |
| Telex release / surrendered B/L / sea waybill | No original paper B/L travels; the carrier releases on the shipper's instruction |
| On-board date | Date the goods were loaded; the "shipment date" for L/C and for ship-date payment terms |
| ROG | Receipt of goods at the buyer's warehouse; a payment basis ("15 days ROG") |
| W/M, chargeable weight | Sea LCL bills by the greater of weight (tonnes) and measure (CBM). Air bills by the greater of gross and volumetric weight (L × W × H cm ÷ divisor, 6,000 common) |
| ISF | US Importer Security Filing, due 24 h before loading for ocean cargo; one example of a destination filing rule |
| Deduction | Amount the buyer withholds from a payment: bank charges, chargeback, claim, discount |
| Chargeback | A fixed penalty in the buyer's PO terms (the reference PO: $200 per PO for a late TOP sample) |

---

## 1. Flow

```
Finishing A-grade (D6) ──► Packing List (cartons, SSCC)  ──►  Final Inspection (AQL, cartons picked from the packing list)
                                    │                                   │ Accepted (ship gate)
                                    ▼                                   ▼
        Freight Quotes ──► Export Shipment: booking, cut-off, packing lists, document checklist, destination filing
                                    │  Prepare Documents: commercial invoice drafts per leg, number reserved
                                    │  Export declaration recorded (number, FOB value, cartons, weight checked)
                                    │  Make Delivery Note ──► DN submit: ship gate, SHIPPED in the ledger, EX_FACTORY
                                    │  B/L or AWB recorded (on-board date) ──► invoices submitted (due dates now exact)
                                    │  Forwarder invoices ──► freight actual vs estimate, allocation per order
                                    ▼
          Receivable Follow-up (one per customer invoice): expected due date, reminders, promises, disputes
                                    │  Payment Entry (with deductions) ── intercompany receipt if paid to another group company
                                    ▼
          Buyer Claim / Chargeback ──► Credit Note ──► Commercial Close of the order
```

---

## 2. Prerequisites (slice E0) and why

**Packing cannot post today.** `PACKED ≤ FIN_A − SAMPLE_OUT − PACKED` ([flow.py:120](../arinox_apparel/arinox_apparel/production/flow.py#L120)); `FIN_A` is limited by `FIN_IN` (line 119); `FIN_IN` is posted only by the **Finishing Receipt** (D6, not built); for a style with a garment process (wash) `FIN_IN` is limited by the process's `SC_BACK_GOOD`, posted only by the **Subcontract Return** (D5, not built). **Every style on the reference contract is washed** ("Rinse W/softener"). So:

1. Run the whole suite and fix `test_sewing` (Phase D build status, section 9). Nothing else starts until it is green.
2. Build **D6** as designed (Finishing Receipt, Needle Detector Log, label count). It is small and needed by every style.
3. **D5 (subcontracting)**: decision P4. Default: build D5 before E1. Without it a washed style can reach packing only through Production Adjustments, which defeats the ledger.

---

## 3. Findings from the company's documents (design inputs)

**Invoicing**
1. **Two invoices per shipment carry the same number.** Factory company → trading company at FOB (e.g. 6.56 a piece), and trading company → buyer at the DDP order price (16.85). ERPNext names must be unique per doctype, so the printed number is a field `apparel_commercial_invoice_no`, unique per (company, number), and both legs share it.
2. **A third price appears on a third copy of the same invoice number.** The export-customs invoice (`INV_PKL`) and the export declaration show FOB 6.55 / 7.28 / 9.10 (total USD 86,300). The sheet titled "for BEE FWD" (the forwarder) shows 4.20 / 4.91 / 6.14 for the same goods and the same invoice number. **The ERP will not support different prices on copies of one invoice.** Each leg prints from its submitted invoice. If a separate value is legitimately needed for a destination entry, it is a recorded figure with a basis and an approver (decision P3). The user should confirm the basis of the 4.20 price with their customs broker.
3. **The invoice number looks like a date but is not the invoice date.** `{prefix}{YY}.{MM}.{DD}`: `…25.12.23` on an invoice dated 2025-12-20 (sailing 12-26); `…26.01.14` dated 2026-01-13 (sailing 01-17). A **split** shipment adds a suffix: `…26.06.18` and `…26.06.18-A`, each with its own export declaration but one booking. Numbering is decision P2. Default: suggested from the planned cargo-ready date, editable, unique per company, with automatic `-A`, `-B` on a clash.
4. **One invoice covers many POs, styles and contracts** (4 POs, 3 styles, 12,234 pieces; the receivables ledger has one invoice for three contracts). Invoice lines are per PO × style (the customer copy) with colour and size only on the packing list.
5. **The invoice price can differ from the contract price.** C2027: contract DDP 16.30, invoice 16.85 (+3.37 %). An invoice line must equal the Sales Order rate; a changed price goes through ERPNext's *Update Items* on the Sales Order first (versioned), never by editing the invoice.
6. **Shipped quantity can exceed the contract by more than the allowance.** C4878: contract 1,700, invoiced 1,846 (+8.6 %; the 1,601–3,000 band allows ±5 %). C9502: contract 1,412, invoiced 2,000 (+41.6 %, almost certainly a later PO revision). Over-shipment is checked against the **latest** Sales Order quantity and the contract band (Phase D rule D10), at the Delivery Note.
7. **Sample shipments are invoiced** (4 pieces, $46.80) and appear in the same receivables ledger; courier charges are re-billed to buyers. Both need a route without a production card.
8. **Bank details on the invoice belong to the selling leg's company.** The garment contract prints a bank account of a third group company (UAE), while the invoice prints the trading company's (HK) account. A payment can arrive in a group company that did not issue the invoice (section 10.5).

**Packing list and shipment**
9. Three packing-list levels exist: **per PO detail** (carton ranges × colour × size, which is the Phase D Packing List), **shipment summary per PO** (cartons, net, gross, CBM, carton dimensions), and the **customs format** (per style and PO: cartons, CBM, pieces, net, gross, totals). All three print from the same records.
10. **Carton ranges contain errors**: a sheet lists `103~124` (22 cartons) then `124~127` (3 cartons): carton 124 twice, and `124~127` is 4 numbers, not 3. Ranges must be contiguous, non-overlapping, and `count = to − from + 1`.
11. **Measurements differ between documents**: C2027 CBM 1.596672 on the packing list, 1.600 on the booking, **1.910 on the B/L** (+19.6 %, carrier re-measured); gross weight 344.6 matches everywhere. The air shipment: booking 600 kg, AWB **621.00 kg**, customs **622.5 kg**. The ERP keeps declared (packing list), booked, carrier and customs figures side by side and warns on a difference above a setting. It does not overwrite one with another. Freight is billed on the carrier figure.

**Freight**
12. **Two forwarders quote the same shipment** (sea DDP LCL 7.3 CBM: one totals USD 2,378.90, the other USD 2,731 "estimated" plus duty and fees). Charges come in three groups (origin, main freight, destination), with units per CBM, per kg, per HBL, per container, per pallet or per shipment, plus minimums and maximums, "at cost" lines (duty, MPF, HMF), validity dates, "VAT 8 % excluded" or "included", and "quoted in USD, settled in local currency". One quote bills a per-CBM line on 4.0 CBM instead of 7.3: quote lines need a check that the quantity matches the basis.
13. **Freight terms**: the contract says freight and insurance are paid by the factory company and shipment is DDP. The DDP quotes are addressed to the factory company. The factory → trading invoice is FOB. **Which company carries the freight cost** is decision P1b.
14. **Air is used** (75 cartons, 621 kg, two flight legs). Air chargeable weight here is gross (volumetric 573.75 kg is lower). Air is often a late-shipment remedy, so the reason and who pays are recorded.
15. **The B/L is surrendered, freight prepaid, "zero originals", LCL CFS/DOOR**, with a container number and a delivery agent at destination. The forwarder warehouse entry order and the customs release list show cartons and gross weight again.
16. **The export declaration** carries: number, type code, registration date, status (cleared), inspection channel, invoice number, invoice value and basis (FOB, USD), customs exchange rate, gross weight, package count, HS code per line. The design records these generically as "Export Declaration" rows. No country logic.
17. **Country-specific fees** (a seaport infrastructure fee notice of about 42,653 local currency) are just shipment cost rows.

**Payment**
18. **The due-date basis is inconsistent.** The ledger column says "terms after ROG", the line text says "NET 30 DAYS against the ship date", and the dates are **ETD + 30** (2026-03-26 → 2026-04-25; overdue 131 days on 2026-09-03). The contract says "15 DAYS ROG". The basis must be explicit per contract and visible on every follow-up.
19. **Partial and unallocated payments**: "TT PAYMENT RECEIVED 5,768.90" against 37,483.70 of invoices; a bank reference string sits in the invoice field of the overall list. Receipts need allocation per invoice, bank charges and a reason for every short payment.
20. **The receivable sits in the trading company**, not the factory.

**Claims and quality**
21. **Contract claim windows**: quality claims within **60 days**, quantity claims within **30 days** after clearance at destination; claims are **capped at the CIF value** of the goods; defective goods are returned at the seller's cost if required. These fields already exist on Sales Contract (`quality_claim_days`, `quantity_claim_days`).
22. **The final inspection form** (Phase D finding 15) adds a disclaimer that the inspection "does not release the buyer or seller from contractual responsibilities", so an accepted inspection does not close the claims window.

---

## 4. What ERPNext already has, and how it is used

| Need | ERPNext object | Decision |
|---|---|---|
| Customer invoice, intercompany invoice | **Sales Invoice**; inter-company: internal customer + `make_inter_company_purchase_invoice` (`accounts/doctype/sales_invoice/sales_invoice.py:2650`) | **Reuse**. A Sales Invoice linked to a Delivery Note or Sales Order must have the **same customer and company** (`validate_with_previous_doc`, same file, lines 1099–1118); this shapes section 9 |
| Incoterm, named place | **Incoterm** master; `incoterm`, `named_place` on Delivery Note and Sales Invoice | **Reuse** (Sales Contract already links Incoterm) |
| Payment terms | **Payment Terms Template**; `due_date_based_on` options are only *invoice date*, *end of invoice month*, *months after end of month* (`accounts/doctype/payment_term/payment_term.json`) | **Reuse for invoice-date terms.** B/L date, ETA and ROG bases are handled by section 10.1 |
| Due date after submit | `Sales Invoice.due_date` and `Payment Schedule.due_date` are **not** `allow_on_submit`; Payment Ledger Entry stores its own `due_date` | **Never edit.** Invoices are submitted once the basis date is known (B/L), and ROG is tracked as an *expected* due date on our follow-up (10.1) |
| Receipts | **Payment Entry** (multi-currency, deductions table, exchange gain/loss), **Payment Reconciliation**, **Unreconcile Payment** | **Reuse**. Our code only proposes deduction rows with reasons |
| Reminders | **Dunning** + **Dunning Type** (levels, letters, overdue payments from invoices; `create_dunning` in `sales_invoice.py:3161`) | **Reuse** for reminder letters; our follow-up decides when |
| Statements | **Process Statement Of Accounts** | **Reuse** (configuration) |
| Ageing | **Accounts Receivable** report | **Reuse** for the books; our *Collections* report adds expected due date, basis, promises and disputes |
| Credit note / debit note | Sales Invoice `is_return`, Purchase Invoice `is_return` | **Reuse** for claims and chargebacks |
| Payment received in another group company | **Inter Company Journal Entry** | **Reuse** (10.5) |
| Forwarder bill | **Purchase Invoice** with service items | **Reuse** + custom field `apparel_export_shipment` |
| Parcel shipment | **Shipment** (`stock/doctype/shipment`): pickup and delivery addresses, parcels, courier service, AWB, tracking | **Not used for sea or air freight**: no ports, vessel or flight, booking, cut-off, B/L, containers, ETD/ETA, customs, or several packing lists. Replaced by **Export Shipment**. (Could still be used for courier samples later) |
| Landed cost | **Landed Cost Voucher** | **Not used**: it values *incoming* stock; export freight is a selling cost |
| Bank Guarantee | Bank Guarantee | Not an L/C; not used |
| Packing | Packing Slip | Not used (Phase D section 2) |

---

## 5. Settings, masters, roles, custom fields (built inside each slice that needs them)

### 5.1 Apparel Settings: new section "Shipping and Collections"

| Field | Default | Used by |
|---|---|---|
| `final_min_packed_pct` | 80 (Warn below; Block below 50) | E2 readiness |
| `reinspection_limit` | 2 (a 3rd needs Production Manager + buyer approval reference) | E2 |
| `measure_variance_warn_pct` / `weight_variance_warn_pct` | 5 / 2 | E3 (finding 11) |
| `air_volumetric_divisor` | 6000 | E3, E5 |
| `sea_wm_kg_per_cbm` | 1000 | E5 |
| `rog_buffer_days` | 5 (ETA + buffer = expected ROG until delivery is recorded) | E6 |
| `commercial_invoice_pattern` | `{prefix}{YY}.{MM}.{DD}`; prefix from Company `apparel_contract_prefix` | E4 |
| `submit_invoices_on` | `On-board date recorded` (alternatives: `Manual`, `Delivery Note submit`) | E4 |
| `auto_submit_accounting` | 0 (drafts) | E4, E5, E7 |
| `freight_estimate_variance_pct` | 10 | E5 |
| `reminder_days_before_due` | 7 | E6 |
| `escalation_days` (child: days overdue → action, role) | 1 → reminder, 15 → Dunning level 1, 30 → level 2 + manager, 60 → management | E6 |
| `claim_requires_evidence` | 1 | E7 |

### 5.2 New masters

- **Invoice Route** (per customer, optional per brand; one default): `customer`, `brand`, `is_default`, child **Invoice Route Leg** (sequence, `seller_company`, `buyer` (Customer: the internal customer for leg 1 of a trading route, the end buyer for the last leg), `price_basis` (Sales Order Rate / Price List / Cost Sheet FOB), `price_list`, `incoterm`, `named_place`, `receiving_bank_account` (Link Bank Account; printed), `print_format`, `copy_for` (Data, e.g. "forwarder", "buyer", "customs")). Validation: last leg's buyer is the route's customer; legs chain (leg *n* buyer is the internal customer of leg *n+1* seller); seller companies differ; an internal customer exists for each intercompany leg (ERPNext `is_internal_customer` + `represents_company`).
- **Freight Charge Code** (seed: DOC, THC, CFS, EBS, DDC, AMS, ISF, TELEX, TRUCKING, OCEAN FREIGHT, AIR FREIGHT, X-RAY, CUSTOMS CLEARANCE, HANDLING, DELIVERY, DOC TURNOVER, FORKLIFT, TERMINAL FUEL, STORAGE, PALLET, DUTY, MPF, HMF, PORT FEE, INSURANCE, OTHER): `group` (Origin / Main / Destination / Government), `default_basis`, `is_at_cost`, `expense_account` (per company child), `item` (service item for the Purchase Invoice).
- **Shipment Document Type** (seed: Commercial Invoice, Packing List, Bill of Lading, Sea Waybill, Air Waybill, FCR, Certificate of Origin, Export Declaration, Inspection Certificate, Insurance Certificate, Beneficiary Certificate): `issued_by` (Us / Forwarder / Carrier / Customs / Third Party), `needs_original`.
- **Destination Filing Rule** (seed **one** example, disabled until the user enables it: country US, mode Sea, filing "Importer Security Filing", `hours_before_loading` 24, applies when our side is the importer (DDP)): `country`, `mode`, `filing_name`, `hours_before_loading`, `applies_when` (We Are Importer / Always), `enabled`. Numbers live here, not in code.
- **Payment Deduction Reason** (seed: Bank Charges, Chargeback, Quality Claim, Quantity Claim, Discount, Exchange Difference, Short Payment Unexplained): `account` per company (child), `needs_claim` (Check), `needs_approval` (Check).
- **Chargeback Rule** (optional, from buyer PO terms): `customer`, `event` (Late TOP Sample / Late Shipment / Label Error / Other), `amount`, `per` (PO / Shipment / Piece), `currency`. Seeds nothing from the reference PO; the merchant keys it.

### 5.3 Roles (pre-sync patch, as in Phase D)

`Apparel Shipping` (logistics and documentation: Export Shipment, Freight Quote, document checklist, read on invoices). Accounts work uses ERPNext's `Accounts User` / `Accounts Manager`. Collections: `Accounts User` writes the follow-up; `Apparel Merchandising Manager` reads it and can add notes (merchants often chase buyers).

### 5.4 Custom fields (in `setup/install.py` `get_custom_fields`, module Arinox Apparel)

- **Delivery Note**: `apparel_packing_list` (from D7), `apparel_export_shipment`, `apparel_gate_override` + reason (inspection gate, from D8), `apparel_over_ship_override` + reason (quantity, from D8).
- **Sales Invoice**: `apparel_export_shipment`, `apparel_commercial_invoice_no` (search index), `apparel_invoice_route`, `apparel_route_leg` (Int), `apparel_due_basis` (Select, copied from the contract), `apparel_basis_date`, `apparel_is_sample_invoice` (Check).
- **Purchase Invoice**: `apparel_export_shipment`, `apparel_freight_quote`.
- **Payment Entry**: `apparel_remittance_ref` (Data), `apparel_received_for_company` (Link Company, section 10.5).
- **Customer**: `apparel_invoice_route` (default route).

---

## 6. Packing (slice E1) — Phase D section 10.2, adopted, with these changes

1. **Carton range rules (finding 10)**: per Packing List, ranges are contiguous from 1, non-overlapping, `carton_count = carton_to − carton_from + 1`; a gap or an overlap blocks submit and names the cartons. Carton numbers run **per Packing List** (one PO × ship-to); the "carton n of N" on the label uses this list's N.
2. **Multi-PO and multi-ship-to**: one Packing List = one Sales Order × buyer PO × ship-to. A PO with two ship-tos is two lists (golden test from D7 kept).
3. **Shipment summary fields** computed per list (finding 9): cartons, pieces, net, gross, CBM, distinct carton dimensions with count. These feed the Export Shipment and its prints.
4. **Repack** after a failed inspection: allowed only on a Packing List not yet on a submitted Delivery Note. Cancel and amend (ERPNext amend) keeps the SSCC numbers of the cancelled list retired. A repack that changes pieces by colour × size re-posts `PACKED` through cancel and amend, not through negative rows.
5. **Samples out of packed stock** (TOP, shipment samples, buyer's counter samples): `SAMPLE_OUT` from A-grade before packing (Phase D rule); pieces taken **from a packed carton** need a carton edit (amend) so the carton contents stay true.
6. The FG Material Receipt stays **draft** (Phase D 3.3); the Delivery Note cannot submit before it is submitted unless the site allows negative stock: E3 checks this and names the draft.
7. Agent API: `get_packing_context(sales_order)`, `draft_packing_list(...)` (drafts only, server recomputes everything).

Exit check: golden numbers 8, 9, 16, 17 from Phase D, golden number E12 (overlap) here; a list generated, edited, submitted, cancelled and amended; carton label printed and **scanned by the user** before use.

---

## 7. Final Quality Inspection (slice E2) — Phase D section 10.3, adopted, with these changes

**7.1 Lot and timing**
- An inspection covers one **lot** = one or more submitted Packing Lists of the same Sales Order and style (several POs of the same style may be offered together when they ship together). `offered_qty` = Σ packed pieces of those lists. The result applies to every colour in the lot.
- **Readiness**: a *Final* inspection warns when the lot's packed % of the order quantity is below `final_min_packed_pct` and blocks below 50 %. An *In Line / Pre-final (DUPRO)* never opens the ship gate (Phase D).
- Status flow: `Planned` (date, inspector, party) → `In Progress` → submitted with result. A Planned inspection shows on the shipment board so logistics sees whether the cut-off can be met.

**7.2 AQL** (Phase D table): seed only rows confirmed by two ISO 2859-1 Table 2-A sources (`confirmed = 1`); unconfirmed rows block an inspection that needs them with "QA must confirm the AQL row for lot size N". Sample size from `offered_qty`. **Verify in particular the "500 and over" row**: Phase D lists 21 / 22 for both major 2.5 and minor 4.0, which looks wrong for 4.0 (an arrow in the standard).

**7.3 Carton selection (new)**
- `Pick Cartons` draws `inspected_cartons` (Phase D rule: `ceil(√N)` or fixed %) **at random from the lot's actual carton numbers**, spread across colours, sizes and the tail carton. The seed and the drawn list are stored (child **Final Inspection Carton**: packing list, carton no, SSCC, opened, pieces drawn, resealed).
- The inspector may swap a carton only with a reason (logged). Cartons must exist in the lot, and each may be drawn only once.
- Sample pieces are drawn from the picked cartons. Pieces found defective are replaced from A-grade stock and the carton is amended, or the carton is marked for repack. The inspection never changes the ledger itself.

**7.4 Results (new options and rules)**
- Result: `Accepted`, `Rejected`, `On Hold`, and **`Accepted with Concession`**: the buyer accepts despite a failed sample, with `buyer_approval_ref`, an approver, optional agreed discount % or amount. A concession opens the ship gate and, if a discount is set, creates a **draft Buyer Claim** of type Concession (E7) so it reaches the invoice or a credit note instead of being forgotten.
- Third-party or buyer QA: `inspected_by_party`, their report number and attachment are required for those parties. A third-party re-inspection fee can be recorded (`reinspection_fee`, `fee_borne_by`) and becomes a cost line on the order's profitability (E5).
- Re-inspection limit (`reinspection_limit`), after which a manager and a buyer reference are needed.
- **The acceptance is invalidated** when, after it, the lot's packed pieces change by colour × size (repack, added cartons) by more than the AQL lot band allows: the ship gate re-checks that the Delivery Note's quantities are inside the accepted lot. Adding a new Packing List after acceptance needs a new inspection or a manager override with reason.
- Measurements per size against the tech pack POM tolerances reuse Phase B's tolerance rule (`production/measurements.py`).
- On submit: T&A `FINAL_INSPECTION` (Final or Re-inspection, Accepted or Concession); Rejected lists the defect classes and the lists needing rework.

**7.5 Ship gate**: on Delivery Note `before_submit` (Phase D wording), now keyed on the lot: every Packing List on the DN is in a lot whose latest Final / Re-inspection is Accepted or Concession. Override pair `apparel_gate_override` (Production Manager or QA Manager, reason).

Exit check: golden numbers 14 and 15 (Phase D); a rejected → re-inspected → accepted lot; a concession that creates a draft claim; carton draw reproducible from the stored seed; ship gate blocks then passes.

---

## 8. Export Shipment and Freight (slice E3)

### 8.1 Freight Quote (submittable)

`forwarder` (Supplier), `quote_ref`, `quote_date`, `valid_until`, `mode` (Sea LCL / Sea FCL / Air / Courier / Road), `incoterm`, `pol`, `pod`, `final_destination`, `transit_days`, `quote_currency`, `settlement_currency` (finding 12), `basis_cbm`, `basis_gross_kg`, `basis_containers` (child: type, count), `basis_hbl` (default 1), child **Freight Quote Charge**: `charge_code`, `group`, `unit` (Per CBM / Per kg chargeable / Per kg gross / Per HBL / Per Shipment / Per Container / Per Pallet / % of Invoice / At Cost), `rate`, `qty` (defaults from the basis by unit; editable, **warn when it differs from the basis**, finding 12), `min_amount`, `max_amount`, `vat_pct`, `vat_included` (Check), `amount` (computed, min / max applied), `remark`. Totals per group, total excluding at-cost lines, VAT total, and an "at cost: not included" list.

- **Compare** (script report *Freight Quote Comparison*): quotes for the same shipment (or same route and month) side by side by charge code, origin / main / destination totals, transit time, validity; expired quotes greyed.
- `Select for Shipment` links the quote to an Export Shipment as its estimate; an expired quote needs a reason.

### 8.2 Export Shipment (submittable; the hub)

**Header**: `shipper_company`, `customer`, `mode`, `incoterm`, `named_place`, `forwarder`, `freight_quote`, `booking_no`, `booking_date`, `pol`, `pod`, `final_destination`, `place_of_receipt`, `vessel_voyage` or `flights` (child for air legs: flight, from, to, ETD, ETA), `etd`, `eta`, `cutoff_datetime`, `stuffing_place`, `freight_terms` (Prepaid / Collect), `service_type` (CFS/CFS, CFS/DOOR, CY/CY, DOOR/DOOR, Airport/Door …), `status` (see below), `reason_for_air` + `air_cost_borne_by` (Factory / Buyer / Supplier / Shared; required when mode is Air and the contract mode is Sea, finding 14).

**Children**
- **Shipment Packing List**: packing list (Link, submitted, accepted lot), sales order, buyer PO, style, cartons, pieces, net, gross, CBM (all read-only, fetched).
- **Shipment Container** (Sea): container no (ISO 6346 check digit validated, warn only), type (20GP / 40GP / 40HC / LCL part), seal no, cartons in it.
- **Shipment Measure**: one row each for Declared (Σ packing lists), Booked, Carrier (B/L or AWB), Customs, with cartons, gross kg, CBM, chargeable weight (computed for air from carton dimensions and `air_volumetric_divisor`). Differences above the settings warn on save and are listed on the board (finding 11).
- **Export Declaration**: declaration no, type code, registration date, status (Registered / Cleared / Amended / Cancelled), channel (free text, e.g. Green / Yellow / Red), commercial invoice no, invoice basis (Incoterm), invoice value, currency, customs exchange rate, packages, gross kg. **Checks**: the invoice number exists on a leg-1 invoice of this shipment; invoice value equals that invoice's total (Block, override with reason); packages and gross equal Declared (Warn). A split shipment (finding 3) has one declaration per invoice.
- **Shipment Document** (the checklist): document type, required (from the contract's `documents_list` and, later, an L/C), number, date, issued by, attachment, `sent_to_buyer_on`, `original_count`, `released` (for B/L). The B/L or AWB row also holds: HBL / HAWB no, MBL / MAWB no, `bl_type` (Original / Telex Release / Surrendered / Sea Waybill / AWB), `on_board_date`, `place_of_issue`. **The on-board date is the shipment date** used by E4 and E6.
- **Destination Filing**: rows created from enabled **Destination Filing Rules** matching destination country, mode and the importer condition (DDP = we are importer): filing name, due (`cutoff_datetime` − hours, a conservative proxy for loading time; edit when the loading time is known), filed_by (Us / Forwarder / Buyer), filed_on, reference. Overdue unfiled rows show red on the board and warn on Delivery Note submit.
- **Shipment Cost** (estimate and actual, filled by E5).

**Status** (computed, also settable to On Hold with reason): `Planned` → `Booked` (booking no) → `Documents Prepared` (E4 drafts exist) → `Cargo Handed Over` (Delivery Note submitted) → `Customs Cleared` (declaration Cleared) → `On Board` (on-board date) → `Arrived` (actual arrival date) → `Delivered` (delivery date at the buyer's warehouse, the ROG date) → `Closed` (all invoices submitted, all forwarder bills received or written off).

**Buttons**: `Get Packing Lists` (accepted lots of the customer not yet shipped, same mode and destination), `Prepare Documents` (E4), `Make Delivery Note`, `Record B/L`, `Record Arrival / Delivery`, `Send Documents` (email to the buyer contact with the checklist's attachments; stamps `sent_to_buyer_on`).

**Make Delivery Note**: one Delivery Note per Sales Order (ERPNext `make_delivery_note`), item quantities set from the packing lists per Sales Order item (colour × size × ship-to), `apparel_packing_list`, `apparel_export_shipment`, incoterm and named place, transporter = forwarder, `lr_no` = booking no. DN `before_submit`: ship gate (7.5), over-ship check against the **latest** SO quantity and the contract band (Phase D D10), FG receipt submitted, destination filings not overdue (warn). `on_submit`: ledger `SHIPPED` (Phase D 3.2: `≤ PACKED − SHIPPED`), T&A `EX_FACTORY`. `on_cancel`: blocked when a submitted invoice of the shipment references this DN's lines; otherwise unposts and unstamps.

**Rules on Export Shipment**
1. A Packing List may be on only one non-cancelled shipment.
2. All lists share the shipment's customer; mixed ship-tos are allowed only if `final_destination` is shared (a consolidated LCL).
3. Cut-off passed with no Delivery Note → board red; booking moved = edit `etd` / `cutoff` (versioned), the old values stay in the version log.
4. Mode Air on a Sea contract needs `reason_for_air` and `air_cost_borne_by`.
5. Cancel: blocked once a Delivery Note is submitted; cancel the DNs first.
6. T&A: `FREIGHT_BOOKING` on status Booked; new optional milestone types `ON_BOARD` and `IN_WAREHOUSE` (delivery recorded), non-critical, decision P5.

**Prints**: *Shipment Packing List* (summary per PO, finding 9), *Customs Packing List* (per style and PO), *Shipping Marks* (from the contract's shipping marks text and the PO, style, colour, carton n of N), *Booking Request* to the forwarder.

### 8.3 Edge cases (shipment and freight)

1. A shipment is booked, then a lot fails inspection: remove its packing list from the shipment before Make Delivery Note; if the booking is no longer needed, status On Hold and a reason.
2. Cargo rolled to the next vessel: new `vessel_voyage`, `etd`; T&A EX_FACTORY unchanged; ON_BOARD only when the B/L is recorded.
3. Partial loading by the airline (the booking warns of this): one shipment with two AWB legs; the on-board date is the **last** leg's date for ship-date terms (default), setting can choose first.
4. Carrier weight or CBM above declared: forwarder bills on the carrier figure; the variance shows on the freight variance report, never edits the packing list.
5. One booking, two invoices, two declarations (finding 3): one shipment, two leg-1 invoices, each with its own declaration row.
6. Delivery Note cancelled after customs clearance: blocked unless the declaration row is marked Amended or Cancelled with a reference.
7. FG receipt still draft: DN blocked with the name of the draft.
8. Consolidated LCL with another company's cargo: only our cartons are on our shipment; the container row says "LCL part".
9. Destination country without a filing rule: no filing rows; nothing country-specific is assumed.
10. Courier sample shipment: Export Shipment mode Courier, no packing list, sample invoice (9.6).

---

## 9. Invoicing (slice E4)

### 9.1 The structure question (decision P1)

ERPNext requires a Sales Invoice linked to a Sales Order or Delivery Note to have the **same customer and company** (section 4). The reference chain is factory → trading company (FOB) → buyer (DDP), while the built app keeps the buyer's Sales Order in the contract company, and production, T&A and ledger are keyed to it.

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Route on top of the existing order (recommended)** | Buyer SO and DN stay in the factory company (as built). **Leg 1**: factory Sales Invoice to the internal customer (trading company) at the transfer price, **not linked** to the SO/DN (linked by `apparel_export_shipment` and per line by a custom `apparel_dn_detail`). ERPNext creates the trading company's Purchase Invoice (`make_inter_company_purchase_invoice`). **Leg 2**: trading company Sales Invoice to the buyer at the SO rate, also unlinked. Our code marks the DN billed by closing it (ERPNext *Close* status) once all legs are submitted. | No change to Phases A to D; receivable in the trading company as in the receivables workbook; one place (the shipment) holds all legs | ERPNext's SO / DN "% billed" stays 0 (we close them and report billing from our own links); per-SO revenue reports come from the app, not from ERPNext's SO |
| B. ERPNext-native chain | Buyer SO moves to the trading company; trading company inter-company PO → factory SO (internal customer) → production card on the factory SO → factory DN and SI → trading PI → trading SI against the buyer SO (drop-ship item) | Fully native billing status | Two SOs per order; Phases A to D re-keyed (contract, card, T&A, ledger) |
| C. Direct only | Factory invoices the buyer from its SO / DN | Simplest; native | Does not match the documents |

Every option supports a **direct route** (one leg, the standard ERPNext `make_sales_invoice` from the Delivery Note, linked, native billing status) for buyers who are not billed through the trading company.

The rest of this section assumes **Option A**.

### 9.2 Prepare Documents (button on Export Shipment)

1. Resolve the **Invoice Route**: the contract's customer and brand → route; none → the Customer's default → a direct route.
2. Reserve the **commercial invoice number** (9.4) once per shipment (or per split, finding 3).
3. For each leg create **one draft Sales Invoice per seller company** with lines per Sales Order item group (buyer PO × style; colour and size optional by print format), quantities from the shipment's Delivery Notes (or, before the DN exists, from its packing lists), and the leg's price:
   - Sales Order Rate: the SO item rate. **Mismatch is impossible by construction**; a price change goes through *Update Items* on the SO first (finding 5).
   - Price List: the leg's price list, item price of the variant, falling back to the template item (the builder verifies ERPNext's fallback in `stock/get_item_details.py` and cites it); no price → block and name the item.
   - Cost Sheet FOB: the approved price of the line's Cost Sheet (`Sales Order Item.apparel_cost_sheet`).
4. Header: incoterm and named place (leg), payment terms (contract `payment_terms_template` for the customer leg; the route leg for intercompany), `apparel_due_basis` (contract `payment_basis`), currency (SO currency for the last leg; the leg's price list currency for others), shipping address = the buyer's warehouse (ship-to) on every leg, bank account from the leg.
5. Re-running Prepare Documents **updates the drafts** (quantities, prices) and never touches a submitted invoice. After an Export Declaration row exists for an invoice number, a change to that invoice's total blocks unless the declaration is marked Amended (8.2 check).

### 9.3 Submitting

- `submit_invoices_on = On-board date recorded` (default): when the B/L or AWB on-board date is recorded, the customer-leg invoice's `posting_date` stays the invoice date and the **due date is computed from the basis** (10.1) before submit. Intercompany legs submit first; then the customer leg. Drafts by default (`auto_submit_accounting = 0`): the button "Submit Invoices" is for Accounts Manager.
- On submit of the last leg: close the Delivery Notes (Option A), create the **Receivable Follow-up** (E6), stamp nothing (finance is not in T&A).
- Cancel of a leg: allowed by ERPNext rules (payments first); our hook re-opens the Delivery Note and sets the follow-up to Cancelled.

### 9.4 Numbering (decision P2)

`apparel_commercial_invoice_no` from `commercial_invoice_pattern` and a **number date** (default: the shipment's planned cargo-ready date, editable before reservation). Unique per (seller company, number) across non-cancelled invoices; legs of one shipment share it. On a clash the next free suffix `-A`, `-B` … is offered. A cancelled invoice keeps its number retired (never re-used without a manager action). The ERPNext `name` of the Sales Invoice stays its normal naming series.

### 9.5 Prints

- *Commercial Invoice* (per leg, Arinox header): seller, sold to, consignee, notify party, delivery-to, invoice no and date, vessel or "BY SEA / BY AIR" + incoterm, cartons, PO / style / description / destination / qty / unit price / amount, total in words (`frappe.utils.money_in_words` in the invoice currency), shipping marks, receiving bank block **from the leg's Bank Account record** (never typed), manufacturer line (factory company address).
- *Customs Invoice* (leg 1, numbered fields (1) to (17) like the reference): shipper, for the account and risk of, notify, consignee remark, port of loading, final destination, carrier, sailing on or about, country of origin, commodity / style / PO / qty / unit price / amount.
- The **Shipment Packing List** and **Customs Packing List** (8.2) carry the same invoice number and date.

### 9.6 Sample and charge invoices

- **Sample invoice** (`apparel_is_sample_invoice`): from a Sample Approval or a manual list; no production card, no ledger, no ship gate; may be "no commercial value" (zero price, print "NCV"). Uses the direct route unless the customer's route says otherwise.
- **Re-billed charges** (courier, testing): a normal Sales Invoice with a service item; listed on the follow-up like any invoice.

### 9.7 Edge cases (invoicing)

1. Shipment with several SOs, contracts, currencies: one invoice per leg per **currency**; a mixed-currency shipment yields two customer invoices with the same number + suffix (warn the user).
2. Partial shipment of an order: invoices follow the Delivery Note quantities; the SO stays open for the balance.
3. Over-shipped pieces within the band are invoiced; above the band only with the DN's over-ship override (and then invoiced).
4. Shortage after the DN (cartons lost before loading): cancel and amend the DN before invoice submit; after submit, a Credit Note.
5. Price revised after the drafts were made: Update Items on the SO, then Prepare Documents again.
6. Exchange rates: the invoice uses ERPNext's rate on the posting date; the **customs exchange rate** stays on the declaration row only (finding 16: 26,081).
7. Rounding: amounts per line rounded to the currency precision, total = Σ lines (golden numbers E1 to E3 reproduce the reference totals exactly).
8. Trading company has no stock: leg-1 PI in the trading company is created with `update_stock = 0` (the goods never enter its warehouse).
9. Invoice route changed after drafts exist: drafts deleted and rebuilt; submitted legs block the change.
10. An internal customer missing for a leg: Prepare Documents stops with the setup step to do.

---

## 10. Payment follow-up (slice E6)

### 10.1 Due date by basis

| Contract `payment_basis` (existing options + new) | Basis date | When known | ERPNext due date |
|---|---|---|---|
| Days after Invoice Date | invoice posting date | at submit | exact (Payment Terms Template) |
| **Days after B/L Date** (new) | on-board date | B/L recorded | exact: invoice submitted after the B/L (9.3) |
| **Days after ETA** (new) | ETA, then actual arrival | estimate at submit | provisional; follow-up holds the expected date |
| Days after Receipt of Goods (ROG) | delivery date at the buyer's warehouse | weeks after shipment | provisional = ETA + `rog_buffer_days`; follow-up re-dates when delivery is recorded |
| Advance | before shipment | - | advance Payment Entry; the ship gate can warn when an advance-term order ships unpaid (setting, Warn) |
| L/C | presentation + bank terms | - | out of scope for now (decision P6) |

The **expected due date** on the follow-up = basis date + days. ERPNext's due date is never edited (section 4). Reports and reminders use the expected date and show both when they differ.

### 10.2 Receivable Follow-up (one per submitted customer-leg invoice, auto-created)

Fields: `sales_invoice`, `company`, `customer`, `currency`, `invoice_amount`, `outstanding` (live from the invoice), `due_basis`, `basis_date`, `basis_source` (Invoice / B/L / ETA estimate / Arrival / Delivery), `expected_due_date`, `erp_due_date`, `days_overdue` (computed daily), `status` (Not Due / Due Soon / Overdue / Promised / Partly Paid / Disputed / Paid / Written Off / Cancelled), `promise_date`, `promise_amount`, `owner_user`, `next_action_date`, `escalation_level`, `dispute_reason`, `linked_claims` (from E7), `total_deductions`, child **Follow-up Log** (date, by, channel: Email / Call / Message / Meeting / Dunning, contact, note, outcome, next action date).

Rules:
1. A daily scheduler job (`daily`) recomputes `days_overdue`, `status`, and runs the **escalation table** (5.1): reminder e-mail draft to the buyer contact `reminder_days_before_due` before the expected due date; Dunning (ERPNext) at the configured levels, created as **draft** for the accountant; a ToDo for the role named at each level. It never sends e-mail by itself unless a setting enables it.
2. A broken promise (promise date passed, not paid) moves the status to Overdue and logs it.
3. Disputed: requires a reason or a linked Buyer Claim; Dunning is suppressed while Disputed.
4. Paid: when outstanding is zero (from Payment Entry or Credit Note). Written Off: only through an ERPNext Journal Entry or Credit Note; the follow-up just reflects it.

### 10.3 Receiving money

- **Record Receipt** (button on the follow-up or the customer): opens an ERPNext **Payment Entry** prefilled with the customer's open invoices oldest-first by expected due date, `apparel_remittance_ref`, and proposes **deduction rows** when the received amount is less than the allocation: bank charges (default first), then a reason chosen from **Payment Deduction Reason**; a reason with `needs_claim` must link a Buyer Claim or chargeback. The accountant adjusts and submits.
- **Unallocated receipts** (finding 19) stay as unallocated Payment Entries and show on the Collections report until allocated through Payment Reconciliation.
- Multi-currency: ERPNext handles exchange gain or loss; bank charges in another currency are a deduction row.

### 10.4 Reports and screens

- **Collections** (script report): per company and customer, invoice, commercial invoice no, shipment, ETD / on-board, ETA, delivery, basis, expected due, ERP due, amount, received, deductions, outstanding, days overdue, ageing buckets (Not due, 1–30, 31–60, 61–90, 90+) on the **expected** due date, status, promise, last contact, next action. Matches the company's receivables workbook columns (finding 18) and adds the basis.
- **Customer statement**: ERPNext Process Statement Of Accounts (configuration; a print with the Arinox header).
- Number cards: Overdue amount (by company currency), Promises due this week, Disputed amount, Unallocated receipts.

### 10.5 Money received by another group company (finding 8)

When a receipt lands in group company X for an invoice of company Y: record the Payment Entry in X against a **receivable from Y** (internal party), with `apparel_received_for_company = Y`; then an **Inter Company Journal Entry** pair clears Y's customer receivable against its payable to X. Our button "Settle for Group Company" drafts both entries. The Collections report shows the invoice as paid only when Y's invoice outstanding is zero.

### 10.6 Edge cases (payments)

1. One payment for many invoices of different shipments and companies: allocate per company; the rest becomes 10.5.
2. Payment before the due date or before the B/L: allowed; the follow-up becomes Paid.
3. Overpayment: ERPNext unallocated amount; shown on the report; refund or keep as advance is the accountant's choice.
4. Partial payment with no reason: deduction reason "Short Payment Unexplained"; the follow-up stays Partly Paid with the balance, not Paid.
5. Chargeback deducted by the buyer that we did not expect: the deduction needs a Buyer Claim (E7) of type Chargeback, which may be accepted or disputed.
6. Invoice cancelled and re-issued (wrong price): the old follow-up is Cancelled with a link to the new one; the log is copied.
7. Delivery date never recorded for a ROG term: the expected due stays ETA + buffer and the follow-up shows "basis estimated".
8. Customer in a different currency from the company: buckets and totals are per currency; no silent conversion in the report.

---

## 11. Freight cost and shipment profitability (slice E5)

1. **Estimate**: on Select for Shipment, the quote's charges are copied to Shipment Cost rows (`kind = Estimate`), recomputed on the shipment's **carrier** measure when it is recorded (chargeable weight, W/M), minimums applied.
2. **Actual**: forwarder Purchase Invoices (draft or submitted, `apparel_export_shipment` set) are read as `kind = Actual` rows by charge code (service item ↔ charge code). Button **Make Forwarder Invoice** drafts a Purchase Invoice from the estimate for the accountant to correct to the forwarder's bill. Origin charges with VAT use the company's tax template; "quoted in USD, settled in local currency" means the PI is in the settlement currency with the USD amount noted.
3. **Variance**: per charge and total, warn above `freight_estimate_variance_pct`; "at cost" lines (duty, MPF, HMF) have no estimate and are listed separately. A shipment closes when every forwarder bill is in, or the open lines are marked "No Bill Expected".
4. **Which company carries the cost** (decision P1b): the leg named in the route (`freight_borne_by_leg`), default the **seller of the customer leg** under DDP / CIF / CFR, none under FOB / EXW / FCA (the buyer pays). A forwarder bill addressed to another group company is re-charged by an intercompany invoice (drafted).
5. **Allocation** (report only, no accounting entry): freight and destination costs are allocated to Sales Order × style by **CBM** (sea), **chargeable weight** (air) or **invoice value** (setting per charge group). Duty-type lines are allocated by invoice value.
6. **Shipment Profitability** (script report): per shipment and per SO × style: customer revenue, intercompany transfer value, freight and destination costs allocated, duty, inspection fees (7.4), concessions and claims (E7), chargebacks, so margin after logistics per piece. Each company's view is shown separately; nothing is consolidated.
7. **Air freight responsibility** (8.2 rule 4): when `air_cost_borne_by` is Supplier, a draft debit note to that supplier can be raised for the agreed share; Buyer, a draft charge invoice to the buyer; Factory, nothing extra.

---

## 12. Buyer claims, chargebacks and commercial close (slice E7)

### 12.1 Buyer Claim (submittable)

`customer`, `claim_type` (Quality / Quantity Short / Quantity Over / Wrong Item / Late Delivery / Chargeback / Concession / Other), `sales_invoice` (customer leg), `export_shipment`, `sales_order`, `style`, `colour` / `size` rows with pieces, `claimed_amount`, `currency`, `reported_on`, `evidence` (attachments; required when `claim_requires_evidence`), `buyer_ref`, `status` (Open / Under Review / Accepted / Partly Accepted / Rejected / Settled), `accepted_amount`, `settlement` (Credit Note / Deduction from Payment / Replacement / Return of Goods / None), `fault_source` (same list as the ledger: Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Logistics, Unknown), `recover_from_supplier` (Link Supplier, optional) and `recovery_amount`.

Rules:
1. **Claim window** (finding 21): Quality ≤ contract `quality_claim_days`, Quantity ≤ `quantity_claim_days`, counted from the shipment's **arrival** date (or delivery when arrival is missing; customs clearance at destination is not tracked, so arrival is the proxy and the form says so). Outside the window: a warning and a reason to accept anyway. (Concession and Chargeback claims have no window.)
2. **Cap**: `accepted_amount` ≤ the CIF value of the claimed pieces. On a CIF or CFR invoice that is the customer-leg unit price × pieces. On a DDP invoice it is the invoice value less the destination costs and duty allocated to those pieces (section 11.5). On FOB, FCA or EXW it is the invoice value plus the allocated main freight and insurance. The cap is computed and shown; exceeding it needs a manager with a reason.
3. **Settlement**: Credit Note → a draft Sales Invoice `is_return` on the customer leg against the invoice; Deduction → linked to the Payment Entry deduction row (10.3); Return of Goods → a note only (reverse logistics is out of scope); Replacement → a new Sales Order line (manual).
4. **Recovery**: a supplier-fault claim can draft a Purchase Invoice `is_return` (debit note) to the supplier; for a wash vendor, the Subcontract Settlement (D5) is the place if it is still open.
5. Chargeback claims can be raised from a **Chargeback Rule** event (e.g. TOP late: the T&A `TOP` milestone actual after the planned date generates a **suggested** claim; nothing automatic is posted).
6. A claim on an invoice sets that invoice's follow-up to Disputed until it is settled or rejected.

### 12.2 Commercial Close

Extends Phase D 11.3 "Close Production". **Close Order (Commercial)** on the Sales Order (Accounts Manager and Merchandising Manager): requires production closed (Phase D), every Delivery Note invoiced on all legs, every customer-leg invoice Paid or Written Off, no open claims, the claim windows ended or waived with a reason, every shipment of the order Closed. Writes a closing summary (ordered, shipped, invoiced, received, deductions, claims, freight allocated, margin) and sets SO status Closed. Reopen: manager with reason.

---

## 13. Golden numbers (tests; quantities and amounts only, identifiers invented)

| # | Case | Input | Expected |
|---|---|---|---|
| E1 | Two legs, one number | 1,520 pcs; transfer 6.56; customer DDP 16.85 | leg 1 **9,971.20**; leg 2 **25,612.00**; both print the same invoice number; words "Nine Thousand Nine Hundred Seventy One … and Twenty Cents" via `money_in_words` |
| E2 | Customs invoice, 4 lines | 4,824 × 6.55, 3,564 × 6.55, 2,000 × 7.28, 1,846 × 9.10 | 31,597.20; 23,344.20; 14,560.00; 16,798.60; total **86,300.00**, **12,234** pcs |
| E3 | Same shipment, customer leg | × 11.30, 11.30, 13.10, 15.85 | **150,243.50** |
| E4 | Customs value in local currency | 86,300 × 26,081 | **2,250,790,300** = Σ of the four line values (824,086,573.2 + 608,840,080.2 + 379,739,360 + 438,124,286.6) |
| E5 | Shipment totals | 4 packing lists | **441** cartons, **17.146668** CBM, net **2,136.59**, gross **2,665.79** kg |
| E6 | Measure variance | declared 1.596672 CBM, booked 1.600, carrier 1.910 | carrier **+19.62 %** → warn (setting 5 %); gross 344.6 everywhere → no warn |
| E7 | Air chargeable weight | 75 cartons 54 × 34 × 25 cm, gross 621 kg, divisor 6,000 | volumetric **573.75** kg; chargeable **621**; freight at 5.40/kg = **3,353.40** (quote on 600 kg: 3,240.00; quote total 4,198.10) |
| E8 | Sea LCL quote | 20 charge lines, 7.3 CBM | total **2,378.90**; one per-CBM line on 4.0 CBM → warn "qty differs from basis" |
| E9 | Due date, ship-date basis | on-board 2026-03-26, 30 days | expected due **2026-04-25**; on 2026-09-03 overdue **131** days; second invoice 2026-06-11 → 2026-07-11, **54** days |
| E10 | Partial receipt | invoices 37,436.90 + 46.80, received 5,768.90 | outstanding **31,714.80**, status Partly Paid |
| E11 | Split shipment | two invoices of one booking | 1,953 + 1,013 = **2,966** pcs; FOB 18,106.69 + 8,934.66 = **27,041.35**; gross 785.9 + 582.6 = **1,368.5**; cartons 82 + 42 = **124**; numbers `X` and `X-A` |
| E12 | Carton range overlap | `103~124` (22) then `124~127` (3) | block: carton 124 twice; `124~127` is 4 cartons, not 3 |
| E13 | Price change | contract 16.30, invoice 16.85 | invoice blocked until SO rate updated (+**3.37 %**) |
| E14 | Over-ship band | contract 1,700, shipped 1,846 (band ±5 % for 1,601–3,000) | **+8.59 %** → DN blocked without override |
| E15 | ROG estimate | ETA 2026-04-08, buffer 5, 15 days ROG | expected due **2026-04-28**; delivery recorded 2026-04-14 → **2026-04-29** |
| E16 | Claim window | arrival 2026-01-30, quality 60 days, quantity 30 days | quality claim on 2026-03-31 OK, 2026-04-01 warns; quantity claim on 2026-03-02 warns |

E1 to E11 come from the reference documents. E12 to E14 come from the reference sheets and contracts. E15 and E16 are invented to test rules.

---

## 14. Slices (build in this order; stop for review after each)

| Slice | Content | Exit check |
|---|---|---|
| **E0 Prerequisites** | Full suite green (fix `test_sewing`); **D6** Finishing Receipt + Needle Log + label count; **D5** if P4 = yes | A washed (P4) or unwashed style reaches `FIN_A` through documents only; browser check of D6 forms |
| **E1 Packing** | Section 6 (Phase D 10.2 + changes) | Section 6 exit check |
| **E2 Final Inspection** | Section 7 (Phase D 10.3 + changes), AQL rows verified and seeded, ship gate | Section 7 exit check |
| **E3 Export Shipment** | Masters (Freight Charge Code, Shipment Document Type, Destination Filing Rule), role `Apparel Shipping`, Freight Quote + comparison, Export Shipment, Make Delivery Note, DN hooks (gate, over-ship, `SHIPPED`, `EX_FACTORY`), prints, board tab | Golden E5 to E8, E11 (shipment part), E12; one sea LCL with two POs and one air shipment end to end in the browser |
| **E4 Invoicing** | Invoice Route, numbering, Prepare Documents, intercompany legs, submit on B/L, DN close, prints, sample invoices | Golden E1 to E4, E11, E13; one direct and one trading route; leg-1 PI auto-created in the trading company |
| **E5 Freight cost** | Estimate and actual, forwarder PI draft, variance, allocation, profitability, air responsibility | Golden E7, E8; variance by hand; a re-charge between group companies drafted |
| **E6 Payment follow-up** | Due basis, Receivable Follow-up, scheduler, escalation, Record Receipt, deductions, group-company receipt, Collections report, number cards | Golden E9, E10, E15; scheduler run on a fixed date in tests; dunning drafted not sent |
| **E7 Claims and close** | Buyer Claim, chargeback suggestions, credit and debit note drafts, Commercial Close | Golden E16; a claim settled by credit note and one by deduction; an order closed commercially |
| **E8 Close-out** | Workspace "Shipping & Collections" block, Sales Order buttons (Shipment, Invoices, Collections), number cards, `security-review`, full test run, update `PHASE_D_BUILD_STATUS.md` / this file / `CLAUDE.md` / `HANDOFF.md` | All tests pass; review with the user |

### 14.1 Tests (`tests/test_packing.py`, `test_final_inspection.py`, `test_shipment.py`, `test_invoicing.py`, `test_freight.py`, `test_collections.py`, `test_claims.py`)

Reuse `tests/production_base.py` and `tests/utils.py`. Add a fixture for **two companies** (factory, trading) with internal customer / supplier pairs, and a third for 10.5. Every rule in sections 6 to 12 has a pass and a fail test. Every override has a manager and a non-manager test. Every hook has a cancel test. The scheduler job runs with a frozen date (`frappe.tests.utils.change_settings` / `freeze_time`). Pure functions (chargeable weight, W/M, quote line amounts with min/max, carton range check, ISO 6346 check digit, invoice number suggestion and suffix, expected due date per basis, claim window, CIF cap, allocation) are tested directly with section 13.

### 14.2 Agent API (whitelisted, permission-checked in each)

`get_shipment_context(customer)` (accepted lots not shipped, open bookings), `draft_export_shipment(...)`, `get_invoice_preview(export_shipment)` (legs, prices, totals; read-only), `get_collections(customer=None, company=None)`, `log_follow_up(follow_up, note, next_action_date)`, `draft_buyer_claim(...)`. Drafts only; the server recomputes all amounts.

---

## 15. Open decisions (defaults used in this plan; the user confirms)

| # | Question | Default |
|---|---|---|
| **P1** | Invoice structure (section 9.1): A route on top of the existing order, B ERPNext-native chain with two Sales Orders, or C direct only | **A** |
| **P1b** | Which group company carries freight and destination costs on a DDP shipment billed through the trading company | The seller of the customer leg (trading company); forwarder bills addressed to the factory are re-charged intercompany |
| **P2** | Invoice number: what date is in `{YY}.{MM}.{DD}`, and are suffixes `-A`, `-B` right for splits | Planned cargo-ready date, editable; suffixes as in the documents |
| **P3** | The forwarder-copy invoice at a lower price than the export invoice (finding 2): is a separate destination value needed, and on what basis | **Not built.** Each leg prints from its submitted invoice. If needed, it becomes a recorded value with basis and approver after the user's customs broker confirms the method |
| **P4** | Build D5 (subcontracting) before E1 | **Yes**: every reference style is washed |
| P5 | Add T&A milestone types `ON_BOARD` and `IN_WAREHOUSE` | Yes, non-critical |
| P6 | Letters of credit (the contract allows "L/C"; every document seen is T/T) | **Not in this phase**; fields for an L/C record (number, bank, amount ± %, latest ship date, expiry, presentation days default 21, required documents) designed later if used |
| P7 | Who may send reminder e-mails and Dunning letters | Drafts only; Accounts User sends |
| P8 | Final inspection readiness | 80 % packed warns, below 50 % blocks |
| P9 | Expected ROG buffer after ETA | 5 days |
| P10 | Accounting documents (invoices, PIs, credit notes, JEs) created as drafts | Yes, `auto_submit_accounting = 0` |

---

## 16. Research gaps and things not verified

- **ERPNext item-price fallback from variant to template** (9.2) and the exact behaviour of closing a Delivery Note that is unbilled (Option A): verify in source before E4 and cite.
- **AQL rows**: still from Phase D, not verified; the "500 and over" minor row looks wrong.
- **Due-date bases** other than invoice date are not native; the design avoids editing ledgers, so ERPNext's own AR ageing will differ from the Collections report for ROG and ETA terms. That is by design and is shown on the report.
- **Customs and tax**: export declaration is recorded, not filed; no country's tax on intercompany sales, transfer pricing or VAT rules are modelled (Phase D D14 stands). The three-price finding (P3) needs the user's broker or accountant.
- **Destination filings**: only the US ISF rule is described, from secondary sources (CBP page not fetched); it ships disabled.
- **UCP 600** figures (P6) are from secondary commentary; recheck against the ICC text if L/Cs are built.
- **Freight quote formats** vary by forwarder; only three quotes were read. The charge code list will grow.
- Browser and barcode checks: none yet (nothing built).

---

## 17. Out of scope (later)

Filing customs declarations or ISF electronically, EDI 856 / 810, forwarder or carrier tracking APIs, letters of credit (P6), export credit insurance, factoring and invoice discounting, reverse logistics for returned goods, consolidation of group accounts, transfer-pricing documentation, piece-level traceability after shipment, buyer portals.

---

## Decisions the user gave on 2026-11-05 (after reading this plan)

1. **P4:** the wash round trip is done inside the subcontract module itself (Challan, Return, Settlement), not as a separate prerequisite. Built.
2. **P1b:** the customer pays us and we pay the forwarder from that. The forwarder's bills are Purchase Invoices tagged with the shipment, in whichever company receives the customer's payment; no intercompany re-charge was built.
3. **P2:** one number runs through the whole contract. The Sales Contract number is that number. Every new document is named `<contract no>-<code>-<nn>` (`SC` challan, `SR` return, `SS` settlement, `FIN` finishing receipt, `PL` packing list, `FI` final inspection, `INV` commercial invoice, `CL` claim) and carries the contract in a filterable field. An order with no contract uses its Sales Order name. The commercial invoice is one per contract per shipment, so a consolidated multi-PO invoice is split per contract.
4. **Reuse:** do not create modules where ERPNext already has one.

## Status log

### Built and migrated on the dev site (2026-11-05)

**D5 Subcontracting** (inside the existing Subcontract Process master): Subcontract Challan, Subcontract Return, Subcontract Settlement. Process terms (turnaround working days, quantity tolerance, damage limit, service item) are fields on Subcontract Process. Vendor-damaged pieces are not paid; damage above the limit is penalised (all damaged or excess only, from Apparel Settings); the settlement drafts a Purchase Invoice and a debit note. Return date counts working days (Sundays and the company's holiday list skipped).
**D6 Finishing:** Finishing Receipt, Needle Detector Log (a failed check blocks packing until the re-scan is logged; Block, Warn or Off in settings).
**E1 Packing:** Packing List (cartons as runs `1~11`, contiguous and non-overlapping, CBM per row, ratio and solid and assorted packing with a tail carton rule, SSCC from a counter that never goes back, finished-goods receipt drafted). Pack settings sit on the Packing List itself; there is no separate Packing Instruction.
**E2 Final Inspection:** Final Inspection (lot of packing lists, AQL plan, random carton draw with a stored seed, tests and conformity, concession, re-inspection chain and limit, ship gate). **AQL numbers: the lot ranges, code letters and sample sizes are seeded; accept and reject numbers are confirmed and seeded only for codes K, L and M (lots of 1,201 to 35,000 pieces).** Every other row is marked unconfirmed and an inspection that lands on it is refused until QA fills it in from ISO 2859-1 Table 2-A. Two web sources agreed on K, L, M; the third source read was misaligned by columns and was not used.
**E3 Shipment:** ERPNext's own **Shipment**, extended with custom fields (booking, vessel or flight, ETD, ETA, cut-off, B/L and on-board date, arrival and delivery dates, four measures kept side by side, air reason) and four child tables (packing lists, containers, export declarations, documents). Make Delivery Notes (one per Sales Order, quantities as packed, each row tied to its packing list). Delivery Note hooks: final-inspection ship gate with manager override, over-ship check per size and in total against the contract band, SHIPPED posted to the ledger, EX_FACTORY stamped.
**E4 Invoicing:** Prepare Invoices and Submit Invoices on the Shipment. Direct route (one invoice linked to the Delivery Note) and group route (factory invoice to the group trading company at a transfer price, then the trading company's invoice to the buyer, same number on both). Route and transfer price are fields on **Customer**; there is no Invoice Route doctype. The contract's payment basis sets the due date.
**E5 Freight cost:** the forwarder's quote is an ERPNext **Supplier Quotation** and the bills are **Purchase Invoices**, both tagged with the shipment; variance against the quote and a Freight Allocation report (by CBM at sea, weight by air).
**E6 Payment follow-up:** fields on the customer's **Sales Invoice** (basis, basis date, expected due date, status, promise, next action, dispute), a daily job that refreshes them and raises ToDos at the reminder and escalation days, a Log Follow-up dialog (the note becomes a comment), and the Receivables Follow-up report with ageing on the expected due date. The contract's payment basis gained two options: Days after B/L Date and Days after ETA.
**E7 Claims and close:** Buyer Claim (claim window and the cap at the invoice value of the pieces, manager override with reason, credit note drafted, invoice marked Disputed while open) and a Commercial Close checklist on the Sales Order.
**Also:** Contract Trail report (every document under one contract number), print formats (Packing List Form, Commercial Invoice, Final Inspection Report), workspace groups "Production" and "Shipping and Collections" (the Production group was missing since Phase D), form scripts.

### Differences from this plan

| Plan said | Built | Why |
|---|---|---|
| Export Shipment doctype | Custom fields on ERPNext Shipment | User: reuse what exists. Shipment already links Delivery Notes, parcels, AWB, forwarder |
| Freight Quote doctype | ERPNext Supplier Quotation | Same |
| Receivable Follow-up doctype | Fields on Sales Invoice, Dunning, ToDo, comments | Same |
| Invoice Route, Invoice Route Leg | Fields on Customer | Two legs at most; no new master needed |
| Packing Instruction doctype | Fields on the Packing List | Fewer documents; merchant keys the pack rule once per list |
| Shipment Document Type master, Destination Filing Rule | A Select; filing rules not built | Fewer masters |
| Invoice number `{prefix}{YY}.{MM}.{DD}` | `<contract>-INV-<nn>` | User (P2): one number from start to end |
| Settings table for escalation | Three settings fields | Simpler |
| FG receipt always drafted | Drafted only when `post_fg_receipt` is on and a finished-goods warehouse is set | Both exist in settings from Phase D |

### Added after the first status log (same day)

- **Decks:** the main page now has an **Apparel** folder holding four decks: Merchandising, Production, Quality and Packing, Shipping and Collections. Each has its own sidebar, workspace page and number cards (15 new number cards, 2 more for letters of credit).
- **Not-built items done, written to fit Server Scripts and data** (`arinox_apparel/portable/`): ISO 6346 container check and air chargeable weight and sea W/M; freight quote minimum, maximum, at-cost lines and quantity-against-shipment warning; destination filing rules (a master, a child table on Shipment, a seeded **disabled** US Importer Security Filing rule); T&A milestone types `ON_BOARD` and `IN_WAREHOUSE` with stamping (future dates are skipped); they are **not** in the default template, because assumed offsets pushed a fresh order past the buyer's in-warehouse date, so add them to your own template with your own offsets; sample invoices in the follow-up and the report; Letter of Credit (presentation deadline, latest shipment, amount used, expiry, daily reminder); close production (drafts, challans, shipped against the lower tolerance); Production Summary (SQL query report); Carton Label print format with an SSCC barcode.
- **Duplicate removed:** Carton Type replaced by ERPNext's Shipment Parcel Template (`ERPNEXT_OVERLAP_AUDIT.md`).
- **Hosted-site limits:** `HOSTED_CONSTRAINTS.md` lists what fits as data, what must be rewritten as Server Scripts (about 9,000 lines), and what cannot be done.

### Still not built

Intercompany purchase invoice for the first leg of the group route, and receipt of money by a different group company (both are accounting entries that need a second company to test); the forwarder-copy lower-price invoice (P3, deliberately not built); the Production Board page (a Page needs files; number cards and reports replace it); packing instruction as its own document; label control (labels sewn against issued); the vendor scorecard (ERPNext's Supplier Scorecard can be used); an "unaccounted pieces" column (the ledger's flow rules make it zero by construction, so it would say nothing).

### Verification

- `test_shipping.py`: **82 tests pass** (71 for the main flow and 11 that run the Server Scripts through the real sandbox) (pure maths with the company's golden numbers E1–E16 where they apply, every document rule, and one chain packing → inspection → shipment → delivery → invoice → follow-up → contract trail → claim → credit note).
- Phase D's `test_sewing.py` now passes (31 tests). One test (`test_reports`) failed because another test in the class leaves a report on the same line and date, and it read the first row; the assertion now looks for the row.
- **Whole suite after the last change: 396 tests, 0 failures, 2 skipped** (366 s). The earlier baseline run was killed before it reported, so there is no before/after comparison for Phases A to D beyond the sewing fix above.
- **Not verified:** nothing was opened in a browser, so the form scripts, dialogs and print formats are only checked to the extent the tests render the print HTML and call the server methods. The **group route (two companies) was not run end to end**: no second company exists in the test data. The carton label barcode does not exist yet. The hosted site has none of this.
- A `code-review` pass (medium) found ten issues; all were fixed and, where testable, given a test. A `security-review` pass was done by hand over the whitelisted methods (document-level permission checks added); the `security-review` skill itself was not run.

### Decisions still open

P3 (a second, lower value on the forwarder's copy of an invoice) needs the user's customs broker. AQL rows other than K, L and M need QA. The per-company rule for which group company books the forwarder bill is "whichever receives the customer's payment" and is not enforced.
