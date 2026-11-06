# How an order moves through the ERP, and where each paper goes

**Written 2026-11-05.** Traced on one real set of papers: style **C2027-S84-304**, buyer PO **69785 / EM92409** (1,462 pcs, one colour). This was done **on paper against the ERP's actual fields**. The S84 order has not been entered into the ERP; nothing here has been tried in a browser.

## 1. The shape of it

The ERP follows the order from the buyer's email to the money in the bank. Each step is one document. A document is created from the one before it (a button), so you re-type almost nothing. Every document made after the contract carries the **contract number** (for example `CTXGVN25.09.001-PL-01` is the first packing list of that contract). Search the contract number in *Contract Trail* to see the whole life of an order.

There are four decks on the main page: **Apparel** (merchandising), **Apparel Production**, **Apparel Quality**, **Apparel Shipping**.

## 2. The order, step by step

| # | Step | Deck / document | You enter or attach | Comes from this paper | How the next step starts |
|---|---|---|---|---|---|
| 1 | Buyer sends the style | Apparel / **Inquiry** (Opportunity) | customer, style, season, target price and qty, delivery window | the email | link the Tech Pack to the inquiry |
| 2 | Record what the buyer sent | Apparel / **Tech Pack** | style no, fabric content, wash code, colours, sizes, **measurements with tolerance and grades**, **buyer BOM rows** (fabric, trims, labels, buttons with item code and quantity), fit rounds, images and the PDF | tech pack grade sheet, fit PDF, **BOM (STY360)** | *Create Cost Sheet* |
| 3 | Cost it | Apparel / **Cost Sheet** | materials (consumption, wastage %, rate, fabric options), cost heads, margin | **your costing sheets** (see section 4) | *Start Negotiation* |
| 4 | Negotiate | Apparel / **Price Negotiation** | every offer and counter, the agreed price per style | emails | *Create Quotation* |
| 5 | Quote | Apparel / **Quotation** | nothing extra; it carries the price | | *Create Sales Contract* |
| 6 | Contract | Apparel / **Sales Contract** | one line per style and colour, size breakdown, ex-factory, ETD, in-warehouse, payment basis, terms | **the buyer's PO** and your sales contract | *Create Sales Order* |
| 7 | Order | **Sales Order** | (made for you) | | |
| 8 | Plan and approve | Apparel / **Factory Allocation**, **Sample Approval**, **PP Meeting** | factory and lines; each sample and its result; the meeting | PO notes (TOP, PP, customer samples), PP meeting form | gates the start of bulk |
| 9 | Fabric | Apparel / **Fabric Requisition** → Purchase Order → receipt → **Fabric Inspection** | consumption (marker, cost sheet or tech pack), allowance %, stock | **FR form**, the **fabric sales contract**, marker sheet, roll lists | |
| 10 | Trims | Apparel / **Trim Requisition** → Purchase Order → receipt → **Trim Inspection** | which trims, stock used, supplier | **TR form** | |
| 11 | Track | Apparel / **Order T&A** and WIP Board | (automatic, stamped by the documents above) | the WIP sheet | |
| 12 | Production | **Apparel Production** / **Production Card**, Pilot Run, Cut Plan, Lay Report, Line Input, Daily Line Report, Line QC Report | the order cards and daily floor numbers | production card, trim card, OB sheet, daily reports | |
| 13 | Wash and other processes | Production / **Subcontract Challan → Return → Settlement** | pieces sent, received, damaged; the vendor's rate | wash contract and statements | |
| 14 | Finishing, packing | Production / **Finishing Receipt**; **Apparel Quality** / **Needle Detector Log**, **Packing List** | pieces by colour and size, carton weights and sizes | packing list sheets | |
| 15 | Final inspection | Quality / **Final Inspection** | lot, defects found, tests, result | final inspection report form | an accepted lot opens the ship gate |
| 16 | Ship | **Apparel Shipping** / **Shipment** → **Delivery Note** | booking, vessel, bill of lading, customs declaration, weights | booking note, B/L, customs papers | *Make Delivery Notes* |
| 17 | Invoice | Shipping / **Sales Invoice** (from the Shipment: *Prepare Invoices*, then *Submit Invoices*) | nothing; it takes the delivery note | commercial invoice | |
| 18 | Get paid | Shipping / **Payment Entry**, *Log Follow-up*, **Receivables Follow-up** report | receipts, promises, calls | bank advice, receivables sheet | |
| 19 | Claims | Shipping / **Buyer Claim** | claim, evidence | buyer's complaint | credit note |
| 20 | Close | Sales Order button **Commercial Close** | | | |

