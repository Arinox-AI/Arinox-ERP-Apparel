# Phase 1 — Win the order (inquiry → costing → negotiation → contract)

**Status:** Built (dev site) — pending user review
**Module:** Arinox Apparel
**Spec form:** one consolidated spec for the phase (user asked to plan and build in one pass, 2026-11-04).

## The flow

```
Email (BOM + tech pack)  ──AI agent extracts──►  Opportunity (inquiry, ERPNext)
                                                    │
                                                    ▼
                                               Tech Pack  (images, sizes, measurements, colourways, buyer BOM)
                                                    │  "Create Cost Sheet"
                                                    ▼
Costing Parameter (rates per customer × product type) ─► Cost Sheet (materials w/ fabric options, cost heads, FOB, margin)
                                                    │  "Start / Add to Negotiation"
                                                    ▼
                                            Price Negotiation (every offer / counter, per style, with margin)
                                                    │  "Create Quotation"
                                                    ▼
                                               Quotation (ERPNext) ── each submit logs an "Our Offer" round
                                                    │  "Create Sales Contract"
                                                    ▼
Sales Contract Template (tolerance bands, shipping days, claims, ports, terms) ─► Sales Contract (≤ 8 SKUs, per-line dates, size breakdown)
                                                    │  "Create Sales Order"
                                                    ▼
                                               Sales Order (ERPNext, one line per style-colour-size variant)
```

The email-reading AI agent is out of scope. It writes into Opportunity, Tech Pack, Cost Sheet and Price Negotiation through the REST API. `get_costing_context` gives it rates and past costings in one call.

## What ERPNext already has, and how it is used

| Need | ERPNext object | Decision |
|---|---|---|
| Buyer inquiry | Opportunity | **Reuse** + custom fields (product type, season, target FOB/qty, delivery window, source email) |
| Priced offer to buyer | Quotation | **Reuse** + custom fields (price negotiation link; per line: cost sheet, style item, style no). Lines use one generic non-stock item `APPAREL-STYLE` because ERPNext refuses template items on a Quotation (`erpnext/stock/get_item_details.py:426`) |
| Legal contract | Contract (CRM) | **Not used.** Generic party contract with free-text terms and no item lines, prices, per-line dates or tolerance |
| Contract clauses | Terms and Conditions | **Reuse**, linked from Sales Contract Template |
| Payment terms / Incoterm | Payment Terms Template, Incoterm | **Reuse** |
| Operational order | Sales Order | **Reuse** + custom fields (sales contract; per line ETD, in-warehouse date, tolerance %) |
| Style / SKU | Item template + variants (attributes Colour, Size) | **Reuse** |
| Fabric / trim master | Item + Item Price | **Reuse** |

## New doctypes

| Doctype | Kind | Purpose |
|---|---|---|
| Apparel Settings | Single | Max SKUs per contract (8), placeholder words (TBA, TBD…), default margin floor, approval tolerance % |
| Product Type | Master | Garment category used for costing rates (Knit Tee, Woven Shirt, Denim Bottom…) |
| Cost Head | Master | Costing slots, calc type, sequence, mandatory flag |
| Costing Parameter (+ Costing Parameter Rate) | Master | Effective-dated rates per customer × product type, margin floor |
| Tech Pack (+ Image, Size, Measurement, Colour, Material) | Submittable, amend = revision | Everything the buyer sent, structured |
| Cost Sheet (+ Material, Charge) | Submittable, amend = revision | Garment price build-up, fabric options, margin, approval |
| Price Negotiation (+ Round, Style) | Plain | Every offer and counter, with the margin at that price; agreed price per style |
| Sales Contract Template (+ Tolerance Band) | Master | Buyer's standard terms: tolerance bands, ex-factory→ETD days, transit days, claim windows, AQL, ports, clauses |
| Sales Contract (+ Item, Size Qty) | Submittable | The legal garment contract, max 8 SKUs, number `PREFIX` + `YY.MM.###` (e.g. `CTXGVN26.09.001`, counter restarts monthly, prefix from the issuing Company) |

## Costing maths (Cost Sheet)

Follows `APPAREL_COSTING_DETAILED_REVISED.xlsx`. The reference sheet (5,500 pcs) is the golden test: FOB 14.3748 USD, 359,370 VND.

