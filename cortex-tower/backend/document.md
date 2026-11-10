# Cortex Operations Control Tower — Backend API Reference

**Project:** cortex_operations_control_tower
**Backend entry point:** `backend/functions.py`
**Live ERP client:** `backend/erp.py`
**Database:** SQLite at `backend/data/cortex_operations_control_tower.db` (decision state only)
**Configuration:** `backend/config.py` is the single source of truth. Business modules import
from it; none read `os.environ` or hardcode an id/host/price-list. Integration constants
(`ERP_APP_ID`, `ERP_WRITE_MODE`, `SELLING_PRICE_LIST`, `DEFAULT_COMPANY`, `DEFAULT_CURRENCY`,
`MAIL_FROM_NAME`, `SMTP/IMAP_*`) are env-overridable with the current production value as default.
**Tests:** `backend/tests/test_engine.py` (engine guardrails) + `backend/test_email_engine.py`
(email). Run `python3 tests/test_engine.py` from `backend/` — exit 0 = pass.

---

## Data — READ + OPT-IN WRITE

This dashboard reads **live from the client's KOGO ERP / Frappe (KOGO_SAS)** at
`https://apps.kogo.ai:9447` (base discovered at runtime, never hardcoded in
business code).

**Reads are GET-only.** **Writes are opt-in and gated** (`backend/writes.py`):

* mode `ERP_WRITE_MODE` = `off | safe | draft | all` (default **`draft`**)
* every write is a **draft** (`docstatus = 0`) — nothing is ever submitted
* **idempotent** — one ERP record per action; a second Execute is a no-op
* **reversible** — `rollback_action` deletes the created record and reopens the risk
* **audited** — the created doc name is written to the local audit log

Executable writes (mode `draft`, all idempotent + reversible). The `records` column
is the count the action *would* create against the live ERP on **2026-11-02** — it is
re-derived from the ERP at execution time, never stored:

| slug | operation | doctype | records today |
|---|---|---|---|
| `create_boms` / `register_bom_sizewise` | create | BOM | missing per-size BOMs (consumption copied from the Size-S BOM, disclosed in remarks) |
| `raise_delivery_notes` | create | Delivery Note | one per open SO that has none |
| `reinspection_fabric` | create | Quality Inspection | 1 per failing fabric |
| `review_receivables` | create | Payment Request | one per outstanding invoice |
| `submit_trim_mrs` | **submit** | Material Request | the draft MRs |
| `raise_trim_mrs` | create | Material Request | trim demand with no MR |
| `assign_data_owners` | create | Task | 1 |
| `create_item_prices` | create | Item Price | per unpriced item |
| `raise_work_orders` | create | Work Order | per BOM with no WO |
| `close_quality_inspection` | create | Quality Inspection | per open inspection |
| `review_shipment_variance` | create | Task | one per out-of-allowance shipment |
| `request_evidence` | create | Task | 1 |
| `link_client_po` · `review_cost_sheet` · `close_pp_actions` · `raise_material_request` · `renew_quotation` | create | Task | one review task per finding (2026-11-02) |

Everything is capped at 60 records per execution and skipped if it already exists.
The remaining actions are email / review actions that create no ERP record.

### Doctypes read live (verified 2026-11-02)

The dashboard is a **reader over the ERP as it is built today**. Four doctypes it used
to read were retired and now hold zero rows, so the panels drawn from them read empty
while the ERP held real data elsewhere. They are replaced as follows:

| retired | read instead |
|---|---|
| `Garment Shipment Evidence` (0 rows) | **`Shipment Document Evidence`** (22) + **`Freight Booking`** (9), grouped per shipment by `erp_model.shipment_leg()` |
| `Production Daily Evidence` (0 rows) | **`PP Meeting`** (2) · `Cortex Marker` (2) · `Cutting Lay` / `Production Card` / `Cortex WIP` / `Cortex End Line Audit` (built, still empty) |
| `Trim Requisition Evidence` (0 rows) | **`Cortex Trim Requisition`** (6) |
| `Fabric Requisition Evidence` (0 rows) | **`Cortex Fabric Requisition`** (6) |

| Doctype | Count | What the dashboard uses it for |
|---|---|---|
| `Sales Order` (+ child `items`) | 8 (5 submitted) | open orders, order book, units on order, delivery windows, buyer orders |
| `Client Purchase Order` | 13 | the buyer's own PO book (independent of the SO), and POs with no order |
| `Buyer Tech Pack` | 5 | pack readiness, BOM/POM line counts, revisions |
| `Buyer BOM` | 4 | lines, mapped vs unmapped, BOMs generated |
| `Style File` | 5 | the style folder behind each order |
| `Cost Sheet` | 2 | costed FOB, margin, gate blocked, pack moved |
| `Consumption Card` | 1 | CAD consumption + wastage |
| `Quotation` | 7 | offers in play vs converted (via `Sales Order.custom_quotation`) |
| `Item Mapping` | 24 | buyer code → our item |
| `Sales Contract` / `Contract Allowance Band` | 2 / 4 | contract sheets and the quantity allowance bands |
| `Cortex Fabric Requisition` / `Cortex Trim Requisition` | 6 / 6 | requisitions with no Material Request cover |
| `Material Request` | 9 | draft requests (no RFQ/PO) |
| `Purchase Order` / `Purchase Receipt` | 16 / 19 | sourcing pipeline by supplier |
| `BOM` | 39 (28 submitted) | BOM coverage as DISTINCT items (28 of 34 FG variants = 82 %), SAM, operation cost |
| `Item` | 64 | finished-garment variants (`variant_of` + `item_group`) driving BOM coverage |
| `Work Order` / `Job Card` | 34 / 190 | manufacturing order + operation-level work |
| `PP Meeting` | 2 | the PP gate: open actions, bulk-cutting release |
| `Stock Entry` | 50 | material issue / FG receipt |
| `Fabric Roll` | 141 | fabric stock KPI |
| `Freight Booking` | 9 | booking, vessel, mode, ETD/ETA, cartons |
| `Shipment Document Evidence` | 22 | the customs basis, declared quantity/value and document set, per shipment group |
| `Delivery Note` | 16 (10 live) | delivery-note coverage |
| `Sales Invoice` / `Payment Entry` | 17 / 17 | receivables, overdue, payment coverage |
| `Quality Inspection` | 18 | open inspections (draft) only |
| `Fabric Quality Evidence` | 7 | quality results per fabric code |
| `Migration Data Gap` | 17 (13 open) | open migration data gaps |
| `Trim Mapping Exception` | 9 | buyer trim specs with no mapping |
| `Item Price` | 49 | price-master check |

`get_erp_model` returns the full census (45 Cortex process objects across 8 stages:
40 populated, 5 built-but-empty) — it is the honest answer to *"is this dashboard
reading the ERP as it is?"*.

There is **no synthetic seed data**. `seed.py` is a no-op initializer that only
creates the local tables.

---

## `backend/erp.py` — live KOGO ERP client

Bootstraps API credentials from the KOGO gateway and performs the ERP reads (GET). It also
holds the opt-in write helpers (`erp_create`/`erp_update`/`erp_delete`) that only `writes.py`
calls — mode-gated, drafts-only, reversible. **Every helper swallows errors and returns an
empty value — nothing raises.**

| Helper | Signature | Returns |
|---|---|---|
| `get_creds` | `get_creds() -> dict` | `{"BASE": url, "AUTH": {"Authorization": "token key:secret"}}` — cached to `backend/data/sas_creds.json`; re-discovered from the gateway when missing/stale. `{}` on failure. |
| `erp_get` | `erp_get(doctype, fields=None, filters=None, limit=500, order=None) -> list` | list of documents (`[]` on failure) |
| `erp_get_checked` | `erp_get_checked(...) -> (ok, list)` | distinguishes "read failed" from "empty result" |
| `erp_doc` | `erp_doc(doctype, name) -> dict` | full document — required for child tables such as `items` |
| `erp_count` | `erp_count(doctype, filters=None) -> int` | document count (`frappe.client.get_count`) |
| `erp_available` | `erp_available() -> bool` | ERP reachable? |
| `erp_status` | `erp_status() -> dict` | `{"connected": bool, "base": str, "error": str\|None}` (cached ~15 s) |
| `last_error` | `last_error() -> str\|None` | the most recently swallowed error |

Rules honoured by `erp.py`:

* Credentials are cached to `backend/data/sas_creds.json` and preferred when
  present, so the app keeps working even if the gateway JWT is absent at runtime.
* `filters` are Frappe JSON: `[["docstatus","=",1]]`; the doctype is URL-encoded
  (`Sales Order` → `Sales%20Order`).
* No `doctype` query param is passed to `/api/resource/<DT>`.
* Child tables are **not** returned by list fields — the full parent document is
  fetched when `items` are needed.
* Every call is a GET with a short timeout; failures return empty, never raise.
* Environment reads happen only in `erp.py` (bootstrap) and `config.py`.

Runtime env used for bootstrap: `API_PATH`, `USER_JWT_TOKEN`, `SWARM_ID` / `AGENT_ID`.

---

## Response contract — additive keys on EVERY function

Every function (read *and* action) additionally returns:

```json
{
  "live": true,
  "source": "KOGO ERP",
  "generated_at": "2026-09-29T04:50:12.123456",
  "connection": { "connected": true, "base": "https://apps.kogo.ai:9447", "error": null }
}
```

When the ERP is unreachable the functions return their normal shape with **empty
collections**, `"live": false`, and
`"connection": {"connected": false, "base": "", "error": "erp_unavailable: <reason>"}`.
They never raise and never return a 500.

Action functions return `"erp_write"` (true when a real ERP record was created)
and `"mode"` (`off` / `safe` / `draft` / `all`). `execute_action` and `run_action`
now perform the real write; `rollback_action` deletes it. Preview functions remain
read-only.

---

## Database Schema (local decision state only)

### Table `risk_state`
Stable identity + workflow status per live-derived risk. `risk_key` is the upsert
key, so `id` stays constant across calls.

| Column | Type | Description |
|--------|------|-------------|
| id | integer | PK — stable id referenced by recommendations |
| risk_key | string(80) | unique: `BOM_COVERAGE`, `NO_DELIVERY_NOTES`, … |
| risk_type | string(50) | `production_delay` / `shipment_risk` / `quality_risk` / `fabric_shortage` / `margin_risk` / `invoicing_risk` / `data_quality` |
| severity | string(20) | `critical` / `warning` |
| title | string(400) | live-derived title |
| status | string(20) | `open` / `resolved` (default `open`) |
| payload | text | JSON of the live evidence fields (`style`, `affected_orders`, `required_date`, `material`, …) |
| created_at / updated_at | datetime | auto |

### Table `action_state`
Stable identity + workflow state per live-derived recommendation. `action_key`
(`"<risk_key>::<slug>"`) is the upsert key.

| Column | Type | Description |
|--------|------|-------------|
| id | integer | PK — the `action_id` used by the action functions |
| action_key | string(160) | unique, e.g. `BOM_COVERAGE::create_boms` |
| risk_key | string(80) | links back to `risk_state.risk_key` |
| approval_status | string(20) | `pending` / `approved` / `rejected` / `modified` / `executed` |
| modified_text | string(1000) | operator-edited action text |
| executed_at | datetime | set on execution |
| payload | text | JSON: `risk_title`, `action`, `expected_impact`, `responsible_team`, `priority` |
| created_at / updated_at | datetime | auto |

### Table `audit_log`
Unchanged — the local operator audit trail.

| Column | Type | Description |
|--------|------|-------------|
| id | integer | PK |
| action_type | string(50) | `approval` / `modify` / `execute` |
| action_name | string(200) | human label |
| description | text | details |
| actor | string(100) | operator |
| risk_title | string(400) | linked risk |
| approved | string(20) | `approve` / `reject` |
| timestamp | datetime | auto |

> `BuyerOrderModel` was removed — buyer orders are live now. `RiskModel` and
> `RecommendedActionModel` were replaced by `RiskStateModel` / `ActionStateModel`.

### Table `mail_settings` (email connector P1)
Single logical row holding the outbound SMTP configuration. The SMTP password
is stored here but is **never** returned — `to_dict()` exposes only `password_set`.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| id | integer | auto | PK |
| enabled | integer (0/1) | 0 | master on/off for outbound mail |
| email_account | string(160) | "" | sender Gmail/Workspace address |
| from_name | string(160) | "Cortex Textile Limited" | display name on the From header |
| smtp_host | string(160) | "smtp.gmail.com" | SMTP host |
| smtp_port | integer | 587 | SMTP port |
| use_tls | integer (0/1) | 1 | STARTTLS when 1 |
| password | text | null | SMTP password / app password (never serialized) |
| updated_at | datetime | now | auto |

### Table `email_draft` (email connector P1)
Grounded email drafts awaiting human approval. Rows are written only from the
existing `email_engine` output and carry the engine's `fact_sheet` so an edited
send can be re-validated for grounding.

| Column | Type | Description |
|--------|------|-------------|
| id | integer | PK |
| action_id | integer null | `action_state.id` it came from |
| action_key | string(160) | originating action key |
| intent | string(40) | engine intent (`delivery_plan`, `statement_of_account`, …) |
| to_email | string(320) | resolved recipient email (Customer/Contact `email_id`; display name as last-resort fallback) |
| from_name | string(200) | display name |
| subject | string(500) | subject |
| body | text | plain-text body |
| fact_sheet | text (JSON) | engine fact sheet used for grounding re-checks |
| status | string(20) | `draft` / `sent` / `failed` / `rejected` |
| grounding_ok | integer (0/1) | engine/validator result |
| grounding_unsourced | text (JSON list) | any unsourced tokens |
| policy_version | string(60) | `comms-policy/…` |
| edited | integer (0/1) | subject/body/recipient edited by the approver |
| idempotency_key | string(80) unique | `"<action_key>:<sha1(subject+body)>"` |
| message_id | string(200) | SMTP Message-ID after send |
| error | text | failure text |
| created_at / decided_at / sent_at | datetime | |
| decided_by | string(100) | default `Ops Manager` |

> These two tables are created automatically by `database.init_db()`
> (`Base.metadata.create_all`) — the migration is additive only.

---

## Functions

### `get_dashboard`
Full payload: **17 KPIs**, the live risk list (23 on 2026-11-02), recommendations,
audit trail, live buyer orders, 7 charts, factories, delivery-month options,
command suggestions, the **ERP model census** and the **shipment leg**.

