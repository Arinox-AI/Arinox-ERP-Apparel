# Cortex Operations Control Tower — Specification

## Data Source (updated 2026-10-01)
**Reads are LIVE and GET-only. Writes are opt-in, gated and drafts-only** — see
`backend/writes.py` and `ERP_WRITE_MODE` (`off|safe|draft|all`, default `draft`).
All entities below are read from the client's KOGO ERP (Frappe / KOGO_SAS) at
request time via `backend/erp.py`. There is no synthetic data. Executable writes:
`create_boms`/`register_bom_sizewise`→BOM (46), `raise_delivery_notes`→Delivery Note (13),
`reinspection_s84`→Quality Inspection, `review_receivables`→Payment Request (13),
`submit_trim_mrs`→submit Material Request (17), `assign_data_owners`→Task;
`create_item_prices` / `raise_work_orders` are already satisfied in the ERP.
`rollback_action` reverses a write (delete, or cancel for submit).

## Meta
- Project name: cortex-operations-control-tower
- Project slug: cortex_operations_control_tower
- Absolute project directory: artifacts/cortex-operations-control-tower

## Step 0A Values (runtime — injected by middleware; config.js carries the creating agent's values)
- API_BASE: https://agent.kogo.ai/api/agent/common_project_api_v1
- API_PATH: https://os.kogo.ai/api/v1/gateway
- CHAT_API_PATH: https://os.kogo.ai/api/v1/chatai
- USER_ID: 6a97e9c5baf1f227d9ce4e03
- AGENT_ID: 6a97e9c6baf1f227d9ce4e33
- DEPLOYMENT_ID: 6a97e9c6baf1f227d9ce4e28
- SWARM_ID: 6a9e6b745b5ecf9923020aa0
- ORIGIN_ID: 6a9e6b745b5ecf9923020aa0
- SCRIPTS_DIR: skills/appster_skill/scripts

## Tool Proxy Map
none

## Entities

### buyer_order
| Field | Type | Required | Default |
|---|---|---|---|
| id | integer | auto | — |
| order_number | string | yes | — |
| buyer_name | string | yes | — |
| style | string | yes | — |
| quantity | integer | yes | — |
| ship_date | string (date) | yes | — |
| delivery_date | string (date) | no | — |
| status | string | yes | — |
| expected_margin_pct | float | no | — |
| current_margin_pct | float | no | — |
| created_at | datetime | auto | now() |
| updated_at | datetime | auto | now() |

### risk
| Field | Type | Required | Default |
|---|---|---|---|
| id | integer | auto | — |
| risk_type | string | yes | — |
| severity | string | yes | — |
| title | string | yes | — |
| material | string | no | — |
| required_qty | string | no | — |
| affected_orders | string (JSON) | no | — |
| required_date | string | no | — |
| production_line | string | no | — |
| planned_output | string | no | — |
| actual_output | string | no | — |
| style | string | no | — |
| defect_rate | string | no | — |
| inspection_stage | string | no | — |
| affected_order | string | no | — |
| shipment_date | string | no | — |
| vessel | string | no | — |
| expected_delay | string | no | — |
| expected_margin | string | no | — |
| current_margin | string | no | — |
| cost_variance | string | no | — |
| status | string | yes | open |
| created_at | datetime | auto | now() |
| updated_at | datetime | auto | now() |

### recommended_action
| Field | Type | Required | Default |
|---|---|---|---|
| id | integer | auto | — |
| risk_id | integer | yes | — |
| risk_title | string | yes | — |
| action | string | yes | — |
| expected_impact | string | yes | — |
| responsible_team | string | yes | — |
| priority | string | yes | — |
| approval_status | string | yes | pending |
| modified_text | string | no | — |
| created_at | datetime | auto | now() |
| updated_at | datetime | auto | now() |

### audit_log
| Field | Type | Required | Default |
|---|---|---|---|
| id | integer | auto | — |
| action_type | string | yes | — |
| action_name | string | yes | — |
| description | string | yes | — |
| actor | string | yes | — |
| risk_title | string | no | — |
| approved | string | no | — |
| timestamp | datetime | auto | now() |

## Functions

### get_dashboard() → dict
Returns everything the dashboard needs: kpis, risks, recommendations, audit_log, charts, factory/date filter options, command suggestions.
Return shape:
```
{
  "kpis": [ {key,label,value,unit,trend,tone} ... ],
  "risks": [ {...risk dict with affected_orders parsed} ... ],
  "recommendations": [ {...recommended_action dict} ... ],
  "audit_log": [ {...audit dict} ... ],
  "charts": { "orders_at_risk": [...], "material_readiness": [...], "prod_plan_actual": [...], "quality_trends": [...], "shipment_readiness": [...], "order_margin": [...], "supplier_delivery": [...] },
  "factories": [...], "date_options": [...], "command_suggestions": [...]
}
```

### get_buyer_orders(search_query, limit, offset) → dict
### get_risks(search_query, limit, offset) → dict
### get_recommendations(search_query, limit, offset) → dict
### get_audit_log(search_query, limit, offset) → dict

