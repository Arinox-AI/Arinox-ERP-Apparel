# Do our doctypes duplicate something ERPNext already has?

**Checked 2026-11-05**, for all 52 custom parent doctypes against the 266 parent doctypes of ERPNext v16.34.1. "Compared" means I read both field lists. "Judged" means I decided from names and design notes without a field-by-field comparison.

## Result

**One true duplicate, now removed. Everything else is either not in ERPNext, or overlaps only in part and is kept for a reason that is written down.**

### Replaced
| Ours | ERPNext | What was done |
|---|---|---|
| **Carton Type** (name, customer, L, W, H, tare, max gross) | **Shipment Parcel Template** (name, L, W, H, weight) *(compared)* | Carton Type deleted. Packing List and its carton rows now link to Shipment Parcel Template. Customer, tare and max gross are three Custom Fields on it. A migration step copies any old rows. |

### Reused instead of built (Phase E)
Shipment (booking, B/L, parcels, delivery notes), Supplier Quotation (freight quotes), Purchase Invoice (forwarder bills), Sales Invoice (invoice, follow-up fields, credit notes), Customer (invoice route fields), Dunning and ToDo (reminders), Payment Entry (receipts and deductions), Delivery Note, Incoterm, Holiday List, Bank Account, Shipment Parcel Template.

### Overlap in part, kept on purpose *(compared)*
| Ours | ERPNext | Why ours stays | What would change it |
|---|---|---|---|
| **Packing List** (carton runs, ratio and tail packing, SSCC, ledger post) | **Packing Slip**: needs a *draft* Delivery Note first, one slip per case range, items with net weight, no ratio, no SSCC, no CBM | Packing happens before the Delivery Note exists, and the ledger needs pieces by colour and size per ship-to | Making packing start from a draft Delivery Note |
| **Final Inspection** (AQL lot, defect classes, random carton draw, concession) | **Quality Inspection**: per item, readings table, status Accepted/Rejected, `sample_size`; no defect classes, no AQL accept/reject, no carton draw | The AQL decision is by defect class over a lot, not per-parameter readings | Using a Quality Inspection Template with one reading per defect class |
| **Buyer Claim** (window, cap, credit note, dispute hold) | **Issue** (support ticket) and **Non Conformance** (subject, procedure, corrective action) | Neither has an amount, a claim window, a cap at CIF value, or a link to the invoice and credit note | Using Issue with custom fields |
| **Subcontract Challan / Return / Settlement** | **Subcontracting Order / Receipt** (needs a distinct finished item and a Subcontracting BOM per process, supplier warehouse, no size and colour, no damage limit or penalty) | A wash returns the *same* garment, by colour and size, with a penalty above a damage limit | Giving every process its own service item and BOM |
| Vendor scoring (not built) | **Supplier Scorecard** | Native one exists; use it if wanted | — |
| **Needle Detector Log**, **Finishing Receipt**, **Letter of Credit**, **Destination Filing Rule**, **Shipment Filing** | nothing equivalent *(compared against Bank Guarantee, Quality Goal, Pallet, Delivery Trip)* | — | — |

### Overlap in part, from earlier phases *(judged, not field-compared)*
| Ours | ERPNext | Note |
|---|---|---|
| **Fabric Defect Code**, **Trim Defect Type**, **Apparel Defect Code** | Quality Inspection Parameter | Three defect lists of our own is the real duplication here; they could be one master with an "applies to" field. Not changed. |
| **Fabric Inspection**, **Trim Inspection** | Quality Inspection | Roll-level four-point grading and lot sampling by band do not fit readings |
| **AQL Plan**, **Trim Sampling Plan** | Quality Inspection Template | Templates hold parameters, not sampling tables |
| **Order TNA**, **TNA Milestone**, **TNA Template** | Project, Task, Project Template | Planned, revised and actual dates per style and colour, with template offsets. A Project with Tasks could carry the same. Biggest candidate for consolidation. |
| **Operation Bulletin** | BOM Operation, Routing, Operation | OB holds SAM, balance and per-operation targets; BOM operations hold time only |
| **Fabric Requisition**, **Trim Requisition** | Material Request | They plan and compute allowances, then create Material Requests |
| **Production Card** | Work Order, Production Plan | Size by colour matrix, route of processes; Work Order is per SKU |
| **Sales Contract**, **Sales Contract Template** | Contract, Contract Template, Blanket Order | Ours carries lines, tolerance bands and claim terms |
| **Cost Sheet** | BOM costing | Costing before any BOM exists |
| **Price Negotiation** | Quotation revisions, Opportunity | Rounds against a floor price |
| **Factory Allocation** | Production Plan, Plant Floor | Uses Plant Floor and Workstation |
| **Production Movement** | Stock Ledger Entry, Job Card | Quantity ledger by stage, no stock value |

## What I did not do
I did not merge the three defect masters or move T&A onto Projects. Both are real simplifications but they touch Phases B and C and their tests; say if you want either.