KPIs (all live, ordered along the order's own chain):

| # | key | reads | 2026-11-02 |
|---|---|---|---|
| 1 | `open_orders` | submitted SO with `per_delivered < 100` | 4 |
| 2 | `order_book` | grand total of those orders | USD 76,630 (all orders 92,930) |
| 3 | `units_on_order` | sum of their order lines | 4,800 pcs |
| 4 | `buyer_book` | `Client Purchase Order` + `linked_sales_order` | 13 · USD 270,671 · 3 linked |
| 5 | `buyer_pack` | `Buyer Tech Pack` readiness/status | 5 · 1 not ready to build a BOM |
| 6 | `quotations` | `Quotation` not converted (via `Sales Order.custom_quotation`) | 1 of 7 |
| 7 | `cost_gate` | `Cost Sheet` gate shut or `pack_stale` | 1 of 2 |
| 8 | `bom_coverage` | **distinct** FG items with a BOM ÷ FG variants | 82 % (28 of 34 · 39 BOMs) |
| 9 | `fabric_rolls` | `Fabric Roll` | 141 |
| 10 | `requisitions` | submitted `Cortex Fabric/Trim Requisition` with no `material_request` | 2 of 12 |
| 11 | `trim_mr_draft` | `Material Request` in Draft | 4 of 9 |
| 12 | `floor_gate` | `PP Meeting` with open actions / bulk cutting not released | 2 of 2 |
| 13 | `shipments` | declared quantity, **once per shipment group** | 3,488 pcs · 10 groups · 22 evidence rows |
| 14 | `shipment_docs` | groups missing a Customs Declaration / B/L + unlinked evidence rows | 3 groups · 5 unlinked rows |
| 15 | `receivables` | submitted `Sales Invoice` past due with a balance | 9 · USD 79,558 |
| 16 | `delivery_notes` | `Delivery Note` not cancelled | 10 |
| 17 | `open_gaps` | `Migration Data Gap` not resolved | 13 of 17 |

Charts: `orders_at_risk`, `material_readiness`, `prod_plan_actual` (ordered · factory
packed · sent — `sent` is the declared quantity per shipment group),
`quality_trends`, `shipment_readiness` (per shipment group), `order_margin`,
`supplier_delivery`.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `inbox_action` | string | no | "" — see the Inbox bridge below |
| `bridge_action` | string | no | "" — reaches a function that is in `FUNCTIONS` but not yet in the published allowlist (`get_erp_model`, `get_shipment_leg`, `get_recommendations`, `get_erp_preview`, `get_ai_next_steps`, `run_monitor`, `submit_in_erp`, `rollback_action`) |

**Returns:** `{kpis, risks, recommendations, risk_summary, forecast, migration_gaps,
audit_log, buyer_orders, charts, factories, date_options, command_suggestions,
erp_model, shipment_leg, demo:false, write_mode}` + the 4 additive keys.

`erp_model` — the census: `{generated_at, source, stages:[{key,label,objects:[{doctype,
purpose,count,status}],populated,total}], totals:{objects,populated,empty,missing,rows},
retired:[{retired,use}]}`. `status` is `populated` / `empty` / `missing`.

`shipment_leg` — `{groups, evidence_rows, shipped_pcs, ordered_pcs, groups_with_qty,
allowance_flags, groups_missing_documents, unlinked_rows}`. One group = one shipment;
the declaration row and its size-grid row are the same cartons, so the quantity is the
group's max, never a sum.

#### Inbox bridge (temporary)
The middleware's callable-function list is snapshotted at **publish** time, so the inbound-mail
functions (`sync_inbox`, `get_inbox`, `get_inbox_summary`, `get_mail_message`, `dismiss_mail`,
`get_order_changes`, `decide_order_change`) are not directly callable until the project is
re-published. Until then they are reached through this already-published function:

| Parameter | Type | Notes |
|-----------|------|-------|
| `inbox_action` | string | one of the 7 inbound-mail function names → dispatched, returns that function's exact shape |
| (any further params) | | forwarded verbatim to the target inbox function (e.g. `limit`, `notify`, `status`, `mail_id`, `change_id`) |

A call with no `inbox_action` behaves exactly as before. Whitelisted to the inbound-mail
functions and (via `bridge_action`) the newer read/edit helpers only. Removable once the
project is re-published.

### `get_buyer_orders`
Live `Sales Order` (docstatus 1), one row per order.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| search_query | string | no | "" |
| limit | integer | no | 50 |
| offset | integer | no | 0 |

**Returns:** `{buyer_orders, total, total_count, offset, limit}`. Each row carries
`id, order_number, buyer_name, style, quantity, ship_date, delivery_date, status
("Overdue" when past due, else the ERP status), expected_margin_pct,
current_margin_pct, created_at, updated_at` plus the additive live fields
`po_no, transaction_date, grand_total, per_delivered, currency, company, items_note`.

### `get_risks` / `get_recommendations`
Live-derived lists (with the stored state overlay), searchable and paginated.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| search_query | string | no | "" |
| limit | integer | no | 50 |
| offset | integer | no | 0 |

**Returns:** `{risks, total, total_count, offset, limit}` /
`{recommendations, total, total_count, offset, limit}`.

### `get_audit_log`
Local audit trail, newest first.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| search_query | string | no | "" |
| limit | integer | no | 50 |
| offset | integer | no | 0 |

**Returns:** `{audit_log, total, total_count, offset, limit}`.

### `get_erp_model`
The ERP model census — every Cortex process object, stage by stage, with the live row
count and whether it is populated, built-but-empty, or not installed. This is the
answer to "is the dashboard reading the ERP as it is?".

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| (none) | | | |

**Returns:** `{erp_model: {generated_at, source, stages[], totals, retired[]}}` + the 4
additive keys. Cached 120 s (`erp_model.census()`).

Until the project is re-published it is reachable as
`get_dashboard(bridge_action="get_erp_model")` — same shape.

### `get_wip_plan`

**The WIP as a drawing, not a table.** 5 orders x 28 SKU lines x **29 gates** = **812 rows** is unreadable as a
grid, so this returns the same `Cortex WIP` records positioned for two views:

* `lanes[]` — one lane per (order, SKU): `sku`, `qty`, `stage`, `pct`, `late`, `ship_date`, `pcd`, and
  `bars[]` = the 29 gates, each with `start` / `end` (the bar window), `date` (the drop-dead), `actual`,
  `status` (`Pending` / `Late` / `Done` / `Passed` / `Waived`), `late_days`, `critical`, `department`, `phase`,
  `phase_name`, `evidence_doctype`, `duration_source`, `source` and `marker_only` (true for the first gate of
  each SKU — it has no earlier gate, so it draws as a marker).
* `orders[].plan[]` — the same 29 gates **once per order** (not per SKU), which is what the Plan tab edits:
  `suggested` (delivery − `offset_days`, from the gate master), `planned` (the date on the record), `actual`,
  `status`, `late_days`, `delta_days` (planned vs suggested), `offset_days`, `duration_days`, `phase`,
  `phase_name`, `department`, `evidence_doctype`, `duration_source` (`measured` / `default` / `pinned`) and
  `source_note` (why that number). Also `missed[]`, `projected_ship` and `slip_days`.
* `phases[]` — the client's five phases: `phase`, `name`, `gates[]`, `count`, `span_days`, `first_offset`,
  `last_offset`, `missed`, `done`, `unset`.
* `alerts[]` — every gate whose drop-dead has passed with no document and no goods behind it: `order`, `wip`,
  `milestone`, `phase`, `due`, `days_overdue`, `department`, `evidence_doctype`.
  `projected_ship` = the promised delivery date + the **worst single overdue gate** (one late gate delays its
  successors by exactly that much — it is not a sum). `alert_basis` is the sentence that says so.
* `calendar` — `months` (only the months that carry a drop-dead), `chips[]` (one per milestone, with `date`,
  `wip`, `order`, `sku`, `milestone`, `department`, `status`, `late_days`) and `departments`.
* `summary` — orders, SKUs, milestones, pcs, late / done / pending, `next_7_days`, and per plant
  `capacity.pcs_month` with the pcs `booked` in it.
* `bar_basis` — the sentence that says how a bar's window was derived, so the drawing cannot be misread.

Params: `refresh` (`bool`, default `false`) — bypass the 90 s cache. Read-only; never writes, never raises; an
unreachable ERP returns `live: false` with empty views. Reached from the shipped app through
`get_dashboard(bridge_action="get_wip_plan")` until the project is re-published.

The source is `backend/wip_plan.py`. Child tables are read **through the parent document** — `Cortex WIP Line` and
`Cortex WIP Milestone` are not listable over REST (403, same as `Sales Order Item`).

---

### `wip_apply_plan`

**The Plan tab's one write.** Sends the dates a planner settled on after pressing `+` / `−`, and writes them to
`Cortex WIP.milestones` (`planned` + `drop_dead`) for every SKU row of the named gate, then recomputes the lines'
`next_due` / `late` / `pct_complete` and the header's `late_count` / `next_due`. The `+` / `−` arithmetic happens
in the browser, so nothing is written until Save and a half-applied plan cannot exist.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `wip` | string | yes | — |
| `changes` | string | yes | `"Gate=YYYY-MM-DD;Gate two=YYYY-MM-DD"` |
| `ship_date` | string (`YYYY-MM-DD`) | no | the record's own |
| `note` | string | no | `""` — appended to the Comment it leaves on the record |

**Refuses** (never raises): an unknown gate name (the reason lists the gates the record does have); a value that
is not a date; an empty change set. **Never moves a gate whose rows are `Done` or `Waived`** — the reply names
them in `gates_kept_done`, because an actual is history and a re-plan may not rewrite what happened.
Mode-gated by `ERP_WRITE_MODE`; every call leaves a `Comment` on the ERP record.

**Returns:** `{wip, ok, phase_writes, rows_moved, gates_kept_done, late_count, next_due, ship_date, message}`

---

### `get_shipment_leg`
The customs leg, grouped per shipment: ordered vs declared quantity, variance, allowance
status, documents held and documents missing, ETD/ETA and mode.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| (none) | | | |

**Returns:** `{shipment_leg: {groups[], evidence_rows, shipped_pcs, ordered_pcs,
groups_with_qty, allowance_flags, groups_missing_documents, unlinked_rows}}` + the 4
additive keys. Each group carries `group, sales_order, client_purchase_order, style,
rows[], ordered, shipped, variance_qty, variance_pct, variance_status, qty_captured,
documents[], missing[], commercial_missing[]`.

Until the project is re-published it is reachable as
`get_dashboard(bridge_action="get_shipment_leg")` — same shape.

### `preview_action`
Auto-detects the channel (email when the action targets a supplier / buyer /
Cortex, otherwise ERP) and returns the matching preview.

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |

**Returns:** `{action_id, channel:"email", email:{to,from,subject,body}, intent}` or
`{action_id, channel:"erp", record:{doctype, fields}, intent}` — plus `erp_write:false`, `mode:"read-only"`.
`record.doctype` is always a real ERPNext doctype (`BOM`, `Work Order`, `Delivery Note`,
`Quality Inspection`, `Material Request`, `Item Price`, `Payment Entry`, `Shipment`, `Task`)
filled with real values from the live risk.

### `get_email_preview` / `get_erp_preview`
The two specific branches of `preview_action`.

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |

### `decide_action`
Approve or reject a recommendation (local state + audit only).

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |
| decision | string | yes (`approve` / `reject`) |

**Returns:** `{recommendation, decision, audit}` + `erp_write:false`, `mode:<current>`.

### `modify_action`
Rewrite a recommendation's text and mark it `modified`.

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |
| new_text | string | yes |

### `execute_action`
Requires `approved`; sets `executed`, resolves the linked risk
(`risk_state.status = "resolved"`), and writes the audit entry. **No ERP write.**

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |

**Returns:** `{recommendation, risks, dashboard, audit, erp_write:false, mode:"read-only", note}`.

### `run_action`
End-to-end simulation: intent + `data_used` (with the live evidence numbers) +
`result` + audit.

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |

**Returns:** `{intent, data_used, result:{status:"success", channel, note}, recommendation, erp_write:<bool>, mode:<current>}`.

### `ask_kogo`
Grounded, **ERP-aware** copilot — see `COPILOT.md` and `copilot.py`.

For each question it **retrieves the relevant live ERP data** (via
`copilot.build_evidence` → `rulebook.live_facts()` + `forecast.build()`), asks the
LLM to answer from that evidence only, then validates every number in the answer
against the evidence (`grounded`/`unsourced`). Falls back to the deterministic
answerer if the model is unavailable. No reasoning/chain-of-thought is ever
returned (the model's `<think>` block is stripped).

Always included: `today`, `order_book`, `orders` (per-order value/`qty_pcs`/
delivery dates/`days_to_earliest_delivery` where negative = overdue/status/
customer/item codes), `styles_in_demand`, `risk_summary`, `risks`, `forecast`.
Routed by keyword: `finance`, `materials`, `procurement`, `quality`, `logistics`,
`production`, `gaps` — when nothing matches, all sections are included.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| question | string | yes | — |
| context | object | no | null |

**Returns:** `{answer, related, grounded, unsourced, evidence_sections}` + the 4
additive keys.

---

### `get_fabric_intelligence`
Fabric & price intelligence — one live row per **style**, joining four ERP sources and
applying explicit detection rules. Read-only; nothing is written to the ERP.

| Parameter | Type | Required |
|-----------|------|----------|
| — | — | (no parameters) |

**Sources joined (per style):**

| What | ERP source |
|------|------------|
| Fabric per garment | `BOM Item.stock_qty` / `qty` (normalised to **yard**) |
| Quoted consumption + cost build | `Internal Costing Evidence.avg_consumption_yard`, `source_*_usd` |
| Buyer PO yield + allowed price | `Client Purchase Order Evidence.fabric_yield_yd`, `fabric_price_usd`, `unit_price_usd` |
| Actual buying rate | `Purchase Order Item.rate` (USD, normalised to USD/yard) |
| Ordered qty + selling price | `Sales Order Item.qty` / `rate`, mapped through `Item.variant_of` → style |

**Detection rules** (thresholds returned in `meta`):

| Flag | Severity | Fires when |
|------|----------|-----------|
| `consumption_conflict` | warning &gt;5% / critical &gt;15% | BOM, costing and buyer-PO consumption disagree by more than the threshold |
| `rate_drift` | warning | Buying rate differs from the quoted rate by &gt;5% |
| `price_below_cost` | critical | Selling price &lt; costed total |
| `thin_margin` | warning | Margin below 15% |
| `no_buy_rate` | warning | The fabric item has no submitted purchase order |
| `missing_bom` / `missing_costing` | critical / warning | No BOM fabric line / no internal costing for the style |
| `po_vs_so_price` | info | Client PO unit price ≠ Sales Order rate (a revision) |
| `uom_mix` | info | BOM states yard while the purchase states metre |

**Returns:**

```json
{
  "summary": {
    "styles": 10, "order_qty_pcs": 17450, "order_value_usd": 281041.66,
    "styles_ok": 0, "styles_watch": 6, "styles_alert": 4,
    "consumption_conflicts": 6, "rate_drifts": 4, "price_below_cost": 0,
    "missing_data": 5, "fabric_exposure_usd": 100079.61,
    "cost_of_goods_usd": 202383.64, "blended_margin_pct": 27.99
  },
  "rows": [
    {
      "style": "C8009-R43-304", "description": "Dress", "fabric_item": "FAB-R43-WSTPN",
      "order_qty_pcs": 1786, "sell_price_usd": 21.5, "client_po_price_usd": 21.5,
      "consumption_yd": {"bom": 2.5, "costing": 2.5, "consensus": 2.5, "spread_pct": 0.0, "sources": 2},
      "required_m_unit": {"bom": 2.286}, "required_m_total": {"bom": 4082.8, "costing": 4082.8},
      "rate_usd": {"buy_per_yd": 2.021, "buy_per_m": 2.21, "po": "PUR-ORD-2026-00006-1",
                   "supplier": "Cortex Fashion (HK) Limited", "quoted_per_yd": 2.3},
      "cost_usd": {"fabric_bom_basis": 5.05, "cm": 3.3, "trim": 0.7, "wash": 0.3,
                   "overhead": 2.02, "rejection": 0.4, "finance": 0.29, "depreciation": 0.29,
                   "bom_basis_total": 14.53, "reference": 14.53},
      "margin_usd": 6.97, "margin_pct": 32.4, "fabric_exposure_usd": 9023.0,
      "flags": [], "verdict": "watch"
    }
  ],
  "flags": [{"style":"C4878-H96-304","type":"consumption_conflict","severity":"critical",
             "title":"Consumption sources disagree by 28.2%","detail":"bom 1.170 yd / costing 1.500 yd / client_po 1.170 yd — consensus 1.170 yd.",
             "impact_usd": 4065.41}],
  "charts": {"consumption_sources": [], "cost_vs_price": [], "fabric_value_by_style": [], "flags_by_type": []},
  "meta": {"consumption_warn_pct": 5.0, "consumption_crit_pct": 15.0,
           "rate_warn_pct": 5.0, "margin_warn_pct": 15.0, "yard_per_metre": 1.093613},
  "live": true, "source": "KOGO ERP", "generated_at": "…",
  "connection": {"connected": true, "base": "…", "error": null}
}
```

---

## Outbound Mail (email connector P1)

Approve → Send loop over SMTP. **SMTP runs only in `backend/mailer.py`**; the
browser only calls these middleware functions. Every draft body is still written
by `email_engine` (grounded + validated), and nothing is sent without an explicit
human approval call.

### `get_mail_settings`
Return the SMTP configuration. The password is masked to `password_set`.

| Parameter | Type | Required |
|-----------|------|----------|
| — | — | (no parameters) |

**Returns:** `{settings: {id, enabled, email_account, from_name, smtp_host, smtp_port, use_tls, password_set, updated_at}, connected: bool}`
(`connected` = enabled **and** account set **and** a password is saved).

### `save_mail_settings`
Create/update the single settings row. The `password` is only overwritten when a
non-empty value is passed.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| email_account | string | yes | — |
| from_name | string | no | None (unchanged) |
| smtp_host | string | no | "smtp.gmail.com" |
| smtp_port | integer | no | 587 |
| use_tls | integer (0/1) | no | 1 |
| password | string | no | None (unchanged) |
| enabled | integer (0/1) | no | 1 |

**Returns:** `{ok: true, settings: {…password_set…}}`

### `test_mail_settings`
Send a short test email to `to` (defaults to the configured account).

| Parameter | Type | Required |
|-----------|------|----------|
| to | string | no |

**Returns:** `{ok: bool, error: string, to: string}` (never raises).

### `create_email_draft`
Generate a grounded email via the existing `_live_ctx` + `email_engine` path
(mirrors `_email_preview`, including the blocked path) and store it in the
approval queue. Idempotent per `action_key + sha1(subject+body)`.

The engine's recipient is a party *display* name; the stored `to_email` is
resolved to a real address via `_resolve_recipient_email` (matching `Customer`
then `Contact` by case-insensitive `name` contains -> `email_id`), falling back
to an explicit `to_email` and finally to the raw display name.

| Parameter | Type | Required |
|-----------|------|----------|
| action_id | integer | yes |
| subject | string | no |
| body | string | no |
| to_email | string | no |

**Returns:** `{ok, draft, blocked, blocked_reason}`. If the engine blocks, `ok:false`,
`blocked:true`, `blocked_reason` set (e.g. `ambiguous_supplier`, `erp_unavailable`)
and **nothing is stored**.

### `get_email_drafts`
List stored drafts, newest first. `status="all"` returns every row.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| status | string | no | "draft" |

**Returns:** `{drafts: [...]}`

### `approve_and_send_email`
Apply optional edits, **re-run `email_engine.validate_grounding()` against the
stored fact sheet**, refuse if ungrounded (`ok:false, error:"ungrounded"`), then
send over SMTP; sets `status` to `sent`/`failed` and writes an `audit_log` row.
Idempotent: a row already `sent` is returned unchanged.

The final recipient is `to_email or draft.to_email`; it must look like an email
address (contains `@` with a dot after it). If not, the call is refused with
`ok:false, error:"invalid_recipient"` and **nothing is sent**. When `to_email` is
supplied it is persisted on the draft (`edited=1`).

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| draft_id | integer | yes | — |
| subject | string | no | None (keep) |
| body | string | no | None (keep) |
| to_email | string | no | None (keep) |
| actor | string | no | "Ops Manager" |

**Returns:** `{ok, status, message_id, error, draft}`. `error` is `invalid_recipient`
for a non-address recipient or `ungrounded` when grounding re-validation fails.

### `reject_email_draft`
Mark a draft `rejected` (never sends). Writes an `audit_log` row. Refuses a `sent` row.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| draft_id | integer | yes | — |
| reason | string | no | "" |

**Returns:** `{ok, draft}`

### `delete_email_draft`
Delete a draft. Only allowed when `status != sent`.

| Parameter | Type | Required |
|-----------|------|----------|
| draft_id | integer | yes |

**Returns:** `{ok}`

---

## How to Call

### CLI

```bash
cd artifacts/cortex-operations-control-tower/backend
python3 functions.py get_dashboard '{}'
python3 functions.py get_buyer_orders '{"limit":10}'
python3 functions.py ask_kogo '{"question":"What is blocking shipment?"}'
python3 functions.py preview_action '{"action_id":1}'
python3 functions.py decide_action '{"action_id":1,"decision":"approve"}'
python3 functions.py run_action '{"action_id":1}'
```

### Middleware API v1

```json
POST {API_BASE}/api/agent/common_project_api_v1
{
  "project": "cortex_operations_control_tower",
  "function": "get_dashboard",
  "params": {},
  "agentId": "{agentId}",
  "deploymentId": "{deploymentId}",
  "swarmId": "{swarmId}",
  "originId": "{originId}"
}
```

### Health

```bash
curl "${API_HEALTH}?userId=${USER_ID}&originId=${ORIGIN_ID}&project=cortex_operations_control_tower"
```

---

# Inbound Mail (P2) — mailbox → understood inbox → order-change flags

Read-only ingestion of the connected mailbox. Understanding is **deterministic**
(no OCR — by client decision): headers + text body + attachment *names/sizes* only.
Nothing here writes to the ERP on its own; order-affecting mail becomes a flagged
row a human decides on.

### Local tables (additive)

**mail_message** — one row per inbound email.
| field | type | notes |
|---|---|---|
| id | integer | PK |
| uid | string | IMAP UID (unique, idempotency key) |
| message_id / thread_id | string | RFC headers |
| from_name / from_addr / to_addr | string | |
| subject / snippet / body_text | text | snippet = 280-char preview |
| received_at | string | ISO-8601 UTC |
| has_attachments | integer | 0/1 |
| attachments | JSON | `[{filename, mime, size}]` — contents never read |
| classification | string | `new_order` \| `order_amendment` \| `invoice` \| `remittance` \| `query` \| `other` |
| confidence | integer | 0–100 |
| reasons | JSON | why it was classified this way |
| po_refs | JSON | PO references found in subject/body/filenames |
| matched_orders | JSON | `[{so, po_no, customer}]` matched against live Sales Orders |
| status | string | `new` \| `read` \| `actioned` \| `dismissed` \| `ignored` |

**order_change** — a flagged inbound event awaiting a decision.
| field | type | notes |
|---|---|---|
| id | integer | PK |
| mail_id | integer | → mail_message.id |
| change_type | string | `new_order` \| `order_amendment` \| `invoice` \| `remittance` \| `query` |
| title / summary | string/text | |
| so_name / po_no / customer | string | matched order (if any) |
| severity | string | `critical` \| `warning` \| `info` |
| next_steps | JSON | recommended actions, plain words |
| status | string | `pending` \| `approved` \| `dismissed` |
| result_doctype / result_doc / result_note | string/text | what happened on approval |
| decided_at / decided_by | datetime/string | |

### sync_inbox(limit: int = 50, notify: int = 1) → dict
Fetches **new** mail (IMAP high-water mark; first run reads only the newest `limit`),
classifies it, extracts PO refs, matches against live Sales Orders (by `po_no`), stores
the message, and creates an `order_change` row for order-affecting types.
Sends one notification email to the mailbox owner when `notify=1` and something new was flagged.
Idempotent: re-running fetches 0. The Tower's own notification mail is stored with
`status="ignored"` and never flagged.
```json
{"ok": true, "fetched": 12, "flagged": 3, "notified": true, "notify_error": ""}
```

### get_inbox(classification: str = "", status: str = "", limit: int = 100) → dict
Newest-first list of understood messages (excludes `ignored` unless `status="ignored"`).
```json
{"messages": [{"id": 8, "classification": "new_order", "confidence": 67, "po_refs": ["69785"], "matched_orders": [{"so": "SAL-ORD-2026-00001-1", "po_no": "69785"}]}]}
```

### get_mail_message(mail_id: int) → dict
One message in full (marks it `read`). `{"message": {...}}`

### get_inbox_summary() → dict
Counts for the dashboard header: total, unread, per-classification, pending/critical changes.

### dismiss_mail(mail_id: int) → dict
Marks a message `dismissed`. `{"ok": true}`

### get_order_changes(status: str = "pending") → dict
Flagged inbound items. `{"changes": [{...}]}`

### decide_order_change(change_id: int, decision: str, note: str = "", actor: str = "Ops Manager") → dict
`decision` = `"approve"` | `"dismiss"`. Approving a **new_order** attempts a real,
**drafts-only** ERP write (a draft `Sales Order`) when the customer resolves — nothing is
submitted; the outcome is recorded in `result_note`. Approving other types records the
decision (no ERP write yet). Idempotent for already-decided rows.
Returns `{"ok": true, "change": {...}}`.

---

## Chat Module

### `get_chat_config`
Returns config for SSE streaming: api_path, chat_api_path, user_id, deployment_id, swarm_id, agent_id, token, agent_name, agent_icon.
**Params:** none
**Returns:** ChatConfig dict

### `create_room`
Creates a Kogo user room. Call once before first message.
**Params:** none
**Returns:** `{ room_id }`

### `send_message`
Sends a message via SSE streaming (backend accumulates full reply).
**Params:** message (str, required), thread_id (str, optional), deployment_id (str, optional), swarm_id (str, optional)
**Returns:** `{ created_thread_id, message (cleaned), boatReply, repliedAgent, chat_id, cardContent }`

### `fetch_threads`
Fetches thread list for a room, grouped by dateCategory.
**Params:** room_id (str, required)
**Returns:** `{ threads: [{ _id, title, summary, dateCategory, unread_count }] }`

### `fetch_chat_history`
Fetches full message history for a thread.
**Params:** thread_id (str, required)
**Returns:** `{ chats: [...], thread: {...}, deployment_details: {...} }`

---

# Cortex TnA Calendar (merged module)

The TnA plan/calendar experience ships **inside** the Control Tower. Its backend lives in
`backend/tna_app/` (own SQLite overlay store at `tna_app/data/`, own live-ERP reader, own plan
engine). The functions below are registered in this project's `FUNCTIONS` registry and are
callable through the same middleware endpoint with `"project": "cortex_operations_control_tower"`.

Three TnA names collide with Control Tower functions, so the TnA variants publish under a
`tna_` prefix:

| TnA internal name | Published name |
|---|---|
| `get_audit_log` | `tna_get_audit_log` |
| `run_action` | `tna_run_action` |
| `rollback_action` | `tna_rollback_action` |

The data contract is unchanged from the standalone TnA app — full field-level documentation is in
`backend/tna_app/` and summarised below.

### `get_tna_calendar`
Flagship read. Params: `order_id`, `calendar` (default `VN_FACTORY`), `product_type`, `as_of`,
`force_snapshot`. Returns `{source, generated_at, as_of, header, milestones[61], kpis, exceptions[],
alerts[], calendar, template, data_quality[], warnings[]}`. Reads the ERP live (GET-only) with a
bundled snapshot fallback; every response carries `source: "live" | "snapshot"`.

### `get_tna_orders`
In-scope orders for the picker. Params: `product_type`, `search_query`, `limit`, `offset`,
`force_snapshot`. Returns `{orders[], total, total_count, offset, limit, source, warnings[]}`.

### `get_tna_template`
The product-type plan template (data, not code). Params: `product_type`, `template_id`.
Returns `TnaTemplate` — milestones, categories, owner roles, dependency graph.

### `get_holidays`
Working-day calendar. Param: `calendar` (empty = all). Returns a `HolidayCalendar`
(`calendar, label, country, tz, year, working_weekdays, holidays{}, special_working_days[]`).

### `get_tna_kpis`
Delivery KPI block for one order. Params: `order_id`, `calendar`, `as_of`, `force_snapshot`.

### `update_milestone`
The only write path — edits the **local overlay** (never the ERP), preview-first and reversible.
Params: `order_id`, `code`, `actual_start`, `actual_finish`, `revised_finish`, `delay_reason`,
`owner`, `note`, `status_override`, `apply` (false = preview), `actor`, `as_of`, `calendar`.

### `tna_run_action`
Commit a previously staged TnA action. Params: `action_id`, `as_of`, `calendar`, `force_snapshot`.

### `tna_rollback_action`
Reverse an applied TnA action by restoring its `before_json`. Params: `action_id`, `as_of`,
`calendar`, `force_snapshot`.

### `tna_get_audit_log`
Append-only TnA journal + `action_log` history. Params: `order_id`, `action_id`, `limit`, `offset`.

### `get_tna_alerts`
Ranked, escalated alerts + optional plain-text reminder digest. Params: `order_id`, `as_of`,
`calendar`, `force_snapshot`, `include_digest`.

### `get_tna_owners`
Milestone workload grouped by effective owner / role. Params: `order_id`, `as_of`, `calendar`,
`force_snapshot`.

### `get_tna_program`
Multi-order / capacity view. Params: `as_of`, `horizon_wd`, `limit`, `calendar`, `force_snapshot`,
`detail`, `search_query`. Returns per-order RAG, progress, delays and capacity by ship month.

### `get_tna_intake`
New-order intake queue (notification inbox) enriched from the Cortex Tower bridge.
Params: `status`, `sync`, `force`. Returns `{notifications[], summary, bridge, generated_at, warnings[]}`.

### `approve_tna_order`
The "Approve" click — starts the TnA plan for an order. Params: `order_id`, `actor`, `note`.

### `reject_tna_order`
Dismiss a new-order notification without starting a plan. Params: `order_id`, `actor`, `note`.

### `snooze_tna_order`
Keep a new-order notification for later. Params: `order_id`, `actor`, `note`.

### `get_bridge_status`
Health of the TnA ↔ Cortex Tower link. Returns `{tower_project, tower_configured,
tower_functions[], tower_app_url, tower_jump_enabled, tower_url_source, erp{...}, note}`.

### `set_tower_link`
Save (or clear) the Cortex Tower app URL used by the "Open in Cortex Tower" jump.
Params: `url` (http/https, empty clears), `actor`.

**Safety:** ERP reads are GET-only. TnA writes touch only the local overlay + action/audit logs;
`erp_write` is always false. Preview-first, reversible, no invented data.

---

## Intake — mail → understanding → ERP drafts (2026-11-03)

The Control Tower now reads the company mailbox and **starts the process** the mail implies.
Full design: `docs/INTAKE_PLAN_EMAIL_TO_PROCESS.md`. Everything is draft-only and
human-approved (L1): no function here submits, cancels or amends a posted document.

Pipeline: **fetch → read (PDF/XLSX/CSV) → understand (facts + per-field confidence) →
arithmetic gates → match (buyer/PO/style/fabric/FX) → route → plan → approve → drafts**.

### `sync_inbox`
Fetch new mail from the connected mailbox, **draining it in batches** (the old single call
stopped at `limit` and silently skipped the newest mail), store each attachment's bytes and
extracted text, then open one intake run per document. Params: `limit` (per batch, default 50),
`notify`. Returns `{fetched, flagged, scanned, remaining, batches}`. `erp_write: false`.

### `sync_intake_mail`
(Re-)read ONE already-stored mail: fetch its attachments now and open its intake run. Used for
mail that arrived before intake existed. Params: `mail_id`, `use_llm`.

### `get_intake_queue`
The intake queue, newest first — one card per understood document. Params: `status`
(`understood` | `simulated` | `approved` | `rejected` | `blocked`), `limit`.
Returns `{items[], count}` where each item carries route, document type, summary, missing and
blocking fields.

### `get_intake_summary`
Badge counts: `{total, understood, approved, rejected, blocked, simulated, ready_to_approve}`.

### `get_intake`
One intake in full: the mail, every attachment (with its text preview), the extracted facts with
their confidence, what matched in the ERP, the ordered plan (ready/blocked with reasons), the
stored field edits, and the proposed acknowledgement. Params: `run_id`.

### `understand_intake`
Re-read the document and rebuild the plan — optionally with the model (`use_llm=1`), which is
merged field by field and never overrides the paper without flagging a conflict. Params:
`run_id`, `use_llm`.

### `simulate_intake`
Dry run: returns the exact ERP payloads that approval would create, plus what is blocked and why.
Writes nothing, anywhere. Params: `run_id`.

### `intake_review`
**Step 1 of the human gate (2026-11-07).** Rebuilds the plan against the ERP now, applies the person's
own edits, and returns every step with the exact payload it will write, the blocked steps with their
reasons, the steps not used on this ERP (`status: "skipped"`, e.g. Client Purchase Order), and a
`review_hash`. Writes nothing to the ERP. Requires sign-in.

| Param | Type | Required | Notes |
|---|---|---|---|
| `run_id` | int | yes | the intake run |

Returns: `{ok, run_id, status, route, steps:[{key, seq, label, doctype, status, kind, payload, reason, edited?}], blocked, skipped, missing, warnings, review_hash, options:{currency:[{value,label}]}, buyer:{name, email, customer, candidates}, write_mode, erp_write:false}`

`options.currency` is the site's own enabled currency list (see `get_intake_options`); `buyer` is what
the Customer step was built from, so the sheet can show the gate before anyone approves.

### `get_intake_options`
**Every dropdown in the review sheet reads its choices from here (2026-11-07).** Returns the ERP's
own list — nothing is hard-coded on the frontend, and nothing is cached to disk (currencies are
memoised in-process for 10 minutes). Read-only.

| Param | Type | Required | Notes |
|---|---|---|---|
| `kind` | str | no | `currency` (default) · `customer` · `customer_group` · `territory` |
| `q` | str | no | for `customer`: match on `customer_name` **or** `name`; empty = most recently modified |
| `limit` | int | no | for `customer`: 1–50, default 20 |

Returns: `{ok, kind, count, options:[{value, label, hint?}], live}`. When the ERP cannot be read the
currency list falls back to `DEFAULT_CURRENCY` with `fallback: true` rather than an empty select.

### `intake_plan_edit`
Change one value inside one step of the plan before approval — any scalar, or a row cell such as
`items.0.qty` / `payloads.2.item_name`. Stored per run and re-applied whenever the plan is rebuilt.
`value: null` removes the edit. `doctype`, `name`, `owner`, `docstatus`, `naming_series` cannot be set.
Editing `customer_name` also renames the buyer on the run (`buyer.name`), so the Customer step and the
Opportunity agree — that is the “correct buyer.name, then re-plan” loop without leaving the sheet.
Merchandiser, Management or Admin only.

| Param | Type | Required | Notes |
|---|---|---|---|
| `run_id` | int | yes | |
| `step_key` | str | yes | `customer`, `sales_order`, `style`, … |
| `field` | str | yes | dotted path inside that step's payload |
| `value` | any | yes | the new value (`null` = undo the edit) |

Returns: the same shape as `intake_review` (with a new `review_hash`).

### `approve_intake`
**Step 2 of the human gate.** Creates the ERP drafts exactly as reviewed. Refused (`needs_review: true`)
when `review_hash` is missing or no longer matches the plan, and when any step is blocked unless
`accept_blocked=1` (blocked steps never run). Every create goes through `pipeline.execute` — role
check, field guard, the ERP's business rules run inside the tower (needed while ERP server scripts
are off), audit and journal — unless `INTAKE_WRITE_PATH=direct`. Never submits. Merchandiser,
Management or Admin only; the signed-in person is recorded, a client-supplied `actor` is ignored.

| Param | Type | Required | Notes |
|---|---|---|---|
| `run_id` | int | yes | |
| `review_hash` | str | yes | from `intake_review` / `intake_plan_edit` |
| `accept_blocked` | int | no | `1` = create the rest without the blocked steps |
| `note` | str | no | kept on the run |

Returns: `{ok, status, refs:[{doctype, name, step}], note, customer, sales_order, write_path, run}` or `{ok:false, needs_review:true, review_hash, blocked?, error}`

### `reject_intake`
Reject an intake with a reason (kept as the classifier's training signal). Params: `run_id`,
`reason`, `actor`.

### `edit_intake`
Correct one field before approval (`commercial.rate`, `po.number`, `lines.0.qty`, …), re-run the
arithmetic gates and re-plan. The original value is stored. Params: `run_id`, `field`, `value`,
`actor`.

### `rollback_intake`
Delete what an approval created, newest first (drafts only; posted records are refused by the
ERP and reported as kept). Params: `run_id`, `actor`.

### `create_intake_ack`
Draft the buyer's acknowledgement from the facts through `email_engine` and prove it is grounded
(every number, date and reference traceable to the record). Stored as an `email_draft` for the
existing approval queue — nothing is sent here. Params: `run_id`, `actor`.

### `dismiss_intake`
Hide a run that is not an order at all (kept, never deleted). Params: `run_id`, `actor`.

**Safety:** reads are GET-only. The only ERP writes are in `approve_intake`, they are **drafts**,
they are recorded in `created_refs` for one-click rollback, and every decision is written to the
audit log. A document that cannot be read (a scan) is flagged `needs_ocr` and never guessed.

### `get_intake_document`
The original attachment as an embeddable `data:` URL, fetched on demand (kept out of `get_intake` so a
card stays light). Returns `{ok, filename, mime, data_url}`; `not_embeddable` for a file over 1.5 MB or
a non-PDF. Params: `run_id`.

### `get_buyer_inquiries`
**The buyer-enquiry register** — where an enquiry sits after the intake card is closed. One row per
enquiry: buyer, quantity, the date they want the quote by, every style they named, and for each style
what the ERP already holds — *made before* (with the price we last sold it at and the order it was),
*costed*, *on file*, *new* — read live from `Sales Order` lines, `Cost Sheet`, `Item Price`, `BOM`,
`Buyer Tech Pack` and `Item`. `refresh=1` re-reads the ERP for every row. Reads only; nothing written to
the ERP. Params: `status`, `refresh`.

### `get_buyer_inquiry`
One enquiry in full: the mail, the ask, the target date, and the evidence behind each style's verdict —
last price, order count, last order, cost sheet with its locked FOB, BOM count per size, tech pack
revision, item and size SKUs. A read that failed is returned in that line's `errors` (an unreadable
source is never reported as "none"). Params: `inquiry_id`, `refresh`.

### `update_buyer_inquiry`
Move an enquiry along: `new` → `costing` → `quoted` → `won` | `lost` (or `dismissed`), with a note. The
only place that says where an enquiry stands, so the change is written to `audit_log` with who made it.
Params: `inquiry_id`, `status`, `note`, `actor`.

### `sync_buyer_inquiries`
Import every enquiry the intake has read into the register (idempotent: one row per mail, a follow-up in
the same thread adds to the existing row rather than forking a second one). Params: `refresh`.

### `get_mail_chain`
The whole conversation behind one card: every mail in, every reply out, the runs it produced, the buyer
address, and the headers the next reply will use. A chain is identified by the mail **thread** (the root
Message-ID), never by the subject. Params: `chain_id` or `run_id`. Returns
`{ok, chain, timeline[], runs[], reply_to, reply_subject, reply_headers, in_thread}`.

### `send_chain_reply`
**Answer the buyer from the Tower, inside the buyer's own thread.** The send carries
`In-Reply-To` + `References` for the chain, so the answer comes back to the same chain and never
starts a second Opportunity. Two guardrails: nothing leaves without `confirm=1`, and every number in the
text must come from the chain's records (`enforce_grounding=1`, the default) — `enforce_grounding=0` lets a
human send text the engine cannot source, and the draft is stored with `grounding_ok=0` plus the
unsourced tokens so the record says so. Params: `chain_id` | `run_id`, `subject`, `body`, `confirm`,
`enforce_grounding`, `actor`.

### `ingest_chain_pack`
Read the tech pack / BOM that arrived in the thread into the ERP. Hands the stored file to the phase-A
builder (`build/phaseA/techpack.py` → `Buyer Tech Pack`; then `bom_from_pack.py` → one BOM per size) and
records every name it created on the chain and on the run. Refuses — with the reason — when there is no
file, no Customer, or when the builder is not on disk. Params: `run_id`, `apply`.

### `set_intake_customer`
Answer the buyer gate: link the existing Customer the name reads like (60-85 % match), or declare it a
different company so the approval creates a new one. Rebuilds the plan. Params: `run_id`, `customer`,
`create`, `name` (a typed company name, which rewrites `buyer.name`), `actor`.

### `reopen_intake`
Put an approved run back to `understood` so it can be approved again — **only** when everything it
created was a `Task` (an approval whose ERP steps were all blocked left the deal where it was). Refuses
with `has_erp_records` when a Customer, PO, order or style was made, because a second approval would
double it. Params: `run_id`, `actor`.

---

## Registry — the rest of the callable surface

Every name below is in `FUNCTIONS` and therefore callable through the middleware. They
reached the registry without a section above; the descriptions are their own docstrings,
generated by `build/arch_counts.py --write` (2026-11-04, D-127).

### `decide_order_change`

Approve or dismiss a flagged inbound item.

### `dismiss_mail`

_No docstring yet._

### `get_ai_next_steps`

Generate grounded next-step plans for one risk, or the top `limit` risks.

### `get_erp_preview`

_No docstring yet._

### `get_inbox`

The understood inbox, newest first.

### `get_inbox_summary`

Counts for the dashboard header.

### `get_mail_message`

One inbound message in full; marks it read.

### `get_order_changes`

Flagged inbound items (new orders, amendments, invoices…) awaiting a decision.

### `get_recommendations`

_No docstring yet._

### `get_wip_analytics`

Every non-Gantt WIP chart in one read: stages · ageing · output vs plan · SAM · rejects · completion ·

### `get_wip_thread`

The discussion on one WIP — the `Comment` rows on the ERP record, newest first.

### `rollback_action`

Delete the ERP record this action created and reopen its risk.

### `rollback_order_change`

Undo an approved inbound item: delete everything it created in the ERP and

### `run_monitor`

Scan live risks and push an alert for new/escalated criticals.

### `submit_in_erp`

_No docstring yet._

### `wip_adjust`

Re-baseline: new ship date / plant, every OPEN gate shifted by the delta, actuals untouched.

### `wip_comment`

The discussion: a Comment on the WIP, visible in the Tower and on the ERP form.

### `wip_finalise`

Draft → Planned: the planner accepts the proposed plan. Mode-gated (ERP_WRITE_MODE).

### `wip_reject`

A proposal that will not be planned → Superseded, with the reason on the record.

---

# Arinox layer (2026-11-06) — identity, guarded ERP writes, Tower Script Runtime, sync, inquiries

Every function except `kogo_login`, `kogo_register_users` and `erp_event` needs a signed-in caller (KOGO SSO or app login).
A client-supplied `actor` is ignored: the audited actor is always the verified identity. Writes go through one pipeline
(`pipeline.py`): role → mode gate → field guard → preview → approval → lock → optimistic lock → execute (rule scripts + journal)
→ audit → ERP comment → event ledger. See `CORTEX_TOWER_PLAN.md`.

### `kogo_me`
Who am I? The frontend calls this first.

**Params:** (none)

**Returns:** `{authenticated, registered, email, name, role, is_admin, tower_roles, erp_user, via}`

### `kogo_register_users`
KOGO calls this at install / share. Idempotent. Never called by the frontend.

**Params:** `users: [{email, name, is_admin, role}]`

**Returns:** `{ok, count}`

### `kogo_login`
Manual login for someone opening the app outside KOGO.

**Params:** `email, password`

**Returns:** `{ok, token, name, role, is_admin}` or `{error}`

### `kogo_logout`
End the app session.

**Params:** `_app_token`

**Returns:** `{ok}`

### `kogo_set_password`
Set your own password (min 10 characters).

**Params:** `new_password`

**Returns:** `{ok}` or `{error}`

### `kogo_admin_set_password`
Administrator sets someone's password.

**Params:** `email, new_password`

**Returns:** `{ok}` or `{error}`

### `list_tower_users`
Administrators: users, their tower roles and the roles available.

**Params:** (none)

**Returns:** `{users, all_roles}`

### `set_tower_user`
Administrators: set a user's tower roles, ERP user, or active flag.

**Params:** `email, roles?, erp_user?, active?`

**Returns:** `{ok}` or `{error}`

### `cx_catalog`
The process sidebar for the caller: only the screens their role may read.

**Params:** (none)

**Returns:** `{ok, nav: [{key,label,items:[{key,label,kind,doctype?,report?}]}], me, write_mode}`

### `cx_nav_counts`
Open (draft) counts per document screen, for sidebar badges.

**Params:** (none)

**Returns:** `{ok, counts: {key: n}}`

### `cx_search`
Global search across the main ERP documents the caller may read.

**Params:** `q`

**Returns:** `{ok, results: [{doctype, name}]}`

### `cx_doc_meta`
Form definition of an ERP doctype (fields, child tables, required, read-only), filtered for the caller's role.

**Params:** `doctype`

**Returns:** `{ok, fields, is_submittable, numbered}`

### `cx_doc_list`
A page of an ERP doctype's records with search and status filter.

**Params:** `doctype, search?, page?, page_size?, status?, order_by?`

**Returns:** `{ok, columns, rows, total, page}`

### `cx_doc_get`
One ERP document with its child tables and the action buttons that apply to it.

**Params:** `doctype, name`

**Returns:** `{ok, doc, actions, can_write, can_submit, can_cancel}`

### `cx_link_search`
Autocomplete for a Link field.

**Params:** `doctype, txt`

**Returns:** `{ok, results: [{value, description}]}`

### `cx_write`
THE way a form writes to the ERP: insert | save | submit | cancel | delete. Runs the Arinox rule scripts, enforces roles, locks, approvals and undo. `preview: true` shows what would happen and writes nothing.

**Params:** `op, doctype, name?, data?, modified?, preview?, approval_id?, idem_key?`

**Returns:** `{ok, doc?, preview?, needs_approval?, approval_id?, conflict?, run_id?, undone?, error?}`

### `cx_run_script`
Run one of the Arinox buttons (an API script) through the same guarded pipeline.

**Params:** `method, params?, doctype?, name?, preview?, approval_id?, idem_key?`

**Returns:** same as `cx_write`, plus `result`

### `cx_approvals`
Pending (or all) approvals with the preview of what each would do, and **the ERP page each one belongs to**.

A held write is a decision about an ERP document, so every row also carries `doctype`, `name`, `op`, the document's own
`url` and `decide_in_erp: true`. The screen uses that to send the person to the ERP instead of deciding a business
document inside the tower.

**Params:** `status? = pending | approved | rejected | used | approved-in-erp | rejected-in-erp | all`

**Returns:** `{ok, can_decide, approvals: [{id, requester, approver, class, reason, status, preview, request, doctype,
name, op, url, decide_in_erp, mine, created_at}]}`

### `cx_decide`
Close a held write. Nobody takes their own decision **in the tower**: deciding an ERP document is done in the ERP, and
`in_erp=1` records that it was (`approved-in-erp` / `rejected-in-erp`). Neither path performs a write — the ERP document
is the only thing that changed, through the ERP's own permission check.

**Params:** `approval_id, decision = approve | reject, in_erp? = 0|1`

**Returns:** `{ok, status, approval_id, in_erp}` or, for your own request without `in_erp`,
`{ok: false, error, in_erp_required: true}` naming the document to decide in the ERP.

### `cx_runs`
Recent guarded writes (managers see all, others their own).

**Params:** `limit?`

**Returns:** `{ok, runs}`

### `cx_rollback_run`
Managers: undo a finished run from its journal; what cannot be undone is listed.

**Params:** `run_id`

**Returns:** `{ok, undone, irreversible, failed}`

### `sync_changes`
Poll the ERP for changes made outside the tower and reconcile them. Safe to call often; overlapping calls are skipped.

**Params:** (none)

**Returns:** `{ok, poll, reconcile}`

### `erp_event`
Webhook receiver for the ERP. Authenticated by a shared secret; only enqueues.

**Params:** `secret, doctype, name, event?, modified?, docstatus?`

**Returns:** `{ok, queued}`

### `cx_sync_status`
Sync health: queue depth, watermarks, open breaches.

**Params:** (none)

**Returns:** `{ok, queue, doctypes, breaches_open, webhook_configured}`

### `cx_breaches`
ERP-side changes that break a rule the scripts enforce. Never auto-reverted.

**Params:** `state? = open | resolved | dismissed | all`

**Returns:** `{ok, breaches}`

### `cx_breach_decide`
Managers: dismiss a breach, or start a (risky, approval-gated) cancel of the record.

**Params:** `breach_id, decision = dismiss | cancel, note?`

**Returns:** `{ok}`

### `cx_retry_change`
Managers: retry a change whose reconcile failed.

**Params:** `change_id`

**Returns:** `{ok}`

### `tsr_status`
Administrators: every rule script with runs, failures, average time, and vendor checksum status.

**Params:** (none)

**Returns:** `{ok, rules_off, scripts, vendor}`

### `tsr_set_script`
Administrators: switch one rule script on or off.

**Params:** `name, enabled`

**Returns:** `{ok}`

### `tsr_kill_switch`
Administrators: turn every RULE script off or on (numbering and the ledger engine stay on).

**Params:** `state = off | on | status`

**Returns:** `{ok, rules_off}`

### `cx_connection`
Administrators: is the tower talking to the Arinox ERP? API user, Arinox doctypes present, ERP-side server scripts.

**Params:** (none)

**Returns:** `{ok, base, api_user, arinox_doctypes, server_scripts_on_erp, missing_core_doctypes}`

### `cx_reports`
The Script Reports the caller may run.

**Params:** (none)

**Returns:** `{ok, reports}`

### `cx_report_run`
Run one of the 17 Script Reports through the Tower Script Runtime. Cached 60 s.

**Params:** `name, filters?`

**Returns:** `{ok, columns, rows, truncated, ms}`

### `cx_today`
My queue: approvals, breaches, failed syncs, inquiries waiting, overdue T&A milestones.

**Params:** (none)

**Returns:** `{ok, approvals, breaches, sync_failed, inquiries_waiting, overdue_milestones, erp}`

### `cx_inquiry_analyse`
Read a stored mail and all its attachments (PDF, Excel, Word, zip, forwarded mail, images queued for a person), score its completeness and propose next steps.

**Params:** `mail_id, refresh?`

**Returns:** `{ok, classification, fields, completeness, buyer, revision, links, parts, needs_reading, proposals}`

### `cx_inquiry_queue`
Mails that look like inquiries, with analysis state.

**Params:** (none)

**Returns:** `{ok, mails}`

### `cx_inquiry_step`
Run one proposed step (create customer / Opportunity / Tech Pack) through the guarded pipeline. A later step uses the result of an earlier one.

**Params:** `mail_id, step_id, preview?, approval_id?`

**Returns:** same as `cx_write`

### `cx_inquiry_draft_reply`
Store the 'please send us …' reply as a draft in Outbound Mail. Nothing is sent from here.

**Params:** `mail_id`

**Returns:** `{ok, draft_id}`

## Added 2026-11-07 — demo-readiness fixes

### `kogo_list_users`
The people who can use this app with their tower roles (administrators only). Same data as `list_tower_users`.

Returns: `{users:[{email, name, is_admin, roles, role, erp_user, active}], all_roles}`

### `kogo_add_user`
Give a person access (administrators only).

| Param | Type | Required | Notes |
|---|---|---|---|
| `email` | str | yes | |
| `name` | str | no | |
| `roles` | list[str] | no | any of the tower roles (Merchandiser, Costing, …, Management, Admin) |
| `role` | str | no | a single role, when `roles` is not sent |

Returns: `{ok, email, roles}`

### `kogo_set_user_role`
Replace a person's tower roles (administrators only). Params: `email` (required), `roles` (list) or `role` (str).

Returns: `{ok}`

### `kogo_remove_user`
Switch a person off (their history and audit trail are kept). Administrators only. Params: `email` (required).

Returns: `{ok}`

### `kogo_list_roles`
The tower roles and the record groups each may change. Requires sign-in.

Returns: `{ok, roles:[{name, groups}]}`

### `cx_tna_push_milestone`
Write a T&A calendar edit to the ERP's `TNA Milestone` (through the pipeline) when the order has an
`Order TNA` there; otherwise the calendar's overlay keeps the edit and the answer says so.

| Param | Type | Required | Notes |
|---|---|---|---|
| `order_id` | str | yes | the Sales Order |
| `code` | str | yes | milestone code (matched to `milestone_type`, then to `label`) |
| `label` | str | no | |
| `actual_date` / `revised_date` | str | no | `YYYY-MM-DD` |
| `status` | str | no | mapped to Not Started / In Progress / Done / Late / Not Applicable |
| `remarks` | str | no | |
| `preview` | bool | no | dry run |

Returns: `{ok, erp: "written"|"no_order_tna"|"no_matching_milestone"|"unavailable", milestone?, order_tna?, note?}`

### Changed behaviour (no new parameters)
* `sync_inbox` / `test_mail_settings` / sends: a saved password the current key cannot open now
  answers `error: "password_unreadable"` with a sentence saying to re-enter it (it used to say
  `mailbox_not_configured`). `get_mail_settings` → `settings.password_readable`, `problem`.
* `cx_catalog` adds an **All ERP records** group with every Arinox doctype not already in the menu.
* `cx_search` covers 33 doctypes (was 12), queried in parallel.
* `cx_today` → `health: {mail, rules, write_mode, intake_write_path}`.
* `cx_reports` lists 20 reports (the 3 Query Reports are run through the tower's SQL layer).
* `get_tna_calendar` / `get_tna_orders`: draft Sales Orders are included; actual dates come from the
  Arinox doctypes (Sales Contract, Tech Pack, Sample Approval, PP Meeting, Fabric/Trim/Final
  Inspection, Cut Plan, Packing List) and the ERP's own TNA Milestone rows; with no orders in the ERP
  a bundled order is shown with `source: "sample"` (turn off with `TNA_SAMPLE_WHEN_EMPTY=0`).
* Attachments: `.docx`, `.zip`, forwarded `.eml` are read; `.xls` when `xlrd` is installed.

---

## Workspace — one inbox, deals from inquiry to Sales Order (2026-11-07)

Every function below resolves the signed-in caller first (KOGO SSO or the tower's password session) and answers
`{"ok": false, "error": "..."}` with a sentence for the user when something is refused. ERP writes go through
`pipeline.execute` (role check, field guard, the Arinox business rules run in the tower, journal, audit). Tables:
`deal` (new) and new columns on `mail_message` (`thread_key`, `gm_thrid`, `in_reply_to`, `cc_addr`, `direction`,
`deal_id`, `label`) and `email_draft` (`thread_key`, `deal_id`, `cc`).

### `inbox_threads`
Conversations, newest first. Params: `folder` (`all` | `inquiry` | `orders` | `money` | `questions` | `other` |
`needs_reply` | `archived` | `system`), `q`, `limit`, `offset`. Returns `{ok, threads: [{key, subject, label,
label_name, count, unread, needs_reply, archived, from_name, from_addr, last_at, last_from, snippet, attachments,
deal}], total, counts}`.

### `inbox_thread`
One conversation. Params: `key`. Returns `{ok, key, subject, label, messages: [{id, kind, direction, from_name,
from_addr, to, cc, subject, at, body, fresh, attachments, label, reasons, message_id}], party, deal, inquiry_mail_id,
customer_match}`. Marks the buyer's messages read.

### `inbox_reply`
Send a reply in the conversation. Params: `key`, `body`, `to` (optional, defaults to the buyer), `cc`. The message
carries `Re: <subject>`, `In-Reply-To` (last message) and `References` (the chain), so the buyer's answer returns to
the same thread. Returns `{ok, message_id, to, subject}`.

### `inbox_sync`
Read new mail now: inbox, and Gmail's Sent folder (replies sent from Gmail itself), thread it, and flag deals whose
buyer answered. Returns `{ok, fetched, sent_read, threaded, deal_replies}`.

### `inbox_label`
Correct a conversation's label. Params: `key`, `label` (`inquiry` | `new_order` | `order_amendment` | `invoice` |
`remittance` | `query` | `other`). Returns `{ok, label}`.

### `inbox_link_customer`
Remember the buyer of a conversation as an ERP customer (by their e-mail), so the deal started from it and later mail
from the same address are linked automatically. Params: `key`, `customer`. Returns `{ok, email, customer}`.

### `inbox_archive`
Params: `key`, `archived` (bool). Returns `{ok, archived}`.

### `inbox_attachment`
Params: `attachment_id`. Returns `{ok, filename, mime, data}` (base64, max 12 MB).

### `customer_list`
Params: `q`, `limit`. Returns `{ok, customers: [{name, customer_name, default_currency, territory, customer_group}]}`.

### `customer_create`
Add a Customer to the ERP and a Contact with the buyer's e-mail; optionally link it to a deal. Params:
`customer_name`, `email`, `currency`, `country`, `customer_group`, `territory`, `contact_name`, `deal_id`.
Returns `{ok, customer, contact, existing}`.

### `customer_overview`
Params: `customer`. Returns `{ok, customer, deals, orders, contracts}`.

### `deal_list`
Params: `stage` (`open` or a stage key), `q`. Returns `{ok, deals: [{id, title, stage, stage_label, customer_name,
total_qty, total_value, next, styles}]}`.

### `deal_get`
Params: `deal_id`, `erp` (bool: also read the live status of every ERP document the deal made). Returns
`{ok, deal: {..., styles, refs, events, attention, next, contract_draft}, product_types, erp}`.

### `deal_from_thread`
Start a deal from an inquiry conversation. Params: `key`. Styles, quantities, season, incoterm, dates and each style's
BOM are read from the mail and its sheets. No price is needed. Returns `{ok, deal}`.

### `deal_create`
A deal typed in by hand. Params: `customer`, `title`, `contact_email`. Returns `{ok, deal}`.

### `deal_update`
Params: `deal_id`, `patch` (`title`, `customer`, `currency`, `incoterm`, `destination`, `season`, `ex_factory`,
`in_warehouse`, `notes`, `styles: [{key, style_no, style_name, colour, fabric, qty, sizes, product_type, bom,
target_price, status}]`). Returns `{ok, deal}`.

### `deal_erp_setup`
Check and fix the ERP master data the Arinox scripts need. Two things stopped the chain on this site: **Product Type** rows
with no Item Group (so the style Item could not be made - "Set an Item Group on Product Type X or a Style Item Group in
Apparel Settings") and **Apparel Settings** pointing at the previous company's warehouses ("Could not find Finished Goods
Warehouse …"). Both are filled from records that already exist - a missing warehouse is made under the company's own
abbreviation, the Item Group is taken from the ERP's own Item Groups - and anything that cannot be fixed mechanically is
returned in `unresolved` rather than invented. Params: `deal_id` (optional, for the audit trail).
Returns `{ok, created, set, unresolved, item_groups}`. The tower also runs this automatically, once, when a write fails
with "could not find".

### `deal_documents`
What the deal's conversation actually carries, file by file: `{ok, documents: [{attachment_id, filename, mime, size_mb,
readable, parsed, error}]}`. `readable` means the bytes are on disk, `parsed` means a reader opened it, and `error` says
why not when either is false (too large for the mailbox limit, a scan with no text layer, a format nothing here opens).
Params: `deal_id`.

### `deal_read_documents`
Read **every** document on the deal's conversation again - the buyer's Tech Pack (specification: measurement chart,
construction/cutting notes, wash & care, packing) and the buyer's BOM (materials and how much per garment). Each
attachment is given to the model, which says what kind of document it is, and the two halves land where they belong:
the BOM lines on the style's Buyer BOM, the specification on the style (and on its Tech Pack when the inquiry is sent
to the ERP). Use it when a document arrived late, or when a mail was stored before it could be read. Params: `deal_id`.
Returns `{ok, documents, skipped, bom_lines, spec_styles, deal}`. A document that cannot be read is reported with the
reason, never dropped silently.

### `deal_bom_upload`
Read an uploaded BOM sheet into one style of the deal. Excel (.xlsx/.xls/.xlsm) and CSV/TSV; the sheet is read by
the same reader that parses the buyer's mail attachment, and the header block (Style / Colour / Fabric) fills the
style when those fields are empty. Params: `deal_id`, `style_key`, `filename`, `data` (base64, a `data:` URL is
accepted). Returns `{ok, deal, bom: {rows, source, warnings, style_detected}}`. Refused when the style is already a
Tech Pack in the ERP (edit materials in the Cost Sheet there).

### `deal_bom_from_mail`
Same, from one of the deal's own mail attachments instead of an upload. Params: `deal_id`, `style_key`,
`attachment_id`. Returns `{ok, deal, bom}`.

### `deal_bom_from_erp`
Same, from the BOM the ERP already holds for the style's Item (its default active submitted BOM, quantities divided
by the BOM batch size so they stay per garment). Params: `deal_id`, `style_key`. Returns `{ok, deal, bom}`. Says
which of the two is missing when it cannot: no Item for the style, or no active BOM for that Item.

### `deal_bom_ai`
Read the uploaded BOM sheet with the KOGO model instead of the fixed column map, and put the rows on the style.
This is the door for a buyer layout the deterministic reader does not know: the sheet goes to the model as plain
text (row by row, no interpretation), and the model is asked for JSON only. Its answer is validated before it is
used (only the nine material types, quantities as numbers, nothing invented, no totals rows), and a line the model
could not fill stays empty with a warning. Needs the signed-in KOGO session. Params: `deal_id`, `style_key`,
`filename`, `data` (base64 or a `data:` URL). Returns `{ok, deal, bom: {rows, source, warnings, erp}}`.

### `deal_bom_paste`
Rows typed in, or the model's JSON pasted from any chat window (ChatGPT, Claude, this agent). `rows` is a list of
line objects or a string holding JSON; accepted keys per line: `item_code`, `material_type`, `description`,
`colour`, `uom`, `consumption`, `rate`, `remarks`, `placement`. Params: `deal_id`, `style_key`, `rows`, `source`.
Returns `{ok, deal, bom}`.

### `deal_bom_apply`
Send the style's BOM lines to the ER: the Tech Pack's material rows, then a rebuilt draft Cost Sheet (the ERP copies
materials only when it makes the sheet, so a draft made before the BOM existed is replaced, not patched). A submitted
Cost Sheet or Tech Pack is never touched - the answer names the document to amend. Params: `deal_id`, `style_key`.
Returns `{ok, deal, erp: [sentences]}`.

### `deal_bom_sources`
What could feed a BOM on this deal: the spreadsheet attachments of its mail. Params: `deal_id`.
Returns `{ok, attachments: [{id, filename, mail_id, size}]}`.

### `deal_register`
Send the inquiry to the ERP: an Opportunity, and per style a Tech Pack with the buyer's BOM, colours and sizes (and the
style Item). Idempotent. Params: `deal_id`. Returns `{ok, deal}`.

### `deal_cost_open`
Open or start one style's Cost Sheet (`arinox_tech_pack_make_cost_sheet`). Params: `deal_id`, `style_key`.
Returns `{ok, cost_sheet: {name, docstatus, totals, materials, charges}, heads, style}`.

### `deal_cost_save`
Params: `deal_id`, `style_key`, `materials`, `charges`, `quoted_price`, `extra`, `preview`. The ERP's Cost Sheet rules
compute the price; `preview: true` computes without saving. Returns `{ok, cost_sheet, messages, saved}`.

### `cost_sheet_list`
Every style of every deal with its **costing sheet**, for the Costing page. One row per style (dropped styles left out):
the deal, buyer and stage, the style number and description, the quantity, and - if the style has a sheet already - its
FOB per piece, order value, when it was last touched, and whether the prices were transferred to the ERP Cost Sheet.
A style with no sheet yet is listed too, so it can be started from the page. Params: none. Returns `{ok, sheets}`.

### `deal_cost_sheet`
The style's **costing sheet** - a document this app owns, not a file it borrows. It is the factory's own template,
**APPAREL_COSTING_DETAILED_REVISED.xlsx** (sheet `DETAILED COSTING`), line for line: the header block (style, buyer,
season, factory, order qty, FOB port, currency, version, pcs per carton, VND per USD, the four sign-off boxes), 18 raw
material rows including the fabric export and import cost per metre, 5 processing charges with APPLY 1/0, 6 percentage
expenses, and profit. It is created from that template the first time the sheet is opened - material lines filled from the
buyer's BOM when one arrived, any BOM material the template has no row for added by name, the order quantity taken from
the style - so there is never an empty page, and anything else can still be added by hand. Stored in the app's own tables
(`costing_sheet`, `costing_line`) per style, and the totals are always recomputed by the sheet's rules. Params:
`deal_id`, `style_key`. Returns `{ok, sheet, lines, totals, deal}`.

### `deal_cost_sheet_save`
Save what a person typed into the costing sheet and return the recomputed totals. `lines` is the whole sheet as shown (a
line left out is deleted); each line carries `id` when it already exists. Nothing is written to the ERP by this call.
Params: `deal_id`, `style_key`, `header` (`order_qty`, `pcs_per_carton`, `profit_pct`, `currency`, `fob_port`, `version`,
`note`, `buyer`, `season`, `factory`, `costing_date`, `vnd_per_usd`, `signoffs`), `lines` (each line carries `tpl` for a
template row and `rule` when the sheet works its usage out, `per_carton` or `fabric_metres`). Returns
`{ok, sheet, lines, totals, deal}`.

### `deal_cost_sheet_calc`
Recalculate the costing sheet without saving anything: `{ok, totals, lines}`. Same rules as the save, exactly the
workbook's arithmetic - usage × (1 + wastage) × rate per material, the fabric export / import lines priced on the total
**fabric metres** including wastage, a carton at one per `pcs_per_carton`, percentages on the product cost, profit on the
total cost, FOB per piece in USD and in local currency (`vnd_per_usd`), and the order value. Pass `header` and `lines` to
add up the sheet **as it is on screen**, before it is saved - what the Costing page calls while a rate is being typed.
Params: `deal_id`, `style_key`, optional `header`, `lines`. Nothing is written to the database by this call.

### `deal_cost_sheet_transfer`
Transfer the costing sheet's prices into the ERP Cost Sheet as a **draft**: materials matched by name (or all replaced,
with `replace`), charges matched by the ERP's own `Cost Head` (the fabric export / import cost travels as a charge there,
because in the ERP it is a head priced per metre of fabric), the sheet's FOB as the quoted price, and the ERP's rules
recomputing the price. A submitted Cost Sheet is refused with a reason - amend it in the ERP. Params: `deal_id`,
`style_key`, `replace`. Returns `{ok, applied, cost_sheet, sheet, totals, messages, deal}`.

### `deal_cost_read`
Read a **pre-made costing sheet** - the merchandiser's own spreadsheet with USAGE / WASTAGE / RATE, the processing
charges (CMT, washing, printing, testing), the percentages (rejection, financing, banking, freight, overheads) and the
FOB - and record it on the style so it can be looked at and then applied. The sheet is read by the model, which is given
the ERP's own `Cost Head` list so each charge line is mapped to a real head; every number it returns is validated, and a
line it cannot map is reported instead of being dropped. **Nothing is written to the ERP by this call.**
Params: `deal_id`, `style_key`, plus either `filename` + `data` (base64, a `data:` URL is accepted) or `attachment_id`
(one of the mail's own files). Returns `{ok, cost_doc: {header, materials, charges, totals, unmapped_charges, source},
deal}`.

### `deal_cost_apply_prices`
**One click: the cost goes onto the BOM items.** The costing sheet keeps *what item* and *what price* (the price book,
table `item_price`, filled as prices are typed on the sheet or when a sheet somebody sent is imported). This walks the
style's Cost Sheet - its material rows **are** the BOM items that came in with the inquiry - and writes each item's price
onto it, by item code first and by description second. Nothing else is touched: consumption, wastage, charges and the
quoted price stay as they are, and the Cost Sheet stays a **draft** so a person can change it in the ERP afterwards. A
submitted sheet is refused with a reason. Params: `deal_id`, `style_key`. Returns
`{ok, items, priced, updated, missing, written, cost_sheet, messages}`.

### `deal_cost_autofill`
**The one that fills the ERP cost sheet from the standard costing.** The ERP refuses to submit a costing that leaves a
mandatory cost head at 0 without N/A ticked, and every figure it wants is already on the app's own sheet (the workbook:
a rate on every line, CMT 5.000, rejection 3 %, and APPLY 0 on the lines the factory does not use). This walks the Cost
Sheet - material rows that came from the Buyer BOM, and the cost heads - and puts them there:

* a material line with **no price** takes the price of the sheet line carrying the same item (by item code first, then by
description), then the app's price book; a wastage that comes with it brings its reason, because the ERP refuses a
wastage % without one;
* a cost head at 0 takes the sheet's figure for that head (a processing rate per piece, a percentage for the expense
heads) and the sheet's APPLY column becomes the ERP's **N/A** tick - APPLY 0 means N/A, so washing, printing,
embroidery and testing do not block the submit, and a head priced at 0 % is N/A too;
* a head the sheet does not cost at all (this site's **Depreciation**) is reported in `unmatched`, never guessed;
* **nothing else is touched**: no consumption, no submit. The Cost Sheet stays a **draft**. The **quoted price** stays as
a person chose it and follows the computed price only while it was never chosen (0, or equal to what the ERP worked out
last time), so filling a line never leaves a fresh costing showing "below the margin floor". Only blanks are filled and
an N/A a person ticked is never cleared, so it is safe to run again. A submitted sheet is left as it is and says so. It
is **not** run on its own: the Cost sheet tab of the Costing page has one button for it, *Fill from the costing sheet*.

Params: `deal_id`, `style_key`. Returns
`{ok, materials, heads, priced, na, missing, unmatched, quoted, written, cost_sheet, heads_list, messages}`.

### `cost_prices`
The app's **price book**: what each item costs, newest first, so the price of an item is there to see (and to reuse when
the same item turns up on another style's BOM). Params: `q` (a word to search), `limit`. Returns `{ok, prices}`.

### `deal_cost_apply`
Apply the **recorded** costing sheet to the ERP Cost Sheet: material lines are matched by description (an existing line is
updated, a new one is added), charges are matched by `Cost Head` (a line the sheet turns off is marked N/A), the sheet's
FOB becomes the quoted price, and the ERP's own rules recompute the price. The Cost Sheet stays a **draft** - it is never
submitted here, and every value remains editable in the costing screen afterwards. A submitted Cost Sheet is refused
with a reason. Params: `deal_id`, `style_key`, `replace` (start the material lines from the sheet instead of matching
them). Returns `{ok, applied: {materials_updated, materials_added, charges_set, quoted_price, unmapped}, cost_sheet,
messages, deal}`.

### `deal_cost_submit`
Params: `deal_id`, `style_key`. Submits the Cost Sheet (the ERP checks mandatory cost heads and the margin floor).
Returns `{ok, style, deal}`.

### `deal_quote_draft`
Params: `deal_id`. Returns `{ok, to, body, styles}` — the quote e-mail text from the submitted costings.

### `deal_quote_send`
Params: `deal_id`, `body`, `to`, `cc`, `subject`. Adds each costing to the Price Negotiation (our opening offer) and
sends the quote in the deal's thread. Returns `{ok, sent, deal}`.

### `deal_record_reply`
The buyer's answer → Price Negotiation rounds. Params: `deal_id`, `outcome` (`counter` | `our_counter` | `accepted` |
`drop` | `lost`), `prices: {style_key: price}`, `note`, `channel`, `lost_reason`. Returns `{ok, deal}`.

### `deal_contract_prepare`
Params: `deal_id`. Makes and submits the Quotation at the agreed prices, then the Sales Contract draft
(`arinox_sales_contract_make_sales_contract`), filled with the deal's dates and quantities. Returns
`{ok, draft, readiness, deal}`; `readiness` lists what the ERP will ask before signing.

### `deal_contract_form`
The contract draft plus the **ERP's own field list** for the contract form: every Sales Contract field the tower writes,
with its type, label, section and - for a Select - the ERP's choices, and the records that exist for a Link field
(`Incoterm`, `Payment terms template`, `Contract template`, `Clauses`). The form is rendered from this, so a value the ERP
does not know cannot be typed into it. Params: `deal_id`, `refresh` (re-read the contract from the ERP first, so a
change made there shows up here). Returns `{ok, draft, readiness, fields, options}`.
It also answers **which trade term to pick**: `incoterm_help` is the ERP's eleven Incoterms in plain words (what each
obliges, where risk passes, who pays freight/insurance/duty), and `trade_notes` names any mismatch between the chosen
term and the contract's own `shipment_mode` / `freight_by` / `insurance_by` / `named_place` lines.
Returns `{ok, draft, readiness, fields, options, incoterm_help, trade_notes}`.

### `deal_contract_update`
Save the contract draft: `params` `deal_id`, `draft` (header terms, `items[i]` dates/qty/colour, `sizes[i].qty`). A value
on a Link field that is not a record in the ERP (a typed-in Incoterm, say) is refused **here**, with the values that do
exist, instead of failing later when the contract is written. Returns `{ok, draft, readiness, fields, options}`.

### `deal_contract_create`
Write the contract into the ERP: `params` `deal_id`, `sign` (bool). Every term in the draft goes in, the Link values are
checked first, and afterwards the tower **re-reads the Sales Contract from the ERP** into the draft, so what the deal shows
is exactly what the ERP holds. `sign` submits it. Returns `{ok, deal}`.

### `deal_make_order`
Params: `deal_id`. The Sales Order draft from the signed contract (`arinox_sales_contract_make_sales_order`).
Returns `{ok, deal}`.

### `deal_track`
Params: `deal_id`. The whole shipping picture of a deal, derived from what is on file and nothing else:

* **The four clocks** — ex-factory (the latest line), ETD (the line's own, or ex-factory + `days_ex_factory_to_etd`),
  ETA (ETD + `transit_days`), in-warehouse, and the **payment due date** worked out from `payment_basis` +
  `payment_days` (ROG counts from the warehouse date, B/L from ETD…). Each row carries `state`
  (`late`/`today`/`soon`/`pending`/`unknown`), `days_left` and the `basis` it came from. A date that is not on the
  contract is `unknown` with `basis: "no date on the contract"` — never invented.
* **`documents`** — the papers the contract's `documents_list` names ("Invoice, Packing List, FCR or MAWB" reads as
  four papers), each with who produces it (`us` / `carrier` / `authority`), the day it is needed (ETD, or 3 days before
  for certificates) and whether it has been handed over.
* **`shipments` / `shipment`** — the ERP's Shipment rows that name this contract, read field by field: forwarder,
  booking, cut-off, POL/POD, vessel-voyage, ETD/ETA, on-board, arrival, delivery, HBL/MBL/AWB, carrier, tracking link
  and status, weight/volume, containers, documents.
* **`alerts`** — the trade term against the contract's own freight/insurance/mode lines (FOB on an air shipment, DAP
  with the buyer paying freight, blank insurance, no named place), the dates against each other (an ETD that ignores
  the lead time, goods arriving after they are in the warehouse), a late paper, and a shipment behind the contract.
* **`incoterm` / `incoterm_help`** — the term on this contract in plain words (meaning, where risk passes, who pays
  freight/insurance/duty), and all eleven of the ERP's terms the same way.

Returns `{ok, schedule, documents, documents_done, documents_total, shipments, shipment, alerts, incoterm,
incoterm_code, incoterm_help, mode, signed, contract, sales_order, erp_error, today}`. With the ERP down the plan is
still built from the contract and `erp_error` says why the shipment facts are missing.

### `deal_track_doc`
Params: `deal_id`, `doc` (a row's `id` from `deal_track`), `given` (1/0), `on` (YYYY-MM-DD, default today), `note`.
Marks a paper the contract names as handed to the buyer — the one fact the ERP has no field for. A paper the contract
**does not** name is refused, so a typo cannot invent one. Writes an event on the deal with the date and the person.
Returns the fresh `deal_track` payload.

### `deal_track_shipment`
Params: `deal_id`, `values` (`carrier`, `awb_number`, `tracking_url`, `tracking_status`, `tracking_status_info`,
`apparel_forwarder`, `apparel_booking_no`, `apparel_booking_date`, `apparel_cutoff`, `apparel_etd`, `apparel_eta`,
`apparel_on_board_date`, `apparel_arrival_date`, `apparel_vessel_voyage`, `apparel_hbl_no`, `apparel_mbl_no`).
Writes the tracking facts to the ERP's own **Shipment** (guardrailed, audit-journalled) and never to a copy. When the
ERP has no shipment for this contract yet it refuses in words that say what comes first (a Shipment in this ERP hangs
off a Delivery Note), instead of inventing one. Returns the fresh `deal_track` payload.

### `deal_dashboard`
Pipeline by stage (count, qty, value), win rate, quotes waiting on the buyer, deals waiting on us, inquiries ageing,
top customers, inbox counts, and live ERP figures (open orders and value, due in 30 days, orders by month,
receivables). Returns `{ok, stages, open, open_value, win_rate, waiting_on_buyer, needs_us, aging, top_customers,
inbox, erp}`.

### `order_get`
One Sales Order's whole post-order picture, read only (the Order page, ORDER_TO_SHIP_PLAN sections 3 and 4). Reads every
follow-on document of the order in a few batched ERP reads and returns the header (buyer, contract, qty, value, ex-factory,
days to ex-factory, overall RAG), ten steps (`confirm`, `allocate`, `tna`, `samples`, `materials`, `cutsew`, `subcontract`,
`pack`, `ship`, `invoice`) each with a state (`todo|doing|done|blocked|na`), counts, its documents (name, status, style,
colour, ERP link, history flag), blockers in plain sentences and the next action, plus each step's own ERP page
(`by_step`), the page the order is on now (`focus`), the most urgent next action (`next`) and KPIs. An amended order
(`-1`) is followed: documents of an earlier amendment are shown as history and never counted. Steps the caller's role may not
read come back with `restricted: true` and no contents. When the ERP cannot be reached the answer is
`{ok: false, stale: true, error}`. Params: `sales_order`. Returns `{ok, sales_order, head, chain, steps, by_step, focus, next,
kpis, header, timeline, errors, erp_profile}`. `timeline` is the ERP comments on the order plus the tower's audit lines
that name it, newest first.

### `order_list`
The order book: submitted Sales Orders (open ones unless `open_only` is false) with one chip per step, newest first. One
batched read of follow-on counts, not one read per order. Params: `q` (order name or customer), `limit`, `open_only`.
Returns `{ok, orders:[{name, customer, customer_name, delivery_date, grand_total, currency, status, url, chips}], erp_profile}`;
`erp_profile` is `arinox` when the Arinox layer is on the ERP (the old Cortex evidence screens then leave the sidebar) and
`cortex_evidence` otherwise.

### `order_allocation_get`
Everything the allocation board (step 2, "Plan and allocate") shows for one Sales Order, read only: the order's style x colour
lines with quantity and ex-factory date, the factories with their lines (headcount and line type from the Workstation fields),
the pieces already booked on each line in the next eight weeks, the allocation already saved, the **suggestion**, and a setup
checklist (no factory, no line, no operators, no SAM) with the ERP page that fixes each item. The suggestion is deterministic: the
same order and the same ERP data give the same draft. Capacity per line per day is headcount x working minutes x efficiency /
total SAM x the learning-curve percent of the day; the SAM comes from the style's active Operation Bulletin, else the Product
Type default in Apparel Settings, else the line is reported as capacity unknown and nothing is placed on it. Every row carries a
reason sentence; what cannot fit is a shortfall with the earliest feasible ex-factory date. Planners and managers only. Params:
`sales_order`, `suggest` (default true). Returns `{ok, order_lines, factories, load_strip, current, suggestion:{lines, shortfalls,
unknown_lines, notes, setup}, setup, settings}`.

### `order_alloc_suggest_defaults`
"Suggest from my history", read only, writes nothing. Proposes a SAM and efficiency per Product Type from the tenant's own active
Operation Bulletins (median, with sample counts) plus one tenant-wide measured efficiency from submitted Daily Line Reports. With no
history it returns empty lists and `empty: true` (the board says "nothing to suggest yet"). Planners and managers. No params.
Returns `{ok, suggestions:[{product_type, sewing_sam, sam_samples, efficiency_pct, efficiency_samples, source}], measured_efficiency, writes:false, empty, note}`.

### `order_allocation_save`
Save the allocation of an order through the ERP's own script `arinox_factory_allocation_save_allocation`, so the ERP's validation
runs (order submitted, each row a style x colour of the order, line belongs to its factory, dates in order, nothing above the
order plus tolerance). With `preview` true nothing is saved and the ERP's answer or refusal comes back: that is the live
validation shown before save. `planned_by` is `AI Agent` when the suggestion was saved untouched, otherwise `Manual`;
`agent_notes` keeps the reasoning. Zero-quantity rows are dropped, never sent. Planners and managers only. Params: `sales_order`,
`lines`, `planned_by`, `agent_notes`, `preview`. Returns `{ok, name, saved, planned_by}` or `{ok: false, error}`.

### `order_tna_get`
The T&A of one order, per style x colour (read only). Every milestone of the 63-task plan (the tower's 61 milestones plus FABRIC_ETD
and PCD) with its three date lanes (baseline = planned, forecast, actual), float, status (On track, At risk, Overdue, Not recorded,
Done, Not Applicable), the document that proves it, and the plan's ship feasibility as a number of working days with the milestone
that drives it. Also the baselines (versions kept forever) and the revisions after a lock. When the ERP has no Order TNA yet the plan
is a proposal computed from the allocation's PCD and the order's ex-factory date and nothing is written. Calendars are seven-day with
no holidays (decision D5); holidays stay data. Params: `sales_order`. Returns `{ok, proposed, head, plans:[{order_tna, style_no,
colour, ex_factory, locked, rows, summary:{feasible, plan_feasible, ship_miss_wd, plan_infeasible_by_wd, message, driver}, baselines,
revisions}]}`.

### `order_tna_make`
Make the T&A of the order in the ERP (the ERP's own planner script makes the Order TNA per style x colour x ex-factory date) and write
the tower's computed dates onto it with one call per plan (`arinox_tna_apply_plan`), so the ERP desk and the tower show the same plan.
Idempotent; a locked plan is never touched here. With `preview` nothing is written. Roles: planner, sampling, merchandiser, manager.
Params: `sales_order`, `preview`. Returns `{ok, made, written, preview}`.

### `order_tna_lock`
Lock the baseline of one Order TNA: refused when the plan is infeasible (the answer says by how many working days) or not fully written
to the ERP; otherwise the snapshot is stored (version 1, 2, ...) and the ERP's lock script runs. Params: `sales_order`, `order_tna`.
Returns `{ok, version}`.

### `order_tna_revise`
Move one milestone on a locked plan (the revised date). Needs a reason code (Buyer, Supplier, Factory, Logistics or Other, the ERP's own
five) and a note; a move that changes the forecast ship date needs a merchandising manager (`need_approval` otherwise). The baseline
never moves; every revision is kept with who, why and the ship impact. Params: `sales_order`, `order_tna`, `code`, `new_date`,
`reason_code`, `note`. Returns `{ok, ship_before, ship_after}`.

### `order_tna_health`
The evidence health check: for each Arinox document type the T&A reads (30 rules over 20 types), whether it exists on the ERP and how many
documents it has, and the contract test of every field the rules read. Returns `{ok, sources, missing, empty, contract, rules}`.

## Order page, steps 4 and 5 (samples and PP, materials)

### `order_samples_get`
Everything the step-4 page shows for one order: the **approval matrix** (sample type x style/colour; each cell is the status of the approval, its
rounds, or Missing when the rule requires it and none is raised), the **bulk gate card** per style/colour (green when the ERP's own gate script
reports no blockers, else red with the missing items in plain sentences) and the PP meetings with their attendance and open actions. Read only. The
rules come from the ERP (`arinox_sample_approval_get_sample_rules`). Params: `sales_order`. Returns `{ok, head, types, rows:[{style_item, colour, qty,
cells, gate}], meetings, summary}`.

### `order_samples_create`
Create the Sample Approvals the order needs from the ERP's rules: one per style and colour for a per-colour type (Lab Dip, Bulk Fabric), one per
style for the others, only for types the rule marks Required (plus any in `types`, for If Raised ones) and only where none exists yet, so it can be
run again safely. Each is inserted through the pipeline; the ERP sets the due date from the rule. With `preview` nothing is written and the ERP's
own preview of each document comes back. Params: `sales_order`, `types`, `preview`. Returns `{ok, made:[names], planned:[{sample_type, style_item,
colour}], skipped, previews}`.

### `order_sample_round`
Record a round on a Sample Approval: sent to the buyer (decision Pending) or the buyer's decision. A Pending last round is decided in place;
otherwise a new round is added. Approved with Comments, Rejected and Resubmit need the buyer's comment (the ERP refuses without). `in_bulk_fabric`
marks a PP sample made in bulk fabric (the ERP will not approve a PP sample otherwise). Params: `sales_order`, `sample_approval`, `decision`,
`sent_on`, `decision_on`, `comment`, `category`, `relevant_to_cutting`, `in_bulk_fabric`, `tested_after_wash`, `remarks`, `preview`. Returns
`{ok, name, round_no}` or `{ok: false, error}`.

### `order_sample_load`
Fill a Sample Approval's table from the ERP's own scripts: `what` = `spec` (the Tech Pack measurements for `sample_size`,
`arinox_sample_approval_load_spec_from_tech_pack`) or `tests` (the standard test list from Apparel Settings,
`arinox_sample_approval_load_standard_tests`). The rows come back from the script and are saved through the pipeline. Params: `sales_order`,
`sample_approval`, `what`, `sample_size`, `preview`. Returns `{ok, count}`.

### `order_pp_meeting_make`
Make the PP meeting of one style as a draft: the PP sample is the style's approved PP approval, the attendance list has a row for every required
department (`arinox_pp_meeting_add_standard_participants`; `attended` lists the departments that came), fabric and trim readiness per colour come from
the requisitions (`arinox_pp_meeting_load_from_requisitions`) and every open buyer comment is an action row (`arinox_pp_meeting_get_buyer_comments`).
The meeting is held after the production card is issued (`card_issued_on`). It is not submitted here. Params: `sales_order`, `style_item`, `attended`,
`card_issued_on`, `meeting_date`, `preview`. Returns `{ok, name, actions, colours}`.

### `order_pp_meeting_actions`
Fill a draft PP meeting: for each action row the action taken, its owner (a user) and a target date (`actions` = `[{idx, action_taken, action_owner,
target_date}]`), and the departments that attended. A row with no change is left alone. The ERP checks everything again at submit. Params: `name`,
`actions`, `attended`, `card_issued_on`, `preview`. Returns `{ok, name}`.

### `order_pp_meeting_submit`
Submit a PP meeting (the ERP checks: the PP sample is buyer approved, every required department attended, every buyer comment is an action with an
owner and a date, and the production card date). Submitting it is the last condition of the bulk gate. Params: `name`, `preview`. Returns `{ok, name}`.

### `order_materials_get`
The material status table of one order, from the ERP's **Material Status** report (so its status words are the ERP's): per requisition line what is
required, ordered, received, passed (accepted by inspection) and short, with the ETA set against the PCD, and a summary (all passed, any late). Also
which styles have no requisition yet, the requisitions with what can be done next, and the receipt rows with their inspection. Read only. Params: `sales_order`. Returns `{ok, head, rows, summary, no_requisition, requisitions, receipts}`.

### `order_req_lines`
The requisition lines the ERP proposes for the order (one per style x colour x material of the Tech Pack, quantities from the Sales Order), through
`arinox_fabric_requisition_get_lines_from_sales_orders` or the trim equivalent. Read only: nothing is saved until `order_req_save`. Params:
`sales_order`, `kind` (fabric or trim). Returns `{ok, kind, customer, company, items}`.

### `order_items_create`
Make the ERP items (the style of fabric or trim and its colour variant) for the rows that have none, through
`arinox_fabric_requisition_create_fabric_items` / `arinox_trim_requisition_create_trim_items`. Returns the rows with their item codes. Params: `kind`, `items`, `preview`.

### `order_req_save`
Save a DRAFT requisition through the ERP's script (`arinox_fabric_requisition_save_fabric_requisition` / trim): its validation runs (width, GSM, the
source of the consumption, the supplier, the allowance). Rows with no garment quantity are never sent. Never submits (see `order_req_approve`).
Params: `sales_order`, `kind`, `items`, `name` (to update a draft), `preview`. Returns `{ok, name}`.

### `order_req_approve`
Approve (submit) a requisition. The ERP then makes the Material Requests that the purchase orders are made from. Purchase role or a manager.
Params: `kind`, `name`, `preview`. Returns `{ok, name}`.

### `order_req_revise`
Revise an approved requisition: the ERP makes a new draft revision (quantities refreshed from the order; only the increase is requested again when it
is submitted). A reason is required. Params: `kind`, `name`, `reason`, `preview`. Returns `{ok, name}`.

### `order_po_make`
Make draft Purchase Orders from an approved requisition, one per supplier, for the lines not yet ordered (`arinox_purchase_order_make_purchase_orders`).
This is a risky class: the answer is `needs_approval` with an `approval_id` until a manager approves it; run it again with that `approval_id`. Params:
`kind`, `name`, `preview`, `approval_id`. Returns `{ok, made:[PO names]}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_rolls_import`
Import a roll list into one row of a DRAFT Purchase Receipt (`arinox_rolls_import_roll_list`): one batch per roll and the bundle. `rolls` is a list of
`{roll_no, dye_lot, length, width_cm}` or pasted text (`roll no, dye lot, length` per line). The roll total must equal the row quantity unless
`update_row_qty`. Params: `purchase_receipt`, `row_name`, `rolls`, `length_uom`, `update_row_qty`, `preview`. Returns `{ok, rolls, total}`.

### `order_inspection_make`
Make the inspection of one received Purchase Receipt row: the ERP's script builds it (a fabric one comes with a line per roll), then it is saved as a
draft through the pipeline. The Purchase Receipt must be submitted. Params: `kind`, `purchase_receipt`, `purchase_receipt_item`, `preview`. Returns `{ok, name}`.

### `order_inspection_submit`
Submit a drafted inspection: the ERP works out the lot result and moves the accepted quantity to store (and the rejected to the rejected warehouse).
After a real submit the requisition's passed quantity is recomputed (`arinox_fabric_requisition_refresh_quantities`), because the
ERP's after-submit rule computes it on a read made before the submit; `warnings` carries anything the ERP said that needs setup. Role: QC or a manager.
Params: `kind`, `name`, `preview`. Returns `{ok, name, refreshed, warnings}`.

### `order_cutsew_get`
Everything the step-6 page shows for one order: the **production matrix** (stage cut / line input / sewn / QC pass / finished / packed x colour x size,
from the ERP's `arinox_production_card_get_summary`, with the percentage of the order and what was posted today), the production cards with what can be
done next, the cut plans (suggest rolls / release / approve / reopen), the operation bulletins of the styles and the recent line reports. Read only.
Params: `sales_order`. Returns `{ok, head, matrix, cards, cut_plans, bulletins, reports, summary, can_write}`.

### `order_card_context`
What a new Production Card needs, from the ERP (`arinox_production_card_get_production_context` and `_get_card_lines`): the styles of the order, the
colour x size lines with the order quantity, the allocation (factory, line, PCD) and the defaults (extra cut %, bundle size). Read only.
Params: `sales_order`, `style_item` (optional: only that style). Returns `{ok, head, customer, company, styles:[{style_item, lines, ex_factory_date, allocation, card}], defaults}`.

### `order_card_save`
Save a DRAFT Production Card through the ERP's script (`arinox_production_card_save_production_card`): its validation runs. Lines with no order
quantity are never sent. Never submits (see `order_card_approve`). Params: `sales_order`, `style_item`, `header` (factory, line, ex_factory_date, pcd,
bundle_size, default_extra_cut_pct, ...), `lines` (colour, size, order_qty, extra_cut_pct), `fabrics` (colour, fabric_item, consumption, ... as `order_card_context` gives them), `processes` (the route: subcontract_process, position Before Sewing / After Sewing, sequence, supplier, colour; a challan can only go to a process on the route), `name` (to update a draft), `preview`. Returns `{ok, name, red_flags}`.

### `order_card_approve`
Issue (submit) a draft Production Card: the ERP's own submit rules decide (pilot, bulk gate). Params: `name`, `preview`. Returns `{ok, name}`.

### `order_card_revise`
Revise an issued Production Card: the ERP makes a new draft revision (quantities refreshed from the order when it is saved). A reason is required.
Params: `name`, `reason`, `preview`. Returns `{ok, name}`.

### `order_cutplan_suggest`
Suggest which accepted rolls go to which lay of a Cut Plan (`arinox_cut_plan_suggest_rolls`). Read only: nothing is saved. Params: `name`.
Returns `{ok, suggestion}` as the ERP answers it.

### `order_cutplan_release`
Release a Cut Plan (`arinox_cut_plan_release`). A marker variance above the limit sends it to a manager instead (the answer says `Pending Approval`).
Params: `name`, `preview`. Returns `{ok, name, status}`.

### `order_cutplan_approve`
Accept a marker consumption that is outside the limit (`arinox_cut_plan_approve`): production or merchandising manager, a reason is required.
Params: `name`, `note`, `preview`. Returns `{ok, name, status}`.

### `order_cutplan_reopen`
Send a Cut Plan back to draft (`arinox_cut_plan_reopen`), unless a lay was already cut from it. Params: `name`, `preview`. Returns `{ok, name, status}`.

### `order_cut_issuable`
The accepted rolls in the fabric store for the fabrics of a Production Card, with their free length (`arinox_cutting_get_issuable_rolls`). Read only.
Params: `card`. Returns `{ok, rolls}`.

### `order_cut_issue`
Issue rolls to the cutting floor (`arinox_cutting_issue_fabric`, a Stock Entry). Rolls with no quantity are never sent. A risky class: the answer is
`needs_approval` with an `approval_id` until a manager approves; run it again with that `approval_id`. Params: `card`, `rolls` ([{batch_no, qty}]),
`preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_ob_activate`
Make an Operation Bulletin the active one of its style; the earlier one is superseded (`arinox_operation_bulletin_activate`). Needs the operation times.
Params: `name`, `preview`. Returns `{ok, name}`.

### `order_prefill`
The pre-filled starting values of a floor document, for the generic form: `kind` is `dlr` (Daily Line Report: today, the card's line, one output row per
colour x size that can still be reported, quantity = what is left), `lay` (Lay Report header from the cut plan), `line_input` (one row per colour x size cut and not yet loaded), `cut_plan` or
`operation_bulletin` (header only). Read only; nothing is created. Params: `sales_order`, `kind`, `card` (default: the first live card), `name` (a cut plan
for `lay`). Returns `{ok, doctype, initial, note}`.

### `production_board_get`
The production board: every order with a live Production Card, one row each with order quantity, cut, line input, sewn, QC pass, finished, packed
(the Production Movement ledger), the sewn percentage of the order and what was sewn today. Read only; this is the Arinox reader that replaces the old
Cortex WIP screen (`erp_profile` = arinox). Params: `limit`. Returns `{ok, rows, totals, erp_profile}`.

### `order_subcontract_get`
Everything the step-7 page shows for one order: the **out / back balance per process** (wash, print, embroidery: sent, back good, rejected by the vendor,
rejected by the factory, short-closed, still out), the challans with what can be done next (return, short-close, settlement), the settlements with
their invoices and the finishing receipts. Read only. Params: `sales_order`. Returns `{ok, head, balance, challans, settlements, finishing, summary, can_write}`.

### `order_challan_short_close`
Accept that the rest of a challan will not come back (`arinox_subcontract_challan_short_close`): Production Manager only, a reason is required; the gap
shows as Short on the settlement. A risky class: `needs_approval` until a manager approves; run it again with the `approval_id`. Params: `name`, `reason`,
`preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_settlement_invoices`
Draft the vendor's Purchase Invoice (and a debit note for the penalty) from a submitted Subcontract Settlement
(`arinox_subcontract_settlement_make_invoices`). The drafts are not submitted here: Accounts submits them. A risky class: `needs_approval` until a manager
approves; run it again with the `approval_id`. Params: `name`, `preview`, `approval_id`. Returns `{ok, purchase_invoice, debit_note}`.

### `order_prefill_sub`
Pre-filled starting values of a subcontract or finishing document for the generic form: `kind` is `challan` (rows = what was sewn and not yet sent), `return`
(against `challan`: one row per challan row with what is still out), `settlement` (against `challan`) or `finishing` (rows = what is sewn or back, not yet
received). Read only. Params: `sales_order`, `kind`, `challan`, `card`. Returns `{ok, doctype, initial, note}`.

### `order_pack_get`
Everything the step-8 page shows for one order: the **packing position** per colour and size (order quantity, finished A-grade, packed, still packable), the
packing lists with their carton and piece totals and the share of the order, the final inspections with the AQL result (what was found against what
the plan accepts, the ERP's computed result and the recorded one) and the recent needle detector checks. Read only. Params: `sales_order`.
Returns `{ok, head, cards, matrix, packing_lists, inspections, needle, summary, can_pack, can_inspect, can_needle}`.

### `order_pack_plan`
The **carton plan**, worked out by the ERP's own script and set against the order, writing nothing: for the `pack_type` (solid colour and size, solid
colour with an assorted-size ratio, or assorted), the pieces per carton and the ratio rows (`{colour, size, pieces_per_pack}`), the cartons needed per colour
and size, the pieces, what is packable now and the total against the order. Params: `sales_order`, `card`, `pack_type`, `pcs_per_carton`, `ratios`,
`tail_carton_rule`, `carton_start`, `ship_to`. Returns `{ok, plan, summary:{rows, cartons, pieces, order_qty, pct_of_order, any_over}}`.

### `order_prefill_pack`
Pre-filled starting values of a pack or inspection document for the generic form: `kind` is `packing` (a Packing List with the cartons and contents the
ERP's generator planned from the same arguments as `order_pack_plan`), `inspection` (a Final Inspection over the `packing_lists` of the lot, with the cartons
drawn at random by the ERP and the seed kept so the draw can be repeated) or `needle` (a Needle Detector Log for today on a `line`). Writes nothing.
Params: `sales_order`, `kind`, plus the plan or lot arguments. Returns `{ok, doctype, initial, note}`.

### `order_ship_get`
Everything the step-9 wizard shows for one order: the **packing lists waiting for a shipment** (submitted, not on one, with the state of their final
inspection), the shipments of the order with where each stands (lists picked, delivery notes made, delivery notes submitted, on board), their delivery
notes, the booking / bill of lading / tracking facts, the freight shared over the orders on board, and the `deal_id` of the Deal this order came from (the
shipping clocks and papers of `deal_track` belong to this step). Read only. Params: `sales_order`.
Returns `{ok, head, deal_id, available, shipments, summary, can_write}`.

### `order_shipment_create`
Create the Shipment (a draft) from the picked packing lists: they must be submitted, not on another shipment, belong to this order, have an accepted
final inspection and be for one customer. The ERP fills the contracts, parcels, weight, volume and value from the lists. With `preview` nothing is
written. Params: `sales_order`, `packing_lists`, `mode` (Sea LCL, Sea FCL, Air, Courier, Road), `preview`. Returns `{ok, name}`.

### `order_ship_make_dns`
Make the draft Delivery Notes of a shipment, one per Sales Order on it, quantities exactly as packed (`arinox_shipment_make_delivery_notes`). A risky
class: `needs_approval` until a manager approves; run it again with the `approval_id`. Params: `shipment`, `preview`, `approval_id`.
Returns `{ok, made:[names]}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_ship_submit`
Submit a Delivery Note or a Shipment of the order. Both post to the ledger: a risky class, `needs_approval` until a manager approves; run it again with
the `approval_id`. Params: `doctype` (Delivery Note or Shipment), `name`, `preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_ship_record`
Record the booking, bill of lading and tracking on the ERP's Shipment: carrier, AWB, tracking link and status, forwarder, booking number and date,
cut-off, ETD, ETA, on-board, arrival and delivery dates, vessel, HBL and MBL. Only fields the Shipment has are written (`ship_track.WRITABLE_SHIPMENT`); an
empty value is not sent. Params: `shipment`, `values`, `preview`. Returns `{ok, name, fields}`.

### `order_invoice_get`
Everything the step-10 page shows for one order: the **receivable card** (each customer invoice with due date, days overdue, outstanding, state, the buyer's
promise, the next action, and the contracts it covers), its totals, the payment entries, the follow-up log (the notes), the shipments that can be invoiced (with
their draft and submitted invoices), the buyer claims, and the **close checklist** from the ERP. Read only. Params: `sales_order`.
Returns `{ok, head, invoices, totals, payments, claims, shipments, checklist, close, summary, can_write, can_close}`.

### `order_invoice_prepare`
Draft the commercial invoices of a shipment whose delivery notes are all submitted (`arinox_invoicing_prepare_invoices`): one per contract per shipment
(an invoice may list several contracts), a group customer gets two legs. Re-running replaces the drafts and keeps their numbers; submitted invoices are left alone.
Drafts are not posted. Params: `shipment`, `preview`. Returns `{ok, made:[names]}`.

### `order_invoice_submit`
Submit the draft invoices of a shipment, the factory's leg first (`arinox_invoicing_submit_invoices`). Posts the ledger: a risky class, `needs_approval`
until a manager approves; run it again with the `approval_id`. A contract that counts payment from the bill of lading needs the on-board date first (the ERP
refuses otherwise). Params: `shipment`, `preview`, `approval_id`. Returns `{ok, made:[names]}` or `{ok: false, needs_approval: true, approval_id}`.

### `order_followup_log`
Log a call or a promise on a customer invoice (`arinox_followup_log_follow_up`): the note becomes a comment, the promised date and amount and the next action
are fields, the follow-up status is recomputed. The note is required; a promise needs a future date and an amount no larger than what is owed. Params: `invoice`,
`note`, `promise_date`, `promise_amount`, `next_action_date`, `dispute_reason` (empty string clears a dispute), `preview`. Returns `{ok, name, status}`.

### `order_claim_credit_note`
Draft the credit note of an accepted buyer claim against the customer invoice (`arinox_buyer_claim_make_credit_note`): only a submitted claim settled by
credit note with an accepted amount; it answers the existing note if there is one. The accountant submits the note. A risky class: `needs_approval` until a
manager approves. Params: `claim`, `preview`, `approval_id`. Returns `{ok, name, credit_note}`.

### `order_close`
Close the order commercially (`arinox_close_commercial_close`): production finished, everything shipped invoiced, every customer invoice paid, no claim open.
Only the claim windows may be waived, with a reason. An accounts or merchandising manager only; sets the Sales Order to Closed: a risky class, `needs_approval`
until a manager approves. The checklist is read first, so a blocked close says why before an approval is asked for. Params: `sales_order`, `waive_reason`,
`preview`, `approval_id`. Returns `{ok, name}` or `{ok: false, error | needs_approval}`.
