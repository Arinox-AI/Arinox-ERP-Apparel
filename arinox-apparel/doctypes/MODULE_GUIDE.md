# Arinox Apparel: DocType Guide

This guide lists every custom DocType in the `Arinox Apparel` module (app `arinox_apparel`), what each one holds, which deck (workspace section) it belongs in, and every field, read straight from the DocType JSON files.

**Terms**
- **Parent DocType**: a document you create and save (for example Cost Sheet, Sales Contract). It is a table in the database.
- **Child table**: a DocType that only exists inside a parent (Table field). Each row of the grid is one record in the child table. It is listed under its parent and shares the parent's deck.
- **Settings (single)**: one record per site (Apparel Settings).
- **Submittable**: the document has Draft, Submitted and Cancelled states. Submitted documents are locked and changes are made by amending.
- **Deck**: the workspace section on the Apparel desk page where users find the DocType. The workspace is `Apparel` (`workspace/apparel/apparel.json`).

The sections below are generated from the DocType JSON, so the field lists are exact. The purposes and deck assignments are written by hand.

**Totals:** 128 DocTypes: 51 parent documents, 76 child tables, 1 settings single.

## 1. Deck map

| Deck | Where it sits | Parent documents | Child tables | Total |
|---|---|---|---|---|
| Pre-Sales | workspace card exists | 3 | 11 | 14 |
| Contract & Order | workspace card exists | 2 | 2 | 4 |
| Plan and Approve | workspace section exists | 6 | 7 | 13 |
| Materials | workspace section exists | 7 | 9 | 16 |
| Production | NOT on workspace yet; add a section | 19 | 32 | 51 |
| Shipping & Claims | NOT on workspace; Phase E, partly wired | 1 | 5 | 6 |
| Setup | workspace card exists | 14 | 7 | 21 |

Shared child tables (appear under two parents): `Sample Measurement` (Shared: Production (Pilot Run) and Plan and Approve (Sample Approval)); `Sample Shrinkage Reading` (Shared: Materials (Fabric Inspection) and Plan and Approve (Sample Approval)); `Sales Contract Tolerance Band` (Shared: Contract & Order (Sales Contract) and Setup (Sales Contract Template)).

Settings child tables (Apparel Sample Rule, Fabric Sampling Band, Learning Curve Day, Traffic Light Rule) sit under Setup, with Apparel Settings.

Not in any deck yet: the Phase D Production doctypes are built but not on the workspace. Add a `Production` section (and `Shipping & Claims` once Phase E ships) to the workspace before users can find them.

## Deck: Pre-Sales

Where: workspace card exists.

### Tech Pack

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Series field (the 'Series' select on the form)
- **Deck:** Pre-Sales

**What it holds:** Buyer tech pack (submitted): style identification, buyer details, sizes and base size, measurement chart (POM), colourways, buyer BOM materials, construction notes, wash and care, images, and fit rounds. Source fields record whether it came by email, portal or AI extraction.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Series | `naming_series` | Select | TP-.YYYY.- | Yes |
| 2 | - | Customer | `customer` | Link | Customer | Yes |
| 3 | - | Customer Name | `customer_name` | Data |  |  |
| 4 | - | Inquiry (Opportunity) | `opportunity` | Link | Opportunity |  |
| 5 | - | Buyer Style No | `style_no` | Data |  | Yes |
| 6 | - | Style Name | `style_name` | Data |  |  |
| 7 | - | Season | `season` | Data |  |  |
| 8 | - | Product Type | `product_type` | Link | Product Type |  |
| 9 | - | Style Item (template) | `style_item` | Link | Item |  |
| 10 | - | Buyer Revision | `revision` | Data |  |  |
| 11 | - | Received On | `received_on` | Date |  |  |
| 12 | - | Status | `status` | Select | Draft, Under Review, Accepted, Cancelled |  |
| 13 | Buyer Details | Fabric Code | `fabric_code` | Data |  |  |
| 14 | Buyer Details | Wash Code | `wash_code` | Data |  |  |
| 15 | Buyer Details | Wash Description | `wash_description` | Data |  |  |
| 16 | Buyer Details | Fabric Content | `fabric_content` | Data |  |  |
| 17 | Buyer Details | Group / Category | `group_name` | Data |  |  |
| 18 | Buyer Details | Division | `division` | Data |  |  |
| 19 | Buyer Details | Designer | `designer` | Data |  |  |
| 20 | Buyer Details | Tech Designer | `tech_designer` | Data |  |  |
| 21 | Buyer Details | Factory Code | `factory` | Data |  |  |
| 22 | Buyer Details | Sample Size | `sample_size` | Data |  |  |
| 23 | Buyer Details | Latest Fit Result | `fit_status` | Select | (blank), Pending, Submitted, AWC, Approved, Rejected |  |
| 24 | Files | Front Image | `front_image` | Attach Image |  |  |
| 25 | Files | Tech Pack File | `tech_pack_file` | Attach |  |  |
| 26 | Files | Back Image | `back_image` | Attach Image |  |  |
| 27 | Files | Buyer BOM File | `buyer_bom_file` | Attach |  |  |
| 28 | Source | Received Via | `source` | Select | Email, Buyer Portal, Manual, Other |  |
| 29 | Source | Email / Message Reference | `source_reference` | Data |  |  |
| 30 | Source | Extracted by AI Agent | `extracted_by_ai` | Check |  |  |
| 31 | Source | Extraction Confidence | `extraction_confidence` | Percent |  |  |
| 32 | Source | AI Extraction Notes | `ai_extraction_notes` | Small Text |  |  |
| 33 | Sizes & Measurements | Size Range | `size_range` | Data |  |  |
| 34 | Sizes & Measurements | Measurement Unit | `measurement_uom` | Select | cm, inch |  |
| 35 | Sizes & Measurements | Base Size | `base_size` | Data |  |  |
| 36 | Sizes | Sizes | `sizes` | Table | Tech Pack Size |  |
| 37 | Measurement Chart | Measurement Matrix | `measurement_matrix` | HTML |  |  |
| 38 | Measurement Chart | Measurements | `measurements` | Table | Tech Pack Measurement |  |
| 39 | Colours & Materials | Colourways | `colours` | Table | Tech Pack Colour |  |
| 40 | Buyer BOM | Materials | `materials` | Table | Tech Pack Material |  |
| 41 | Construction & Images | Construction Notes | `construction_notes` | Text Editor |  |  |
| 42 | Construction & Images | Wash & Care | `wash_care` | Small Text |  |  |
| 43 | Construction & Images | Packing Notes | `packing_notes` | Small Text |  |  |
| 44 | Images | Images | `images` | Table | Tech Pack Image |  |
| 45 | Fit Rounds | Fit / PP / TOP rounds | `fit_rounds` | Table | Tech Pack Fit Round |  |
| 46 | Fit Rounds | Amended From | `amended_from` | Link | Tech Pack |  |

### Tech Pack Colour

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. Colourway: name, buyer colour code, Pantone reference, remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Buyer Colour Code | `buyer_colour_code` | Data |  |  |
| 3 | - | Pantone / Reference | `pantone` | Data |  |  |
| 4 | - | Remarks | `remarks` | Data |  |  |

### Tech Pack Fit Round

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. Fit round (proto, 1st fit, PP, TOP...) with date, result and buyer comments.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Round | `fit_round` | Select | Proto, 1st Fit, 2nd Fit, 3rd Fit, PP, TOP, Other | Yes |
| 2 | - | Date | `round_date` | Date |  |  |
| 3 | - | Result | `round_status` | Select | Pending, Submitted, AWC, Approved, Rejected | Yes |
| 4 | - | Buyer Comments | `comments` | Small Text |  |  |
| 5 | - | Comment File | `comments_file` | Attach |  |  |

### Tech Pack Image

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. Image of the garment (front, back, side, detail, artwork, label) with caption.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | View | `view` | Select | Front, Back, Side, Detail, Artwork, Label, Other |  |
| 2 | - | Image | `image` | Attach Image |  | Yes |
| 3 | - | Caption | `caption` | Data |  |  |

### Tech Pack Material

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. BOM line: type, description, linked item, placement, consumption per piece, composition, GSM, width, colour, nominated supplier, buyer-supplied flag.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Type | `material_type` | Select | Fabric, Lining, Contrast Fabric, Trim, Label, Packaging, Thread, Fusing, Other | Yes |
| 2 | - | Description | `description` | Data |  | Yes |
| 3 | - | Item | `item` | Link | Item |  |
| 4 | - | Placement | `placement` | Data |  |  |
| 5 | - | Consumption / pc | `consumption` | Float |  |  |
| 6 | - | UOM | `uom` | Link | UOM |  |
| 7 | - | Composition | `composition` | Data |  |  |
| 8 | - | GSM / Weight | `gsm` | Data |  |  |
| 9 | - | Width | `width` | Data |  |  |
| 10 | - | Colour | `colour` | Data |  |  |
| 11 | - | Nominated Supplier | `nominated_supplier` | Link | Supplier |  |
| 12 | - | Buyer Supplied | `buyer_supplied` | Check |  |  |
| 13 | - | Buyer Item Code | `buyer_item_code` | Data |  |  |
| 14 | - | Job Code | `job_code` | Data |  |  |
| 15 | - | Applies to Size | `size_applicability` | Data |  |  |
| 16 | - | Remarks | `remarks` | Small Text |  |  |

### Tech Pack Measurement

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. Point of measure (POM code, name), size, spec value, plus and minus tolerance, and how to measure it.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | POM Code | `pom_code` | Data |  |  |
| 2 | - | Point of Measure | `point_of_measure` | Data |  | Yes |
| 4 | - | Size | `size` | Data |  | Yes |
| 5 | - | Value | `value` | Float |  |  |
| 6 | - | Tol + | `tolerance_plus` | Float |  |  |
| 7 | - | Tol − | `tolerance_minus` | Float |  |  |
| 8 | - | How to Measure | `how_to_measure` | Small Text |  |  |

### Tech Pack Size