### get_email_preview(action_id) → dict
Previews the email that would be sent for a given recommended action. Generation lives in
`backend/email_engine.py`: the communication **intent** is derived from the live context, every
value comes from a provenance-tagged **fact sheet**, and a **grounding validator** rejects any
number/date/reference that cannot be traced to the ERP. The draft carries `comm_type`,
`policy_version` and `grounding: {ok, unsourced}`. Nothing is ever sent; no internal product
branding appears in the email. See `EMAIL_AUTOMATION_PLAN.md`.
### get_erp_preview(action_id) → dict
Previews the ERP draft record KOGO would create for a given action.

### decide_action(action_id, decision) → dict
decision in {approve, reject}. Returns updated action + audit entry.

### modify_action(action_id, new_text) → dict
Updates the action text, marks modified, logs.

### execute_action(action_id) → dict
Simulates execution of an approved action: updates risk status, logs to audit.

### run_action(action_id, channel) → dict
channel in {email, erp, generic}. Simulates the end-to-end action with data used, confirmation, and audit log.

### ask_kogo(question, context) → dict
Deterministic KOGO analysis computed from LIVE ERP figures (order book, BOM coverage, quality,
shipments, sourcing, data gaps). No synthetic/canned demo values.

## Pages
Single full-width dashboard with sections (state-based, no router):
- TopBar (title, demo badge, date + factory filters, command bar)
- ExecutiveKpis
- RiskCards (5 risk types, each with 4 actions)
- RecommendedActions panel
- OperationalViews (7 charts)
- AuditLog panel
- ActionModal (intent → data → confirm → simulate → result)
- EmailPreviewModal / ErpPreviewModal

## Design
- Aesthetic: premium enterprise, clean white, deep navy text, teal/amber/red status, minimal decoration.
- Font: Inter (@fontsource/inter)
- Color scheme: from DESIGN.md tokens (brand override).

---

# Addendum — Phase 4A/4B: "Fabric & price intelligence" tab (added 2026-09-29)

## Why
The ERP holds fabric consumption in three places that had never been compared, and no view tied a
**customer order** to what its fabric **costs**. The request: *"add a tab … how much does it use in bom,
how much have they ordered, what should be the cost based on bom … like an intelligent price tracking or
price detection"*.

## Entities
No new entities. This tab is **fully derived** — it reads the ERP on every call and stores nothing.

## Sources joined per style (all live, read-only)
| What | Source | Field |
|---|---|---|
| Fabric per garment — ERP master | `BOM Item` | `qty` (Yard) / `stock_qty` (Metre) |
| Fabric per garment — quoted | `Internal Costing Evidence` | `avg_consumption_yard`, `avg_consumption_plus_3pct_yard` |
| Fabric per garment — buyer PO | `Client Purchase Order Evidence` | `fabric_yield_yd` |
| Actual buying rate | `Purchase Order Item` | `rate` + `uom` → normalised to USD/yard |
| Ordered qty + selling price | `Sales Order Item` → `Item.variant_of` | `qty`, `rate` |
| Cost build-up | `Internal Costing Evidence` | `source_cm/trim/wash/additional/overhead/rejection/finance/depreciation_usd` |

**Normalisation:** all consumption → **yard**, all rates → **USD/yard** (`1 yd = 0.9144 m`). A unit
mismatch therefore surfaces as the `uom_mix` flag instead of a silently wrong number.

## Function
### get_fabric_intelligence() → dict
No parameters. Returns `{summary, rows[], flags[], charts{}, meta, live, source, generated_at, connection}`.

Detection rules (thresholds returned in `meta`):
| Flag | Severity | Fires when |
|---|---|---|
| `consumption_conflict` | warning >5% / critical >15% | the consumption sources disagree beyond the threshold |
| `rate_drift` | warning | buying rate differs from the quoted rate by >5% |
| `price_below_cost` | critical | selling price < costed total |
| `thin_margin` | warning | margin < 15% |
| `no_buy_rate` | warning | fabric item has no submitted purchase order |
| `missing_bom` / `missing_costing` | critical / warning | no BOM fabric line / no internal costing |
| `po_vs_so_price` | info | client PO unit price ≠ SO rate |
| `uom_mix` | info | BOM in yard, purchase in metre |

Verdict per style: `alert` (any critical) > `watch` (any warning) > `ok`.

## Pages
New sidebar view **"Fabric & price"** (`View = "fabric"`, group *Analyse*, icon `Coins`), lazily fetched
on first open so the initial dashboard load is unaffected:
- 6 metric tiles — styles analysed, need attention, consumption conflicts, price moved, fabric exposure,
  blended margin
- 4 charts — consumption by source (grouped bar), cost vs price (grouped bar), fabric value by style (bar),
  flags detected (donut)
- "Needs a decision" feed — highest-severity findings first, with the money at risk
- Style table — 12 columns, All/Flagged tabs + search, row click opens a **Drawer** with the full evidence
  (consumption per source, requirement, rates, cost build-up, margin, findings)

## Design
Reuses the existing design system unchanged (analytics-light shell, DESIGN.md tokens, `ui.tsx` and
`charts.tsx` primitives). No new dependencies.

