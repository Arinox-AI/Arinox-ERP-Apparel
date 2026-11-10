# Phase 4 — forecasting, and the grounded copilot

## `backend/forecast.py` — predictive layer
Transparent projections from live ERP records (no ML), served on the dashboard as
`forecast`:

| Block | What it projects |
|---|---|
| `delivery` | per **open** order: coverage, days left, miss-probability, verdict |
| `stockout` | per style: required vs available fabric (roll metres), cover %, days cover |
| `margin` | sell rate vs BOM material cost — **only when the two are on the same scale**; otherwise the style is counted in `margin_unverified` (never a fabricated %) |
| `cash` | receivables/payables **kept per currency** (never summed across), with ageing buckets |
| `supplier` | open/late POs, received %, verdict |

**Data-integrity notes learned live:** the VN entity carries BOM cost and supplier
payables in **VND** while customer invoices are in **USD** — so cash is split per
currency and margin is suppressed when the scales differ rather than rendering a
nonsense percentage.

## Grounded copilot (`ask_kogo`, upgraded)
The floating **Ask KOGO** panel now answers from a compact live fact digest via the
LLM (falls back to the deterministic answerer if the model is unavailable). Every
number in the reply is validated against the digest; the response carries
`grounded` + `unsourced`.

*Caveat:* the agent stream can include a little of the model's own reasoning in the
reply; the grounding flag flags any numbers it can't source.

## Frontend
New **Forecast** view (Analyse group) renders cash (per currency), supplier
performance, delivery risk, stock-out cover and margin. Bundle rebuilt; `config.js`
first script, once.