Freight cost: put the forwarder's quote in as a **Supplier Quotation** (pick the shipment on it), and their bill as a **Purchase Invoice** with the same shipment. The *Freight Allocation* report shares it over the orders on board.

## 3. Before the first order (one-time set-up)

1. **Companies:** the factory (Cortex Vietnam), the trading company (Cortex Fashion HK) and the fabric company (Cortex Textile FZE) each need to be a Company if their books are kept in the ERP. For a buyer billed through HK, set on the Customer: *Invoice Through Group Company* = HK, plus the transfer-price basis. HK and the factory each need an internal Customer and the factory needs an internal Supplier for FZE.
2. **Masters:** Customer (with payment terms and a contract template), Supplier, Items for fabrics and trims, Item Attributes *Size* and *Colour*, Warehouses (fabric store, cutting, finished goods), Holiday List, Bank Account on the company.
3. **Apparel Settings:** warehouses, wash penalty rule, GS1 prefix for SSCC (blank = off), AQL plan, reminder days.
4. **Costing Parameter:** your rates (CMT, wash, overhead, agent commission) by customer and product type.
5. **AQL plan:** only codes K, L and M (lots of 1,201 to 35,000 pieces) are filled in. QA must complete the rest from ISO 2859-1 before inspecting smaller lots.

## 4. Where the costing sheets go

There is **one** costing document, **Cost Sheet** (Apparel deck). It is made from the Tech Pack with *Create Cost Sheet*.

- **`APPAREL_COSTING_DETAILED_REVISED.xlsx`** (raw materials, process charges, other expenses as a percent, profit as a markup) is the layout of the Cost Sheet. It is the test case for the maths (FOB 14.3748 on 5,500 pcs).
- **`INTERNAL COSTING.xlsx`** (one line per style: order qty, average yards, +3 %, fabric required, fabric price, cuttable width, wash) is the *material lines* of the same Cost Sheet: *consumption*, *wastage %*, *rate*, *price currency and exchange rate*, *cuttable width*. It is not a separate document.
- Rates you reuse for every order (CMT, wash, testing, overhead, bank, agent commission) live in **Costing Parameter**, not in each sheet.
- The sheet's price goes to **Price Negotiation**, then the **Quotation**, and the agreed price must equal the **Sales Contract** price (the ERP checks).

## 5. S84 traced through the papers

