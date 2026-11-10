# Live ERP Integration Spec — Cortex Operations Control Tower

**Status:** APPROVED PLAN · 2026-09-29
**Goal:** Replace 100% synthetic demo data with **live reads from the client's Frappe/KOGO ERP**
(app `KOGO ERP` / KOGO_SAS, base `https://apps.kogo.ai:9447`). The frontend/backend contract stays the
same shape; only the **data source** changes. **READ-ONLY** — the dashboard must never write to the ERP.

> Architecture rule (appster): the frontend talks ONLY to the Kogo middleware (`API_BASE`).
> The ERP is reached from `backend/erp.py` at runtime. No ERP URL/token ever appears in frontend code.

---

## 0. Verified live facts (as of 2026-09-29, do NOT hardcode — re-read at runtime)

| Signal | Source doctype | Live value |
|---|---|---|
| Sales Orders | `Sales Order` | 25 total · **13 live (docstatus 1, "To Deliver")** · 12 cancelled originals |
| Order book value | Σ live SO `grand_total` | **USD 281,041.66** |
| Customer | `Sales Order.customer` | `EMJ APPAREL GROUP, LLC` (single buyer on the live book) |
| Delivery window | `Sales Order.delivery_date` | 2026-01-30 → 2026-06-26 |
| BOMs | `BOM` | **10** (all submitted, Size S only) |
| FG variants | `Item` (has_variants) | 56 → **BOM coverage 10/56 = 18%** |
| Fabric rolls | `Fabric Roll` | **423** |
| Trim requisitions | `Trim Requisition Evidence` | **17** |
| Material Requests | `Material Request` | **17, all Draft** (no RFQ/PO) |
| Purchase Orders | `Purchase Order` | 10 |
| Purchase Receipts | `Purchase Receipt` | 8 |
| Delivery Notes | `Delivery Note` | **0** |
| Sales Invoices | `Sales Invoice` | 13 · USD 281,041.66 |
| Payment Entries | `Payment Entry` | **0** |
| Work Orders | `Work Order` | **1 — `MFG-WO-2026-00001`, "Not Started", docstatus 1 (test)** |
| Job Cards | `Job Card` | 28 (belong to the test WO) |
| Fabric quality | `Fabric Quality Evidence` | 7 · results: 1 Fail, 1 Pass, 5 Not conclusively extracted |
| Shipments | `Garment Shipment Evidence` | 12 · **all 12 have non-zero `shipment_variance_qty`** |
| Production daily | `Production Daily Evidence` | 23 rows (order qty vs cutting/sewing/wash/packed) |
| Migration data gaps | `Migration Data Gap` | 15 · 14 `Awaiting Cortex evidence`, 1 `Resolved` |
| Item Price | `Item Price` | **0** |
| Fleet/entity | `Sales Order.company` | CORTEX VIETNAM GARMENT LLC / CORTEX FASHION (HK) LIMITED |

Live sample row shapes (verified):
```
Sales Order : {name, customer, po_no, transaction_date, delivery_date, grand_total,
               status:"To Deliver", docstatus:1, per_delivered:0.0, custom_source_document}
               child table `items` (fetch full doc: item_code, qty, rate, amount)
Migration Data Gap : {name(MDG-00466), gap_key, process_area, missing_information, why_required,
               affected_records, recommended_request_to_cortex, status, remarks}
Garment Shipment Evidence : {name, sales_order, item, customer_po_no, ship_via, carton_count,
               shipped_qty, sales_order_qty, shipment_variance_qty, source_invoice_no}
Production Daily Evidence : {name, style_no, sales_order, source_order_qty_pcs,
               source_total_cutting, source_total_sewing, source_total_sent_wash,
               source_total_received_wash, source_total_packed}
Fabric Quality Evidence : {name, source_fabric_code, inspection_result, detailed_metrics_extracted}
BOM : {name, item, total_sam, op_cm_usd, op_cost_per_minute_usd,
       op_total_operation_cost_usd, op_target_cost, op_achieved_cost,
       op_planned_operators, op_planned_helpers}
Material Request : {name, status:"Draft", custom_trim_requisition, transaction_date, child `items`}
```

---

## 1. New file: `backend/erp.py` — live KOGO ERP client

Runtime env vars available to the backend (fixed contract): `API_PATH`, `USER_JWT_TOKEN`, `SWARM_ID`,
`KOGO_API_BASE`, `AGENT_ID`, `USER_ID`, `DEPLOYMENT_ID`.

**Bootstrap (VERIFIED WORKING — use exactly this GraphQL shape):**

