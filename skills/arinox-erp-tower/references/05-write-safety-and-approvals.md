# 05 Write safety and approvals

## The path every write takes (`pipeline.execute`)

1. **Identity and role**: who you are, what your roles allow for that doctype group.
2. **Preview** (dry run of the Arinox Before-scripts). A preview is always allowed, in any mode.
3. **Mode gate**: global `ERP_WRITE_MODE`.
4. **Rate limit**: 120 writes per minute per actor by default.
5. **Field guard**: forbidden/negative values.
6. **Approval** if the class is `risky` (or the value exceeds `APPROVAL_VALUE_LIMIT`, off by default).
7. **Idempotency** (`idem_key`), then **document lock** (one editor per document, short TTL), then **optimistic lock** (`modified`).
8. **Execute** through the Tower Script Runtime: the real Arinox scripts run, then ERP REST.
9. **Journal** (what was created/changed, for undo), **audit log**, **ERP trace comment**, **event ledger**, cache invalidation.

A failure compensates (undoes) what the run already did, and opens a *breach* for a person if something could not be undone.

## Write modes

| Mode | Allows | Default for |
|---|---|---|
| `off` | nothing (previews only) | emergency stop |
| `safe` | Comment, ToDo and Task writes only | – |
| `draft` | creating and saving drafts, any Arinox API script not on the risky list, and submits of non-ledger doctypes (Cost Sheet, Quotation, Sales Contract, requisitions …) | **the shipped default** |
| `all` | everything, including risky class, once approved | real use |

Under `draft`, risky operations are **refused outright** (before any approval). For real operation an administrator sets `ERP_WRITE_MODE=all`; approvals then gate the risky ones. The mode is the environment value `ERP_WRITE_MODE` read in `config.py`; only the platform administrator changes it (no agent function does). `tsr_set_script`, `tsr_kill_switch`, `set_tower_user` and `install_webhooks` are admin-only functions.

**Kill switch:** `tsr_kill_switch` switches the Arinox rules off in the Tower (an always-on prefix list, e.g. naming, stays on). Admin only. Do not touch it.

## Risky class (needs a manager's approval)

**Any cancel and any delete, on any doctype, is risky.** Submitting any of: Sales Invoice, Purchase Invoice, Delivery Note, Stock Entry, Purchase Receipt, Payment Entry, Packing List, Lay Report, Daily Line Report, Production Adjustment, Subcontract Return, Subcontract Challan, Finishing Receipt, Line Input, Shipment.

Also API methods matching: `make_delivery_notes`, `invoicing_submit`, `commercial_close`, `ledger_rebuild`, `settlement_make_invoices`, `credit_note`, `short_close`, `api_close`, `scripts_switch`, `issue_fabric`, `make_purchase_orders`.

In practice that means these Tower functions will answer `needs_approval` the first time: `order_po_make`, `order_cut_issue`, `order_ship_make_dns`, `order_ship_submit`, `order_invoice_submit`, `order_settlement_invoices`, `order_claim_credit_note`, `order_close`, and `cx_write` submit/cancel on any doctype above.

**Hard stops regardless of anything:** you never cancel ledger documents on your own; you never delete; only Management/Admin delete. Frappe has no trash, so a deletion is permanent.

## Role matrix (defaults)

| Group | Doctypes (examples) | Create / edit | Submit / cancel | Read |
|---|---|---|---|---|
| enquire | Opportunity, Tech Pack, Price Negotiation, Quotation, Lead, Customer | Merchandiser, Costing | Merchandiser | all |
| costing | Cost Sheet, Costing Parameter, Cost Head | Costing, Merchandiser | Costing | Costing, Merchandiser, Accounts, mgmt |
| win | Sales Contract, Sales Order, Item | Merchandiser | Merchandiser | all |
| plan | Factory Allocation, Sample Approval, PP Meeting, Order TNA, TNA Milestone | Planner, Sampling, Merchandiser | Planner, Sampling | all |
| materials | Fabric/Trim Requisition, PO, Material Request, Purchase Receipt, Supplier | Purchase, Merchandiser, Planner | Purchase | all |
| inspection | Fabric/Trim/Final Inspection, Line QC, AQL Plan, Quality Inspection | QC | QC | all |
| make | Production Card, Cut Plan, Lay Report, Daily Line Report, Line Input, Operation Bulletin, Pilot Run, Subcontract docs, Finishing Receipt, Work Order | Production, Planner | Production | all |
| pack | Packing List | Shipping, QC | Shipping, QC | all |
| ship | Shipment, Delivery Note, LC, declarations | Shipping | Shipping | all |
| accounts | Sales/Purchase Invoice, Payment Entry, Buyer Claim | Accounts | Accounts | Accounts, Shipping, Merchandiser, Costing, mgmt |
| settings | Apparel Settings, rules | nobody but mgmt/Admin | – | Management, Admin only |
| masters | Product Type, Size Chart, defect codes, Subcontract Process … | Merchandiser, Costing, Planner, Purchase, QC | – | all |

Management and Admin may do everything except that only they delete. Unknown doctypes are readable by all and changeable by Management/Admin only. A `guardrails.json` next to `guardrails.py` overrides these without a release. The ERP's own role permissions still apply behind the Tower: the Tower is never looser than the ERP.

## Email rule

An outbound mail (supplier chase, buyer reply, quote) is created as a draft in Outbound Mail (`create_email_draft`, `deal_quote_draft`, `cx_inquiry_draft_reply`, `create_intake_ack`). It is sent only by `approve_and_send_email` or `deal_quote_send` / `inbox_reply` **after a person has approved the text**. Never send on your own initiative.

## Autonomy ladder (design; the agent layer is not built)

L0 inform · L1 propose, person approves (**default for all writes**) · L2 act and tell (internal notes, tasks, refreshing forecasts) · L3 autonomous (off). Until the agent layer exists, behave as L1 everywhere and L0 for anything you are unsure about.

## Audit

Every write leaves: an `audit_log` row, a journal entry, and an ERP comment on the document naming the run. After any write, you can show the person `cx_runs` (own runs; managers see all).