## Verification
| Function | Type | Status |
|---|---|---|
| get_fabric_intelligence | live ERP | PASS — 10 rows, live=true, exposure USD 100,079.61 |
| all 13 pre-existing functions | live ERP / SQLite | PASS (re-run after the change) |
| tsc --noEmit (strict) | build | PASS |
| bundle-artifact.sh → index.html | build | PASS — 1,432,012 bytes, `config.js` first script |

---

# Workspace release — Specification (2026-11-07)

## Entities
| Entity | Where | Key fields |
|---|---|---|
| Deal | `backend/models_deal.py` (`deal`) | id, title, stage, thread_key, mail_id, customer, customer_name, contact_email, contact_name, currency, incoterm, destination, season, product_type, ex_factory, in_warehouse, notes, styles (JSON), refs (JSON), contract_draft (JSON), events (JSON), attention (JSON), owner, quote_sent_at, buyer_reply_at, created_at, updated_at |
| Mail thread | `mail_message` + `email_draft` | thread_key, gm_thrid, in_reply_to, cc_addr, direction (in/out), deal_id, label (manual correction) |

Style (inside `deal.styles`): key, style_no, style_name, colour, fabric, qty, sizes[], product_type, bom[{item_code,
material_type, description, colour, uom, consumption, rate, remarks}], bom_file, warnings[], tech_pack, style_item,
cost_sheet, cost_status (draft/submitted), cost{computed_price, quoted_price, margin_pct, …}, in_negotiation, offer_price,
buyer_price, agreed_price, target_price (optional, never asked), status (open/agreed/dropped).

## Functions (all in `backend/deal_api.py`, documented in `backend/document.md`)
inbox_threads · inbox_thread · inbox_reply · inbox_sync · inbox_label · inbox_archive · inbox_link_customer ·
inbox_attachment · customer_list · customer_create · customer_overview · deal_list · deal_get · deal_from_thread ·
deal_create · deal_update · deal_register · deal_cost_open · deal_cost_save · deal_cost_submit · deal_quote_draft ·
deal_quote_send · deal_record_reply · deal_contract_prepare · deal_contract_form · deal_contract_update ·
deal_contract_create · deal_make_order · deal_track · deal_track_doc · deal_track_shipment · deal_dashboard.
Signatures and return shapes: `backend/document.md` → "Workspace".

## The deal's seven steps (`frontend/src/app/DealPage.tsx`)

inquiry → costing → quote → buyer's answer → contract → sales order → **ship & track**.

**Ship & track** (`app/TrackStep.tsx`, backend `ship_track.py`) is what the contract costs us afterwards. It holds no
copy of anything: the dates are derived from the contract's own lead times (`days_ex_factory_to_etd`, `transit_days`,
`payment_basis`/`payment_days`), the papers are parsed out of its `documents_list`, and the goods come from the ERP's
**Shipment** rows that name the contract. What it does keep is the one fact the ERP has no field for — the day a paper
was actually handed to the buyer (`app_kv` key `shipdocs:<deal_id>`, plus an event on the deal).

The **Incoterm** is explained where it is chosen: `deal_contract_form` returns `incoterm_help` (the ERP's eleven terms,
what each obliges, where risk passes, who pays freight/insurance/duty), and both that form and `deal_track` name any
mismatch between the chosen term and the contract's own `shipment_mode` / `freight_by` / `insurance_by` / `named_place`
lines — plus dates that contradict each other (an ETD that ignores the lead time, goods arriving after they are in the
warehouse).

## ERP calls per step (all through `pipeline.execute`)
| Step | ERP operation |
|---|---|
| Register | insert Opportunity; per style insert Tech Pack (materials from the BOM); API `arinox_tech_pack_create_style_item` |
| Costing | API `arinox_tech_pack_make_cost_sheet` → insert Cost Sheet; save (preview = price without writing); submit |
| Quote | API `arinox_cost_sheet_make_price_negotiation` per cost sheet; mail via SMTP in the thread |
| Buyer's answer | save Price Negotiation with new rounds (Buyer Counter / Our Counter / Agreed / Dropped) or status Lost |
| Contract | API `arinox_price_negotiation_make_quotation` → insert + submit Quotation; API `arinox_sales_contract_make_sales_contract` → edited draft → insert, submit (sign) |
| Order | API `arinox_sales_contract_make_sales_order` → insert Sales Order (draft) |

## Pages (frontend `src/app/`)
Workspace.tsx (shell, routes `#/dashboard`, `#/inbox[/key]`, `#/deals[/id]`, `#/customers[/name]`, `#/orders`, `#/tna`,
`#/records[/doctype]`, `#/reports[/name]`, `#/settings[/tab]`, `#/more/<legacy>`), Dashboard.tsx, Inbox.tsx, Deals.tsx,
DealPage.tsx, Customers.tsx, CustomerPicker.tsx, Settings.tsx, kit.tsx, theme.css.

## Design
Professional Slate — navy `#1e293b` structure, action blue `#2563eb`, `#f1f5f9` canvas, Inter. See DESIGN.md.