```python
import os, json, requests
from pathlib import Path

APP_ID = "6a84626b933cd6f2680eedac"          # KOGO ERP (app_type KOGO_SAS)
_CACHE = Path(__file__).resolve().parent / "data" / "sas_creds.json"

def _gateway(query, variables):
    url = os.environ.get("API_PATH", "")
    if url and not url.endswith("/gateway"):
        url += "/gateway"
    r = requests.post(url, json={"query": query, "variables": variables},
                      headers={"Authorization": f"Bearer {os.environ.get('USER_JWT_TOKEN','')}",
                               "Content-Type": "application/json"}, timeout=40)
    r.raise_for_status()
    return r.json().get("data") or {}

def _discover():
    ws = os.environ.get("SWARM_ID", "") or os.environ.get("AGENT_ID", "")
    data = _gateway(
        "query($a:String!,$w:ID!){ getKogoSasApiKeys(app_id:$a, workspace_id:$w){ api_base api_key api_secret } }",
        {"a": APP_ID, "w": ws})
    k = data.get("getKogoSasApiKeys") or {}
    return {"BASE": (k.get("api_base") or "").rstrip("/"),
            "AUTH": {"Authorization": f"token {k.get('api_key')}:{k.get('api_secret')}"}}

def get_creds():
    """Cached creds; re-discover if missing/blank. Never raises — returns {} on failure."""
    ...

# helpers (all return [] / {} / 0 on failure, never raise):
def erp_get(doctype, fields=None, filters=None, limit=500, order=None) -> list
def erp_doc(doctype, name) -> dict
def erp_count(doctype) -> int
def erp_available() -> bool
```

**Rules for `erp.py`**
- Cache creds to `backend/data/sas_creds.json`; if the cache is present and non-blank use it first
  (so the app works even if the gateway JWT is absent at runtime). Re-discover and re-cache on failure.
- `filters` is Frappe JSON: `[["docstatus","=",1]]`. URL-encode the doctype (`Sales Order` → `Sales%20Order`).
- **NEVER** pass a `doctype` param to `/api/resource/<DT>` (500).
- **Child tables do NOT come back via list fields** — fetch the full doc for `items`.
- Every helper swallows errors → `log`-free, returns empty. No exceptions escape.
- Add `def erp_status() -> dict` → `{"connected": bool, "base": str, "error": str|None}`.

---

## 2. Backend contract — function signatures UNCHANGED

All 13 function names and their params stay exactly as today. Every function additionally returns:

```
"live": true, "source": "KOGO ERP", "generated_at": "<iso>",
"connection": {"connected": bool, "base": str, "error": str|None}
```

If the ERP is unreachable: return the normal shape with **empty** collections, `"live": false`,
`"connection": {"connected": false, "error": "erp_unavailable: <reason>"}` — **never crash**.

### 2.1 `get_dashboard(db)` → same keys
`kpis, risks, recommendations, audit_log, buyer_orders, charts, factories, date_options,
command_suggestions, demo` (keep `demo` for compat; set it to **`false`**) + the 4 new keys above.

**KPIs (8)** — `{key,label,value,unit,tone}`:
| key | label | value | unit | tone |
|---|---|---|---|---|
| `open_orders` | Open Sales Orders | 13 | — | neutral |
| `order_book` | Order Book Value | 281,042 | USD | positive |
| `units_on_order` | Units on Order | Σ SO item qty | pcs | neutral |
| `bom_coverage` | BOM Coverage | 18 | % | warning |
| `fabric_rolls` | Fabric Rolls in Stock | 423 | rolls | positive |
| `trim_mr_draft` | Trim Requests (Draft) | 17 | — | warning |
| `delivery_notes` | Delivery Notes Raised | 0 | — | critical |
| `open_gaps` | Open Data Gaps | 14 | — | critical |

All values computed live (no literals except labels/units).

**RISKS (9) — derived live, upserted into `risk_state` by `risk_key` so `id` stays stable.**
Map each into the existing `Risk` interface (fields render only when present):

