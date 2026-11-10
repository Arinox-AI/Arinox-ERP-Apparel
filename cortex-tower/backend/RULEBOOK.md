# Rulebook — generic live detection engine

`backend/rulebook.py` + `backend/rulebook.json` replace the old hard-coded risk
list. Everything is derived **live** from the ERP, **per record**, and with
**threshold-computed severity**. Nothing here writes to the ERP.

## Why it changed

| Before | After |
|---|---|
| 9 fixed risk keys, mostly appended unconditionally | one rule per condition; a rule fires only when its condition is true |
| global aggregates ("13 of 13 orders…") | **per-record** rows (per order / style / supplier / invoice / shipment) |
| severity hard-coded per risk | severity computed from live magnitude + **days to deadline** + USD/% |
| no clean state | `risk_summary.all_clear` is true when nothing is wrong |
| tailored literals (`reinspection_s84`, "Da Nang sewing", "Standard Selling") | entity/field-driven; a brand-new style, order or supplier is covered automatically |

## Config — `rulebook.json`

All thresholds live here (never in code). Edit and the engine picks it up on the
next read:

```jsonc
{
  "delivery":   { "overdue_critical_days": 7, "due_soon_critical_days": 30, "due_soon_warning_days": 60 },
  "bom":        { "coverage_critical_below_pct": 50 },
  "fabric":     { "shortage_warning_pct": 5, "shortage_critical_pct": 20 },
  "payment":    { "overdue_warning_days": 1, "overdue_critical_days": 30 },
  "shipment":   { "variance_warning_pct": 2, "variance_critical_pct": 10 },
  "production": { "shortfall_warning_pct": 5, "shortfall_critical_pct": 20 },
  "supplier":   { "po_late_warning_days": 0, "po_late_critical_days": 7 },
  "limits":     { "max_risks_per_rule": 25, "max_recommendations": 60 }
}
```

## Rules (all generic, all conditional)

| Risk key | Type | Fires when | Severity from |
|---|---|---|---|
| `FABRIC_SHORTAGE#<style>` | sourcing (preventive) | fabric needed for **open** orders > received roll metres | % short |
| `PRODUCTION_SHORTFALL#<style>` | production (predictive-lite) | packed < ordered for an open order | % short + days left |
| `BOM_MISSING_ORDER#<style>` | production | an open order's style has no BOM | days to delivery |
| `WORK_ORDER_MISSING#<style>` | production | style has no *producing* Work Order (open → dated; shipped → completeness) | days / completeness |
| `BOM_COVERAGE#<style>` | production | per-size BOM coverage < 100% for a style in live demand | % missing |
| `ORDER_OVERDUE#<so>` | shipment | open order past its delivery date | days late |
| `NO_DELIVERY_NOTE#<so>` | shipment | open order with no Delivery Note | days to delivery |
| `DOC_GAP_NO_DELIVERY#<so>` | logistics | **shipped/invoiced** order with no Delivery Note | completeness (warning) |
| `PAYMENT_OVERDUE#<sinv>` | invoicing | Sales Invoice outstanding, overdue | days overdue + USD |
| `PO_LATE#<po>` | supplier | Purchase Order past schedule, not received | days late |
| `FABRIC_QUALITY_FAIL#<code>` | quality | fabric quality evidence FAIL / undetermined | result |
| `QUALITY_INSPECTION_OPEN#<qi>` | quality | Quality Inspection not submitted | warning |
| `TRIM_UNMAPPED` | sourcing | Trim Mapping Exception rows exist | count |
| `SHIPMENT_VARIANCE#<gse>` | shipment | shipped vs ordered beyond tolerance | % variance |
| `MISSING_SHIPMENT_DOCS#<sde>` | logistics | shipment group missing BL / invoice / packing list | warning |
| `PAYABLE_OUTSTANDING` | cash | supplier invoices fully outstanding | USD |
| `TRIM_MR_DRAFT` | sourcing | draft Material Requests exist | count |
| `MDG_OPEN` | data quality | open Migration Data Gaps | count |

## Facts the engine reads (live, read-only)

Sales Order + items · BOM + components · Item variants · Bin · **Fabric Roll**
(mtrs) · Delivery Note items · Sales/Purchase Invoice · Payment Entry · Work
Order · Material Request · Purchase Order/Receipt · Quality Inspection · Fabric
Quality Evidence · Garment Shipment Evidence · Shipment Document Evidence · Trim
Mapping Exception · Migration Data Gap · Production Daily Evidence.

## Order lifecycle (important)

Shipment evidence references the **original** order name; the live order is the
`-…-1` amendment. The engine normalises both. A **shipped or billed** order is
*closed* — it no longer raises live operational risks (`ORDER_OVERDUE`,
`FABRIC_SHORTAGE`, `NO_DELIVERY_NOTE`); what remains on it is a **completeness**
gap (`DOC_GAP_NO_DELIVERY`, `WORK_ORDER_MISSING` as a warning).

## Adding a rule

1. Write `def _r_my_rule(f, cfg) -> list[dict]` returning risk dicts with
   `key`, `risk_type`, `severity`, `title`, `record`, and an `extra` = `_act(...)`.
2. Add it to `RULES`.
3. (Optional) map its `risk_type` in `functions._RISK_TYPE_MAP` if it's a new
   category the frontend doesn't know yet.

No other file changes needed — writes stay keyed by action **slug**
(`action_key.split("::")[-1]`), so existing builders keep working.