- Materials: `amount = consumption × (1 + wastage%) × conversion factor × rate × exchange rate`. Carton rows use `1 ÷ pcs per carton`. Rows sharing an `option_group` are fabric/trim options (max 4); exactly one is selected and only selected rows count. Fabric, Lining and Contrast Fabric rows are fabric; the fabric metres (from each row's UOM: Meter, Yard, cm, inch) drive the per-metre heads.
- Cost heads, in sequence:
  - Per Piece → `rate`; Per SAM Minute → `rate × SAM`; **Per Metre of Fabric** → `rate × fabric metres` (fabric export / import cost)
  - Percent of Material → `rate% × material cost`
  - **Percent of Product Cost** → `rate% × (materials + all per-piece / per-metre heads)`. Used for rejection, finance, bank, freight, overhead, agent commission
  - **Percent of Subtotal** → `rate% × cost so far`. Used for **profit as a markup on cost**
  - Percent of Price → gross-up on the selling price (kept for customers who price that way)
- Profit heads are kept out of cost. `computed price = (cost + profit) ÷ (1 − Σ price-based %)`.
- `quoted price` defaults to the computed price (2 dp) and can be overridden. The local-currency price is `quoted × rate`.
- **Margin on price** (what the floor and negotiation use) = `quoted − cost`, as % of price. **Markup on cost** is shown beside it.
- Four sign-off steps (fabric cost checked, first costing, 2nd check, final approval). Required before submit only when Apparel Settings → Require Costing Sign-off is on (off by default).

## Rules enforced in Python (an API write cannot skip them)

| Rule | Where |
|---|---|
| Wastage % > 0 needs a reason | Cost Sheet validate |
| 2–4 options per option group, exactly one selected | Cost Sheet validate |
| Every mandatory cost head present; rate 0 needs "Not Applicable" ticked | Cost Sheet submit |
| Margin below floor needs Costing Manager approval; a price move > tolerance after approval resets it | Cost Sheet validate / submit |
| Quotation line with a cost sheet: cost sheet must be submitted; rate below its quoted price needs a re-costed sheet | Quotation validate (hook) |
| Max 8 SKUs (style × colour) per contract | Sales Contract validate |
| No placeholder text (TBA, TBD, N/A, -) on a submitted contract | Sales Contract submit |
| Contract rate = quotation rate for the same cost sheet | Sales Contract validate |
| ex-factory ≤ ETD ≤ in-warehouse; ETD and in-warehouse auto-filled from template days | Sales Contract validate |
| Size breakdown must equal line quantity | Sales Contract submit |
| Quantity tolerance % taken from the template band matching line quantity | Sales Contract validate |
| One Sales Order per contract | Sales Contract / Sales Order hooks |

## Desk

- **Workspace "Apparel"**: shortcuts, number cards, chart, and link cards for Pre-Sales, Contract, Masters and Reports. It has a v16 Workspace Sidebar and a Desktop Icon.
- **Dashboard "Apparel Pre-Sales"**: number cards and charts.
- **Page `apparel-order-desk`**: the pipeline board (Inquiry → Tech Pack → Costing → Negotiation → Quoted → Contract → Order).
- **Reports**: Inquiry to Contract Tracker, Costing Margin Review, Negotiation History.
- **Connections**: the dashboards of Opportunity, Quotation and Customer show the apparel documents. Each new doctype shows its downstream documents.

## Roles

- Apparel Merchandiser: create and submit Tech Pack, Cost Sheet and Sales Contract; run negotiations.
- Apparel Costing Manager: everything above, plus Cost Head, Costing Parameter and margin approval.

## Open questions

1. Name collision on the hosted site: it already has a UI-made `Cost Sheet`, `Sales Contract` and `custom_cost_sheet`. The app's custom fields use the `apparel_` prefix to avoid this. The doctype names still need a migration decision before install there.
2. Quantity allowance: the contract clause starts "Each size / style and ..." and is cut off in the sample. Tolerance is applied per contract line (style × colour) today. Confirm whether it applies per size.
3. Above 3,000 pcs the sample contract defines no tolerance. A warning shows on the contract line.