- **Type:** Child table (child of `Tech Pack`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Tech Pack. Size in the range, its ratio and whether it is the base size.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Size | `size` | Data |  | Yes |
| 2 | - | Size Ratio | `ratio` | Float |  |  |
| 3 | - | Base Size | `is_base_size` | Check |  |  |

### Cost Sheet

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Series field (the 'Series' select on the form)
- **Deck:** Pre-Sales

**What it holds:** Costing for a style: customer, buyer style, product type, SAM, currency, costing parameter, revision chain, materials (fabric options and trims), cost heads, FOB price, margin and floor check, order value, and sign-off trail. Submittable.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Series | `naming_series` | Select | CS-.YYYY.- | Yes |
| 2 | - | Customer | `customer` | Link | Customer | Yes |
| 3 | - | Customer Name | `customer_name` | Data |  |  |
| 4 | - | Inquiry (Opportunity) | `opportunity` | Link | Opportunity |  |
| 5 | - | Tech Pack | `tech_pack` | Link | Tech Pack |  |
| 6 | - | Buyer Style No | `style_no` | Data |  | Yes |
| 7 | - | Style Name | `style_name` | Data |  |  |
| 8 | - | Product Type | `product_type` | Link | Product Type | Yes |
| 9 | - | Style Item (template) | `style_item` | Link | Item |  |
| 10 | - | Costing Date | `costing_date` | Date |  | Yes |
| 11 | - | Currency | `currency` | Link | Currency | Yes |
| 12 | - | Expected Order Qty | `order_qty` | Int |  |  |
| 13 | - | SAM (minutes) | `sam` | Float |  |  |
| 14 | - | Costing Parameter | `costing_parameter` | Link | Costing Parameter |  |
| 15 | - | Based On (previous costing) | `reference_cost_sheet` | Link | Cost Sheet |  |
| 16 | - | Revision | `revision_no` | Int |  |  |
| 17 | - | Margin Approval | `approval_status` | Select | Not Required, Pending, Approved, Rejected |  |
| 18 | Costing Header | Factory / Company | `company` | Link | Company |  |
| 19 | Costing Header | Season | `season` | Data |  |  |
| 20 | Costing Header | FOB Port | `fob_port` | Data |  |  |
| 21 | Costing Header | Pcs per Carton | `pcs_per_carton` | Int |  |  |
| 22 | Costing Header | Front Image | `front_image` | Attach Image |  |  |
| 23 | Costing Header | Back Image | `back_image` | Attach Image |  |  |
| 24 | Costing Header | PO Date | `po_date` | Date |  |  |
| 25 | Costing Header | Required In-Warehouse Date | `in_warehouse_date` | Date |  |  |
| 26 | Costing Header | Local Currency | `local_currency` | Link | Currency |  |
| 27 | Costing Header | Local Currency per Sheet Currency | `local_exchange_rate` | Float |  |  |
| 28 | Materials | Materials (fabric options & trims) | `materials` | Table | Cost Sheet Material |  |
| 29 | Cost Heads | Cost Heads | `charges` | Table | Cost Sheet Charge |  |
| 30 | Summary | Fabric Cost / pc | `fabric_cost` | Currency | currency |  |
| 31 | Summary | Trims & Other Material / pc | `trim_cost` | Currency | currency |  |
| 32 | Summary | Material Cost / pc | `material_cost` | Currency | currency |  |
| 33 | Summary | Other Cost Heads / pc | `conversion_cost` | Currency | currency |  |
| 34 | Summary | Cost before price-based charges | `subtotal` | Currency | currency |  |
| 35 | Summary | Price-based Charges % (excl. profit) | `price_cost_pct` | Percent |  |  |
| 36 | Summary | Profit % (from cost heads) | `profit_pct` | Percent |  |  |
| 37 | Summary | Computed FOB / pc | `computed_price` | Currency | currency |  |
| 38 | Summary | Quoted FOB / pc | `quoted_price` | Currency | currency |  |
| 39 | Margin | Total Cost at Quoted Price | `total_cost_at_quote` | Currency | currency |  |
| 40 | Margin | Margin / pc | `margin_amount` | Currency | currency |  |
| 41 | Margin | Margin % | `margin_pct` | Percent |  |  |
| 42 | Margin | Margin Floor % | `margin_floor_pct` | Percent |  |  |
| 43 | Margin | Below Floor | `below_floor` | Check |  |  |
| 44 | Margin | Order Value | `order_value` | Currency | currency |  |
| 45 | Margin | Fabric Metres / pc (incl. wastage) | `fabric_metres` | Float |  |  |
| 46 | Margin | Product Cost / pc (materials + process) | `product_cost` | Currency | currency |  |
| 47 | Margin | Profit / pc (markup on cost) | `profit_amount` | Currency | currency |  |
| 48 | Margin | Markup on Cost % at Quoted Price | `markup_pct` | Percent |  |  |
| 49 | Margin | Quoted FOB (local currency) | `quoted_price_local` | Currency | local_currency |  |
| 50 | Approval | Approved By | `approved_by` | Link | User |  |
| 51 | Approval | Approved On | `approved_on` | Datetime |  |  |
| 52 | Approval | Approved at Price | `approved_price` | Currency | currency |  |
| 53 | Approval | Approval Remarks | `approval_remarks` | Small Text |  |  |
| 54 | Notes | Costing Notes (AI / merchandiser) | `ai_notes` | Small Text |  |  |
| 55 | Sign-off | Costing Sign-off | `signoffs` | Table | Cost Sheet Signoff |  |
| 56 | Sign-off | Amended From | `amended_from` | Link | Cost Sheet |  |

### Cost Sheet Charge

- **Type:** Child table (child of `Cost Sheet`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Cost Sheet. One cost head line with rate, amount per piece, source (parameter, manual, AI or previous costing) and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Cost Head | `cost_head` | Link | Cost Head | Yes |
| 2 | - | Calculation | `calc_type` | Data |  |  |
| 3 | - | Rate | `rate` | Float |  |  |
| 4 | - | N/A | `not_applicable` | Check |  |  |
| 5 | - | Amount / pc | `amount` | Currency | currency |  |
| 6 | - | Source | `source` | Select | Parameter, Manual, AI, Previous Costing |  |
| 7 | - | Sequence | `sequence` | Int |  |  |
| 8 | - | Group | `head_group` | Data |  |  |
| 9 | - | Remarks | `remarks` | Data |  |  |

### Cost Sheet Material

- **Type:** Child table (child of `Cost Sheet`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Cost Sheet. One material line: type, description, consumption per piece, wastage %, rate, linked item and supplier, lab dip status, cuttable width, per-carton flag.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Type | `material_type` | Select | Fabric, Lining, Contrast Fabric, Trim, Label, Packaging, Thread, Fusing, Other | Yes |
| 2 | - | Option Group | `option_group` | Data |  |  |
| 3 | - | Selected | `is_selected` | Check |  |  |
| 4 | - | Description | `description` | Data |  | Yes |
| 5 | - | Consumption / pc | `consumption` | Float |  | Yes |
| 6 | - | Wastage % | `wastage_pct` | Percent |  |  |
| 7 | - | Rate | `rate` | Currency | currency |  |
| 8 | - | Amount / pc | `amount` | Currency | currency |  |
| 9 | - | Item | `item` | Link | Item |  |
| 10 | - | UOM | `uom` | Link | UOM |  |
| 11 | - | Wastage Reason | `wastage_reason` | Data |  |  |
| 12 | - | Supplier | `supplier` | Link | Supplier |  |
| 13 | - | Lab Dip Status | `lab_dip_status` | Select | (blank), Not Required, Submitted, Approved, Rejected |  |
| 14 | - | Cuttable Width | `cuttable_width` | Data |  |  |
| 15 | - | Rate UOM | `rate_uom` | Link | UOM |  |
| 16 | - | Rate UOM per Consumption UOM | `conversion_factor` | Float |  |  |
| 17 | - | Rate Currency | `price_currency` | Link | Currency |  |
| 18 | - | Rate Currency to Sheet Currency | `exchange_rate` | Float |  |  |
| 19 | - | Per Carton | `per_carton` | Check |  |  |
| 20 | - | Remarks | `remarks` | Small Text |  |  |

### Cost Sheet Signoff

- **Type:** Child table (child of `Cost Sheet`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Cost Sheet. Sign-off step (fabric cost checked, first costing done, second round checked, final approved) with user, time and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Step | `step` | Select | Fabric Cost Checked, First Costing Done, Second Round Checked, Final Checked & Approved | Yes |
| 2 | - | Signed By | `signed_by` | Link | User |  |
| 3 | - | Signed On | `signed_on` | Datetime |  |  |
| 4 | - | Remarks | `remarks` | Data |  |  |

### Price Negotiation

- **Type:** Parent document
- **Submittable:** no
- **Naming:** Series field (the 'Series' select on the form)
- **Deck:** Pre-Sales

**What it holds:** Negotiation log with a buyer for one customer: status (open, partly agreed, agreed, on hold, lost), latest quotation, and styles with rounds of offers and counter-offers.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Series | `naming_series` | Select | PN-.YYYY.- | Yes |
| 2 | - | Customer | `customer` | Link | Customer | Yes |
| 3 | - | Customer Name | `customer_name` | Data |  |  |
| 4 | - | Inquiry (Opportunity) | `opportunity` | Link | Opportunity |  |
| 5 | - | Currency | `currency` | Link | Currency | Yes |
| 6 | - | Status | `status` | Select | Open, Partly Agreed, Agreed, On Hold, Lost |  |
| 7 | - | Lost Reason | `lost_reason` | Small Text |  |  |
| 8 | - | Latest Quotation | `quotation` | Link | Quotation |  |
| 9 | Styles | Styles | `styles` | Table | Price Negotiation Style |  |
| 10 | Rounds (every offer and counter) | Rounds | `rounds` | Table | Price Negotiation Round |  |

### Price Negotiation Round

- **Type:** Child table (child of `Price Negotiation`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Price Negotiation. One offer or counter (buyer target, our offer, buyer counter, agreed, dropped) with date, price, quantity, margin, below-floor flag, channel and quotation.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Date | `round_date` | Date |  | Yes |
| 2 | - | Cost Sheet | `cost_sheet` | Link | Cost Sheet | Yes |
| 3 | - | Style | `style_no` | Data |  |  |
| 4 | - | Who / What | `direction` | Select | Buyer Target, Our Offer, Buyer Counter, Our Counter, Agreed, Dropped | Yes |
| 5 | - | Price / pc | `price` | Currency | currency |  |
| 6 | - | Qty | `qty` | Int |  |  |
| 7 | - | Margin % | `margin_pct` | Percent |  |  |
| 8 | - | Below Floor | `below_floor` | Check |  |  |
| 9 | - | Channel | `channel` | Select | Email, Call, Meeting, Portal, Other |  |
| 10 | - | Quotation | `quotation` | Link | Quotation |  |
| 11 | - | Remarks | `remarks` | Small Text |  |  |
| 12 | - | Attachment | `attachment` | Attach |  |  |
| 13 | - | Recorded By | `recorded_by` | Link | User |  |
| 14 | - | Recorded by AI Agent | `recorded_by_ai` | Check |  |  |

### Price Negotiation Style

- **Type:** Child table (child of `Price Negotiation`)
- **Submittable:** no
- **Deck:** Pre-Sales

**What it holds:** Child of Price Negotiation. Per style: linked cost sheet, quantity, costed FOB, our last price, buyer last price, agreed price and margin at agreed price.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Cost Sheet | `cost_sheet` | Link | Cost Sheet | Yes |
| 2 | - | Style | `style_no` | Data |  |  |
| 3 | - | Qty | `qty` | Int |  |  |
| 4 | - | Costed FOB | `cost_price` | Currency | currency |  |
| 5 | - | Our Last | `our_last_offer` | Currency | currency |  |
| 6 | - | Buyer Last | `buyer_last_offer` | Currency | currency |  |
| 7 | - | Agreed | `agreed_price` | Currency | currency |  |
| 8 | - | Margin @ Agreed | `margin_at_agreed` | Percent |  |  |
| 9 | - | Status | `style_status` | Select | Open, Agreed, Dropped |  |

## Deck: Contract & Order

Where: workspace card exists.

### Sales Contract

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Contract & Order

**What it holds:** Signed buyer contract (submittable): customer, buyer PO, currency, issuing company, status, SKU lines by style and colour, size breakdown, incoterm and shipment terms, shipping days, tolerances, claim windows, payment terms and revisions.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Customer | `customer` | Link | Customer | Yes |
| 2 | - | Customer Name | `customer_name` | Data |  |  |
| 3 | - | Contract Date | `contract_date` | Date |  | Yes |
| 4 | - | Buyer PO No | `buyer_po_no` | Data |  |  |
| 5 | - | Season | `season` | Data |  |  |
| 6 | - | Brand / Buyer Company | `brand` | Data |  |  |
| 7 | - | Division | `division` | Data |  |  |
| 8 | - | Buyer Contact | `buyer_contact` | Data |  |  |
| 9 | - | Merchant | `merchant` | Data |  |  |
| 10 | - | Quotation | `quotation` | Link | Quotation |  |
| 11 | - | Price Negotiation | `price_negotiation` | Link | Price Negotiation |  |
| 12 | - | Inquiry (Opportunity) | `opportunity` | Link | Opportunity |  |
| 13 | - | Currency | `currency` | Link | Currency | Yes |
| 14 | - | Issuing Company | `company` | Link | Company | Yes |
| 15 | - | Bank Account | `bank_account` | Link | Bank Account |  |
| 16 | - | Buyer Address | `customer_address` | Link | Address |  |
| 17 | - | Status | `status` | Select | Draft, Signed, Ordered, Cancelled |  |
| 18 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 19 | - | Total Qty | `total_qty` | Int |  |  |
| 20 | - | Total Amount | `total_amount` | Currency | currency |  |
| 21 | - | SKUs | `sku_count` | Int |  |  |
| 22 | Revision | Revision No | `revision_no` | Int |  |  |
| 23 | Revision | Revision Date | `revision_date` | Date |  |  |
| 24 | Revision | Revised For | `revised_for` | Small Text |  |  |
| 25 | Items & Sizes | SKU Lines (style × colour) | `items` | Table | Sales Contract Item | Yes |
| 26 | Size Breakdown | Size Breakdown | `sizes` | Table | Sales Contract Size Qty |  |
| 27 | Terms | Contract Template | `contract_template` | Link | Sales Contract Template |  |
| 28 | Shipment | Incoterm | `incoterm` | Link | Incoterm |  |
| 29 | Shipment | Named Place | `named_place` | Data |  |  |
| 30 | Shipment | Shipment Mode | `shipment_mode` | Select | (blank), Sea, Air, Sea-Air, Courier, Road |  |
| 31 | Shipment | Country of Origin | `country_of_origin` | Data |  |  |
| 32 | Shipment | Freight Paid By | `freight_by` | Select | (blank), Seller, Buyer |  |
| 33 | Shipment | Insurance Paid By | `insurance_by` | Select | (blank), Seller, Buyer |  |
| 34 | Shipment | Port of Loading | `port_of_loading` | Data |  |  |
| 35 | Shipment | Port of Discharge | `port_of_discharge` | Data |  |  |
| 36 | Shipping Days | Days Ex-Factory → ETD | `days_ex_factory_to_etd` | Int |  |  |
| 37 | Shipping Days | Transit Days ETD → In-Warehouse | `transit_days` | Int |  |  |
| 38 | Shipping Days | Delay in Shipment Allowed (days) | `delay_days_allowed` | Int |  |  |
| 39 | Shipping Days | Late Shipment Terms | `late_shipment_terms` | Small Text |  |  |
| 40 | Quantity Tolerance | Tolerance Bands (by line quantity) | `tolerance_bands` | Table | Sales Contract Tolerance Band |  |
| 41 | Claims & Quality | Quantity Claim Window (days) | `quantity_claim_days` | Int |  |  |
| 42 | Claims & Quality | Quality Claim Window (days) | `quality_claim_days` | Int |  |  |
| 43 | Claims & Quality | Objection Window (days) | `objection_days` | Int |  |  |
| 44 | Claims & Quality | Quality / Quantity Discrepancy Window (days) | `discrepancy_days` | Int |  |  |
| 45 | Claims & Quality | AQL Level | `aql_level` | Data |  |  |
| 46 | Claims & Quality | Inspection Terms | `inspection_terms` | Small Text |  |  |
| 47 | Packing | Packing Instructions | `packing_instructions` | Small Text |  |  |
| 48 | Packing | Shipping Marks | `shipping_marks` | Small Text |  |  |
| 49 | Payment & Clauses | Payment Basis | `payment_basis` | Select | (blank), Days after Receipt of Goods (ROG), Days after Invoice Date, Advance, L/C |  |
| 50 | Payment & Clauses | Payment Days | `payment_days` | Int |  |  |
| 51 | Payment & Clauses | Payment Terms Template | `payment_terms_template` | Link | Payment Terms Template |  |
| 52 | Payment & Clauses | Documents With Shipment | `documents_list` | Small Text |  |  |
| 53 | Payment & Clauses | Clauses (Terms and Conditions) | `terms_and_conditions` | Link | Terms and Conditions |  |
| 54 | Payment & Clauses | Arbitration / Governing Law | `arbitration` | Small Text |  |  |
| 55 | Payment & Clauses | Clauses | `terms` | Text Editor |  |  |
| 56 | Signatures | Signed by (Buyer) | `signed_by_buyer` | Data |  |  |
| 57 | Signatures | Buyer Signed On | `buyer_signed_on` | Date |  |  |
| 58 | Signatures | Signed by (Company) | `signed_by_company` | Link | User |  |
| 59 | Signatures | Company Signed On | `company_signed_on` | Date |  |  |
| 60 | Signatures | Amended From | `amended_from` | Link | Sales Contract |  |

### Sales Contract Item

- **Type:** Child table (child of `Sales Contract`)
- **Submittable:** no
- **Deck:** Contract & Order

**What it holds:** Child of Sales Contract. SKU line: style, colour, quantity, rate, amount, ex-factory, ETD, in-warehouse date, tolerance, finish, fabric description, linked cost sheet and tech pack, PCD, category.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Style Item | `style_item` | Link | Item | Yes |
| 2 | - | Style No | `style_no` | Data |  |  |
| 3 | - | Colour | `colour` | Data |  |  |
| 4 | - | Qty | `qty` | Int |  |  |
| 5 | - | Rate | `rate` | Currency | currency |  |
| 6 | - | Amount | `amount` | Currency | currency |  |
| 7 | - | Ex-Factory | `ex_factory_date` | Date |  |  |
| 8 | - | Tol ± % | `tolerance_pct` | Percent |  |  |
| 9 | - | ETD | `etd` | Date |  |  |
| 10 | - | In-Warehouse | `in_warehouse_date` | Date |  |  |
| 11 | - | UOM | `uom` | Link | UOM |  |
| 12 | - | Finish / Wash | `finish` | Data |  |  |
| 13 | - | Product Description | `description` | Small Text |  |  |
| 14 | - | Cost Sheet | `cost_sheet` | Link | Cost Sheet |  |
| 15 | - | Tech Pack | `tech_pack` | Link | Tech Pack |  |
| 16 | - | Buyer PO Code | `buyer_po_code` | Data |  |  |
| 17 | - | Fabric (content, count, construction, GSM) | `fabric_description` | Small Text |  |  |
| 18 | - | Planned Cut Date (PCD) | `pcd` | Date |  |  |
| 19 | - | Category | `category` | Data |  |  |
| 20 | - | Price Term | `price_term` | Link | Incoterm |  |
| 21 | - | Remarks | `line_remarks` | Small Text |  |  |

### Sales Contract Size Qty

- **Type:** Child table (child of `Sales Contract`)
- **Submittable:** no
- **Deck:** Contract & Order

**What it holds:** Child of Sales Contract. Size breakdown per colour: style, colour, size, quantity, ship-to, buyer PO and the ERPNext variant (SKU) item.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Style Item | `style_item` | Link | Item | Yes |
| 2 | - | Colour | `colour` | Data |  |  |
| 3 | - | Size | `size` | Data |  | Yes |
| 4 | - | Qty | `qty` | Int |  |  |
| 5 | - | Ship To | `ship_to` | Data |  |  |
| 6 | - | Buyer PO | `buyer_po_no` | Data |  |  |
| 7 | - | SKU (variant) | `item_code` | Link | Item |  |

### Sales Contract Tolerance Band

- **Type:** Child table (Shared: Contract & Order (Sales Contract) and Setup (Sales Contract Template))
- **Submittable:** no
- **Deck:** Shared: Contract & Order (Sales Contract) and Setup (Sales Contract Template)

**What it holds:** Child of Sales Contract and Sales Contract Template. Quantity band (from/to) with the plus/minus % tolerance allowed.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | From Qty | `from_qty` | Int |  |  |
| 2 | - | To Qty | `to_qty` | Int |  |  |
| 3 | - | Tolerance ± % | `tolerance_pct` | Percent |  | Yes |

### Sales Contract Template

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: template_name
- **Deck:** Contract & Order

**What it holds:** Reusable contract terms for a customer: incoterm, shipment mode, shipping days, tolerance bands, claim windows, AQL level, packing and shipping marks, payment basis, and governing clauses.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Template Name | `template_name` | Data |  | Yes |
| 2 | - | Customer | `customer` | Link | Customer |  |
| 3 | - | Default for this Customer | `is_default` | Check |  |  |
| 4 | - | Enabled | `enabled` | Check |  |  |
| 5 | Shipment | Incoterm | `incoterm` | Link | Incoterm |  |
| 6 | Shipment | Named Place | `named_place` | Data |  |  |
| 7 | Shipment | Shipment Mode | `shipment_mode` | Select | (blank), Sea, Air, Sea-Air, Courier, Road |  |
| 8 | Shipment | Country of Origin | `country_of_origin` | Data |  |  |
| 9 | Shipment | Freight Paid By | `freight_by` | Select | (blank), Seller, Buyer |  |
| 10 | Shipment | Insurance Paid By | `insurance_by` | Select | (blank), Seller, Buyer |  |
| 11 | Shipment | Port of Loading | `port_of_loading` | Data |  |  |
| 12 | Shipment | Port of Discharge | `port_of_discharge` | Data |  |  |
| 13 | Shipping Days | Days Ex-Factory → ETD | `days_ex_factory_to_etd` | Int |  |  |
| 14 | Shipping Days | Transit Days ETD → In-Warehouse | `transit_days` | Int |  |  |
| 15 | Shipping Days | Delay in Shipment Allowed (days) | `delay_days_allowed` | Int |  |  |
| 16 | Shipping Days | Late Shipment Terms | `late_shipment_terms` | Small Text |  |  |
| 17 | Quantity Tolerance | Tolerance Bands (by line quantity) | `tolerance_bands` | Table | Sales Contract Tolerance Band |  |
| 18 | Claims & Quality | Quantity Claim Window (days) | `quantity_claim_days` | Int |  |  |
| 19 | Claims & Quality | Quality Claim Window (days) | `quality_claim_days` | Int |  |  |
| 20 | Claims & Quality | Objection Window (days) | `objection_days` | Int |  |  |
| 21 | Claims & Quality | Quality / Quantity Discrepancy Window (days) | `discrepancy_days` | Int |  |  |
| 22 | Claims & Quality | AQL Level | `aql_level` | Data |  |  |
| 23 | Claims & Quality | Inspection Terms | `inspection_terms` | Small Text |  |  |
| 24 | Packing | Packing Instructions | `packing_instructions` | Small Text |  |  |
| 25 | Packing | Shipping Marks | `shipping_marks` | Small Text |  |  |
| 26 | Payment & Clauses | Payment Basis | `payment_basis` | Select | (blank), Days after Receipt of Goods (ROG), Days after Invoice Date, Advance, L/C |  |
| 27 | Payment & Clauses | Payment Days | `payment_days` | Int |  |  |
| 28 | Payment & Clauses | Payment Terms Template | `payment_terms_template` | Link | Payment Terms Template |  |
| 29 | Payment & Clauses | Documents With Shipment | `documents_list` | Small Text |  |  |
| 30 | Payment & Clauses | Clauses (Terms and Conditions) | `terms_and_conditions` | Link | Terms and Conditions |  |
| 31 | Payment & Clauses | Arbitration / Governing Law | `arbitration` | Small Text |  |  |

## Deck: Plan and Approve

Where: workspace section exists.

### Factory Allocation

- **Type:** Parent document
- **Submittable:** no
- **Naming:** Frappe default (number)
- **Deck:** Plan and Approve

**What it holds:** Which factory and line makes each order, by colour and quantity. Status is Unplanned, Partly Planned or Planned, with the option of an AI agent planner. Submission drives the TNA.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 2 | - | Sales Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Customer | `customer` | Link | Customer |  |
| 4 | - | Company | `company` | Link | Company |  |
| 5 | - | Status | `status` | Select | Unplanned, Partly Planned, Planned |  |
| 6 | - | Planned By | `planned_by` | Select | Manual, AI Agent |  |
| 7 | - | Order Qty | `order_qty` | Int |  |  |
| 8 | - | Allocated Qty | `allocated_qty` | Int |  |  |
| 9 | Allocation | Allocation Lines | `lines` | Table | Factory Allocation Line |  |
| 10 | Allocation | Agent Notes | `agent_notes` | Small Text |  |  |

### Factory Allocation Line

- **Type:** Child table (child of `Factory Allocation`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of Factory Allocation. One allocation: style, colour, buyer PO, ship-to, order qty, allocated qty, factory (Plant Floor), line (Workstation), PCD, sewing start and end, ex-factory date and reason.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Style | `style_item` | Link | Item | Yes |
| 2 | - | Style No | `style_no` | Data |  |  |
| 3 | - | Colour | `colour` | Data |  | Yes |
| 4 | - | Buyer PO | `buyer_po` | Data |  |  |
| 5 | - | Ship To | `ship_to` | Data |  |  |
| 6 | - | Order Qty | `order_qty` | Int |  |  |
| 7 | - | Allocated Qty | `qty` | Int |  | Yes |
| 8 | - | Factory | `factory` | Link | Plant Floor | Yes |
| 9 | - | Line | `line` | Link | Workstation |  |
| 10 | - | PCD | `pcd` | Date |  |  |
| 11 | - | Sewing Start | `sewing_start` | Date |  |  |
| 12 | - | Sewing End | `sewing_end` | Date |  |  |
| 13 | - | Ex-Factory | `ex_factory_date` | Date |  |  |
| 14 | - | Reason | `reason` | Small Text |  |  |

### Sample Requirement

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series SRQ-{#####}
- **Deck:** Plan and Approve

**What it holds:** Master rule for which samples a style needs (sample type, gate, due basis and offset, qty per colour, split-PO behaviour, late chargeback). Used to create the sample approvals for an order.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Scope | `scope_note` | HTML | <p class='text-muted'>Overrides the sample rules in Apparel Settings. The most specific record wins: Sales Order + Style, then Sales Order, then Customer + Style, then Customer, then Style. Leave a field blank to keep the default.</p> |  |
| 2 | - | Customer | `customer` | Link | Customer |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Style (Item template) | `style_item` | Link | Item |  |
| 5 | - | Enabled | `enabled` | Check |  |  |
| 6 | - | Sample Type | `sample_type` | Select | Proto, Fit, Size Set, Lab Dip, Strike Off, Desk Loom, Bulk Fabric, Bulk Trim, PP, Garment Test (GPT), TOP, Salesman, Photo Sample, Customer Sample, Fabric Test (FPT) | Yes |
| 7 | - | Gate | `gate` | Select | (blank), Required, If Raised, No |  |
| 8 | - | Per Colour | `per_colour` | Select | (blank), Yes, No |  |
| 9 | Due Date and Quantity | Due Basis | `due_basis` | Select | (blank), PCD, Ex-Factory, In-Warehouse, After Fit Approval |  |
| 10 | Due Date and Quantity | Days Offset | `days_before` | Int |  |  |
| 11 | Due Date and Quantity | Qty per Colour | `qty` | Int |  |  |
| 12 | Due Date and Quantity | Sample Size / Mix | `sample_size` | Data |  |  |
| 13 | Due Date and Quantity | Not Required on Split PO | `split_po_exempt` | Check |  |  |
| 14 | Due Date and Quantity | Late Chargeback | `chargeback_amount` | Currency |  |  |
| 15 | Source | Remarks | `remarks` | Small Text |  |  |

### Sample Approval

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series SA-{YY}-{#####}
- **Deck:** Plan and Approve

**What it holds:** One sample to be approved by the buyer (for example Fit, PP, TOP, GPT, lab dip): material, supplier, due dates, submission rounds, buyer comments, measurements, shrinkage readings, lab test results and waiver. Status moves Open, Submitted, Approved, Rejected or Resubmit.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sample Type | `sample_type` | Select | Proto, Fit, Size Set, Lab Dip, Strike Off, Desk Loom, Bulk Fabric, Bulk Trim, PP, Garment Test (GPT), TOP, Salesman, Photo Sample, Customer Sample, Fabric Test (FPT) | Yes |
| 2 | - | Status | `status` | Select | Open, Submitted, Approved, Approved with Comments, Rejected, Resubmit, Not Required |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Sales Contract | `sales_contract` | Link | Sales Contract |  |
| 5 | - | Customer | `customer` | Link | Customer |  |
| 6 | - | Style (Item template) | `style_item` | Link | Item | Yes |
| 7 | - | Style No | `style_no` | Data |  |  |
| 8 | - | Tech Pack | `tech_pack` | Link | Tech Pack |  |
| 9 | - | Colour | `colour` | Data |  |  |
| 10 | Material / Process | Material Type | `material_type` | Select | (blank), Fabric, Lining, Contrast Fabric, Trim, Label, Packaging, Thread, Fusing, Other |  |
| 11 | Material / Process | Material Item | `material_item` | Link | Item |  |
| 12 | Material / Process | Material Description | `material_description` | Data |  |  |
| 13 | Material / Process | Supplier | `supplier` | Link | Supplier |  |
| 14 | Material / Process | Buyer Reference | `buyer_reference` | Data |  |  |
| 15 | Material / Process | Garment is Washed | `is_washed` | Check |  |  |
| 16 | Material / Process | Wash Description | `wash_description` | Data |  |  |
| 17 | Material / Process | Made in Bulk Fabric | `in_bulk_fabric` | Check |  |  |
| 18 | Material / Process | Sample Size | `sample_size` | Data |  |  |
| 19 | Material / Process | Sample Qty | `sample_qty` | Int |  |  |
| 20 | Dates | PCD | `pcd` | Date |  |  |
| 21 | Dates | Ex-Factory | `ex_factory_date` | Date |  |  |
| 22 | Dates | In-Warehouse | `in_warehouse_date` | Date |  |  |
| 23 | Dates | Due Date | `due_date` | Date |  |  |
| 24 | Dates | Late Chargeback (rule) | `chargeback_amount` | Currency |  |  |
| 25 | Dates | Chargeback Exposure | `late_chargeback` | Currency |  |  |
| 26 | Dates | Buyer Requirement | `requirement_note` | Small Text |  |  |
| 27 | Dates | Submitted On | `submitted_on` | Date |  |  |
| 28 | Dates | Approved On | `approved_on` | Date |  |  |
| 29 | Rounds | Submission Rounds | `rounds` | Table | Sample Approval Round |  |
| 30 | Rounds | Buyer Comments | `comments` | Table | Sample Approval Comment |  |
| 31 | Measurements | Measured | `measurement_stage` | Select | (blank), Before Wash, After Wash, Final |  |
| 32 | Measurements | Measurements (up to 5 samples) | `measurements` | Table | Sample Measurement |  |
| 33 | Shrinkage | Shrinkage Readings | `shrinkage` | Table | Sample Shrinkage Reading |  |
| 34 | Lab Test (GPT / FPT) | Lab | `lab_name` | Data |  |  |
| 35 | Lab Test (GPT / FPT) | Report No | `lab_report_no` | Data |  |  |
| 36 | Lab Test (GPT / FPT) | Lab Report | `lab_report` | Attach |  |  |
| 37 | Lab Test (GPT / FPT) | Test Results | `tests` | Table | Sample Test Result |  |
| 38 | Waiver | Not Required (Waived) | `waived` | Check |  |  |
| 39 | Waiver | Waiver Reason | `waiver_reason` | Small Text |  |  |
| 40 | Waiver | Waived By | `waived_by` | Link | User |  |

### Sample Approval Comment

- **Type:** Child table (child of `Sample Approval`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of Sample Approval. Buyer comment: round, category (fit, colour, fabric, trim, construction...), comment, whether it is relevant to cutting, open or closed, and the PP meeting where it was closed.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Round | `round_no` | Int |  |  |
| 2 | - | Category | `category` | Select | Fit, Colour, Fabric, Trim, Construction, Label / Packing, Measurement, Other |  |
| 3 | - | Buyer Comment | `comment` | Small Text |  | Yes |
| 4 | - | Relevant to Cutting | `relevant_to_cutting` | Check |  |  |
| 5 | - | Status | `status` | Select | Open, Closed |  |
| 6 | - | Closed In | `closed_in` | Link | PP Meeting |  |

### Sample Approval Round

- **Type:** Child table (child of `Sample Approval`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of Sample Approval. One submission: round number, sent date, courier and AWB, received date, buyer decision, shade or option, tested after wash, file and photo.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Round | `round_no` | Int |  |  |
| 2 | - | Sent On | `sent_on` | Date |  |  |
| 3 | - | Courier | `courier` | Data |  |  |
| 4 | - | AWB No | `awb_no` | Data |  |  |
| 5 | - | Buyer Received On | `buyer_received_on` | Date |  |  |
| 6 | - | Decision | `decision` | Select | Pending, Approved, Approved with Comments, Rejected, Resubmit | Yes |
| 7 | - | Decision On | `decision_on` | Date |  |  |
| 8 | - | Shade / Option | `shade_option` | Data |  |  |
| 9 | - | Tested After Wash | `tested_after_wash` | Check |  |  |
| 10 | - | File | `attachment` | Attach |  |  |
| 11 | - | Photo | `photo` | Attach Image |  |  |
| 12 | - | Remarks | `remarks` | Small Text |  |  |

### Sample Test Result

- **Type:** Child table (child of `Sample Approval`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of Sample Approval. Lab test result: property tested, requirement, pass/fail, value and remarks (GPT and FPT).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Test Property | `test_property` | Data |  | Yes |
| 2 | - | Requirement | `requirement` | Data |  |  |
| 3 | - | Result | `result` | Select | (blank), Pass, Fail, N/A, Data |  |
| 4 | - | Value | `value` | Data |  |  |
| 5 | - | Remarks | `remarks` | Small Text |  |  |

### PP Meeting

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series PPM-{YY}-{#####}
- **Deck:** Plan and Approve

**What it holds:** Pre-production meeting (or pilot-run review) record: style, sales order, dates, production card reference, participants, colour and fabric or trim matrix, trim availability, technical notes (SPI, needle, washing, finishing, packing), and the actions raised. Submittable.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Meeting Type | `meeting_type` | Select | PP Meeting, Pilot Run | Yes |
| 2 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 3 | - | Style (Item template) | `style_item` | Link | Item | Yes |
| 4 | - | Style No | `style_no` | Data |  |  |
| 5 | - | Description | `description` | Small Text |  |  |
| 6 | - | Work Order / Job No | `work_order_ref` | Data |  |  |
| 7 | - | Order Qty | `order_qty` | Int |  |  |
| 8 | - | Sales Contract | `sales_contract` | Link | Sales Contract |  |
| 9 | - | Customer | `customer` | Link | Customer |  |
| 10 | - | Tech Pack | `tech_pack` | Link | Tech Pack |  |
| 11 | - | Status | `status` | Select | Draft, Open Actions, Closed |  |
| 12 | - | Meeting Date | `meeting_date` | Date |  | Yes |
| 13 | - | Delivery Date | `delivery_date` | Date |  |  |
| 14 | - | PCD | `pcd` | Date |  |  |
| 15 | - | Factory | `factory` | Link | Plant Floor |  |
| 16 | - | Line | `line` | Link | Workstation |  |
| 17 | Production Card and Samples | Production Card Ref | `production_card_ref` | Data |  |  |
| 18 | Production Card and Samples | Production Card Issued On | `production_card_issued_on` | Date |  |  |
| 19 | Production Card and Samples | PP Sample | `pp_sample` | Link | Sample Approval |  |
| 20 | Production Card and Samples | Size Set Sample | `size_set_sample` | Link | Sample Approval |  |
| 21 | Production Card and Samples | Garment is Washed | `is_washed` | Check |  |  |
| 22 | Participants | Participants | `participants` | Table | PP Meeting Participant |  |
| 23 | PO / Colour / Fabric / Trim Matrix | Colours | `colours` | Table | PP Meeting Colour |  |
| 24 | PO / Colour / Fabric / Trim Matrix | Sewing Trims | `sewing_trims` | Select | (blank), Available, Partial, Not Available |  |
| 25 | PO / Colour / Fabric / Trim Matrix | Packing Trims | `packing_trims` | Select | (blank), Available, Partial, Not Available |  |
| 26 | PO / Colour / Fabric / Trim Matrix | Pre-washed Trims | `prewashed_trims` | Select | (blank), Yes, No, N/A |  |
| 27 | PO / Colour / Fabric / Trim Matrix | Pre-dyed Trims | `predyed_trims` | Select | (blank), Yes, No, N/A |  |
| 28 | PO / Colour / Fabric / Trim Matrix | Line Setting Checklist Available | `line_setting_checklist` | Check |  |  |
| 29 | Technical Notes | Critical Operations / Special Instructions | `critical_operations` | Small Text |  |  |
| 30 | Technical Notes | Expected Problems | `expected_problems` | Small Text |  |  |
| 31 | Technical Notes | Corrective / Preventive Actions | `preventive_actions` | Small Text |  |  |
| 32 | Technical Notes | Check Point Locations | `checkpoints` | Small Text |  |  |
| 33 | Technical Notes | SPI | `spi` | Data |  |  |
| 34 | Technical Notes | Needle Size | `needle_size` | Data |  |  |
| 35 | Technical Notes | Needle Type | `needle_type` | Data |  |  |
| 36 | Technical Notes | Needle Change Frequency | `needle_change_frequency` | Data |  |  |
| 37 | Technical Notes | Marker for Marking | `marking_method` | Data |  |  |
| 38 | Technical Notes | Washing Method | `washing_method` | Data |  |  |
| 39 | Technical Notes | Finishing Instructions | `finishing_instructions` | Small Text |  |  |
| 40 | Technical Notes | Ironing | `ironing` | Small Text |  |  |
| 41 | Technical Notes | Packing | `packing` | Small Text |  |  |
| 42 | Technical Notes | Special Requirements | `special_requirements` | Small Text |  |  |
| 43 | Technical Notes | PP Corrections Relevant to Cutting | `pp_corrections_for_cutting` | Check |  |  |
| 44 | Technical Notes | Size Set Corrections Relevant to Cutting | `size_set_corrections_for_cutting` | Check |  |  |
| 45 | Comments and Actions | Every Buyer Comment → Owner and Date | `actions` | Table | PP Meeting Action |  |
| 46 | Comments and Actions | Amended From | `amended_from` | Link | PP Meeting |  |

### PP Meeting Action

- **Type:** Child table (child of `PP Meeting`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of PP Meeting. Action item: source (buyer comment or meeting), comment, whether it is for cutting, action taken, owner, target date and status.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sample Approval | `sample_approval` | Link | Sample Approval |  |
| 2 | - | Comment Row | `comment_ref` | Data |  |  |
| 3 | - | Source | `source` | Select | Buyer Comment, Meeting |  |
| 4 | - | Category | `category` | Data |  |  |
| 5 | - | Comment / Issue | `comment` | Small Text |  | Yes |
| 6 | - | Cutting | `relevant_to_cutting` | Check |  |  |
| 7 | - | Action Taken | `action_taken` | Small Text |  |  |
| 8 | - | Owner | `action_owner` | Link | User |  |
| 9 | - | Target Date | `target_date` | Date |  |  |
| 10 | - | Status | `status` | Select | Open, Closed |  |
| 11 | - | Closed On | `closed_on` | Date |  |  |

### PP Meeting Colour

- **Type:** Child table (child of `PP Meeting`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of PP Meeting. Colour line: colour, buyer PO, order qty, fabric required and received, number of shades.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Buyer PO | `buyer_po` | Data |  |  |
| 3 | - | Order Qty | `order_qty` | Int |  |  |
| 4 | - | Fabric Required (m) | `fabric_required_m` | Float |  |  |
| 5 | - | Fabric Received (m) | `fabric_received_m` | Float |  |  |
| 6 | - | No. of Shades | `no_of_shades` | Int |  |  |

### PP Meeting Participant

- **Type:** Child table (child of `PP Meeting`)
- **Submittable:** no
- **Deck:** Plan and Approve

**What it holds:** Child of PP Meeting. Attendee: department, name, linked user, designation and whether they attended.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Department | `department` | Data |  | Yes |
| 2 | - | Name | `participant_name` | Data |  |  |
| 3 | - | User | `user` | Link | User |  |
| 4 | - | Designation | `designation` | Data |  |  |
| 5 | - | Attended | `attended` | Check |  |  |

### Order TNA

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series TNA-{#####}
- **Deck:** Plan and Approve

**What it holds:** Time and action plan for one sales order: style, order received date, PCD, ex-factory date, the TNA template used, baseline lock, overall status (on track, at risk, late, completed), and critical delay days.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 2 | - | Buyer | `customer` | Link | Customer |  |
| 3 | - | Company | `company` | Link | Company |  |
| 4 | - | Style | `style_item` | Link | Item | Yes |
| 5 | - | Style No | `style_no` | Data |  |  |
| 6 | - | Colour | `colour` | Data |  |  |
| 7 | - | Order Qty | `order_qty` | Int |  |  |
| 8 | - | Ship To | `ship_tos` | Small Text |  |  |
| 9 | - | Merchant | `merchant` | Link | User |  |
| 10 | - | Factory | `factory` | Link | Plant Floor |  |
| 11 | Dates | Order Received | `order_received_date` | Date |  |  |
| 12 | Dates | Order Date Estimated | `order_date_missing` | Check |  |  |
| 13 | Dates | PCD | `pcd` | Date |  |  |
| 14 | Dates | Ex-Factory | `ex_factory_date` | Date |  | Yes |
| 15 | Dates | Template | `template` | Link | TNA Template |  |
| 16 | Dates | Baseline Locked | `baseline_locked` | Check |  |  |
| 17 | Status | Status | `status` | Select | On Track, At Risk, Late, Completed, Cancelled |  |
| 18 | Status | Critical Delay (days) | `critical_delay_days` | Int |  |  |
| 19 | Status | Plan Fits Ex-Factory | `plan_feasible` | Check |  |  |
| 20 | Status | Plan Note | `feasibility_note` | Small Text |  |  |

### TNA Milestone

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series TAM-{#####}
- **Deck:** Plan and Approve

**What it holds:** One milestone row of an Order TNA: milestone type, department, owner, critical flag, baseline, revised and actual dates, delay days, status, and what stamped it (document, user or manual).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Order TNA | `order_tna` | Link | Order TNA | Yes |
| 2 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 3 | - | Buyer | `customer` | Link | Customer |  |
| 4 | - | Style No | `style_no` | Data |  |  |
| 5 | - | Colour | `colour` | Data |  |  |
| 6 | - | Factory | `factory` | Link | Plant Floor |  |
| 7 | - | Milestone | `milestone_type` | Link | TNA Milestone Type | Yes |
| 8 | - | Label | `label` | Data |  |  |
| 9 | - | Sequence | `sequence` | Int |  |  |
| 10 | - | Department | `department` | Select | Merchandising, Sampling, Purchasing, Quality, Production, Washing, Shipping |  |
| 11 | - | Owner | `owner_user` | Link | User |  |
| 12 | - | Critical | `is_critical` | Check |  |  |
| 13 | - | Not Applicable | `not_applicable` | Check |  |  |
| 14 | Dates | Start | `planned_start` | Date |  |  |
| 15 | Dates | Planned (Baseline) | `planned_date` | Date |  |  |
| 16 | Dates | Revised | `revised_date` | Date |  |  |
| 17 | Dates | Revision Reason | `revision_reason` | Small Text |  |  |
| 18 | Dates | Delay Caused By | `delay_reason_category` | Select | (blank), Buyer, Supplier, Factory, Logistics, Other |  |
| 19 | Dates | Actual | `actual_date` | Date |  |  |
| 20 | Dates | Partly Done | `partial` | Check |  |  |
| 21 | Dates | Status | `status` | Select | Not Started, In Progress, Done, Late, Not Applicable |  |
| 22 | Dates | Delay (days) | `delay_days` | Int |  |  |
| 23 | Source and Chart | Stamped By Document Type | `source_doctype` | Data |  |  |
| 24 | Source and Chart | Stamped By Document | `source_name` | Data |  |  |
| 25 | Source and Chart | Depends On | `depends_on_tasks` | Data |  |  |
| 26 | Source and Chart | Chart Colour | `color` | Data |  |  |
| 27 | Source and Chart | Progress | `progress` | Int |  |  |
| 28 | Source and Chart | Remarks | `remarks` | Small Text |  |  |

## Deck: Materials

Where: workspace section exists.

### Fabric Requisition

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Materials

**What it holds:** Fabric requirement for a buyer or season, by style and colour: fabric item and supplier, garment quantity, consumption per piece, allowance, gross and net metres, required-by dates, and links to Material Requests and received quantities. Revised by copying into a new revision.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Company | `company` | Link | Company | Yes |
| 2 | - | Buyer | `customer` | Link | Customer | Yes |
| 3 | - | Season | `season` | Data |  |  |
| 4 | - | Date | `fr_date` | Date |  | Yes |
| 5 | - | Ordered By | `ordered_by` | Link | User |  |
| 6 | - | Approved By | `approved_by` | Link | User |  |
| 7 | - | Approved On | `approved_on` | Datetime |  |  |
| 8 | - | Status | `status` | Select | Draft, Approved, Partly Ordered, Ordered, Partly Received, Received, Superseded, Cancelled |  |
| 9 | Revision | Previous FR | `previous_fr` | Link | Fabric Requisition |  |
| 10 | Revision | Revision No | `revision_no` | Int |  |  |
| 11 | Revision | Revision Reason | `revision_reason` | Small Text |  |  |
| 12 | Lines | Fabric Lines | `items` | Table | Fabric Requisition Item | Yes |
| 13 | Summary for Supplier | Summary | `summary` | Table | Fabric Requisition Summary |  |
| 14 | Summary for Supplier | Total Net (m) | `total_order_m` | Float |  |  |
| 15 | Red Flags and Terms | Red Flags and Alerts | `red_flags` | Small Text |  |  |
| 16 | Red Flags and Terms | Merchandiser Notes | `notes` | Small Text |  |  |
| 17 | Red Flags and Terms | Terms | `terms` | Text Editor |  |  |
| 18 | Red Flags and Terms | Amended From | `amended_from` | Link | Fabric Requisition |  |

### Fabric Requisition Item

- **Type:** Child table (child of `Fabric Requisition`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Fabric Requisition. One fabric line: sales order, style, colour, role (shell, lining...), fabric item, cuttable width, GSM, lab dip, quantity, consumption, allowance, gross and net metres, stock used, order UOM and quantity, Material Request link, and ordered, received, accepted and rejected metres.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 2 | - | Sales Contract | `sales_contract` | Data |  |  |
| 3 | - | Buyer PO | `buyer_po` | Data |  |  |
| 4 | - | Style | `style_item` | Link | Item | Yes |
| 5 | - | Style No | `style_no` | Data |  |  |
| 6 | - | Style Name | `style_name` | Data |  |  |
| 7 | - | Colour | `colour` | Data |  | Yes |
| 8 | - | Role | `material_role` | Select | Shell, Lining, Pocketing, Contrast, Other |  |
| 9 | - | Tech Pack Row | `tech_pack_material` | Data |  |  |
| 10 | Fabric | Fabric Item | `fabric_item` | Link | Item |  |
| 11 | Fabric | Fabric Description | `fabric_description` | Small Text |  |  |
| 12 | Fabric | Fabric Colour | `fabric_colour` | Data |  |  |
| 13 | Fabric | Supplier | `supplier` | Link | Supplier |  |
| 14 | Fabric | Nominated by Buyer | `nominated_by_buyer` | Check |  |  |
| 15 | Fabric | Cuttable Width (cm) | `cuttable_width_cm` | Float |  | Yes |
| 16 | Fabric | GSM | `gsm` | Float |  |  |
| 17 | Fabric | Lab Dip | `lab_dip_status` | Data |  |  |
| 18 | Fabric | On Hold | `hold` | Check |  |  |
| 19 | Quantity | Garment Qty | `garment_qty` | Int |  | Yes |
| 20 | Quantity | Consumption / pc | `consumption` | Float |  | Yes |
| 21 | Quantity | Consumption UOM | `consumption_uom` | Link | UOM | Yes |
| 22 | Quantity | Source | `consumption_source` | Select | (blank), Mini Marker, Bulk Marker, Cost Sheet, Tech Pack, Manual | Yes |
| 23 | Quantity | Costed Consumption | `costed_consumption` | Float |  |  |
| 24 | Quantity | Allowance % | `allowance_pct` | Percent |  |  |
| 25 | Quantity | Allowance Reason | `allowance_reason` | Data |  |  |
| 26 | Quantity | Pack Size | `pack_size` | Float |  |  |
| 27 | Quantity | Gross (m) | `gross_qty` | Float |  |  |
| 28 | Quantity | Stock Warehouse | `stock_warehouse` | Link | Warehouse |  |
| 29 | Quantity | Stock Used (m) | `stock_used` | Float |  |  |
| 30 | Quantity | Net (m) | `net_qty` | Float |  |  |
| 31 | Quantity | Order UOM | `order_uom` | Link | UOM |  |
| 32 | Quantity | Order Qty | `order_qty` | Float |  |  |
| 33 | Quantity | Required By | `required_by` | Date |  |  |
| 34 | Tracking | Material Request | `material_request` | Link | Material Request |  |
| 35 | Tracking | MR Row | `material_request_item` | Data |  |  |
| 36 | Tracking | Ordered (m) | `ordered_qty` | Float |  |  |
| 37 | Tracking | Received (m) | `received_qty` | Float |  |  |
| 38 | Tracking | Accepted (m) | `accepted_qty` | Float |  |  |
| 39 | Tracking | Rejected (m) | `rejected_qty` | Float |  |  |
| 40 | Tracking | Remarks | `remarks` | Small Text |  |  |

### Fabric Requisition Summary

- **Type:** Child table (child of `Fabric Requisition`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Fabric Requisition. Supplier-facing summary per fabric item: order qty, UOM, earliest required date and number of lines.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Fabric Item | `fabric_item` | Link | Item |  |
| 2 | - | Fabric | `fabric_description` | Small Text |  |  |
| 3 | - | Supplier | `supplier` | Link | Supplier |  |
| 4 | - | Order Qty | `total_order_qty` | Float |  |  |
| 5 | - | UOM | `uom` | Link | UOM |  |
| 6 | - | Earliest Required By | `earliest_required_by` | Date |  |  |
| 7 | - | Lines | `line_count` | Int |  |  |

### Trim Requisition

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Materials

**What it holds:** Trim requirement for a buyer or season, by style, colour and size: trim lines with category, item, quantity basis, allowances, stock, Material Request link and received quantities. Revised like the FR.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Company | `company` | Link | Company | Yes |
| 2 | - | Buyer | `customer` | Link | Customer | Yes |
| 3 | - | Season | `season` | Data |  |  |
| 4 | - | Date | `tr_date` | Date |  | Yes |
| 5 | - | Shipment Mode | `shipment_mode` | Select | (blank), Sea, Air |  |
| 6 | - | Made By | `ordered_by` | Link | User |  |
| 7 | - | Approved By | `approved_by` | Link | User |  |
| 8 | - | Approved On | `approved_on` | Datetime |  |  |
| 9 | - | Status | `status` | Select | Draft, Approved, Partly Ordered, Ordered, Partly Received, Received, Superseded, Cancelled |  |
| 10 | Revision | Previous TR | `previous_tr` | Link | Trim Requisition |  |
| 11 | Revision | Revision No | `revision_no` | Int |  |  |
| 12 | Revision | Revision Reason | `revision_reason` | Small Text |  |  |
| 13 | Lines | Trim Lines | `items` | Table | Trim Requisition Item | Yes |
| 14 | Red Flags and Terms | Red Flags and Alerts | `red_flags` | Small Text |  |  |
| 15 | Red Flags and Terms | Merchandiser Notes | `notes` | Small Text |  |  |
| 16 | Red Flags and Terms | Amended From | `amended_from` | Link | Trim Requisition |  |

### Trim Requisition Item

- **Type:** Child table (child of `Trim Requisition`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Trim Requisition. One trim line: sales order, style, colour, size, trim category, trim item, buyer item code, supplier, basis (per garment, per carton, by length...), quantity per garment, spare, pieces per carton, length, allowance, stock used, order qty, required-by and tracking quantities.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 2 | - | Buyer PO | `buyer_po` | Data |  |  |
| 3 | - | Style | `style_item` | Link | Item | Yes |
| 4 | - | Style No | `style_no` | Data |  |  |
| 5 | - | Colour | `colour` | Data |  |  |
| 6 | - | Size | `size` | Data |  |  |
| 7 | Trim | Category | `trim_category` | Link | Trim Category | Yes |
| 8 | Trim | Trim Item | `trim_item` | Link | Item |  |
| 9 | Trim | Buyer Item Code | `buyer_item_code` | Data |  |  |
| 10 | Trim | Description | `description` | Data |  |  |
| 11 | Trim | Trim Colour | `trim_colour` | Data |  |  |
| 12 | Trim | Supplier | `supplier` | Link | Supplier |  |
| 13 | Trim | Nominated by Buyer | `nominated_by_buyer` | Check |  |  |
| 14 | Trim | Buyer Supplied | `customer_provided` | Check |  |  |
| 15 | Trim | Trim Approval | `approval_status` | Data |  |  |
| 16 | Trim | On Hold | `hold` | Check |  |  |
| 17 | Quantity | Basis | `calc_basis` | Select | Per Garment, Per Size, Per Colour, Per Carton, By Length, Fixed Qty | Yes |
| 18 | Quantity | Garment Qty | `garment_qty` | Int |  |  |
| 19 | Quantity | Qty / Garment (or Carton) | `qty_per_garment` | Float |  |  |
| 20 | Quantity | Spare / Garment | `spare_per_garment` | Float |  |  |
| 21 | Quantity | Pcs per Carton | `pcs_per_carton` | Int |  |  |
| 22 | Quantity | Length / Garment | `consumption` | Float |  |  |
| 23 | Quantity | Length UOM | `consumption_uom` | Link | UOM |  |
| 24 | Quantity | Allowance % | `allowance_pct` | Percent |  |  |
| 25 | Quantity | Allowance Reason | `allowance_reason` | Data |  |  |
| 26 | Quantity | Pack Size | `pack_size` | Float |  |  |
| 27 | Quantity | Gross | `gross_qty` | Float |  |  |
| 28 | Quantity | Stock Warehouse | `stock_warehouse` | Link | Warehouse |  |
| 29 | Quantity | Stock Used | `stock_used` | Float |  |  |
| 30 | Quantity | Net | `net_qty` | Float |  |  |
| 31 | Quantity | Order UOM | `order_uom` | Link | UOM |  |
| 32 | Quantity | Order Qty | `order_qty` | Float |  |  |
| 33 | Quantity | Required By | `required_by` | Date |  |  |
| 34 | Tracking | Material Request | `material_request` | Link | Material Request |  |
| 35 | Tracking | MR Row | `material_request_item` | Data |  |  |
| 36 | Tracking | Ordered | `ordered_qty` | Float |  |  |
| 37 | Tracking | Received | `received_qty` | Float |  |  |
| 38 | Tracking | Accepted | `accepted_qty` | Float |  |  |
| 39 | Tracking | Rejected | `rejected_qty` | Float |  |  |
| 40 | Tracking | Remarks | `remarks` | Small Text |  |  |

### Fabric Inspection

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series FI-{YY}-{#####}
- **Deck:** Materials

**What it holds:** Inspection of a fabric receipt (4-point system). Records rolls received and sampled, inspection machine and light source, per-roll widths and points, shrinkage readings, defects, average points per 100 sq yd, accepted, rejected and on-hold metres, and the lot result. Submittable.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Purchase Receipt | `purchase_receipt` | Link | Purchase Receipt | Yes |
| 2 | - | Receipt Row | `purchase_receipt_item` | Data |  | Yes |
| 3 | - | Company | `company` | Link | Company |  |
| 4 | - | Supplier | `supplier` | Link | Supplier |  |
| 5 | - | Purchase Order | `purchase_order` | Link | Purchase Order |  |
| 6 | - | Fabric Requisition | `fabric_requisition` | Link | Fabric Requisition |  |
| 7 | - | Fabric Item | `fabric_item` | Link | Item |  |
| 8 | - | Colour | `colour` | Data |  |  |
| 9 | - | Buyer | `customer` | Link | Customer |  |
| 10 | - | Sales Orders | `sales_orders` | Small Text |  |  |
| 11 | - | Styles | `style_nos` | Small Text |  |  |
| 12 | Inspection | Inspection Date | `inspection_date` | Date |  | Yes |
| 13 | Inspection | Inspected By | `inspected_by` | Link | User |  |
| 14 | Inspection | Inspection Machine | `inspection_machine` | Data |  |  |
| 15 | Inspection | Light Source | `light_source` | Select | (blank), D65, TL84, CWF, Daylight |  |
| 16 | Inspection | Points Basis | `points_basis` | Select | Per 100 Linear Yards, Per 100 Square Yards |  |
| 17 | Inspection | Points Threshold | `points_threshold` | Float |  |  |
| 18 | Inspection | Required Width (cm) | `required_width_cm` | Float |  |  |
| 19 | Sampling | Rolls Received | `total_rolls` | Int |  |  |
| 20 | Sampling | Received (m) | `total_received_m` | Float |  |  |
| 21 | Sampling | Sampling % | `sampling_pct` | Percent |  |  |
| 22 | Sampling | Must Inspect (m) | `required_inspect_m` | Float |  |  |
| 23 | Sampling | Inspected (m) | `inspected_m` | Float |  |  |
| 24 | Sampling | Inspected % | `inspected_pct` | Percent |  |  |
| 25 | Sampling | Rolls Inspected | `inspected_rolls` | Int |  |  |
| 26 | Rolls | Rolls | `rolls` | Table | Fabric Inspection Roll |  |
| 27 | Defects | Defects | `defects` | Table | Fabric Inspection Defect |  |
| 28 | Shrinkage | Shrinkage Readings | `shrinkage` | Table | Sample Shrinkage Reading |  |
| 29 | Result | Average Points | `avg_points` | Float |  |  |
| 30 | Result | Points / 100 sq yd | `avg_points_sq` | Float |  |  |
| 31 | Result | Rolls Rejected | `rejected_rolls` | Int |  |  |
| 32 | Result | Accepted (m) | `accepted_m` | Float |  |  |
| 33 | Result | Rejected (m) | `rejected_m` | Float |  |  |
| 34 | Result | On Hold (m) | `hold_m` | Float |  |  |
| 35 | Result | Average Actual Width (cm) | `avg_actual_width_cm` | Float |  |  |
| 36 | Result | Extra Fabric Needed (m) | `width_shortfall_m` | Float |  |  |
| 37 | Result | Shade Bands | `shade_bands_found` | Data |  |  |
| 38 | Result | Put Lot on Hold | `on_hold` | Check |  |  |
| 39 | Result | Lot Result | `lot_result` | Select | (blank), Pass, Fail, Re-inspect 100%, Hold |  |
| 40 | Result | Override Inspection Rules | `result_override` | Check |  |  |
| 41 | Result | Override Reason | `override_reason` | Small Text |  |  |
| 42 | Result | Claim Deadline | `claim_deadline` | Date |  |  |
| 43 | Result | FPT (Fabric Test) | `fpt_sample_approval` | Link | Sample Approval |  |
| 44 | Result | Quality Inspection | `quality_inspection` | Link | Quality Inspection |  |
| 45 | Result | Stock Entry | `stock_entry` | Link | Stock Entry |  |
| 46 | Result | Remarks | `remarks` | Small Text |  |  |
| 47 | Result | Amended From | `amended_from` | Link | Fabric Inspection |  |

### Fabric Inspection Defect

- **Type:** Child table (child of `Fabric Inspection`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Fabric Inspection. Defect found on a roll: roll number, yard, defect code, length, points.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Roll No | `roll_no` | Data |  | Yes |
| 2 | - | Yard No | `yard_position` | Int |  |  |
| 3 | - | Defect | `defect_code` | Link | Fabric Defect Code | Yes |
| 4 | - | Length (in) | `defect_length_in` | Float |  |  |
| 5 | - | Points | `points` | Int |  |  |
| 6 | - | Remarks | `remarks` | Data |  |  |

### Fabric Inspection Roll

- **Type:** Child table (child of `Fabric Inspection`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Fabric Inspection. Roll record: batch, dye lot, ticket and actual length, width readings, points, shade band, centre-selvedge and skew check, result and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Batch | `batch` | Link | Batch | Yes |
| 2 | - | Roll No | `roll_no` | Data |  |  |
| 3 | - | Dye Lot | `dye_lot` | Data |  |  |
| 4 | - | Ticket Length (m) | `ticket_length` | Float |  |  |
| 5 | - | Actual Length (m) | `actual_length` | Float |  |  |
| 6 | - | Variance (m) | `length_variance` | Float |  |  |
| 7 | - | Inspected | `inspected` | Check |  |  |
| 8 | - | Inspected (m) | `inspected_length_m` | Float |  |  |
| 9 | Width | Required Width (cm) | `width_required_cm` | Float |  |  |
| 10 | Width | Width Start | `width_start_cm` | Float |  |  |
| 11 | Width | Width Middle | `width_middle_cm` | Float |  |  |
| 12 | Width | Width End | `width_end_cm` | Float |  |  |
| 13 | Width | Width OK | `width_ok` | Check |  |  |
| 14 | Result | Points | `total_points` | Int |  |  |
| 15 | Result | Points / 100 yd | `points_per_100` | Float |  |  |
| 16 | Result | Shade Band | `shade_band` | Data |  |  |
| 17 | Result | Centre-Selvedge OK | `csv_ok` | Check |  |  |
| 18 | Result | Bowing / Skew % | `bowing_skew_pct` | Percent |  |  |
| 19 | Result | Face Side Marked | `face_side_marked` | Check |  |  |
| 20 | Result | Result | `roll_result` | Select | (blank), Accept, Reject, Hold |  |
| 21 | Result | Remarks | `remarks` | Small Text |  |  |

### Sample Shrinkage Reading

- **Type:** Child table (Shared: Materials (Fabric Inspection) and Plan and Approve (Sample Approval))
- **Submittable:** no
- **Deck:** Shared: Materials (Fabric Inspection) and Plan and Approve (Sample Approval)

**What it holds:** Child of Fabric Inspection and Sample Approval. Before and after lengthwise, widthwise and bias measurements of a roll or lot, giving the shrinkage % for warp, weft, bias and torque.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Roll / Lot | `roll_no` | Data |  |  |
| 2 | - | Before Warp | `before_warp` | Float |  |  |
| 3 | - | Before Weft | `before_weft` | Float |  |  |
| 4 | - | Before Bias | `before_bias` | Float |  |  |
| 5 | - | After Warp | `after_warp` | Float |  |  |
| 6 | - | After Weft | `after_weft` | Float |  |  |
| 7 | - | After Bias | `after_bias` | Float |  |  |
| 8 | - | Warp % | `shrink_warp_pct` | Percent |  |  |
| 9 | - | Weft % | `shrink_weft_pct` | Percent |  |  |
| 10 | - | Bias % | `shrink_bias_pct` | Percent |  |  |
| 11 | - | Torque % | `torque_pct` | Percent |  |  |

### Trim Inspection

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series TI-{YY}-{#####}
- **Deck:** Materials

**What it holds:** Inspection of a trim receipt: received and inspected quantities, sampling plan and sample size, defective count and %, accepted and rejected quantities, the defects found, approved bulk trim reference, pass/fail/hold result, and the stock entry. Submittable.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Purchase Receipt | `purchase_receipt` | Link | Purchase Receipt | Yes |
| 2 | - | Receipt Row | `purchase_receipt_item` | Data |  | Yes |
| 3 | - | Company | `company` | Link | Company |  |
| 4 | - | Supplier | `supplier` | Link | Supplier |  |
| 5 | - | Purchase Order | `purchase_order` | Link | Purchase Order |  |
| 6 | - | Trim Requisition | `trim_requisition` | Link | Trim Requisition |  |
| 7 | - | Trim Item | `trim_item` | Link | Item |  |
| 8 | - | Material Description | `material_description` | Data |  |  |
| 9 | - | Colour | `colour` | Data |  |  |
| 10 | - | Buyer | `customer` | Link | Customer |  |
| 11 | - | Styles | `style_nos` | Small Text |  |  |
| 12 | Inspection | Received Date | `received_date` | Date |  | Yes |
| 13 | Inspection | Invoice No | `invoice_no` | Data |  |  |
| 14 | Inspection | Received Qty | `received_qty` | Float |  | Yes |
| 15 | Inspection | Sampling Plan | `sampling_plan` | Link | Trim Sampling Plan |  |
| 16 | Inspection | Sample Size | `sample_size` | Float |  |  |
| 17 | Inspection | Inspected Qty | `inspected_qty` | Float |  | Yes |
| 18 | Inspection | Defective Found | `defective_qty` | Float |  |  |
| 19 | Inspection | Defective % | `defective_pct` | Percent |  |  |
| 20 | Inspection | Accepted Qty | `accepted_qty` | Float |  |  |
| 21 | Inspection | Rejected Qty | `rejected_qty` | Float |  |  |
| 22 | Inspection | Rejected % | `rejected_pct` | Percent |  |  |
| 23 | Defects | Defects Found | `defects` | Table | Trim Inspection Defect |  |
| 24 | References | Approved Trim (Bulk Trim) | `approved_trim_ref` | Link | Sample Approval |  |
| 25 | References | Original Sample | `original_sample` | Attach Image |  |  |
| 26 | References | Defective Sample | `defective_sample` | Attach Image |  |  |
| 27 | References | Result | `result` | Select | (blank), Pass, Fail, Hold |  |
| 28 | References | Override Inspection Rules | `result_override` | Check |  |  |
| 29 | References | Override Reason | `override_reason` | Small Text |  |  |
| 30 | References | Warehouse In-charge | `warehouse_incharge` | Link | User |  |
| 31 | References | Trim Sourcing Manager | `trim_sourcing_manager` | Link | User |  |
| 32 | References | Quality Inspection | `quality_inspection` | Link | Quality Inspection |  |
| 33 | References | Stock Entry | `stock_entry` | Link | Stock Entry |  |
| 34 | References | Remarks | `remarks` | Small Text |  |  |
| 35 | References | Amended From | `amended_from` | Link | Trim Inspection |  |

### Trim Inspection Defect

- **Type:** Child table (child of `Trim Inspection`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Trim Inspection. Trim defect (linked to Trim Defect Type) with count and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Defect | `defect_type` | Link | Trim Defect Type | Yes |
| 2 | - | Count | `count` | Int |  | Yes |
| 3 | - | Remarks | `remarks` | Data |  |  |

### Material Purchase Terms

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: terms_name
- **Deck:** Materials

**What it holds:** Reusable purchase terms for fabric or trims: claim window, fabric points threshold, what to do with over-band quantity, quantity bands, delay penalty bands and the text printed on the PO.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Terms Name | `terms_name` | Data |  | Yes |
| 2 | - | Used For | `material_kind` | Select | Fabric, Trim |  |
| 3 | - | Claim Window (days) | `claim_window_days` | Int |  |  |
| 4 | - | Fabric Points Threshold | `points_threshold` | Float |  |  |
| 5 | - | Quantity Over the Band | `extra_qty_policy` | Select | Reject, Accept Unpaid, Accept Paid |  |
| 6 | Quantity Allowance | Quantity Bands | `qty_bands` | Table | Purchase Qty Band |  |
| 7 | Late Delivery | Delay Penalty Bands | `delay_bands` | Table | Delay Penalty Band |  |
| 8 | Terms Text | Printed on the PO | `terms_text` | Text Editor |  |  |

### Delay Penalty Band

- **Type:** Child table (child of `Material Purchase Terms`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Material Purchase Terms. Late-delivery band (from and to days) with the penalty % of order value and the action (discount, or cancel or discount).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | From Days | `from_days` | Int |  | Yes |
| 2 | - | To Days | `to_days` | Int |  | Yes |
| 3 | - | Penalty % of Value | `penalty_pct` | Percent |  |  |
| 4 | - | Action | `action` | Select | Discount, Cancel or Discount |  |

### Purchase Qty Band

- **Type:** Child table (child of `Material Purchase Terms`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Material Purchase Terms. Quantity band (from and to) with UOM and the plus/minus % tolerance allowed on that band.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | From Qty | `from_qty` | Float |  | Yes |
| 2 | - | To Qty | `to_qty` | Float |  | Yes |
| 3 | - | UOM | `uom` | Link | UOM |  |
| 4 | - | Tolerance ± % | `tolerance_pct` | Percent |  | Yes |

### Material Allowance Rule

- **Type:** Parent document
- **Submittable:** no
- **Naming:** Frappe default (number)
- **Deck:** Materials

**What it holds:** Rule that sets the wastage or allowance % for a material type, trim category, customer or item group, with pack size and minimum order qty.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Material Type | `material_type` | Select | (blank), Fabric, Lining, Contrast Fabric, Trim, Label, Packaging |  |
| 2 | - | Trim Category | `trim_category` | Link | Trim Category |  |
| 3 | - | Customer | `customer` | Link | Customer |  |
| 4 | - | Item Group | `item_group` | Link | Item Group |  |
| 5 | - | Allowance % | `allowance_pct` | Percent |  | Yes |
| 6 | - | Pack Size | `pack_size` | Float |  |  |
| 7 | - | Min Order Qty | `min_order_qty` | Float |  |  |
| 8 | - | Enabled | `enabled` | Check |  |  |
| 9 | - | Remarks | `remarks` | Small Text |  |  |

### Trim Sampling Plan

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: plan_name
- **Deck:** Materials

**What it holds:** Sampling plan for trim inspection: percent method or AQL table, inspect percent, max defective percent, inspect-100%-up-to quantity.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Plan Name | `plan_name` | Data |  | Yes |
| 2 | - | Method | `method` | Select | Percent, AQL Table |  |
| 3 | - | Inspect % | `inspect_pct` | Percent |  |  |
| 4 | - | Max Defective % (Percent plan) | `max_defective_pct` | Percent |  |  |
| 5 | - | Inspect 100% Up To (pcs) | `full_inspect_up_to` | Int |  |  |
| 6 | - | AQL Rows | `rows` | Table | Trim Sampling Plan Row |  |
| 7 | - | Note | `note` | Small Text |  |  |

### Trim Sampling Plan Row

- **Type:** Child table (child of `Trim Sampling Plan`)
- **Submittable:** no
- **Deck:** Materials

**What it holds:** Child of Trim Sampling Plan. AQL table row: lot from/to, sample size, accept and reject defect counts.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Lot From | `lot_from` | Int |  | Yes |
| 2 | - | Lot To | `lot_to` | Int |  | Yes |
| 3 | - | Sample Size | `sample_size` | Int |  | Yes |
| 4 | - | Accept (max defects) | `accept_max` | Int |  | Yes |
| 5 | - | Reject (min defects) | `reject_min` | Int |  | Yes |

## Deck: Production

Where: NOT on workspace yet; add a section.

### Production Card

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Master production instruction for one style order (submittable). Holds the colour x size breakdown, the fabric requirement, the sub-contract route, pilot-run settings, packing instructions, ex-factory and PCD dates, status flow from Draft to Closed, and revision and sign-off trail. Every shop-floor document links here.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Company | `company` | Link | Company | Yes |
| 2 | - | Customer | `customer` | Link | Customer | Yes |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order | Yes |
| 4 | - | Style | `style_item` | Link | Item | Yes |
| 5 | - | Style No | `style_no` | Data |  |  |
| 6 | - | Style Name | `style_name` | Data |  |  |
| 7 | - | Season | `season` | Data |  |  |
| 8 | - | Status | `status` | Select | Draft, Issued, In Cutting, In Sewing, At Subcontractor, In Finishing, Packed, Shipped, Closed, Superseded, Cancelled |  |
| 9 | - | Ex-Factory Date | `ex_factory_date` | Date |  | Yes |
| 10 | - | PCD (Planned Cut Date) | `pcd` | Date |  |  |
| 11 | - | Factory | `factory` | Link | Plant Floor |  |
| 12 | - | Line | `line` | Link | Workstation |  |
| 13 | - | Issue Date | `issue_date` | Date |  |  |
| 14 | References | Sales Contract | `sales_contract` | Link | Sales Contract |  |
| 15 | References | Buyer POs | `buyer_pos` | Small Text |  |  |
| 16 | References | Local Contract No | `local_contract_no` | Data |  |  |
| 17 | References | Declaration No | `declaration_no` | Data |  |  |
| 18 | References | TOP Sample Size | `top_sample_size` | Data |  |  |
| 19 | References | TOP Pcs per Colour | `top_sample_qty_per_colour` | Int |  |  |
| 20 | References | TOP Sample ETA | `top_sample_eta` | Date |  |  |
| 21 | References | Washed Style | `is_washed` | Check |  |  |
| 22 | Pilot Run | Pilot Run Required | `pilot_required` | Check |  |  |
| 23 | Pilot Run | Waive Pilot Run | `pilot_waiver` | Check |  |  |
| 24 | Pilot Run | Waiver Reason | `pilot_waiver_reason` | Small Text |  |  |
| 25 | Pilot Run | Bundle Size (pcs) | `bundle_size` | Int |  |  |
| 26 | Pilot Run | Default Extra Cut % | `default_extra_cut_pct` | Percent |  |  |
| 27 | Pilot Run | Trim Allowance % | `trim_allowance_pct` | Percent |  |  |
| 28 | Size Breakup | Colour x Size | `lines` | Table | Production Card Line | Yes |
| 29 | Fabric | Fabric Required | `fabrics` | Table | Production Card Fabric |  |
| 30 | Subcontract Route | Processes | `processes` | Table | Production Card Process |  |
| 31 | Packing | Packing Instruction | `packing_instruction` | Data |  |  |
| 32 | Packing | Packing Requirements | `packing_requirements` | Small Text |  |  |
| 33 | Revision and Sign-off | Revision No | `revision_no` | Int |  |  |
| 34 | Revision and Sign-off | Previous Card | `previous_card` | Link | Production Card |  |
| 35 | Revision and Sign-off | Revision Reason | `revision_reason` | Small Text |  |  |
| 36 | Revision and Sign-off | Made By | `made_by` | Link | User |  |
| 37 | Revision and Sign-off | Checked By | `checked_by` | Link | User |  |
| 38 | Revision and Sign-off | QC for This Style | `qc_assigned` | Link | User |  |
| 39 | Revision and Sign-off | Remarks | `remarks` | Small Text |  |  |
| 40 | Revision and Sign-off | Plan of Action for Fabric, Cutting and Sewing | `action_plan_for_fabric` | Small Text |  |  |
| 41 | Revision and Sign-off | Red Flags | `red_flags` | Small Text |  |  |
| 42 | Revision and Sign-off | Amended From | `amended_from` | Link | Production Card |  |

### Production Card Fabric

- **Type:** Child table (child of `Production Card`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Production Card. Fabric line for the card: colour, FR row, fabric, role, consumption, UOM, source (FR, cost sheet, marker or manual), required, FR net, accepted, issued and shortage metres.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | FR Row | `fabric_requisition_item` | Data |  |  |
| 3 | - | Fabric | `fabric_item` | Link | Item |  |
| 4 | - | Role | `material_role` | Select | Shell, Lining, Pocketing, Contrast, Other |  |
| 5 | - | Material Code (reference) | `material_code_ref` | Data |  |  |
| 6 | - | Consumption | `consumption` | Float |  | Yes |
| 7 | - | UOM | `consumption_uom` | Link | UOM |  |
| 8 | - | Source | `consumption_source` | Select | FR, Cost Sheet, Marker, Manual |  |
| 9 | - | Required (m) | `required_m` | Float |  |  |
| 10 | - | FR Net (m) | `fr_net_m` | Float |  |  |
| 11 | - | Accepted (m) | `accepted_m` | Float |  |  |
| 12 | - | Issued (m) | `issued_m` | Float |  |  |
| 13 | - | Shortage (m) | `shortage_m` | Float |  |  |

### Production Card Line

- **Type:** Child table (child of `Production Card`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Production Card. Colour x size line: order qty, max ship qty, extra cut %, planned cut, sample or pilot pieces, remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Order Qty | `order_qty` | Int |  |  |
| 4 | - | Max Ship Qty | `max_qty` | Int |  |  |
| 5 | - | Extra Cut % | `extra_cut_pct` | Percent |  |  |
| 6 | - | Planned Cut | `planned_cut_qty` | Int |  |  |
| 7 | - | Sample / Pilot Pcs | `planned_sample_qty` | Int |  |  |
| 8 | - | Remarks | `remarks` | Data |  |  |

### Production Card Process

- **Type:** Child table (child of `Production Card`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Production Card. Subcontract process route: process, before or after sewing, sequence, sent as garments or cut panels, vendor, colour (blank means all), purchase order, approved standard sample and notes.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Process | `subcontract_process` | Link | Subcontract Process | Yes |
| 2 | - | Position | `position` | Select | Before Sewing, After Sewing | Yes |
| 3 | - | Sequence | `sequence` | Int |  |  |
| 4 | - | Sent As | `item_state` | Select | Garments, Cut Panels |  |
| 5 | - | Vendor | `supplier` | Link | Supplier |  |
| 6 | - | Colour (blank = all) | `colour` | Data |  |  |
| 7 | - | Purchase Order | `purchase_order` | Link | Purchase Order |  |
| 8 | - | Approved Standard | `approved_standard` | Link | Sample Approval |  |
| 9 | - | Notes | `notes` | Data |  |  |

### Cut Plan

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series CP-{YY}-{#####}
- **Deck:** Production

**What it holds:** Cutting plan for one production card and colour: fabric, component, pattern version, nap and stripe-matching flags, card vs marker consumption and variance, approval, lays, and the size ratio used to plan output. Status is Draft, Pending Approval, Released or Superseded.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 3 | - | Style No | `style_no` | Data |  |  |
| 4 | - | Colour | `colour` | Data |  | Yes |
| 5 | - | Fabric | `fabric_item` | Link | Item | Yes |
| 6 | - | Component | `component` | Select | Shell, Lining, Pocketing, Contrast, Other |  |
| 7 | - | Status | `status` | Select | Draft, Pending Approval, Released, Superseded |  |
| 8 | - | Pattern Version | `pattern_version` | Data |  |  |
| 9 | - | Directional Fabric (nap) | `nap_direction` | Check |  |  |
| 10 | - | Check / Stripe Matching | `match_pattern` | Check |  |  |
| 11 | Consumption | Card Consumption (m / pc) | `fr_consumption` | Float |  |  |
| 12 | Consumption | Marker Consumption (m / pc) | `marker_consumption` | Float |  |  |
| 13 | Consumption | Variance % | `variance_pct` | Percent |  |  |
| 14 | Consumption | Approved By | `approved_by` | Link | User |  |
| 15 | Consumption | Approved On | `approved_on` | Datetime |  |  |
| 16 | Consumption | Approval Note | `approval_note` | Small Text |  |  |
| 17 | Lays | Lays | `lays` | Table | Cut Plan Lay |  |
| 18 | Lays | Size Ratios | `ratios` | Table | Cut Plan Ratio |  |
| 19 | Plan vs Card | Planned Output per Size | `size_summary` | Small Text |  |  |
| 20 | Plan vs Card | Red Flags | `red_flags` | Small Text |  |  |
| 21 | Plan vs Card | Notes | `notes` | Small Text |  |  |

### Cut Plan Lay

- **Type:** Child table (child of `Cut Plan`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Cut Plan. Planned lay: lay number, marker name, marker length and width, efficiency, plies, shade band, width and shrinkage group, pieces per ply and planned pieces.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Lay No | `lay_no` | Int |  | Yes |
| 2 | - | Marker | `marker_ref` | Data |  |  |
| 3 | - | Marker Length (m) | `marker_length_m` | Float |  | Yes |
| 4 | - | Marker Width (cm) | `marker_width_cm` | Float |  |  |
| 5 | - | Efficiency % | `marker_efficiency_pct` | Percent |  |  |
| 6 | - | Plies | `planned_plies` | Int |  | Yes |
| 7 | - | Shade Band | `shade_band` | Data |  |  |
| 8 | - | Width Group (cm) | `width_group_cm` | Float |  |  |
| 9 | - | Shrinkage Group | `shrinkage_group` | Data |  |  |
| 10 | - | Pcs / Ply | `pieces_per_ply` | Int |  |  |
| 11 | - | Planned Pcs | `planned_pieces` | Int |  |  |

### Cut Plan Ratio

- **Type:** Child table (child of `Cut Plan`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Cut Plan. Size ratio: lay number, size, pieces per ply.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Lay No | `lay_no` | Int |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Pieces per Ply | `ratio` | Int |  | Yes |

### Lay Report

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series LAY-{YY}-{#####}
- **Deck:** Production

**What it holds:** Actual cutting record (submittable) for one lay: lay number, colour, fabric, purpose (bulk, pilot, re-cut, sample), marker and actual length, rolls laid, sizes cut, panels rejected, total plies, pieces cut, actual vs CAD consumption, bulk-gate override, and the remnant return stock entry.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Cut Plan | `cut_plan` | Link | Cut Plan |  |
| 3 | - | Lay No | `lay_no` | Int |  | Yes |
| 4 | - | Colour | `colour` | Data |  | Yes |
| 5 | - | Fabric | `fabric_item` | Link | Item | Yes |
| 6 | - | Component | `component` | Select | Shell, Lining, Pocketing, Contrast, Other |  |
| 7 | - | Paired Shell Lay | `paired_with` | Link | Lay Report |  |
| 8 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample | Yes |
| 9 | - | Re-cut Request | `recut_request` | Link | Recut Request |  |
| 10 | - | Lay Date | `lay_date` | Date |  | Yes |
| 11 | - | Table No | `table_no` | Data |  |  |
| 12 | - | Line | `line` | Link | Workstation |  |
| 13 | - | Shade Band | `shade_band` | Data |  |  |
| 14 | Marker | Marker | `marker_ref` | Data |  |  |
| 15 | Marker | Marker Length (m) | `marker_length_m` | Float |  | Yes |
| 16 | Marker | Marker Width (cm) | `marker_width_cm` | Float |  |  |
| 17 | Marker | Marker Efficiency % | `marker_efficiency_pct` | Percent |  |  |
| 18 | Marker | Cutting Supervisor | `cutting_supervisor` | Link | User |  |
| 19 | Marker | Spreading Operator | `spreading_operator` | Data |  |  |
| 20 | Marker | Cutting Operator | `cutting_operator` | Data |  |  |
| 21 | Rolls Laid | Rolls | `rolls` | Table | Lay Roll | Yes |
| 22 | Sizes Cut | Sizes | `sizes` | Table | Lay Size | Yes |
| 23 | Panels Rejected at Cutting | Rejected Panels | `panel_rejects` | Table | Lay Panel Reject |  |
| 24 | Totals | Total Plies | `total_plies` | Int |  |  |
| 25 | Totals | Laid (m) | `laid_m` | Float |  |  |
| 26 | Totals | Pieces Cut | `pieces_cut` | Int |  |  |
| 27 | Totals | Rejected Panels | `rejected_pieces` | Int |  |  |
| 28 | Totals | Lay Consumption (m / pc) | `lay_consumption` | Float |  |  |
| 29 | Totals | CAD Consumption (m / pc) | `cad_consumption` | Float |  |  |
| 30 | Totals | Difference | `consumption_difference` | Float |  |  |
| 31 | Bulk Gate | Override Bulk Gate | `gate_override` | Check |  |  |
| 32 | Bulk Gate | Override Reason | `gate_override_reason` | Small Text |  |  |
| 33 | Bulk Gate | Remnant Return Stock Entry | `remnant_entry` | Link | Stock Entry |  |
| 34 | Bulk Gate | Remarks | `remarks` | Small Text |  |  |
| 35 | Bulk Gate | Amended From | `amended_from` | Link | Lay Report |  |

### Lay Panel Reject

- **Type:** Child table (child of `Lay Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Lay Report. Panel rejected at cutting: size, quantity, defect code, fault source, whether it needs a re-cut, and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Size | `size` | Data |  | Yes |
| 2 | - | Qty | `qty` | Int |  | Yes |
| 3 | - | Defect | `defect_code` | Link | Apparel Defect Code | Yes |
| 4 | - | Fault | `fault_source` | Select | (blank), Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Unknown |  |
| 5 | - | Needs Re-cut | `replace` | Check |  |  |
| 6 | - | Remarks | `remarks` | Data |  |  |

### Lay Roll

- **Type:** Child table (child of `Lay Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Lay Report. Roll used in a lay: batch, roll number, dye lot, shade, width, available, plies, laid length, end bit, damage, splices and balance.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Roll (Batch) | `batch` | Link | Batch | Yes |
| 2 | - | Roll No | `roll_no` | Data |  |  |
| 3 | - | Dye Lot | `dye_lot` | Data |  |  |
| 4 | - | Shade | `shade_band` | Data |  |  |
| 5 | - | Width (cm) | `width_cm` | Float |  |  |
| 6 | - | Available (m) | `roll_length_m` | Float |  |  |
| 7 | - | Plies | `plies` | Int |  | Yes |
| 8 | - | Laid (m) | `length_laid_m` | Float |  |  |
| 9 | - | End Bit (m) | `end_bit_m` | Float |  |  |
| 10 | - | Damage (m) | `damage_m` | Float |  |  |
| 11 | - | Splices | `splices` | Int |  |  |
| 12 | - | Balance (m) | `balance_returned_m` | Float |  |  |
| 13 | - | Remarks | `remarks` | Data |  |  |

### Lay Size

- **Type:** Child table (child of `Lay Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Lay Report. Size cut in the lay: pieces per ply, pieces cut, panels checked and rejected.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Size | `size` | Data |  | Yes |
| 2 | - | Pcs / Ply | `ratio` | Int |  | Yes |
| 3 | - | Pieces Cut | `pieces_cut` | Int |  |  |
| 4 | - | Panels Checked | `panels_checked` | Int |  |  |
| 5 | - | Panels Rejected | `panels_rejected` | Int |  |  |

### Cut Bundle

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series BDL-{#######}
- **Deck:** Production

**What it holds:** Bundle of cut pieces (for example BDL-0000001) tied to a production card and lay: colour, size, component, purpose, bundle number, ply range, quantity, shade band, roll details, kit key, status (cut, issued, at subcontractor, back, complete), sewn and rejected counts, and line.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Lay Report | `lay_report` | Link | Lay Report | Yes |
| 3 | - | Colour | `colour` | Data |  |  |
| 4 | - | Size | `size` | Data |  |  |
| 5 | - | Component | `component` | Select | Shell, Lining, Pocketing, Contrast, Other |  |
| 6 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample |  |
| 7 | - | Bundle No | `bundle_no` | Int |  |  |
| 8 | - | Body | `body_no` | Int |  |  |
| 9 | - | Ply From | `ply_from` | Int |  |  |
| 10 | - | Ply To | `ply_to` | Int |  |  |
| 11 | - | Qty | `qty` | Int |  | Yes |
| 12 | - | Shade Band | `shade_band` | Data |  |  |
| 13 | - | Rolls | `roll_nos` | Small Text |  |  |
| 14 | - | Kit Key | `kit_key` | Data |  |  |
| 15 | - | Status | `status` | Select | Cut, Issued, At Subcontractor, Back, Complete, Closed, Voided |  |
| 16 | - | Sewn | `sewn_qty` | Int |  |  |
| 17 | - | Rejected | `rejected_qty` | Int |  |  |
| 18 | - | Line | `line` | Link | Workstation |  |
| 19 | - | Short Bundle | `is_short` | Check |  |  |

### Recut Request

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series RC-{YY}-{#####}
- **Deck:** Production

**What it holds:** Request to re-cut panels or a bundle after a defect (submittable): production card, colour, size, quantity, reason, what it replaces, the roll to cut from, and approval for a different roll or dye lot.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Colour | `colour` | Data |  | Yes |
| 3 | - | Size | `size` | Data |  | Yes |
| 4 | - | Qty | `qty` | Int |  | Yes |
| 5 | - | Reason | `reason` | Link | Apparel Defect Code | Yes |
| 6 | - | Status | `status` | Select | Open, Cut, Closed |  |
| 7 | - | Replaces Lay | `replaces_lay` | Link | Lay Report |  |
| 8 | - | Replaces Bundle | `replaces_bundle` | Link | Cut Bundle |  |
| 9 | - | Roll to Cut From | `source_roll` | Link | Batch |  |
| 10 | - | Different Roll / Dye Lot Approved | `different_roll_approved` | Check |  |  |
| 11 | - | Approved By | `approved_by` | Link | User |  |
| 12 | - | Remarks | `remarks` | Small Text |  |  |
| 13 | - | Amended From | `amended_from` | Link | Recut Request |  |

### Line Input

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series LIN-{YY}-{#####}
- **Deck:** Production

**What it holds:** Record of bundles loaded onto a sewing line (submittable): production card, line, date, purpose, who loaded them, garments loaded, and the bundle rows.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Line | `line` | Link | Workstation | Yes |
| 3 | - | Date | `input_date` | Date |  | Yes |
| 4 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample | Yes |
| 5 | - | Loaded By | `loaded_by` | Link | User |  |
| 6 | - | Garments Loaded | `total_qty` | Int |  |  |
| 7 | Bundles | Bundles | `bundles` | Table | Line Input Bundle | Yes |
| 8 | Bundles | Remarks | `remarks` | Small Text |  |  |
| 9 | Bundles | Amended From | `amended_from` | Link | Line Input |  |

### Line Input Bundle

- **Type:** Child table (child of `Line Input`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line Input. Bundle loaded onto the line: bundle, colour, size, quantity, component and shade.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Bundle | `bundle` | Link | Cut Bundle |  |
| 2 | - | Colour | `colour` | Data |  |  |
| 3 | - | Size | `size` | Data |  |  |
| 4 | - | Qty | `qty` | Int |  | Yes |
| 5 | - | Component | `component` | Data |  |  |
| 6 | - | Shade | `shade_band` | Data |  |  |

### Line QC Report

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series LQC-{YY}-{#####}
- **Deck:** Production

**What it holds:** Quality audit of a line or station (submittable): audit type (inline traffic light, end-line or finishing), hourly checks, defect analysis, dispositions (rework, reject, B-grade), finishing pass counts, operator traffic lights, and the totals with DHU, defective %, RFT %.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Audit Type | `audit_type` | Select | Inline (Traffic Light), End-line, Finishing | Yes |
| 2 | - | Date | `report_date` | Date |  | Yes |
| 3 | - | Line | `line` | Link | Workstation |  |
| 4 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 5 | - | Inspected By | `inspected_by` | Link | User |  |
| 6 | - | Line QA | `line_qa` | Link | User |  |
| 7 | Hourly Check | Hourly | `hours` | Table | Line QC Hour |  |
| 8 | Hourly Check | Defect Analysis | `defects` | Table | Line QC Defect |  |
| 9 | Dispositions (rework, reject, B-grade) | Dispositions | `dispositions` | Table | Line QC Disposition |  |
| 10 | Dispositions (rework, reject, B-grade) | Passed A-Grade by Colour and Size (finishing) | `passes` | Table | Line QC Pass |  |
| 11 | Traffic Light (inline) | Operators Checked | `traffic` | Table | Line QC Traffic |  |
| 12 | Result | Total Checked | `total_checked` | Int |  |  |
| 13 | Result | Total Passed | `total_passed` | Int |  |  |
| 14 | Result | Total Defects | `total_defects` | Int |  |  |
| 15 | Result | Repaired and Passed Later | `reworked_passed` | Int |  |  |
| 16 | Result | DHU | `dhu` | Float |  |  |
| 17 | Result | Defective % | `defect_pct` | Percent |  |  |
| 18 | Result | RFT % | `rft_pct` | Percent |  |  |
| 19 | Result | Remarks | `remarks` | Small Text |  |  |
| 20 | Result | Amended From | `amended_from` | Link | Line QC Report |  |

### Line QC Defect

- **Type:** Child table (child of `Line QC Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line QC Report. Defect counted in the hour: defect code, quantity and operation.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Hour | `hour_slot` | Data |  |  |
| 2 | - | Defect | `defect_code` | Link | Apparel Defect Code | Yes |
| 3 | - | Qty | `qty` | Int |  | Yes |
| 4 | - | Operation | `operation` | Data |  |  |

### Line QC Disposition

- **Type:** Child table (child of `Line QC Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line QC Report. Disposition of defective pieces: rework, reject or B-grade, with colour, size, quantity, defect, fault source and whether re-cut is needed.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card |  |
| 2 | - | Colour | `colour` | Data |  | Yes |
| 3 | - | Size | `size` | Data |  | Yes |
| 4 | - | Disposition | `disposition` | Select | Rework, Reject, B-Grade | Yes |
| 5 | - | Qty | `qty` | Int |  | Yes |
| 6 | - | Defect | `defect_code` | Link | Apparel Defect Code |  |
| 7 | - | Fault | `fault_source` | Select | (blank), Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Unknown |  |
| 8 | - | Needs Re-cut | `replace` | Check |  |  |

### Line QC Hour

- **Type:** Child table (child of `Line QC Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line QC Report. Hour: checked and passed quantity.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Hour | `hour_slot` | Data |  | Yes |
| 2 | - | Checked | `checked` | Int |  | Yes |
| 3 | - | Passed | `passed` | Int |  | Yes |

### Line QC Pass

- **Type:** Child table (child of `Line QC Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line QC Report. Passed A-grade pieces by colour and size (finishing).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Passed A-Grade | `qty` | Int |  | Yes |

### Line QC Traffic

- **Type:** Child table (child of `Line QC Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Line QC Report. Inline traffic light entry for one operator and round: checked, defects and colour light.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Operator | `operator` | Data |  | Yes |
| 2 | - | Round | `round_no` | Int |  |  |
| 3 | - | Checked | `pieces_checked` | Int |  |  |
| 4 | - | Defects | `defects` | Int |  |  |
| 5 | - | Light | `light` | Select | (blank), Green, Yellow, Red |  |

### Daily Line Report

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series DLR-{YY}-{#####}
- **Deck:** Production

**What it holds:** Daily output record for a line (submittable): date, line, shift minutes, operators and helpers, overtime, downtime and reason, output by colour and size, hourly target vs output, computed efficiency, learning-curve %, and the amendment link.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Date | `report_date` | Date |  | Yes |
| 2 | - | Line | `line` | Link | Workstation | Yes |
| 3 | - | Shift Minutes | `shift_minutes` | Int |  |  |
| 4 | - | Operators Present | `operators_present` | Int |  | Yes |
| 5 | - | Helpers Present | `helpers_present` | Int |  |  |
| 6 | - | Overtime Minutes | `overtime_minutes` | Int |  |  |
| 7 | - | Downtime Minutes | `downtime_minutes` | Int |  |  |
| 8 | - | Downtime Reason | `downtime_reason` | Select | (blank), No Work, Machine, Power, Material, Absence, Changeover, Other |  |
| 9 | Output | Output | `outputs` | Table | Daily Line Report Output | Yes |
| 10 | Output | Hourly | `hours` | Table | Daily Line Report Hour |  |
| 11 | Result | Total Output | `total_output` | Int |  |  |
| 12 | Result | Produced Minutes | `produced_minutes` | Float |  |  |
| 13 | Result | Available Minutes | `available_minutes` | Float |  |  |
| 14 | Result | Efficiency % | `efficiency_pct` | Percent |  |  |
| 15 | Result | Target | `target_qty` | Float |  |  |
| 16 | Result | Output vs Target | `variance_to_target` | Float |  |  |
| 17 | Result | Day on Line | `learning_day` | Int |  |  |
| 18 | Result | Learning Curve % | `learning_factor_pct` | Percent |  |  |
| 19 | Result | Notes | `notes` | Small Text |  |  |
| 20 | Result | Amended From | `amended_from` | Link | Daily Line Report |  |

### Daily Line Report Hour

- **Type:** Child table (child of `Daily Line Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Daily Line Report. Hour slot with target and output.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Hour | `hour_slot` | Data |  | Yes |
| 2 | - | Target | `target_qty` | Int |  |  |
| 3 | - | Output | `output_qty` | Int |  |  |

### Daily Line Report Output

- **Type:** Child table (child of `Daily Line Report`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Daily Line Report. Output row: production card, colour, size, purpose, passed end-line quantity and bundle.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Colour | `colour` | Data |  | Yes |
| 3 | - | Size | `size` | Data |  | Yes |
| 4 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample |  |
| 5 | - | Passed End-line | `qty` | Int |  | Yes |
| 6 | - | Bundle | `bundle` | Link | Cut Bundle |  |

### Production Movement

- **Type:** Parent document
- **Submittable:** no
- **Naming:** random hash
- **Deck:** Production

**What it holds:** Stock-ledger style record of garments moving between production stages (cut, sewn in, sewn out, subcontract out and back, finishing, packed, shipped). Each row links to its source document; it is the basis for WIP and output reports.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 3 | - | Style | `style_item` | Link | Item |  |
| 4 | - | Colour | `colour` | Data |  |  |
| 5 | - | Size | `size` | Data |  |  |
| 6 | - | Stage | `stage` | Select | CUT, CUT_REJECT, SEW_IN, SEW_OUT, SEW_REJECT, SC_OUT, SC_BACK_GOOD, SC_BACK_REJECT_VENDOR, SC_BACK_REJECT_FACTORY, FIN_IN, FIN_A, FIN_B, FIN_REJECT, SAMPLE_OUT, PACKED, SHIPPED | Yes |
| 7 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample |  |
| 8 | - | Process | `subcontract_process` | Link | Subcontract Process |  |
| 9 | - | Qty | `qty` | Float |  | Yes |
| 10 | - | Posting Date | `posting_date` | Date |  |  |
| 11 | - | Line | `line` | Link | Workstation |  |
| 12 | - | Supplier | `supplier` | Link | Supplier |  |
| 13 | - | Shade Band | `shade_band` | Data |  |  |
| 14 | - | Fault Source | `fault_source` | Select | (blank), Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Unknown |  |
| 15 | - | Source Document Type | `source_doctype` | Link | DocType |  |
| 16 | - | Source Document | `source_name` | Dynamic Link | dynamic (by another field) |  |
| 17 | - | Source Row | `source_row` | Data |  |  |

### Production Adjustment

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series PADJ-{YY}-{#####}
- **Deck:** Production

**What it holds:** Manual correction to a production stage count (submittable): production card, date, stage, purpose, colour, size, signed quantity and the reason.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Posting Date | `posting_date` | Date |  | Yes |
| 3 | - | Stage | `stage` | Select | CUT, CUT_REJECT, SEW_IN, SEW_OUT, SEW_REJECT, SC_OUT, SC_BACK_GOOD, SC_BACK_REJECT_VENDOR, SC_BACK_REJECT_FACTORY, FIN_IN, FIN_A, FIN_B, FIN_REJECT, SAMPLE_OUT, PACKED, SHIPPED | Yes |
| 4 | - | Purpose | `purpose` | Select | Bulk, Pilot, Re-cut, Sample |  |
| 5 | - | Process | `subcontract_process` | Link | Subcontract Process |  |
| 6 | - | Colour | `colour` | Data |  | Yes |
| 7 | - | Size | `size` | Data |  | Yes |
| 8 | - | Qty (+ or -) | `qty` | Float |  | Yes |
| 9 | - | Reason | `reason` | Small Text |  | Yes |
| 10 | - | Amended From | `amended_from` | Link | Production Adjustment |  |

### Pilot Run

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** series PR-{YY}-{#####}
- **Deck:** Production

**What it holds:** Pilot run review before bulk (submittable): production card, line, team (supervisor, line QC, cutting, CAD), colour quantities, checks, SAM validation by operation, measurements after wash, defects, participants, the outcome (approved, approved with comments, rejected or re-run) and the link to the PP meeting.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 3 | - | Style | `style_item` | Link | Item |  |
| 4 | - | Style No | `style_no` | Data |  |  |
| 5 | - | Result | `status` | Select | Draft, Approved, Approved with Comments, Rejected, Re-run |  |
| 6 | - | Decision | `decision` | Select | (blank), Approved, Approved with Comments, Rejected, Re-run |  |
| 7 | - | Run Date | `run_date` | Date |  | Yes |
| 8 | - | Line | `line` | Link | Workstation |  |
| 9 | - | Pilot Review Meeting (PP Meeting) | `pilot_pp_meeting` | Link | PP Meeting |  |
| 10 | People | Line Supervisor | `line_supervisor` | Link | User |  |
| 11 | People | Line QC | `line_qc` | Link | User |  |
| 12 | People | Cutting Supervisor | `cutting_supervisor` | Link | User |  |
| 13 | People | CAD In-charge | `cad_incharge` | Link | User |  |
| 14 | Pieces (from the ledger, purpose Pilot) | Colours | `colours` | Table | Pilot Run Colour | Yes |
| 15 | Checks | Checks | `checks` | Table | Pilot Run Check |  |
| 16 | Pattern and Cutting Comments | QC Comment (pattern and cutting) | `pattern_cutting_qc_comment` | Small Text |  |  |
| 17 | Pattern and Cutting Comments | Supervisor Comment (pattern and cutting) | `pattern_cutting_supervisor_comment` | Small Text |  |  |
| 18 | SAM Validation | Operations | `operations` | Table | Pilot Run Operation |  |
| 19 | SAM Validation | Planned vs Actual SAM % | `achieved_efficiency_pct` | Percent |  |  |
| 20 | SAM Validation | Bottlenecks | `bottleneck_count` | Int |  |  |
| 21 | Measurements After Wash | Measurements | `measurements` | Table | Sample Measurement |  |
| 22 | Measurements After Wash | Reason for Out-of-Tolerance Readings | `measurement_note` | Small Text |  |  |
| 23 | Defects Found | Defects | `defects` | Table | Pilot Run Defect |  |
| 24 | Outcome | Notes | `result_notes` | Small Text |  |  |
| 25 | Outcome | Approved By | `approved_by` | Link | User |  |
| 26 | Outcome | Approved On | `approved_on` | Datetime |  |  |
| 27 | Outcome | Participants | `participants` | Table | Pilot Run Participant |  |
| 28 | Outcome | Amended From | `amended_from` | Link | Pilot Run |  |

### Pilot Run Check

- **Type:** Child table (child of `Pilot Run`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Pilot Run. Check result (yes, no or N/A) against a production check item, with comment, action taken, who and where.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Check | `check_item` | Link | Production Check Item | Yes |
| 2 | - | Result | `result` | Select | (blank), Yes, No, N/A |  |
| 3 | - | Comment | `comment` | Small Text |  |  |
| 4 | - | Action Taken | `action_taken` | Small Text |  |  |
| 5 | - | Who | `responsible` | Data |  |  |
| 6 | - | Where | `location` | Data |  |  |

### Pilot Run Colour

- **Type:** Child table (child of `Pilot Run`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Pilot Run. Colour pieces: planned, cut, sewn, washed and rejected.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Sizes Run | `sizes_run` | Data |  |  |
| 3 | - | Planned Pcs | `qty_planned` | Int |  |  |
| 4 | - | Cut | `cut_qty` | Int |  |  |
| 5 | - | Sewn | `sewn_qty` | Int |  |  |
| 6 | - | Washed | `washed_qty` | Int |  |  |
| 7 | - | Rejected | `rejected_qty` | Int |  |  |

### Pilot Run Defect

- **Type:** Child table (child of `Pilot Run`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Pilot Run. Defect found in the pilot: defect code, quantity and note.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Defect | `defect_code` | Link | Apparel Defect Code | Yes |
| 2 | - | Qty | `qty` | Int |  |  |
| 3 | - | Note | `note` | Data |  |  |

### Pilot Run Operation

- **Type:** Child table (child of `Pilot Run`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Pilot Run. Operation SAM check: planned vs actual SAM and whether it is a bottleneck.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Operation | `operation` | Data |  | Yes |
| 2 | - | Planned SAM | `planned_sam` | Float |  |  |
| 3 | - | Actual SAM | `actual_sam` | Float |  |  |
| 4 | - | Bottleneck | `bottleneck` | Check |  |  |
| 5 | - | Note | `note` | Data |  |  |

### Pilot Run Participant

- **Type:** Child table (child of `Pilot Run`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Pilot Run. Person present at the pilot: name and designation.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Name | `participant_name` | Data |  | Yes |
| 2 | - | Designation | `designation` | Data |  |  |

### Sample Measurement

- **Type:** Child table (Shared: Production (Pilot Run) and Plan and Approve (Sample Approval))
- **Submittable:** no
- **Deck:** Shared: Production (Pilot Run) and Plan and Approve (Sample Approval)

**What it holds:** Child of Pilot Run and Sample Approval. Measurement table: point of measure, size, spec, plus and minus tolerance, up to five sample readings, worst deviation and in-tolerance flag.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | POM | `pom_code` | Data |  |  |
| 2 | - | Point of Measure | `point_of_measure` | Data |  | Yes |
| 3 | - | Size | `size` | Data |  |  |
| 4 | - | Spec | `spec` | Float |  |  |
| 5 | - | Tol + | `tol_plus` | Float |  |  |
| 6 | - | Tol − | `tol_minus` | Float |  |  |
| 7 | - | Sample 1 | `actual` | Float |  |  |
| 8 | - | Sample 2 | `reading_2` | Float |  |  |
| 9 | - | Sample 3 | `reading_3` | Float |  |  |
| 10 | - | Sample 4 | `reading_4` | Float |  |  |
| 11 | - | Sample 5 | `reading_5` | Float |  |  |
| 12 | - | Worst Deviation | `deviation` | Float |  |  |
| 13 | - | In Tolerance | `in_tolerance` | Check |  |  |

### Operation Bulletin

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series OB-{YY}-{#####}
- **Deck:** Production

**What it holds:** Operation breakdown (the SAM sheet) for a style: version and status, working minutes, expected efficiency, operations with machine and manual SAM, total SAM, target per day and hour, pitch time and operators needed.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Style | `style_item` | Link | Item | Yes |
| 2 | - | Version | `version` | Int |  | Yes |
| 3 | - | Status | `status` | Select | Draft, Active, Superseded |  |
| 4 | - | Buyer | `buyer` | Link | Customer |  |
| 5 | - | Description | `description` | Data |  |  |
| 6 | - | Colour (reference) | `colour` | Data |  |  |
| 7 | - | Workers Planned (operators + helpers) | `operators` | Int |  | Yes |
| 8 | - | Working Minutes / Day | `working_minutes` | Int |  |  |
| 9 | - | Expected Efficiency % | `expected_efficiency_pct` | Percent |  |  |
| 10 | Totals | Total SAM / Garment | `total_sam` | Float |  |  |
| 11 | Totals | Sewing (M/C) SAM | `sewing_sam` | Float |  |  |
| 12 | Totals | Manual SAM | `manual_sam` | Float |  |  |
| 13 | Totals | Operations | `operation_count` | Int |  |  |
| 14 | Totals | Target / Day | `target_per_day` | Float |  |  |
| 15 | Totals | Target / Hour | `target_per_hour` | Float |  |  |
| 16 | Totals | Pcs / Machine / Day | `pcs_per_machine` | Float |  |  |
| 17 | Totals | Pitch Time (min) | `pitch_time` | Float |  |  |
| 18 | Operations | Operations | `operations` | Table | OB Operation |  |
| 19 | Operations | Source Workbook | `source_file` | Attach |  |  |

### OB Operation

- **Type:** Child table (child of `Operation Bulletin`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Operation Bulletin. One operation: number, part, description, machine, machine SAM, manual SAM, operators needed, target per hour and pitch comparison.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | No | `seq` | Int |  |  |
| 2 | - | Part / Group | `part_group` | Data |  |  |
| 3 | - | Operation | `operation` | Data |  | Yes |
| 4 | - | Machine | `machine_type` | Data |  |  |
| 5 | - | M/C SAM | `machine_sam` | Float |  |  |
| 6 | - | Manual SAM | `manual_sam` | Float |  |  |
| 7 | - | Operators Needed | `operators_needed` | Float |  |  |
| 8 | - | Target / hr | `target_per_hr` | Float |  |  |
| 9 | - | Vs Pitch | `pitch_flag` | Select | (blank), Above, Below |  |

### Needle Detector Log

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series ND-{YY}.{MM}-{####}
- **Deck:** Production

**What it holds:** Metal detector check log for a line (submittable): date, time, detector, test piece size, pass or fail, checker, and when it fails the last good check, rescans and action taken.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Check Date | `check_date` | Date |  | Yes |
| 2 | - | Check Time | `check_time` | Time |  |  |
| 3 | - | Line | `line` | Link | Workstation | Yes |
| 4 | - | Detector | `machine` | Data |  |  |
| 5 | - | Test Piece (mm) | `test_piece_mm` | Float |  |  |
| 6 | - | Result | `result` | Select | Pass, Fail | Yes |
| 7 | - | Checked By | `checked_by` | Link | User |  |
| 8 | If the check failed | Last Good Check | `last_good_check` | Datetime |  |  |
| 9 | If the check failed | Garments Rescanned | `garments_rescanned` | Int |  |  |
| 10 | If the check failed | Re-scan Done | `rescan_done` | Check |  |  |
| 11 | If the check failed | Action | `action` | Small Text |  |  |

### Subcontract Challan

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Delivery note to a subcontractor for a process (submittable): production card, supplier, process, pieces sent by colour and size, expected return, status (open, partly returned, returned, short closed).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Supplier | `supplier` | Link | Supplier | Yes |
| 5 | - | Process | `subcontract_process` | Link | Subcontract Process | Yes |
| 6 | - | Challan Date | `challan_date` | Date |  | Yes |
| 7 | - | Purchase Order | `purchase_order` | Link | Purchase Order |  |
| 8 | - | Expected Return Date | `expected_return_date` | Date |  |  |
| 9 | - | Vehicle No | `vehicle_no` | Data |  |  |
| 10 | Pieces | Pieces Sent | `rows` | Table | Subcontract Challan Row | Yes |
| 11 | Pieces | Total Qty | `total_qty` | Int |  |  |
| 12 | Pieces | Total Returned | `returned_qty` | Int |  |  |
| 13 | Status | Status | `status` | Select | Open, Partly Returned, Returned, Short Closed |  |
| 14 | Status | Short Close Reason | `short_close_reason` | Small Text |  |  |
| 15 | Status | Remarks | `remarks` | Small Text |  |  |
| 16 | Status | Amended From | `amended_from` | Link | Subcontract Challan |  |

### Subcontract Challan Row

- **Type:** Child table (child of `Subcontract Challan`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Subcontract Challan. Pieces sent: colour, size, quantity sent, returned, unit value and shade band.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Qty Sent | `qty` | Int |  | Yes |
| 4 | - | Returned | `returned_qty` | Int |  |  |
| 5 | - | Unit Value | `unit_value` | Currency |  |  |
| 6 | - | Shade Band | `shade_band` | Data |  |  |

### Subcontract Return

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Receipt of goods back from a subcontractor (submittable): linked challan, return date, delivery note, pieces received with good, vendor-fault and factory-fault counts.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Challan | `challan` | Link | Subcontract Challan | Yes |
| 2 | - | Production Card | `production_card` | Link | Production Card |  |
| 3 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 4 | - | Supplier | `supplier` | Link | Supplier |  |
| 5 | - | Process | `subcontract_process` | Link | Subcontract Process |  |
| 6 | - | Return Date | `return_date` | Date |  | Yes |
| 7 | - | Vendor Delivery Note | `vendor_dn` | Data |  |  |
| 8 | Pieces Received | Pieces | `rows` | Table | Subcontract Return Row | Yes |
| 9 | Pieces Received | Total Good | `total_good` | Int |  |  |
| 10 | Pieces Received | Total Reject Vendor | `total_reject_vendor` | Int |  |  |
| 11 | Pieces Received | Total Reject Factory | `total_reject_factory` | Int |  |  |
| 12 | Pieces Received | Remarks | `remarks` | Small Text |  |  |
| 13 | Pieces Received | Amended From | `amended_from` | Link | Subcontract Return |  |

### Subcontract Return Row

- **Type:** Child table (child of `Subcontract Return`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Subcontract Return. Return by colour and size: sent, good, vendor fault, factory fault, taken back to repair, defect code, shade or wash lot.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card |  |
| 2 | - | Challan Row | `challan_row` | Data |  |  |
| 3 | - | Colour | `colour` | Data |  | Yes |
| 4 | - | Size | `size` | Data |  | Yes |
| 5 | - | Sent | `sent_qty` | Int |  |  |
| 6 | - | Good | `good_qty` | Int |  |  |
| 7 | - | Vendor Fault | `reject_vendor_qty` | Int |  |  |
| 8 | - | Factory Fault | `reject_factory_qty` | Int |  |  |
| 9 | - | Taken Back to Repair | `accepted_for_repair` | Int |  |  |
| 10 | - | Defect Code | `defect_code` | Link | Apparel Defect Code |  |
| 11 | - | Shade / Wash Lot | `shade_band` | Data |  |  |

### Subcontract Settlement

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Invoice settlement for a subcontract challan (submittable): rate per piece, quantity on the vendor invoice, what came back, damage limit and penalty, payable quantity, gross, penalty and net amounts, and the Purchase Invoice and Debit Note links.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Challan | `challan` | Link | Subcontract Challan | Yes |
| 2 | - | Production Card | `production_card` | Link | Production Card |  |
| 3 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 4 | - | Supplier | `supplier` | Link | Supplier |  |
| 5 | - | Process | `subcontract_process` | Link | Subcontract Process |  |
| 6 | - | Purchase Order | `purchase_order` | Link | Purchase Order |  |
| 7 | - | Settlement Date | `settlement_date` | Date |  | Yes |
| 8 | - | Rate per Piece | `rate` | Currency |  | Yes |
| 9 | - | Quantity on Vendor Invoice | `invoiced_qty` | Int |  |  |
| 10 | - | Vendor Invoice | `vendor_invoice_ref` | Data |  |  |
| 11 | What came back | Sent Qty | `sent_qty` | Int |  |  |
| 12 | What came back | Good Qty | `good_qty` | Int |  |  |
| 13 | What came back | Vendor Fault | `reject_vendor_qty` | Int |  |  |
| 14 | What came back | Factory Fault | `reject_factory_qty` | Int |  |  |
| 15 | What came back | Short Qty | `short_qty` | Int |  |  |
| 16 | What came back | Damage Limit % | `threshold_pct` | Percent |  |  |
| 17 | What came back | Vendor Fault % | `vendor_reject_pct` | Percent |  |  |
| 18 | What came back | Penalty Qty | `penalty_qty` | Int |  |  |
| 19 | What came back | Penalty per Piece | `unit_value` | Currency |  |  |
| 20 | Amounts | Payable Qty | `payable_qty` | Int |  |  |
| 21 | Amounts | Gross Amount | `gross_amount` | Currency |  |  |
| 22 | Amounts | Penalty Amount | `penalty_amount` | Currency |  |  |
| 23 | Amounts | Net Amount | `net_amount` | Currency |  |  |
| 24 | Amounts | Quantity Tolerance % | `qty_tolerance_pct` | Percent |  |  |
| 25 | Amounts | Invoice vs Order % | `invoice_variance_pct` | Percent |  |  |
| 26 | Amounts | Variance Note | `variance_note` | Small Text |  |  |
| 27 | Accounts | Purchase Invoice | `purchase_invoice` | Link | Purchase Invoice |  |
| 28 | Accounts | Debit Note | `debit_note` | Link | Purchase Invoice |  |
| 29 | Accounts | Amended From | `amended_from` | Link | Subcontract Settlement |  |

### Finishing Receipt

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Receipt of finished pieces into the finishing area (submittable): source (sewing, subcontract return or other), supplier, line, pieces by colour and size with wash or shade lot, and totals.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Receipt Date | `receipt_date` | Date |  | Yes |
| 5 | - | Source | `source` | Select | Sewing, Subcontract Return, Other | Yes |
| 6 | - | Supplier | `supplier` | Link | Supplier |  |
| 7 | - | Finishing Line | `line` | Link | Workstation |  |
| 8 | Pieces Received into Finishing | Pieces | `rows` | Table | Finishing Receipt Row | Yes |
| 9 | Pieces Received into Finishing | Total Qty | `total_qty` | Int |  |  |
| 10 | Pieces Received into Finishing | Remarks | `remarks` | Small Text |  |  |
| 11 | Pieces Received into Finishing | Amended From | `amended_from` | Link | Finishing Receipt |  |

### Finishing Receipt Row

- **Type:** Child table (child of `Finishing Receipt`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Finishing Receipt. Pieces received: colour, size, quantity and shade or wash lot.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Qty | `qty` | Int |  | Yes |
| 4 | - | Shade / Wash Lot | `shade_band` | Data |  |  |

### Final Inspection

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Final inspection of packed goods (submittable): inspection type, party (factory QA, buyer QA, third party), packing lists in the lot, sampling plan (AQL level and sample size), cartons drawn and inspected, defects, carton-level results, the tests and conformity checks (FPT, GPT, Azo, fibre, metal detection, measurements, carton drop), and the verdict.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Inspection Type | `inspection_type` | Select | In Line, Pre-Final, Final, Re-inspection, 2nd Re-inspection, Other | Yes |
| 5 | - | Customer | `customer` | Link | Customer |  |
| 6 | - | Style Item | `style_item` | Link | Item |  |
| 7 | - | Inspection Date | `inspection_date` | Date |  | Yes |
| 8 | - | Inspector | `inspector` | Link | User |  |
| 9 | - | Inspected By Party | `inspected_by_party` | Select | Factory QA, Buyer QA, Third Party |  |
| 10 | - | Third Party Name | `third_party_name` | Data |  |  |
| 11 | - | External Report No | `report_ref` | Data |  |  |
| 12 | - | Previous Inspection | `previous_inspection` | Link | Final Inspection |  |
| 13 | Lot | Packing Lists in the Lot | `lots` | Table | Final Inspection Lot | Yes |
| 14 | Lot | Order Qty | `po_qty` | Int |  |  |
| 15 | Lot | Offered Qty | `offered_qty` | Int |  |  |
| 16 | Lot | Packed % of Order | `packed_pct` | Percent |  |  |
| 17 | Lot | Total Cartons | `total_cartons` | Int |  |  |
| 18 | Lot | Fibre Content per Test Report | `fibre_content` | Data |  |  |
| 19 | Lot | Size Range | `size_range` | Data |  |  |
| 20 | Lot | Country Of Origin | `country_of_origin` | Data |  |  |
| 21 | Sampling (ISO 2859-1, single, normal) | Aql Plan | `aql_plan` | Link | AQL Plan |  |
| 22 | Sampling (ISO 2859-1, single, normal) | Level | `inspection_level` | Data |  |  |
| 23 | Sampling (ISO 2859-1, single, normal) | Sample Size | `sample_size` | Int |  |  |
| 24 | Sampling (ISO 2859-1, single, normal) | Cartons to Inspect | `inspected_cartons` | Int |  |  |
| 25 | Sampling (ISO 2859-1, single, normal) | Critical Ac | `critical_ac` | Int |  |  |
| 26 | Sampling (ISO 2859-1, single, normal) | Critical Re | `critical_re` | Int |  |  |
| 27 | Sampling (ISO 2859-1, single, normal) | Major Ac | `major_ac` | Int |  |  |
| 28 | Sampling (ISO 2859-1, single, normal) | Major Re | `major_re` | Int |  |  |
| 29 | Sampling (ISO 2859-1, single, normal) | Minor Ac | `minor_ac` | Int |  |  |
| 30 | Sampling (ISO 2859-1, single, normal) | Minor Re | `minor_re` | Int |  |  |
| 31 | Sampling (ISO 2859-1, single, normal) | Carton Draw Seed | `draw_seed` | Int |  |  |
| 32 | Cartons Inspected | Cartons Picked | `cartons_picked` | Table | Final Inspection Carton |  |
| 33 | Tests and Conformity | FPT | `fpt` | Select | (blank), Yes, No, NA |  |
| 34 | Tests and Conformity | GPT | `gpt` | Select | (blank), Yes, No, NA |  |
| 35 | Tests and Conformity | Azo | `azo` | Select | (blank), Yes, No, NA |  |
| 36 | Tests and Conformity | Wash Care per Test Report | `wash_care_ok` | Select | (blank), Yes, No, NA |  |
| 37 | Tests and Conformity | Fibre Content per Test Report | `fibre_ok` | Select | (blank), Yes, No, NA |  |
| 38 | Tests and Conformity | Style as Sealer Sample | `sealer_style` | Select | (blank), Yes, No, NA |  |
| 39 | Tests and Conformity | Material as Sealer Sample | `sealer_material` | Select | (blank), Yes, No, NA |  |
| 40 | Tests and Conformity | Colour as Sealer Sample | `sealer_colour` | Select | (blank), Yes, No, NA |  |
| 41 | Tests and Conformity | Construction as Sealer Sample | `sealer_construction` | Select | (blank), Yes, No, NA |  |
| 42 | Tests and Conformity | Metal Detection Ok | `metal_detection_ok` | Select | (blank), Yes, No, NA |  |
| 43 | Tests and Conformity | Measurements within Tolerance | `measurement_ok` | Select | (blank), Yes, No, NA |  |
| 44 | Tests and Conformity | Carton Drop Test | `drop_test_ok` | Select | (blank), Yes, No, NA |  |
| 45 | Tests and Conformity | Barcode Scan | `barcode_ok` | Select | (blank), Yes, No, NA |  |
| 46 | Tests and Conformity | Packing as Instructed | `packing_ok` | Select | (blank), Yes, No, NA |  |
| 47 | Defects Found | Defects | `defects` | Table | Final Inspection Defect |  |
| 48 | Defects Found | Critical Found | `critical_found` | Int |  |  |
| 49 | Defects Found | Major Found | `major_found` | Int |  |  |
| 50 | Defects Found | Minor Found | `minor_found` | Int |  |  |
| 51 | Result | Result | `result` | Select | (blank), Accepted, Rejected, On Hold, Accepted with Concession |  |
| 52 | Result | Result by the Numbers | `computed_result` | Data |  |  |
| 53 | Result | Buyer Approval Reference | `concession_ref` | Data |  |  |
| 54 | Result | Agreed Discount % | `concession_discount_pct` | Percent |  |  |
| 55 | Result | Shipment Approved By | `approved_by` | Data |  |  |
| 56 | Result | Reinspection Date | `reinspection_date` | Date |  |  |
| 57 | Result | Reinspection Fee | `reinspection_fee` | Currency |  |  |
| 58 | Result | Fee Borne By | `fee_borne_by` | Select | (blank), Factory, Buyer, Supplier |  |
| 59 | Result | Remarks | `remarks` | Small Text |  |  |
| 60 | Result | Amended From | `amended_from` | Link | Final Inspection |  |

### Final Inspection Carton

- **Type:** Child table (child of `Final Inspection`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Final Inspection. Carton drawn for inspection: packing list, carton number, SSCC, pieces drawn, opened flag and swap reason.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Packing List | `packing_list` | Link | Packing List | Yes |
| 2 | - | Carton No | `carton_no` | Int |  | Yes |
| 3 | - | SSCC | `sscc` | Data |  |  |
| 4 | - | Pieces Drawn | `pieces_drawn` | Int |  |  |
| 5 | - | Opened | `opened` | Check |  |  |
| 6 | - | Swap Reason | `swap_reason` | Data |  |  |

### Final Inspection Defect

- **Type:** Child table (child of `Final Inspection`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Final Inspection. Defect found: defect code, severity, quantity, carton number and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Defect Code | `defect_code` | Link | Apparel Defect Code | Yes |
| 2 | - | Severity | `severity` | Data |  |  |
| 3 | - | Qty | `qty` | Int |  | Yes |
| 4 | - | Carton No | `carton_no` | Int |  |  |
| 5 | - | Remarks | `remarks` | Data |  |  |

### Final Inspection Lot

- **Type:** Child table (child of `Final Inspection`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Final Inspection. Packing list in the lot with pieces and cartons.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Packing List | `packing_list` | Link | Packing List | Yes |
| 2 | - | Pieces | `pieces` | Int |  |  |
| 3 | - | Cartons | `cartons` | Int |  |  |

### Packing List

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Production

**What it holds:** Packing list for a production card (submittable): pack type (solid colour solid size, assorted and so on), pieces per carton, carton type, carton ranges, carton contents, totals of cartons, pieces, net, gross and CBM, the over or short check against the order, and the final inspection and shipment links.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Production Card | `production_card` | Link | Production Card | Yes |
| 2 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Sales Order | `sales_order` | Link | Sales Order |  |
| 4 | - | Customer | `customer` | Link | Customer |  |
| 5 | - | Style Item | `style_item` | Link | Item |  |
| 6 | - | Packing Date | `packing_date` | Date |  | Yes |
| 7 | - | Buyer PO | `buyer_po` | Data |  |  |
| 8 | - | Ship To | `ship_to` | Data |  |  |
| 9 | - | Ship Via | `ship_via` | Select | (blank), Sea, Air, Courier, Road |  |
| 10 | - | Status | `status` | Select | Open, On Shipment, Shipped |  |
| 11 | How it is packed | Pack Type | `pack_type` | Select | Solid Colour Solid Size, Solid Colour Assorted Size, Assorted | Yes |
| 12 | How it is packed | Pieces per Carton | `pcs_per_carton` | Int |  | Yes |
| 13 | How it is packed | Carton Type | `carton_type` | Link | Carton Type |  |
| 14 | How it is packed | Tail Carton Rule | `tail_carton_rule` | Select | Mixed Colour and Size, Mixed Size Only, Own Carton |  |
| 15 | How it is packed | First Carton No | `carton_start` | Int |  |  |
| 16 | How it is packed | Ratio (assorted packs) | `ratios` | Table | Packing List Ratio |  |
| 17 | Cartons | Cartons | `cartons` | Table | Packing List Carton |  |
| 18 | Cartons | Carton Contents | `contents` | Table | Packing List Content |  |
| 19 | Totals | Total Cartons | `total_cartons` | Int |  |  |
| 20 | Totals | Total Pieces | `total_pieces` | Int |  |  |
| 21 | Totals | Net kg | `total_net_kg` | Float |  |  |
| 22 | Totals | Gross kg | `total_gross_kg` | Float |  |  |
| 23 | Totals | CBM | `total_cbm` | Float |  |  |
| 24 | Totals | Over / Short by Size | `size_summary` | Small Text |  |  |
| 25 | Totals | Total vs Order % | `total_vs_order_pct` | Percent |  |  |
| 26 | Links | Final Inspection | `final_inspection` | Link | Final Inspection |  |
| 27 | Links | Shipment | `shipment` | Link | Shipment |  |
| 28 | Links | Finished Goods Receipt | `fg_stock_entry` | Link | Stock Entry |  |
| 29 | Links | SSCC | `sscc` | Table | Packing List SSCC |  |
| 30 | Links | Remarks | `remarks` | Small Text |  |  |
| 31 | Links | Amended From | `amended_from` | Link | Packing List |  |

### Packing List Carton

- **Type:** Child table (child of `Packing List`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Packing List. Carton range (from and to carton number): carton type, dimensions, CBM, pieces per carton, net and gross weights, shade and tail-carton flag.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | From Carton | `carton_from` | Int |  | Yes |
| 2 | - | To Carton | `carton_to` | Int |  | Yes |
| 3 | - | Cartons | `carton_count` | Int |  |  |
| 4 | - | Carton Type | `carton_type` | Link | Carton Type |  |
| 5 | - | L (cm) | `length_cm` | Float |  |  |
| 6 | - | W (cm) | `width_cm` | Float |  |  |
| 7 | - | H (cm) | `height_cm` | Float |  |  |
| 8 | - | CBM / Carton | `cbm_per_carton` | Float |  |  |
| 9 | - | CBM | `total_cbm` | Float |  |  |
| 10 | - | Pcs / Carton | `pieces_per_carton` | Int |  |  |
| 11 | - | Pieces | `total_pieces` | Int |  |  |
| 12 | - | Net kg / Carton | `net_weight_kg` | Float |  |  |
| 13 | - | Gross kg / Carton | `gross_weight_kg` | Float |  |  |
| 14 | - | Shade | `shade` | Data |  |  |
| 15 | - | Tail Carton | `tail` | Check |  |  |

### Packing List Content

- **Type:** Child table (child of `Packing List`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Packing List. Carton contents: carton number, colour, size, quantity per carton and total pieces.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Carton Row (From) | `carton_from` | Int |  | Yes |
| 2 | - | Colour | `colour` | Data |  | Yes |
| 3 | - | Size | `size` | Data |  | Yes |
| 4 | - | Qty Per Carton | `qty_per_carton` | Int |  | Yes |
| 5 | - | Pieces Total | `pieces_total` | Int |  |  |
| 6 | - | Sales Order Item | `sales_order_item` | Data |  |  |

### Packing List Ratio

- **Type:** Child table (child of `Packing List`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Packing List. Assorted pack ratio: colour, size and pieces per pack.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  |  |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Pieces Per Pack | `pieces_per_pack` | Int |  | Yes |

### Packing List SSCC

- **Type:** Child table (child of `Packing List`)
- **Submittable:** no
- **Deck:** Production

**What it holds:** Child of Packing List. SSCC (GS1 carton label) per carton number.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Carton No | `carton_no` | Int |  | Yes |
| 2 | - | SSCC | `sscc` | Data |  | Yes |

## Deck: Shipping & Claims

Where: NOT on workspace; Phase E, partly wired.

### Buyer Claim

- **Type:** Parent document
- **Submittable:** yes
- **Naming:** Frappe default (number)
- **Deck:** Shipping & Claims

**What it holds:** Buyer claim after shipment (submittable): linked invoice, contract, customer, shipment and production card; claim type (quality, short, over, wrong item, late, chargeback); the pieces claimed; the claim window and cap; the accepted amount, settlement, fault source and supplier recovery; credit and debit notes; and the amendment link.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Customer Invoice | `sales_invoice` | Link | Sales Invoice | Yes |
| 2 | - | Contract | `sales_contract` | Link | Sales Contract |  |
| 3 | - | Customer | `customer` | Link | Customer |  |
| 4 | - | Company | `company` | Link | Company |  |
| 5 | - | Shipment | `shipment` | Link | Shipment |  |
| 6 | - | Production Card | `production_card` | Link | Production Card |  |
| 7 | - | Claim Type | `claim_type` | Select | Quality, Quantity Short, Quantity Over, Wrong Item, Late Delivery, Chargeback, Concession, Other | Yes |
| 8 | - | Reported On | `reported_on` | Date |  | Yes |
| 9 | - | Buyer Reference | `buyer_ref` | Data |  |  |
| 10 | - | Status | `status` | Select | Open, Under Review, Accepted, Partly Accepted, Rejected, Settled |  |
| 11 | What is claimed | Pieces | `rows` | Table | Buyer Claim Row |  |
| 12 | What is claimed | Claimed Amount | `claimed_amount` | Currency |  | Yes |
| 13 | What is claimed | Currency | `currency` | Link | Currency |  |
| 14 | What is claimed | Evidence | `evidence` | Attach |  |  |
| 15 | What is claimed | Description | `description` | Small Text |  |  |
| 16 | Window and cap | Arrival Date | `arrival_date` | Date |  |  |
| 17 | Window and cap | Window Days | `window_days` | Int |  |  |
| 18 | Window and cap | Days Since Arrival | `days_since_arrival` | Int |  |  |
| 19 | Window and cap | Window Note | `window_note` | Small Text |  |  |
| 20 | Window and cap | Cap (CIF value of the pieces) | `cap_amount` | Currency |  |  |
| 21 | Window and cap | Override Reason | `override_reason` | Small Text |  |  |
| 22 | Decision | Accepted Amount | `accepted_amount` | Currency |  |  |
| 23 | Decision | Settlement | `settlement` | Select | (blank), Credit Note, Deduction from Payment, Replacement, Return of Goods, None |  |
| 24 | Decision | Fault Source | `fault_source` | Select | (blank), Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Logistics, Unknown |  |
| 25 | Decision | Recover From Supplier | `recover_from_supplier` | Link | Supplier |  |
| 26 | Decision | Recovery Amount | `recovery_amount` | Currency |  |  |
| 27 | Decision | Credit Note | `credit_note` | Link | Sales Invoice |  |
| 28 | Decision | Supplier Debit Note | `supplier_debit_note` | Link | Purchase Invoice |  |
| 29 | Decision | Decision Note | `decision_note` | Small Text |  |  |
| 30 | Decision | Amended From | `amended_from` | Link | Buyer Claim |  |

### Buyer Claim Row

- **Type:** Child table (child of `Buyer Claim`)
- **Submittable:** no
- **Deck:** Shipping & Claims

**What it holds:** Child of Buyer Claim. Claimed piece: colour, size, pieces and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Data |  | Yes |
| 2 | - | Size | `size` | Data |  | Yes |
| 3 | - | Pieces | `pieces` | Int |  | Yes |
| 4 | - | Remarks | `remarks` | Data |  |  |

### Shipment Container

- **Type:** Child table (child (planned for ERPNext Shipment))
- **Submittable:** no
- **Deck:** Shipping & Claims

**What it holds:** Child of ERPNext Shipment (code is wired; no Table field in this app attaches it yet). Container for sea freight: container number (ISO 6346 check), type (20GP, 40GP, 40HC, LCL part, Air ULD), seal number and cartons in it.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Container No | `container_no` | Data |  | Yes |
| 2 | - | Container Type | `container_type` | Select | (blank), 20GP, 40GP, 40HC, LCL part, Air ULD |  |
| 3 | - | Seal No | `seal_no` | Data |  |  |
| 4 | - | Cartons | `cartons` | Int |  |  |

### Shipment Declaration

- **Type:** Child table (child (planned for ERPNext Shipment))
- **Submittable:** no
- **Deck:** Shipping & Claims

**What it holds:** Child of ERPNext Shipment (code is wired; no Table field in this app attaches it yet). Customs declaration: declaration number, type code, registration date, status (registered, cleared, amended, cancelled), channel, commercial invoice numbers, invoice value and currency, exchange rate, packages and gross kg. When a declaration is Cleared, the linked ERPNext Shipment status moves to Customs Cleared (shipping/shipment.py).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Declaration No | `declaration_no` | Data |  | Yes |
| 2 | - | Type Code | `type_code` | Data |  |  |
| 3 | - | Registered On | `registered_on` | Date |  |  |
| 4 | - | Status | `status` | Select | Registered, Cleared, Amended, Cancelled |  |
| 5 | - | Channel | `channel` | Data |  |  |
| 6 | - | Commercial Invoice No(s) | `invoice_nos` | Small Text |  |  |
| 7 | - | Invoice Value | `invoice_value` | Currency |  |  |
| 8 | - | Currency | `currency` | Link | Currency |  |
| 9 | - | Customs Exchange Rate | `customs_exchange_rate` | Float |  |  |
| 10 | - | Packages | `packages` | Int |  |  |
| 11 | - | Gross Kg | `gross_kg` | Float |  |  |
| 12 | - | Remarks | `remarks` | Small Text |  |  |

### Shipment Document

- **Type:** Child table (child (planned for ERPNext Shipment))
- **Submittable:** no
- **Deck:** Shipping & Claims

**What it holds:** Child of ERPNext Shipment (code is wired; no Table field in this app attaches it yet). Document checklist line: document type (commercial invoice, packing list, bill of lading, waybill, certificate of origin, insurance, etc.), number, date, originals count, date sent to buyer and the attached file.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Document Type | `document_type` | Select | Commercial Invoice, Packing List, Bill of Lading, Sea Waybill, Air Waybill, FCR, Certificate of Origin, Export Declaration, Inspection Certificate, Insurance Certificate, Beneficiary Certificate, Other | Yes |
| 2 | - | Document No | `document_no` | Data |  |  |
| 3 | - | Document Date | `document_date` | Date |  |  |
| 4 | - | Original Count | `original_count` | Int |  |  |
| 5 | - | Sent To Buyer On | `sent_to_buyer_on` | Date |  |  |
| 6 | - | Attachment | `attachment` | Attach |  |  |

### Shipment Packing List

- **Type:** Child table (child (planned for ERPNext Shipment))
- **Submittable:** no
- **Deck:** Shipping & Claims

**What it holds:** Child of ERPNext Shipment (code is wired; no Table field in this app attaches it yet). Packing list included in the shipment: link, contract, buyer PO, cartons, pieces, net, gross and CBM.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Packing List | `packing_list` | Link | Packing List | Yes |
| 2 | - | Contract | `sales_contract` | Data |  |  |
| 3 | - | Buyer PO | `buyer_po` | Data |  |  |
| 4 | - | Cartons | `cartons` | Int |  |  |
| 5 | - | Pieces | `pieces` | Int |  |  |
| 6 | - | Net Kg | `net_kg` | Float |  |  |
| 7 | - | Gross Kg | `gross_kg` | Float |  |  |
| 8 | - | Cbm | `cbm` | Float |  |  |

## Deck: Setup

Where: workspace card exists.

### Apparel Settings

- **Type:** Settings (single record per site)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Single (one record per site). Every switch and default for the apparel layer: contract defaults, costing floors, bulk-gate enforcement, sample rules, PP/pilot departments, materials rules, inspection points and sampling, gates on Work Orders, cutting/pilot/sewing/subcontract/finishing/packing rules, stock-posting warehouses. Holds child tables for sample rules, fabric sampling bands, learning curve and traffic-light rules.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | Sales Contract | Max SKUs per Contract | `max_skus_per_contract` | Int |  | Yes |
| 2 | Sales Contract | Placeholder Words | `placeholder_words` | Small Text |  |  |
| 3 | Sales Contract | Default Contract Template | `default_contract_template` | Link | Sales Contract Template |  |
| 4 | Sales Contract | Default Contract Prefix | `contract_prefix` | Data |  |  |
| 5 | Sales Contract | Colour Attribute | `colour_attribute` | Link | Item Attribute |  |
| 6 | Sales Contract | Size Attribute | `size_attribute` | Link | Item Attribute |  |
| 7 | Sales Contract | Finished Goods Warehouse | `fg_warehouse` | Link | Warehouse |  |
| 8 | Costing | Default Margin Floor % | `default_margin_floor_pct` | Percent |  |  |
| 9 | Costing | Re-approval Tolerance % | `approval_tolerance_pct` | Percent |  |  |
| 10 | Costing | Quotation Style Item | `quote_item` | Link | Item |  |
| 11 | Costing | Style Item Group | `style_item_group` | Link | Item Group |  |
| 12 | Costing | Buying Price List | `buying_price_list` | Link | Price List |  |
| 13 | Costing | Require Costing Sign-off Before Submit | `require_costing_signoff` | Check |  |  |
| 14 | Sampling and Bulk Gate | Enforce Bulk Gate on Work Orders | `enforce_bulk_gate` | Check |  |  |
| 15 | Sampling and Bulk Gate | Require PP Meeting Before Bulk | `require_pp_meeting` | Check |  |  |
| 16 | Sampling and Bulk Gate | Sample Rules | `sample_rules` | Table | Apparel Sample Rule |  |
| 17 | Meetings, Tests and Shrinkage | PP Meeting: Required Departments | `pp_required_departments` | Small Text |  |  |
| 18 | Meetings, Tests and Shrinkage | Pilot Run: Required Departments | `pilot_required_departments` | Small Text |  |  |
| 19 | Meetings, Tests and Shrinkage | Garment Test: Standard Test List | `gpt_test_list` | Small Text |  |  |
| 20 | Meetings, Tests and Shrinkage | Fabric Shrinkage Warning Above % | `max_shrinkage_pct` | Percent |  |  |
| 21 | Materials (Phase C) | FR Material Types | `fr_material_types` | Small Text |  |  |
| 22 | Materials (Phase C) | Requirement Quantity Basis | `fr_qty_basis` | Select | Order Qty, Order Qty + Tolerance |  |
| 23 | Materials (Phase C) | Fabric Due (days before PCD) | `fabric_due_days_before_pcd` | Int |  |  |
| 24 | Materials (Phase C) | Trims Due (days before PCD) | `trim_due_days_before_pcd` | Int |  |  |
| 25 | Materials (Phase C) | Auto-submit Material Requests | `auto_submit_material_request` | Check |  |  |
| 26 | Materials (Phase C) | Fabric Inspection Warehouse | `inspection_warehouse_fabric` | Link | Warehouse |  |
| 27 | Materials (Phase C) | Fabric Store Warehouse | `store_warehouse_fabric` | Link | Warehouse |  |
| 28 | Materials (Phase C) | Trim Inspection Warehouse | `inspection_warehouse_trim` | Link | Warehouse |  |
| 29 | Materials (Phase C) | Trim Store Warehouse | `store_warehouse_trim` | Link | Warehouse |  |
| 30 | Materials (Phase C) | Rejected Material Warehouse | `rejected_warehouse` | Link | Warehouse |  |
| 31 | Materials (Phase C) | Default Purchase Terms | `default_purchase_terms` | Link | Material Purchase Terms |  |
| 32 | Inspection | Fabric Points Basis | `fabric_points_basis` | Select | Per 100 Linear Yards, Per 100 Square Yards |  |
| 33 | Inspection | Fabric Points Threshold | `fabric_points_threshold` | Float |  |  |
| 34 | Inspection | Max Rejected Rolls % | `max_rejected_rolls_pct` | Percent |  |  |
| 35 | Inspection | Submit Stock Entry after Inspection | `submit_inspection_stock_entry` | Check |  |  |
| 36 | Inspection | Fabric Sampling Plan | `fabric_sampling_bands` | Table | Fabric Sampling Band |  |
| 37 | Inspection | Default Trim Sampling Plan | `default_trim_sampling_plan` | Link | Trim Sampling Plan |  |
| 38 | Gates and Checks | Fabric Gate on Work Order | `material_gate_fabric` | Select | Block, Warn, Off |  |
| 39 | Gates and Checks | Trim Gate on Work Order | `material_gate_trims` | Select | Block, Warn, Off |  |
| 40 | Gates and Checks | Gate: Accepted % of Requirement | `material_gate_min_pct` | Percent |  |  |
| 41 | Gates and Checks | Hold PO until Approval | `hold_po_until_approval` | Select | Block, Warn, Off |  |
| 42 | Gates and Checks | Warn when PO Rate Exceeds Costing by % | `cost_overrun_warn_pct` | Percent |  |  |
| 43 | Gates and Checks | Default T&A Template | `default_tna_template` | Link | TNA Template |  |
| 44 | Production: Cutting | Default Extra Cut % | `default_extra_cut_pct` | Percent |  |  |
| 45 | Production: Cutting | Max Extra Cut % (warn above) | `max_extra_cut_pct` | Percent |  |  |
| 46 | Production: Cutting | Trim Allowance % (printed on card) | `trim_allowance_pct` | Percent |  |  |
| 47 | Production: Cutting | Bundle Size (pcs) | `bundle_size` | Int |  |  |
| 48 | Production: Cutting | Cutting Above Plan | `cut_cap_mode` | Select | Block, Warn, Off |  |
| 49 | Production: Cutting | Spare Pcs per Colour x Size | `cut_cap_extra_pcs` | Int |  |  |
| 50 | Production: Cutting | Marker Variance Needing Approval % | `marker_variance_pct` | Percent |  |  |
| 51 | Production: Cutting | Max Width Spread in One Lay (cm) | `max_width_spread_cm` | Float |  |  |
| 52 | Production: Cutting | Max Shrinkage Spread in One Lay % | `max_shrinkage_spread_pct` | Float |  |  |
| 53 | Production: Cutting | Cut Panels Inspected % | `panel_inspection_pct` | Percent |  |  |
| 54 | Production: Cutting | Remnant Roll Minimum (m) | `remnant_min_m` | Float |  |  |
| 55 | Production: Cutting | Kit Check (lining / pocketing bundles) | `kit_check` | Select | Block, Warn, Off |  |
| 56 | Production: Pilot Run | Pilot Required from Order Qty | `pilot_min_order_qty` | Int |  |  |
| 57 | Production: Pilot Run | Pilot Pieces per Style | `pilot_default_qty` | Int |  |  |
| 58 | Production: Pilot Run | Pilot Before Bulk Wash | `require_pilot_before_bulk_wash` | Select | Block, Warn, Off |  |
| 59 | Production: Sewing | Working Minutes per Day | `work_minutes_per_day` | Int |  |  |
| 60 | Production: Sewing | Planned Efficiency % | `planned_efficiency_pct` | Percent |  |  |
| 61 | Production: Sewing | Learning Curve | `learning_curve` | Table | Learning Curve Day |  |
| 62 | Production: Sewing | Line Input Needs Bundles | `require_bundle_on_input` | Check |  |  |
| 63 | Production: Sewing | Line Output Needs Bundles | `require_bundle_on_output` | Check |  |  |
| 64 | Production: Sewing | Inline Check Pieces per Operator | `inline_check_pieces` | Int |  |  |
| 65 | Production: Sewing | Traffic Light Rules | `traffic_light_rules` | Table | Traffic Light Rule |  |
| 66 | Production: Sewing | DHU Alert Above | `dhu_alert_threshold` | Float |  |  |
| 67 | Production: Subcontracting | Default Rejection Threshold % | `subcontract_default_threshold_pct` | Percent |  |  |
| 68 | Production: Subcontracting | Penalty Applies To | `subcontract_penalty_scope` | Select | All Damaged, Excess Only |  |
| 69 | Production: Subcontracting | Penalty Basis | `subcontract_penalty_basis` | Select | Cost Sheet FOB, Sales Order Rate, Fixed Per Piece |  |
| 70 | Production: Subcontracting | Quantity Confirmation Window (days) | `subcontract_reconcile_days` | Int |  |  |
| 71 | Production: Finishing, Packing, Inspection | Metal Detector Check Required | `needle_check_required` | Select | Block, Warn, Off |  |
| 72 | Production: Finishing, Packing, Inspection | Detector Test Piece (mm) | `needle_test_piece_mm` | Float |  |  |
| 73 | Production: Finishing, Packing, Inspection | Detector Re-check Every (hours) | `needle_recheck_hours` | Float |  |  |
| 74 | Production: Finishing, Packing, Inspection | Controlled Trim Tolerance (pcs) | `controlled_trim_tolerance` | Int |  |  |
| 75 | Production: Finishing, Packing, Inspection | Carton Max Gross (kg) | `carton_max_gross_kg` | Float |  |  |
| 76 | Production: Finishing, Packing, Inspection | GS1 Company Prefix | `gs1_company_prefix` | Data |  |  |
| 77 | Production: Finishing, Packing, Inspection | Final Inspection AQL Plan | `final_inspection_plan` | Link | AQL Plan |  |
| 78 | Production: Finishing, Packing, Inspection | Final Inspection Carton Pick | `carton_pick_rule` | Select | Square Root, Fixed Pct |  |
| 79 | Production: Finishing, Packing, Inspection | Delivery Note Needs Passed Final Inspection | `ship_gate_final_inspection` | Select | Block, Warn, Off |  |
| 80 | Production: Finishing, Packing, Inspection | Over / Short Ship Check | `ship_tolerance_basis` | Select | Total, Each Size, Both |  |
| 81 | Production: Stock Postings | Submit Finished Goods and Consumption Entries | `auto_submit_stock_entries` | Check |  |  |
| 82 | Production: Stock Postings | Draft Finished Goods Receipt at Packing | `post_fg_receipt` | Check |  |  |
| 83 | Production: Stock Postings | Cutting WIP Warehouse | `cutting_wip_warehouse` | Link | Warehouse |  |
| 84 | Production: Stock Postings | Line WIP Warehouse | `line_wip_warehouse` | Link | Warehouse |  |
| 85 | Production: Stock Postings | Seconds (B-Grade) Warehouse | `seconds_warehouse` | Link | Warehouse |  |
| 86 | Production: Stock Postings | Scrap Warehouse | `scrap_warehouse` | Link | Warehouse |  |

### Apparel Sample Rule

- **Type:** Child table (child of `Apparel Settings`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of Apparel Settings. One row per sample type (Proto, Fit, PP, TOP, GPT, FPT...) saying whether it is required, if raised, when it is due (PCD, Ex-Factory, In-Warehouse, after fit approval), the day offset, qty per colour, and the late-chargeback amount.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Sample Type | `sample_type` | Select | Proto, Fit, Size Set, Lab Dip, Strike Off, Desk Loom, Bulk Fabric, Bulk Trim, PP, Garment Test (GPT), TOP, Salesman, Photo Sample, Customer Sample, Fabric Test (FPT), Pilot Run | Yes |
| 2 | - | Gate | `gate` | Select | Required, If Raised, No | Yes |
| 3 | - | Per Colour | `per_colour` | Check |  |  |
| 4 | - | Due Basis | `due_basis` | Select | PCD, Ex-Factory, In-Warehouse, After Fit Approval |  |
| 5 | - | Days Offset | `days_before` | Int |  |  |
| 6 | - | Qty per Colour | `qty` | Int |  |  |
| 7 | - | Sample Size / Mix | `sample_size` | Data |  |  |
| 8 | - | Not Required on Split PO | `split_po_exempt` | Check |  |  |
| 9 | - | Late Chargeback | `chargeback_amount` | Currency |  |  |

### Fabric Sampling Band

- **Type:** Child table (child of `Apparel Settings`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of Apparel Settings. Maps a fabric length range (m) to the percent of rolls to inspect.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | From Length (m) | `from_length_m` | Float |  | Yes |
| 2 | - | To Length (m) | `to_length_m` | Float |  |  |
| 3 | - | Inspect % | `inspect_pct` | Percent |  | Yes |

### Learning Curve Day

- **Type:** Child table (child of `Apparel Settings`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of Apparel Settings. Day number on a line and percent of target expected on that day (used for ramp-up targets).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Day | `day_no` | Int |  | Yes |
| 2 | - | % of Target | `pct_of_target` | Percent |  | Yes |

### Traffic Light Rule

- **Type:** Child table (child of `Apparel Settings`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of Apparel Settings. Defect count at which an operator's inline traffic light turns Green, Yellow or Red.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Colour | `colour` | Select | Green, Yellow, Red | Yes |
| 2 | - | Defects From | `defects_from` | Int |  | Yes |

### Apparel Defect Code

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: defect_name
- **Deck:** Setup

**What it holds:** Master list of garment defects (name, stage where found, severity Critical/Major/Minor, usual fault source). Used by line QC, final inspection, pilot runs, recut requests and subcontract returns.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Defect | `defect_name` | Data |  | Yes |
| 2 | - | Stage | `stage` | Select | Any, Cutting, Sewing, Washing, Finishing, Final |  |
| 3 | - | Severity | `severity` | Select | Critical, Major, Minor | Yes |
| 4 | - | Usual Fault Source | `fault_source` | Select | (blank), Factory Sewing, Fabric, Cutting, Subcontractor, Trims, Spec or Pattern, Handling, Unknown |  |
| 5 | - | Enabled | `enabled` | Check |  |  |

### AQL Plan

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: plan_name
- **Deck:** Setup

**What it holds:** Master AQL sampling plan (inspection level plus critical/major/minor AQL values) made of AQL Plan Rows. Used by Final Inspection to decide how many cartons to draw and the accept/reject numbers.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Plan Name | `plan_name` | Data |  | Yes |
| 2 | - | Inspection Level | `inspection_level` | Select | General I, General II, General III |  |
| 3 | - | AQL Critical | `aql_critical` | Data |  |  |
| 4 | - | AQL Major | `aql_major` | Data |  |  |
| 5 | - | AQL Minor | `aql_minor` | Data |  |  |
| 6 | - | Rows | `rows` | Table | AQL Plan Row |  |
| 7 | - | Note | `note` | Small Text |  |  |

### AQL Plan Row

- **Type:** Child table (child of `AQL Plan`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of AQL Plan. One row per lot-size band: lot from/to, sample size, and major/minor/critical accept and reject numbers; flag for QA confirmation.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Lot From | `lot_from` | Int |  | Yes |
| 2 | - | Lot To | `lot_to` | Int |  | Yes |
| 3 | - | Code | `code_letter` | Data |  |  |
| 4 | - | Sample Size | `sample_size` | Int |  | Yes |
| 5 | - | Major Ac | `major_ac` | Int |  | Yes |
| 6 | - | Major Re | `major_re` | Int |  | Yes |
| 7 | - | Minor Ac | `minor_ac` | Int |  | Yes |
| 8 | - | Minor Re | `minor_re` | Int |  | Yes |
| 9 | - | Critical Ac | `critical_ac` | Int |  |  |
| 10 | - | Critical Re | `critical_re` | Int |  |  |
| 11 | - | Confirmed by QA | `confirmed` | Check |  |  |

### Carton Type

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: type_name
- **Deck:** Setup

**What it holds:** Master carton specification: name, optional customer, inner length/width/height (cm), tare and max gross weight (kg), board note. Used by Packing List cartons for CBM and weight.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Carton Type | `type_name` | Data |  | Yes |
| 2 | - | Customer (optional) | `customer` | Link | Customer |  |
| 3 | - | Length (cm) | `length_cm` | Float |  | Yes |
| 4 | - | Width (cm) | `width_cm` | Float |  | Yes |
| 5 | - | Height (cm) | `height_cm` | Float |  | Yes |
| 6 | - | Tare (kg) | `tare_kg` | Float |  |  |
| 7 | - | Max Gross (kg) | `max_gross_kg` | Float |  |  |
| 8 | - | Board Note | `ply_note` | Data |  |  |

### Cost Head

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: head_name
- **Deck:** Setup

**What it holds:** Master cost heads used by the costing sheet (for example fabric, trims, CMT, overhead, profit): group, calculation type (per piece, percent of product cost, per SAM minute and so on), sequence, and whether it is required on every cost sheet.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Cost Head | `head_name` | Data |  | Yes |
| 2 | - | Group | `head_group` | Select | Material, Conversion, Allowance, Financial, Logistics, Overhead, Profit | Yes |
| 3 | - | Calculation Type | `calc_type` | Select | From Materials, Per Piece, Per SAM Minute, Per Metre of Fabric, Percent of Material, Percent of Product Cost, Percent of Subtotal, Percent of Price | Yes |
| 4 | - | Material Scope | `material_scope` | Select | Fabric, Non-Fabric, All |  |
| 5 | - | Sequence | `sequence` | Int |  | Yes |
| 6 | - | Required on every Cost Sheet | `is_mandatory` | Check |  |  |
| 7 | - | Enabled | `enabled` | Check |  |  |
| 8 | - | Description | `description` | Small Text |  |  |

### Costing Parameter

- **Type:** Parent document
- **Submittable:** no
- **Naming:** series CP-{#####}
- **Deck:** Setup

**What it holds:** Costing rate card for a customer or product type, with effective dates, margin floor and target, and child rows giving the rate per cost head.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Title | `title` | Data |  |  |
| 2 | - | Customer | `customer` | Link | Customer |  |
| 3 | - | Product Type | `product_type` | Link | Product Type |  |
| 4 | - | Currency | `currency` | Link | Currency | Yes |
| 5 | - | Effective From | `effective_from` | Date |  | Yes |
| 6 | - | Effective To | `effective_to` | Date |  |  |
| 7 | - | Margin Floor % | `margin_floor_pct` | Percent |  |  |
| 8 | - | Target Margin % | `target_margin_pct` | Percent |  |  |
| 9 | - | Enabled | `enabled` | Check |  |  |
| 10 | Rates | Rates | `rates` | Table | Costing Parameter Rate |  |

### Costing Parameter Rate

- **Type:** Child table (child of `Costing Parameter`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of Costing Parameter. One rate per cost head with calculation type, rate, not-applicable flag and remarks.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Cost Head | `cost_head` | Link | Cost Head | Yes |
| 2 | - | Calculation Type | `calc_type` | Data |  |  |
| 3 | - | Rate | `rate` | Float |  |  |
| 4 | - | Not Applicable | `not_applicable` | Check |  |  |
| 5 | - | Remarks | `remarks` | Data |  |  |

### Fabric Defect Code

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: code
- **Deck:** Setup

**What it holds:** Master fabric defect (code, defect name, category Weaving/Dyeing/Printing/Finishing/Other) and whether it is always 4 points under the 4-point system.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Code | `code` | Data |  | Yes |
| 2 | - | Defect | `defect_name` | Data |  | Yes |
| 3 | - | Always 4 Points | `always_four_points` | Check |  |  |
| 4 | - | Category | `category` | Select | Weaving, Dyeing, Printing, Finishing, Other |  |

### Product Type

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: product_type
- **Deck:** Setup

**What it holds:** Master for garment product types (for example T-shirt, jeans) with default SAM minutes and the ERPNext item group to use.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Product Type | `product_type` | Data |  | Yes |
| 2 | - | Item Group | `item_group` | Link | Item Group |  |
| 3 | - | Default SAM (minutes) | `default_sam` | Float |  |  |
| 4 | - | Description | `description` | Small Text |  |  |

### Production Check Item

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: check_name
- **Deck:** Setup

**What it holds:** Master checklist item for pilot runs and pre-pack and line-setting checks (check name, applies to, order).

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Check | `check_name` | Data |  | Yes |
| 2 | - | Applies To | `applies_to` | Select | Pilot Run, Pre-Pack, Line Setting |  |
| 3 | - | Sequence | `sequence` | Int |  |  |

### Subcontract Process

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: process_name
- **Deck:** Setup

**What it holds:** Master subcontract process (for example embroidery, washing, printing): default position before/after sewing, what is sent (garments or cut panels), billing UOM (pcs or kg), turnaround days, tolerance and damage limit, service item.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Process | `process_name` | Data |  | Yes |
| 2 | - | Default Position | `default_position` | Select | After Sewing, Before Sewing |  |
| 3 | - | Item State Sent | `item_state` | Select | Garments, Cut Panels |  |
| 4 | - | Billing UOM | `billing_uom` | Select | Pcs, Kg |  |
| 5 | - | Needs Approved Standard | `requires_approved_standard` | Check |  |  |
| 6 | - | Enabled | `enabled` | Check |  |  |
| 7 | Default Terms | Turnaround (working days) | `turnaround_days` | Int |  |  |
| 8 | Default Terms | Quantity Tolerance % | `qty_tolerance_pct` | Percent |  |  |
| 9 | Default Terms | Damage Limit % | `damage_threshold_pct` | Percent |  |  |
| 10 | Default Terms | Service Item | `service_item` | Link | Item |  |

### TNA Milestone Type

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: code
- **Deck:** Setup

**What it holds:** Master milestone for time-and-action planning: code, label, department, which document stamps it (PO, sample approval, fabric inspection...), critical flag, when it applies and sequence.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Code | `code` | Data |  | Yes |
| 2 | - | Label | `label` | Data |  | Yes |
| 3 | - | Department | `department` | Select | Merchandising, Sampling, Purchasing, Quality, Production, Washing, Shipping |  |
| 4 | - | Stamped By | `auto_source` | Select | Manual, Tech Pack, Sales Order, Factory Allocation, Sample Approval, PP Meeting, Fabric Requisition, Trim Requisition, Purchase Order, Purchase Receipt, Fabric Inspection, Trim Inspection, Work Order |  |
| 5 | - | Critical | `is_critical` | Check |  |  |
| 6 | - | Applies When | `applies_when` | Select | Always, Washed Only, Printed Only, Sample Type Required |  |
| 7 | - | Sample Type | `sample_type` | Select | (blank), Proto, Fit, Size Set, Lab Dip, Strike Off, Desk Loom, Bulk Fabric, Bulk Trim, PP, Garment Test (GPT), TOP, Salesman, Photo Sample, Customer Sample, Fabric Test (FPT) |  |
| 8 | - | Sequence | `sequence` | Int |  |  |

### TNA Template

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: template_name
- **Deck:** Setup

**What it holds:** Reusable milestone plan (for example Sea export or Air express) for a customer or product type, with a set of TNA Template Milestone rows.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Template Name | `template_name` | Data |  | Yes |
| 2 | - | Customer | `customer` | Link | Customer |  |
| 3 | - | Product Type | `product_type` | Link | Product Type |  |
| 4 | - | Shipment Mode | `shipment_mode` | Select | (blank), Sea, Air |  |
| 5 | - | Default Template | `is_default` | Check |  |  |
| 6 | - | Remarks | `remarks` | Small Text |  |  |
| 7 | Milestones | Milestones | `milestones` | Table | TNA Template Milestone | Yes |

### TNA Template Milestone

- **Type:** Child table (child of `TNA Template`)
- **Submittable:** no
- **Deck:** Setup

**What it holds:** Child of TNA Template. Milestone with its count basis (order received, ex-factory, PCD, after another milestone), days or quantity-per-day duration, and owner role.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Milestone | `milestone_type` | Link | TNA Milestone Type | Yes |
| 2 | - | Counted From | `basis` | Select | Order Received, Ex-Factory, PCD, After Milestone | Yes |
| 3 | - | After | `after_milestone` | Link | TNA Milestone Type |  |
| 4 | - | Days | `offset_days` | Int |  |  |
| 5 | - | Duration | `duration_rule` | Select | Fixed, Qty / Daily Output |  |
| 6 | - | Daily Output (pcs) | `daily_output` | Int |  |  |
| 7 | - | Owner Role | `owner_role` | Link | Role |  |

### Trim Category

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: category_name
- **Deck:** Setup

**What it holds:** Master trim category (buttons, labels, zips, etc.) with default calculation basis (per garment, per size, per carton, by length, fixed qty), where it is needed (cutting, sewing, finishing, packing) and sequence.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Category | `category_name` | Data |  | Yes |
| 2 | - | Default Calc Basis | `calc_basis` | Select | Per Garment, Per Size, Per Colour, Per Carton, By Length, Fixed Qty |  |
| 3 | - | Needed For | `needed_for` | Select | Cutting, Sewing, Finishing, Packing |  |
| 4 | - | Sequence | `sequence` | Int |  |  |

### Trim Defect Type

- **Type:** Parent document
- **Submittable:** no
- **Naming:** field: defect_name
- **Deck:** Setup

**What it holds:** Master trim defect (name and Major/Minor severity) used by trim inspection.

| # | Section | Label | Fieldname | Type | Options / Link | Required |
|---|---|---|---|---|---|---|
| 1 | - | Defect | `defect_name` | Data |  | Yes |
| 2 | - | Severity | `severity` | Select | Major, Minor |  |