| risk_key | risk_type | severity | title | real evidence → fields |
|---|---|---|---|---|
| `BOM_COVERAGE` | `production_delay` | critical | "Per-size BOM missing for 46 of 56 FG variants" | BOM 10 vs 56 variants → `style="10 styles / 56 variants"`, `affected_orders`=live SO names, `required_date`=earliest delivery |
| `NO_DELIVERY_NOTES` | `shipment_risk` | critical | "13 orders To Deliver with zero Delivery Notes raised" | SO 13 / DN 0 → `affected_orders`, `shipment_date`=earliest delivery, `vessel`=GSE `ship_via` |
| `FABRIC_QUALITY_FAIL` | `quality_risk` | critical | "Fabric quality pack FAIL for S84; 5 of 7 not conclusively extracted" | FQE rows → `material="S84"`, `inspection_stage="Fabric inspection & testing"`, `defect_rate="FAIL"`, `style="C2027-S84-304"` |
| `SHIPMENT_VARIANCE` | `shipment_risk` | warning | "Shipped qty differs from order qty on all 12 shipment records" | GSE variance → `affected_order`=worst row, `expected_delay` |
| `NO_REAL_WORK_ORDER` | `production_delay` | warning | "No real Work Order raised — only the test MFG-WO-2026-00001" | WO 1 test → `production_line="Da Nang sewing"`, `planned_output` |
| `TRIM_MR_DRAFT` | `fabric_shortage` | warning | "17 trim Material Requests still Draft — no RFQ or PO raised" | TRE 17 / MR 17 → `material="Trims (labels, thread, fusing, elastic)"`, `required_qty="17 requisitions"` |
| `NO_ITEM_PRICE` | `margin_risk` | warning | "No Item Price master — selling prices and payment terms unverifiable" | Item Price 0 → `expected_margin="not in system"` |
| `NO_PAYMENT_ENTRY` | `invoicing_risk` | warning | "13 Sales Invoices (USD 281,041.66) posted with 0 Payment Entries" | SI 13 / PE 0 → `cost_variance="receivables unrecorded"` |
| `MDG_OPEN` | `data_quality` | warning | "15 migration data gaps recorded, 14 awaiting Cortex evidence" | MDG → `affected_orders`=process areas, `required_date` |

**RECOMMENDATIONS — 1–2 per risk**, upserted into `action_state` by `action_key`
(`"<risk_key>::<slug>"`), each: `{id, risk_id, risk_title, action, expected_impact, responsible_team,
priority, approval_status, modified_text}`. `priority` ∈ high|medium|low. Text must quote real numbers.
Example: `BOM_COVERAGE::create_boms` → "Create the 46 missing per-size BOMs (10 of 56 exist)",
impact "Unblocks Work Orders for 13 live orders", team "Industrial Engineering", priority high.

**CHARTS — same 7 keys, real semantics:**
| key | shape | source |
|---|---|---|
| `orders_at_risk` | `[{x:"2026-01", y:2}, …]` | live SO count by `delivery_date` month |
| `material_readiness` | `[{x:"C2027-S84-304", y:24.4}, …]` | BOM `total_sam` per style |
| `prod_plan_actual` | `[{x:style, planned:order_qty, actual:packed, sent:shipped_qty}, …]` | Production Daily Evidence (factory packed — unverified) + Garment Shipment Evidence (sent — final packing list / invoice, authoritative) |
| `quality_trends` | `[{x:"S84", pass:0, fail:1, not_extracted:1}, …]` | Fabric Quality Evidence grouped by code |
| `shipment_readiness` | `[{x:style, planned:so_qty, actual:shipped_qty}, …]` | Garment Shipment Evidence |
| `order_margin` | `[{x:style, expected:cm_usd, current:op_cost}, …]` | BOM `op_cm_usd` vs `op_total_operation_cost_usd` |
| `supplier_delivery` | `[{x:supplier, otel:pct}, …]` | Purchase Receipt vs Purchase Order schedule per supplier |

**Filters / misc**
- `factories` ← distinct `Sales Order.company` of live SOs.
- `date_options` ← distinct SO delivery months (`"2026-01" … "2026-06"`).
- `command_suggestions` ← data-driven, e.g. `"Which orders are due in Q1 2026?"`,
  `"How many BOMs are missing?"`, `"What is blocking shipment?"`, `"Show the biggest data gap"`.
- `audit_log` ← unchanged (local SQLite).

### 2.2 `get_buyer_orders(search_query, limit, offset)`
Live `Sales Order` (docstatus 1), one row per SO, mapped to:
`{id, order_number, buyer_name, style, quantity, ship_date, delivery_date, status, expected_margin_pct,
current_margin_pct, created_at, updated_at}` **+ additive** `po_no, transaction_date, grand_total,
per_delivered, currency, company, items_note`.
`style` = items' item_code(s) (join), `quantity` = Σ item qty, `status`:
`Overdue` if `delivery_date < today` else SO `status`.

### 2.3 `get_risks` / `get_recommendations` / `get_audit_log`
Same params. `get_risks`/`get_recommendations` return the live-derived lists (with state overlay) as
`{total, items}` — match the existing return shape used by the frontend/CLI.

### 2.4 Action functions — **preview only, NO ERP writes**
- `preview_action(action_id)` → auto-detect channel (`email` if the action targets a supplier/buyer,
  else `erp`). Response shape unchanged: `{action_id, channel, intent, email:{to,from,subject,body}}`
  or `{action_id, channel:"erp", intent, record:{doctype, fields}}`.
  - `record.doctype` must be a **real** ERPNext doctype (`Material Request`, `Quality Inspection`,
    `Production Plan`, `Shipment`), `fields` filled with **real** values from the live risk.
