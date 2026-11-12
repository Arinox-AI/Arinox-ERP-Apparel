# 04 Function catalogue

Grouped by job. **Parameters are in `cortex-tower/backend/document.md`** under each `### name` heading; read the heading before calling. R = read only. W = writes (preview first). **W!** = risky class, will answer `needs_approval`. About 265 functions exist; the ones below are the ones you will use. Older recommendation-engine functions (`get_dashboard`, `get_risks`, `execute_action`, `run_action`, WIP and legacy T&A) still exist but the order and deal functions replace them for new work.

## Orientation and queue

| Function | | Use |
|---|---|---|
| `kogo_me` | R | Who am I, which Tower roles. |
| `cx_today` | R | My queue: approvals, breaches, failed syncs, inquiries waiting, overdue T&A milestones. Start here for "what now?". |
| `cx_catalog`, `cx_nav_counts` | R | Screens my role may see; draft counts. |
| `cx_search` | R | Global search across ERP documents I may read. |
| `cx_connection` | R (admin) | Is the Tower talking to the Arinox ERP? API user, Arinox doctypes present, ERP-side server scripts. Run first when anything looks empty. |
| `cx_sync_status`, `cx_breaches` | R | Sync health. A *breach* is an ERP-side change that breaks a rule the scripts enforce; never auto-reverted. |
| `tsr_status` | R | Script runtime state: which Arinox scripts are loaded, enabled, run counts, failures. |

## Inbox, customers, inquiries

`inbox_sync` (W local) · `inbox_threads` R · `inbox_thread` R · `inbox_reply` W (sends mail: needs a person's approval of the text) · `inbox_label` · `inbox_link_customer` · `inbox_archive` · `inbox_attachment` R (base64, max 12 MB) · `customer_list` R · `customer_create` W · `customer_overview` R · `cx_inquiry_queue` R · `cx_inquiry_analyse` R (reads every attachment, scores completeness, proposes steps) · `cx_inquiry_step` W (runs one proposed step through the pipeline) · `cx_inquiry_draft_reply` W (draft only).

## Order intake (a PO mail → ERP drafts)

`sync_intake_mail` · `get_intake_queue` R · `get_intake_summary` R · `get_intake` R · `understand_intake` · `simulate_intake` R (what it would create) · `intake_review` · `intake_plan_edit` · `edit_intake` (operator correction) · `set_intake_customer` · `approve_intake` **W** (the only call that writes) · `reject_intake` · `rollback_intake` · `create_intake_ack` (draft reply) · `get_intake_document` R · `reopen_intake` · `dismiss_intake`.

## Deal flow (inquiry → Sales Order)

| Stage | Functions |
|---|---|
| list/read | `deal_list` R, `deal_get` R (`erp: true` also reads live status), `deal_dashboard` R |
| start | `deal_from_thread`, `deal_create`, `deal_update`, `deal_documents` R, `deal_read_documents` |
| register | `deal_erp_setup` (repairs masters), `deal_register` (Opportunity + Tech Packs) |
| BOM | `deal_bom_sources` R, `deal_bom_upload`, `deal_bom_from_mail`, `deal_bom_from_erp`, `deal_bom_ai`, `deal_bom_paste`, `deal_bom_apply` |
| cost | `deal_cost_open`, `deal_cost_save`, `deal_cost_sheet` R, `deal_cost_sheet_save`, `deal_cost_sheet_calc` R, `deal_cost_sheet_transfer`, `deal_cost_read`, `deal_cost_apply_prices`, `deal_cost_autofill`, `deal_cost_apply`, `deal_cost_submit`, `cost_sheet_list` R, `cost_prices` R |
| quote | `deal_quote_draft` R, `deal_quote_send`, `deal_record_reply` |
| contract | `deal_contract_prepare`, `deal_contract_form` R, `deal_contract_update`, `deal_contract_create` |
| order | `deal_make_order` |
| track | `deal_track` R, `deal_track_doc`, `deal_track_shipment` |

## Order flow (Sales Order → cash)

| Step | Read | Write |
|---|---|---|
| overview | `order_get`, `order_list`, `production_board_get` | – |
| 2 allocate | `order_allocation_get`, `order_alloc_suggest_defaults` | `order_allocation_save` |
| 3 T&A | `order_tna_get`, `order_tna_health` | `order_tna_make`, `order_tna_lock`, `order_tna_revise` |
| 4 samples/PP | `order_samples_get` | `order_samples_create`, `order_sample_round`, `order_sample_load`, `order_pp_meeting_make`, `order_pp_meeting_actions`, `order_pp_meeting_submit` |
| 5 materials | `order_materials_get`, `order_req_lines` | `order_items_create`, `order_req_save`, `order_req_approve`, `order_req_revise`, `order_po_make` **W!**, `order_rolls_import`, `order_inspection_make`, `order_inspection_submit` |
| 6 cut/sew | `order_cutsew_get`, `order_card_context`, `order_cutplan_suggest`, `order_cut_issuable` | `order_card_save`, `order_card_approve`, `order_card_revise`, `order_cutplan_release`, `order_cutplan_approve`, `order_cutplan_reopen`, `order_cut_issue` **W!**, `order_ob_activate` |
| 7 subcontract | `order_subcontract_get`, `order_prefill_sub` | `order_challan_short_close` **W!**, `order_settlement_invoices` **W!** |
| 8 pack | `order_pack_get`, `order_pack_plan`, `order_prefill_pack` | (packing list and final inspection via `cx_write` with the prefill) |
| 9 ship | `order_ship_get` | `order_shipment_create`, `order_ship_make_dns` **W!**, `order_ship_submit` **W!**, `order_ship_record` |
| 10 invoice | `order_invoice_get` | `order_invoice_prepare`, `order_invoice_submit` **W!**, `order_followup_log`, `order_claim_credit_note` **W!**, `order_close` **W!** |
| floor docs | `order_prefill` (kind `dlr`, …) | create Daily Line Report, Line Input etc. through `cx_write` using the prefilled values |

## Generic ERP access

`cx_doc_meta` R · `cx_doc_get` R · `cx_doc_list` R · `cx_link_search` R · `cx_write` W/W! · `cx_run_script` W/W! · `cx_reports` R · `cx_report_run` R (17 Script Reports through the runtime, cached 60 s) · `cx_approvals` R · `cx_decide` · `cx_runs` R · `cx_rollback_run` (managers).

## Mail drafts (legacy outbound)

`get_mail_settings` · `save_mail_settings` · `test_mail_settings` · `create_email_draft` · `get_email_drafts` · `approve_and_send_email` (a person) · `reject_email_draft` · `delete_email_draft`.

## T&A (legacy overlay, still present)

`get_tna_calendar`, `get_tna_orders`, `get_tna_kpis`, `get_tna_alerts`, `update_milestone`, `tna_run_action`, `tna_rollback_action`, `cx_tna_push_milestone` (writes a calendar edit to the ERP's `TNA Milestone`). **For new work use `order_tna_*`**, which write the ERP's own `Order TNA`. The overlay has its own SQLite store and is not yet retired (open decision).

## Chat helper

`ask_kogo` answers questions over live ERP data, deterministic and grounded. Not a write path.

## Looking up a function you do not know

1. `grep '^### ' cortex-tower/backend/document.md`
2. Read that heading's parameters and return shape.
3. Prefer the narrowest function; the order-level one over `cx_write`.
4. If nothing fits, say so; do not invent a function name (an unknown name returns `Function '<x>' not found`).
