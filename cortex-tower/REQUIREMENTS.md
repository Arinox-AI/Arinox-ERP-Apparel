# Cortex Operations Control Tower — Requirements

## Project
- Name: cortex-operations-control-tower
- Slug: cortex_operations_control_tower
- Purpose: Enterprise operations dashboard for Cortex Textiles Limited (apparel manufacturer, Vietnam operation). Demonstrates KOGO OS's ability to monitor manufacturing operations, detect risks, recommend next-best actions, and let authorised users execute/approve actions with a full audit trail.

## Data Requirement (HARD CONSTRAINT)
- **LIVE data from the client's KOGO ERP** (Frappe / KOGO_SAS). No synthetic/demo data.
- Reads from the ERP are **GET-only**. Writes are opt-in and mode-gated (`off|safe|draft|all`,
  default `draft`): executing an approved action performs a **real, drafts-only, reversible** ERP
  write (see `backend/writes.py`); previews never write. Every action is recorded in the audit log.
- Prominent label: "● Live — KOGO ERP".
- All financials in USD.

## Users
- Operations managers, production planners, quality leads, supply chain, finance (demo personas).

## Entities

### BuyerOrder
- id, order_number, buyer_name, style, quantity, ship_date, status, delivery_date, expected_margin_pct, current_margin_pct

### Risk
- id, risk_type (fabric_shortage | production_delay | quality_risk | shipment_risk | margin_risk), severity (critical | warning), title, material, required_qty, affected_orders (JSON), required_date, production_line, planned_output, actual_output, style, defect_rate, inspection_stage, shipment_date, vessel, expected_delay, expected_margin, current_margin, cost_variance, status (open | resolved), created_at, updated_at

### RecommendedAction
- id, risk_id, risk_title, action, expected_impact, responsible_team, priority (high | medium | low), approval_status (pending | approved | rejected | modified | executed), modified_text

### AuditLog
- id, action_type, action_name, description, actor, risk_title, approved, timestamp

### KpiMetric
- (computed from seed data, served by a get_dashboard function)

## Features
- [x] Dashboard KPIs (8 executive KPIs)
- [x] Risk cards (5 interactive risk types with actions)
- [x] KOGO recommended actions panel (approve / reject / modify / execute)
- [x] KOGO command bar with prompt suggestions
- [x] Operational visualizations (7 charts)
- [x] Action behavior: intent → data → confirm → simulate → status update → audit log
- [x] Email preview before simulated send
- [x] ERP draft record preview before simulated creation
- [x] Filters: date + factory
- [ ] Chat with live agent (NOT used — the analysis is deterministic over live ERP data)
- [x] Analytics / graphs (computed live from ERP aggregates)

## Pages / Tabs
Single full-width dashboard (no sidebar), scrolled sections:
1. Top bar (title, demo label, filters, command bar)
2. Executive KPIs
3. Risks requiring action
4. KOGO recommended actions
5. Operational views (charts)
6. Activity & Audit log

## Design Preference
- Premium modern enterprise. Clean white background, deep navy typography, teal positive, amber warning, red critical, minimal decoration, responsive desktop.


---

## Workspace release (2026-11-07) — the requirements this release was built against

From the owner (verbatim intent): one inbox; flag inquiry mail; never ask for a price on an inquiry; add a customer when
the buyer is not in the ERP; reply in the same thread and capture the buyer's reply in it; follow the order flow
inquiry (BOM) → pricing → acceptance → sales contract → sales order → …; stay in sync with the ERP; easier than making
the entries in the ERP; dashboards; fix UI and UX.

### Entities (new)
* **Deal** (`deal` table): one buyer conversation from inquiry to Sales Order — title, stage (inquiry · costing · quoted ·
  negotiating · accepted · contract · order · lost), thread_key, customer, contact, currency, incoterm, destination,
  season, ex-factory / in-warehouse, styles (JSON: style no, name, colour, fabric, qty, sizes, product type, BOM lines,
  ERP names of its Tech Pack / Cost Sheet / style Item, costed / offered / buyer / agreed price), ERP refs (Opportunity,
  Price Negotiation, Quotation, Sales Contract, Sales Order), contract draft, timeline, attention.
* **Thread**: `mail_message.thread_key` (+ `email_draft.thread_key`) — Gmail thread id, else the References chain.

### Features
- [x] One inbox as conversations, folders by label, needs-reply flag, search, archive, label correction
- [x] Inquiry classification (with BOM / tech-pack attachment signal); quoted history ignored; PO document decisive
- [x] Reply in the thread (Re:, In-Reply-To, References); our replies and Gmail Sent replies shown in the thread
- [x] Buyer replies on a deal's thread flag the deal (accept / counter with the prices mentioned / POs / question)
- [x] Deal from a mail: styles, quantities, colours, season, incoterm, dates and one BOM per style read from the mail
- [x] Customer: recognised (linked address, ERP contact, name/domain) or added (Customer + Contact) in one step
- [x] ERP flow on the ERP's own scripts: Opportunity + Tech Packs → Cost Sheets (ERP rules price) → Price Negotiation
      rounds → Quotation → Sales Contract (readiness checks before signing) → Sales Order (colour/size variants)
- [x] Dashboard: pipeline, waiting on you, quotes waiting on the buyer, ageing inquiries, top customers, open orders,
      due in 30 days, orders by month, receivables, inbox counts
- [x] Customers screen (deals, contracts, orders per customer); Records (every ERP doctype); Reports; T&A; Settings

### Pages
Dashboard · Inbox · Deals (board / list) · Deal (6 steps) · Customers · Sales orders · T&A calendar · ERP records ·
Reports · Settings (mailbox, users, ERP sync, business rules, approvals) · More tools (order intake, WIP, risks, actions,
forecast, operations charts, fabric price check, risk overview, activity log).

### Design
Professional Slate (appster `designs/corporate/professional-slate`), see DESIGN.md.