- `get_email_preview(action_id)` / `get_erp_preview(action_id)` → the two specific branches.
- `decide_action(action_id, decision)` → updates `action_state` (approve|reject) + audit.
- `modify_action(action_id, new_text)` → updates text + audit.
- `execute_action(action_id)` → requires `approved`; sets `executed`; sets the linked `risk_state.status
  = "resolved"`; audit. Add `"erp_write": false, "note": "Preview only — no record written to KOGO ERP."`
- `run_action(action_id)` → end-to-end simulate: `{intent, data_used, result:{status:"success", …},
  erp_write:false}` + audit.
- `ask_kogo(question, context)` → deterministic analysis **over live facts** (order book, BOM coverage,
  data gaps, shipments, quality, sourcing). Must reference real numbers. `{answer, related:[…]}`.
- Add a `"mode": "read-only"` marker to action responses.

### 2.5 `backend/models.py` / `database.py` / `seed.py`
- **Drop** `BuyerOrderModel` (orders are live now).
- Keep `AuditLogModel` as-is.
- Add `RiskStateModel` (`id` PK, `risk_key` unique, `status` default `'open'`, timestamps).
- Add `ActionStateModel` (`id` PK, `action_key` unique, `risk_key`, `approval_status` default
  `'pending'`, `modified_text`, `executed_at`, timestamps).
- `seed.py` → becomes a **no-op initializer**: create tables only, insert NO synthetic rows.
  Keep the file + a docstring explaining data is live.

### 2.6 `backend/document.md`
Rewrite the "Data" section: state the app now reads **live** from KOGO ERP (`Sales Order`, `BOM`,
`Item`, `Fabric Roll`, `Migration Data Gap`, `Fabric Quality Evidence`, `Garment Shipment Evidence`,
`Production Daily Evidence`, `Trim Requisition Evidence`, `Material Request`, `Purchase Order/Receipt`,
`Sales Invoice`, `Payment Entry`, `Work Order`) and is **read-only**. Document `erp.py` and the new
response keys.

---

## 3. Frontend changes (contract-compatible)

1. **`types.ts`**
   - Extend `RISK_ACTIONS` with: `data_quality: ["Ask Cortex for evidence", "Create Follow-up Task",
     "Notify Data Owner", "Ask KOGO"]`, `invoicing_risk: ["Review Receivables", "Post Payment Entry",
     "Notify Finance", "Ask KOGO"]`.
   - Add to `Dashboard`: `live?: boolean; source?: string; connection?: {connected:boolean; base:string;
     error:string|null}; generated_at?: string`.
2. **`TopBar.tsx`** — replace the badge
   `Demo Environment — Synthetic Data` → **`● Live — KOGO ERP`** (positive/green tokens, dot).
   Subtitle → `Cortex Textiles Limited · Live production data from KOGO ERP`.
   If `connection && !connection.connected` → show an amber banner `ERP connection issue: {error}`.
3. **`Modals.tsx`** — the IntentModal warning must stop saying "synthetic":
   → `⚠ Preview only — nothing is written to KOGO ERP. Executing records the decision in the dashboard
   audit log.` PreviewModal buttons: `"Approve & Simulate Send"` → `"Approve (preview only)"`,
   `"Approve & Simulate Create"` → `"Approve (preview only)"`.
4. **`OperationalViews.tsx`** — update card titles/series to the real semantics in §2.1 CHARTS:
   "Live Orders by Delivery Month" (bar), "Sewing SAM by Style" (bar), "Ordered vs Packed" (grouped
   planned/actual), "Fabric Test Results by Code" (grouped pass/fail/not_extracted),
   "Ordered vs Shipped" (grouped planned/actual), "Cut & Make Cost vs Operation Cost" (grouped
   expected/current), "Sourcing Pipeline by Type" (donut `{x,y}`).
5. **`App.tsx`** — if `dash.connection && !dash.connection.connected`, render a top amber banner
   (not the full "Backend offline" screen). Keep everything else.
6. Rebuild: `bash "$SCRIPTS_DIR/bundle-artifact.sh" && cp bundle.html ../index.html`, then **re-inject**
   `<script src="./config.js"></script>` as the first script (the copy overwrites index.html).
   `rm -rf node_modules dist bundle.html .parcel-cache`.

---

## 4. Hard constraints (do not violate)
- ❌ Never write to the ERP. No POST/PUT/PATCH/DELETE to the ERP — GET only.
- ❌ No ERP URL/token/ID in frontend code (only `API_BASE` / `API_HEALTH`).
- ❌ No ORM/HTTP code in `config.py`; env reads only there.
- ✅ Every ERP failure degrades gracefully to an empty-but-valid response with `live:false`.
- ✅ Keep all 13 function names + param names exactly (the frontend and the host expect them).
