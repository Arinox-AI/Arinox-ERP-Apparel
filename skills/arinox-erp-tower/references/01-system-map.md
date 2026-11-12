# 01 System map

## Layers

```
 KOGO platform  ── the agent (you), SSO + roles, chat, Team Tasks (workspace only)
      │  Pattern A: you run `python functions.py <fn> '<json>'` after reading backend/document.md
      │  Pattern B: the React app calls the middleware  POST {project, function, params}
      ▼
 Cortex Tower  (project slug cortex_operations_control_tower)
   backend/   functions.py (registry FUNCTIONS) · cortex_api.py (guarded cx_* fns) · deal_api.py/deals.py ·
              order_api.py + order_*.py · pipeline.py (the single write path) · guardrails.py (roles, risk classes) ·
              write_gate.py + writes.py (mode gate, caps, audit, rollback) · tsr/ (Tower Script Runtime) ·
              mailbox.py / inbound.py / mailer.py (inbox, threads, outbound) · intake*.py (read POs from mail) ·
              tna_plan.py + tna_engine/ (T&A scheduler) · allocation.py (where-to-produce suggester) · config.py (only env reader)
   frontend/  React → one self-contained index.html (frontend/build.sh). config.js stays first and un-inlined.
   SQLite     decision state only: audit_log, approvals, write runs, deals, mail, locks. NOT a copy of ERP data.
      │  REST (only through pipeline.execute)
      ▼
 Arinox ERP (ERPNext v16 + arinox_apparel)   system of record
```

## Where things live in the repo

| Path | What |
|---|---|
| `erpnext/` | ERPNext core. **Never edit.** |
| `arinox-apparel/arinox_apparel/` | The Frappe app (doctypes, controllers, tests) and `portable/` (hosted Server Scripts, tests, loader, export) |
| `arinox-apparel/hosted_bundle/` | The data bundle (doctypes, custom fields, seeds, prints, reports, workspaces, scripts) that is loaded onto a site that takes only data and Server Scripts |
| `arinox-apparel/doctypes/` | One spec per doctype; phase plans A to E; `HOSTED_CONSTRAINTS.md` |
| `cortex-tower/` | The Tower (backend, frontend, tools, docs, `erp_setup/allow_on_submit.json`) |
| `cortex-tower2/apparel-modules.zip` | The KOGO loader bundle (how the data reaches the live site; scripts there are parked `disabled=1`) |
| `erpnext-test/` | A scratch ERPNext copy plus `islands/` (small Vue pieces, e.g. project costing). Not the Arinox app. |
| `appster_skill_*.zip` | The platform skill the Tower was built with (hard rules for KOGO projects) |

## Vocabulary

| Term | Meaning |
|---|---|
| **Deal** | Tower record that carries one inquiry to a Sales Order. Stages: inquiry → registered → costed → quoted/negotiating → contract → order. |
| **Order page** | One page per Sales Order with ten steps. Read model = `order_flow.status`. |
| **Style × colour × size** | Size and colour are ERPNext Item Variants (attributes `Size`, `Colour`). A *style* is the parent Item / Tech Pack. |
| **T&A** | Time and action calendar: `Order TNA` + `TNA Milestone` per style × colour × ex-factory date. 33 seeded milestone types; the Tower's plan carries 61-63 tasks. |
| **PCD** | Production commencement date (T&A anchor, together with ex-factory). |
| **PP meeting / PP sample** | Pre-production meeting and sample, a gate before bulk. |
| **Production Card** | The bulk production authority per style/colour; issued (submitted) before cutting. |
| **Production Movement** | The ledger of cut / line input / sewn / QC pass / finished / packed quantities. |
| **Evidence documents** | Arinox docs the T&A reads to decide a milestone is done (Sample Approval, PP Meeting, requisitions, PO/PR, inspections, Cut Plan, Daily Line Report, Line QC, Pilot Run, Packing List, Final Inspection, Shipment, Delivery Note, invoices). |
| **TSR** | Tower Script Runtime: runs the Arinox Server Scripts inside the Tower against the ERP's REST API while the ERP's own `server_script_enabled` is off. |
| **Pipeline** | `pipeline.execute`: identity/role → mode gate → field guard → preview → approval → lock → optimistic lock → TSR → journal → audit → ERP comment → event ledger. |
| **Risky class** | Writes that post to stock/ledger/production, or call ledger-posting APIs. They need approval. |
| **Write mode** | Global gate `off \| safe \| draft \| all`. |
| **Hosted site** | An ERPNext that accepts only DocTypes, data records and Server Scripts. No bench, no app install. |
