# Phase 1 — Order backbone plan (from the reference documents)

**Status:** Slice A2 built and tested (2026-11-04). Slices A3 (Buyer PO) and A4 (close-out) not started.
**Sources:** `../reference/DOCUMENT_INDEX.md` (what each document is), `PHASE1_ORDER_WIN.md` (what is built today).

## Goal

Finish Phase A completely before starting any other phase. **Phase A = inquiry → tech pack → costing → negotiation → contract → Sales Order.** Within it, capture every field and row the reference documents show for those steps, so later phases can reference Phase A data instead of re-entering it. The key per order is **PO × style × colour × ship-to**, with sizes beneath it.

Out of scope until Phase A is signed off: fabric and trim requisitions, WIP/T&A, markers, production card, intercompany fabric contracts, inspections, production reports, packing, invoices, customs, receivables. See "Parked" at the end.

## What is built vs what the documents need

Built (16 tests pass): Tech Pack, Cost Sheet, Costing Parameter, Cost Head, Price Negotiation, Sales Contract (+ template), Quotation/Opportunity/Sales Order custom fields, Order Desk, reports, dashboard, workspace.

### A. Corrections to what is built (the documents contradict the first design)

| # | Today | Documents show | Change |
|---|---|---|---|
| 1 | Finance, bank and profit are a gross-up on price | Other expenses and **profit are % of product cost** (markup) | Add calc type *Percent of Product Cost*. Profit as markup on cost. Keep margin on price as a displayed result |
| 2 | No fabric-metre heads | Fabric import and export cost are **per metre of fabric incl. wastage** | Add calc type *Per Metre of Fabric* |
| 3 | 12 cost heads | ~20 lines (printing, buying agent commission, carton = 1/pcs per carton, tape, zipper, tissue...) | Re-seed Cost Heads from the Detailed Costing sheet. Add *pcs per carton* |
| 4 | Contract `CTXG-YYYY-MM-###` | `CTXGVN{YY}.{MM}.{###}`, monthly counter | Change the naming rule. Prefix per issuing Company |
| 5 | Bands 15/10/7.5/5 at 0/500/1000/3000 | ≤500 ±15, 501–800 ±10, 801–1600 ±7.5, 1601–3000 ±5 | Correct the seeds and tests. Decide what happens above 3000 |
| 6 | Measurement rows keyed by POM code + size | `T210` appears twice in one tech pack | Key on code + name + size, or the real data is rejected |
| 7 | Materials in one UOM, one currency | BOM in yards, FR in metres, supplier price in RMB | Per-row UOM with conversion, price currency and FX |
| 8 | One trim allowance | 3 % / 5 % / 2 % / 10 % in different documents | Allowance % per cost head and per customer |

### B. Fields to add to what exists

**Cost Sheet:** FOB port, VND per USD (and FOB in VND), pcs per carton, factory, season, front/back image, PO / tech-pack / DDP dates; sign-off chain (fabric checked, first costing, 2nd check, final approval, each with user and date); material rows get cuttable width, yards-or-metres consumption, allowance %, lining/contrast fabric type, price currency; process charges get an apply flag.

**Tech Pack:** wash description and code, group/division, designer, tech designer, factory, sample size, AWC status; POM local-language name and a single ± tolerance; **fit rounds** child (1st fit, 2nd fit, PP, TOP; date; status; comment file); BOM rows get buyer item code, item colour, colour description, job code, size applicability (`*` or a size), UOM (YD/EA/MTR).

**Sales Contract:** buyer contact, brand/company, division, merchant, revision no / date / revised-for, issuing Company; lines get buyer PO code, fabric content/construction/GSM, finish/process, PCD, category, price term (DDP/FOB); size rows get **ship-to** and PO; terms get country of origin, insurance/freight party, delay-days, discrepancy and objection windows, documents list, signatories.

### C. One new doctype for Phase A

| Doctype | Why it belongs in Phase A | Source document |
|---|---|---|
| **Buyer PO** (+ items, size rows) | The PO is what starts an order and sits between negotiation and the contract. It carries PO no + EM no, ship-to, ROG terms, X-factory and in-warehouse dates, size breakup, PP/TOP rules and chargeback, estimated yield and fabric price. It is revised often. Contract lines link to PO lines | Client Purchase Order PDF |

### Parked (not Phase A, not to be started)

Style Consumption / bulk marker, Order WIP rows, Fabric and Trim Requisition generation, Production Card and Trim Card, intercompany Fabric Contract, PP meeting and pilot-run records, all inspection and production reports, washing statements, invoices, packing lists, customs declarations, receivables. The reference index describes them so they are ready when their phase starts.

## Proposed slices

| Slice | Content | Depends on |
|---|---|---|
| A2 Corrections and fields | Items A1–A8 and the field additions in B for Cost Sheet, Tech Pack, Sales Contract. Update seeds and tests | decisions 1, 3 |
| A3 Buyer PO | Buyer PO doctypes, contract lines link to PO lines, API for the AI agent to write a PO | decision 2 |
| A4 Phase A close-out | Print formats (quotation, contract), desk/Order Desk updates for the PO, full test run, review with you against the sample documents | A2, A3 |

Each slice ends with a migrate, tests, and your review before the next starts.

## Decisions (answered 2026-11-04)

1. **Margin convention:** markup on cost is the input (profit head = Percent of Subtotal); margin on price is displayed and is what the approval floor uses. Done.
2. **Buyer PO:** its own doctype. Slice A3.
3. **Issuing company:** use the built-in Company. The contract's Company decides the number prefix (custom field *Apparel Contract Prefix* on Company; falls back to Apparel Settings, default `CTXGVN`) and the bank account (the Company's default bank account). Two companies are expected (Cortex VN and Cortex Fashion HK). Done.

## Slice A2 status

| Item | State |
|---|---|
| A1 percent of product cost; profit as markup | Built, golden-tested against the reference costing |
| A2 per-metre fabric heads (export / import) | Built |
| A3 cost heads re-seeded from the costing sheet (16) + pcs per carton | Built. A patch updates existing sites |
| A4 contract number `PREFIX YY.MM.###`, monthly counter, Company prefix | Built, tested (restarts at 001 each month) |
| A5 tolerance bands 15 / 10 / 7.5 / 5 | Corrected in tests and the template fixture; warning above the top band. The bands themselves are template data, entered per customer |
| A6 duplicate POM code allowed (code + name + size) | Built, tested |
| A7 UOM, conversion and price currency per material row | Built, tested |
| A8 allowance % per trim type / customer | **Not done.** It drives requisitions and the production card, which are parked. Wastage % per costing row already exists |
| B Cost Sheet header, sign-off chain, local-currency price | Built |
| B Tech Pack buyer details, POM local name, ± tolerance, fit rounds, BOM codes | Built |
| B Sales Contract header, lines, ship-to / PO size rows, terms, revision, bank account | Built |

Known gaps in A2:
- Sign-offs do not reset when the costing is edited afterwards (margin approval does).
- Demo records in the dev site that were made before A2 (for example contract `CTXG-2026-11-001`) keep the old shape and number format. They are dev data only.
- The "bank account comes from the Company" test is skipped on the dev site (no company bank account exists).
- Contract and quotation print formats are slice A4.

## Risks

- Documents contain real bank, tax and customs identifiers. Keep them on Company / Bank Account only, never in seeds, tests or specs.
- Several workbooks have `#REF!` and typos. AI extraction needs a review step before anything is submitted.
- The 322 MB zip is untracked in the repo root. Keep it out of any commit.