| Paper (S84) | Value | Where it lands | Fits? |
|---|---|---|---|
| Buyer PO 69785 | PO 69785 / cross ref EM92409 | Contract line *Buyer PO code*; Sales Order line *Buyer PO* | Yes |
| | Vendor Cortex Fashion (HK), ship-to EMJ Los Angeles | Customer EMJ; invoice route via HK; ship-to on the Packing List | Yes (needs the set-up in section 3) |
| | Terms 15 days ROG, DDP | Contract: payment basis *Days after Receipt of Goods*, 15 days; Incoterm DDP | Yes |
| | X-factory / in-warehouse 01/30/2026 | Contract line dates (ex-factory 12-26, ETD 01-02, in-warehouse 01-30 from the contract) | Yes |
| | 1 colour, sizes XS 270, S 436, M 421, L 223, XL 112 = 1,462 | Contract size breakdown; Sales Order variants | Yes. The PO also prints XXS and XXL columns with no quantity |
| | $16.30 DDP; fabric price $3.90 | Contract rate; Cost Sheet fabric row | Yes |
| | TOP: 1 pc per colour, size S, 10 days before ex-factory, **$200 chargeback if late**; customer samples 2 S + 1 L, 10 days after fit approval; PP only if requested | **Sample Requirement** (type TOP, qty 1, size S, due basis *Ex-Factory*, chargeback 200; Customer Sample; PP = *If Raised*) | Yes, built for exactly this |
| | Packing: "customer #6 / pack #2 / fold #2 green colour sticker"; no price tickets, no barcode sticker | Tech Pack *packing notes*, then the Production Card packing text | **Partly**: stored as text, not as yes/no fields |
| | Yield 1.99 yd, weight 92 gsm, width 56", construction V50DxR60S/191x94, content 51/49 | Tech Pack fabric content; material row (consumption, gsm, width); the fabric Item | Yes (construction lives on the fabric Item) |
| | **Production lead time 45 days** | none | **No field**; put it in the T&A template or the notes |
| | Claims within 5 days, cancellation 5 days | Contract holds 60 days (quality) and 30 days (quantity), which are what the ERP uses | **Conflict between the PO and the contract**, not an ERP problem; decide which wins |
| Tech pack grade sheet | season, wash code 304, status AWC, designer, tech designer, factory, sample size S, XS–XL; about 30 POMs with tolerance and five sizes | Tech Pack header, sizes, measurements | Yes. Row with no POM code (sleeve cap height) and a code used twice (T210) are accepted. The Vietnamese POM names have no column (use remarks) |
| BOM (STY360) | fusing 0.2 yd, self fabric 1.69 yd, a second fabric line 0.3 yd, size label, main label, care label (5 languages), size tab, thread, **button BT088 on two lines (1 + 7)** | Tech Pack material rows with the buyer item code | Yes. The two button lines must be added together (8 per piece); check the Trim Requisition does |
| Trim request | labels 1,462 + 10 % = 1,608.2; buttons 12,865.6 (8 × 1,462 × 1.1); "have stock, no need to order" | Trim Requisition: allowance %, **stock used** | Yes |
| Internal costing | avg 1.5967 yd, +3 % = 1.6925, fabric required 2,474.4 yd, fabric price 3.9 | Cost Sheet material row (yard, wastage 3 %) | Yes. **The unit of 3.9 is unclear** (per yard or per metre, USD or RMB) |
| Bulk marker | actual bulk 1.26 m per piece | Fabric Requisition *consumption source = Bulk Marker* | Yes |
| Fabric sales contract (FZE to VN) CTXVNF25.09.005-A | 2,064.5 m at $3.77/m CIF Vietnam, ex-mill 10-10, sea Shanghai to Da Nang, 100 % TT, ±3 % per colour, 7 days delay, 20 points per 100 yd | **Purchase Order** to an internal supplier, with the supplier contract no, ports, mode; **Material Purchase Terms** for the ±3 % and the delay | Yes |
| | | | **Check:** fabric ordered 2,064.5 m; the costing needs about 2,263 m (2,474 yd); the BOM says 1.99 yd per piece (2,660 m); the marker gives about 1,842 m. Four numbers for one need |
| Invoice and packing list | 1,520 shipped, 64 cartons, carton heights 14–22 cm, tail carton | Packing List, Shipment, Sales Invoice | Yes |
| | **Invoice price $16.85; contract and PO $16.30** | | **The ERP will not invoice above the Sales Order price.** Change the contract and order price first, or invoice at 16.30 |
| | **1,520 shipped against 1,462 ordered (+3.97 %)** | Delivery Note over-ship check against the contract band | Allowed (the 801–1,600 band is ±7.5 %); sizes +2.2 % to +6.25 %, all inside |
| | B/L 1.910 CBM against 1.597 CBM on the packing list (+19.6 %) | Shipment keeps both figures and flags the difference | Yes |
| | The invoice for the buyer uses the same number as the internal invoice | `<contract>-INV-<nn>`, same number on both legs | Yes |
| Customs declaration | number, FOB value, rate, cartons, weight | Shipment, *Export Declarations* table | Yes |

**Not in the zip for S84, so not checked:** a production card, a pilot run, a PP meeting record, a wash statement, a final inspection report, the T&A row (the WIP sheet shows other styles). The production card in the zip (`20445`) is another order; the ERP's Production Card follows that sheet.

## 6. What does not fit, in plain words

1. **The invoice price.** The company invoices at a price that differs from the contract (16.85 against 16.30). The ERP is strict here on purpose. Decide the process: revise the contract price, or invoice at the contract price.
2. **The three-price habit.** One invoice number appears with different unit prices on the customs copy and the forwarder copy. The ERP prints each invoice from its own record and will not make a second value on one number. Ask your customs broker before relying on it.
3. **Packing instructions as yes/no flags** (price ticket, barcode) are text.
4. **Production lead time** per PO has no field.
5. **The two screens** (Order Desk, WIP Board) work on this server but cannot exist on the hosted site (see `HOSTED_CONSTRAINTS.md`).
6. **Fabric need has four numbers.** The ERP records which one you used and why (consumption source and allowance reason), but it cannot decide for you.

## 7. Good next step

Enter S84 into the dev ERP end to end (contract, order, tech pack, cost sheet, requisitions, a packing list and a shipment) and fix what breaks. Say if you want that.
