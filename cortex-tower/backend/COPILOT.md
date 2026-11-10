# Ask KOGO — grounded, ERP-aware copilot

`ask_kogo` is a **retrieval-augmented** copilot: it reads live data from the KOGO
ERP, hands the LLM exactly the records the question needs, has the model reason
over them, then validates every number in the answer. It never invents data and
never writes to the ERP.

Implementation: `copilot.py` (retrieval + grounding) + `ai_nextsteps.py` (LLM
transport + `<think>` stripping).

## Why it works this way

The first version fed the model only **counts** (`orders: {open, total,
styles_in_demand}`) plus risk titles, so any per-record question — "biggest
orders?", "who owes us?" — was unanswerable even though the ERP held the rows.
A *fixed* digest will always fail some question. So the copilot **retrieves per
question**:

```
question ──▶ route to relevant live sections ──▶ evidence pack ──▶ LLM ──▶ validate
```

## Pipeline

1. **Retrieve** — `copilot.build_evidence(question)` calls
   `rulebook.live_facts()` (live ERP reads, briefly cached) + `forecast.build()`
   and assembles:
   - **always:** `today`, `order_book`, `orders` (per-order value/qty/dates/
     status/customer/item codes), `styles_in_demand`, `risk_summary`, `risks`,
     `forecast` (cash/margin/supplier/delivery/stockout).
   - **routed by keywords** (`copilot._ROUTES`):
     | section | contents |
     |---|---|
     | `finance` | invoices (outstanding, days overdue, currency), receivables by currency, payment entries |
     | `materials` | BOMs + costs, styles missing BOM, fabric roll metres by item, material requests, trim exceptions |
     | `procurement` | purchase orders, receipts, purchase invoices |
     | `quality` | fabric quality evidence (pass/fail), quality inspections |
     | `logistics` | shipments + variances, shipment documents, orders with a delivery note |
     | `production` | work orders (qty / produced), production daily evidence |
     | `gaps` | migration data gaps |
   - If **nothing** matches (e.g. "summarise what to act on"), **all** sections are
     included so broad questions still work.
2. **Reason** — the model is told to use ONLY the pack, and may rank / filter /
   compare / group / compute from the rows (never mix currencies, never invent).
3. **Validate** — `ai_nextsteps._num_tokens` checks every meaningful number in the
   answer against the pack. Unsourced numbers clear the `grounded` flag and are
   returned in `unsourced`.

Reasoning is never shown: `ai_nextsteps._llm` strips the model's
`<think>…</think>` block and decodes the stream as UTF-8.

## Response

`ask_kogo` / `copilot.answer` returns (plus the standard additive keys):

| key | meaning |
|---|---|
| `answer` | the grounded final answer |
| `related` | top critical risk titles |
| `grounded` | every number in the answer appears in the evidence pack |
| `unsourced` | numbers that could not be sourced (empty when grounded) |
| `evidence_sections` | which live sections were retrieved for the question |

## Extending coverage

Add a new dataset by writing a `_xxx(facts, today)` builder and registering it in
`copilot._BUILDERS` + `copilot._ROUTES`. If the data isn't in `rulebook.live_facts()`
yet, add the ERP read there.

## Verified (live)

| question | result |
|---|---|
| what are my big or hot orders? | ranked biggest by value/qty + overdue days — grounded |
| which invoices are overdue and who owes us? | 13 overdue, USD 281,041.66, per-invoice days — grounded |
| which orders are at risk of shipping late, and why? | overdue days + no Delivery Notes + shipment variances — grounded |
| which styles are missing a BOM? | none missing; flags two zero-cost BOMs — grounded |

All `grounded: True`, `unsourced: []`, and no reasoning/`<think>` leaked.

---

## Ask KOGO (chat) — RETIRED long-prompt path

The long-prompt **grounded-copilot path for `ask_kogo` was RETIRED on 2026-10-06** and replaced by
the appster **chat-module** streaming chat (`AgentChat`, backend functions `get_chat_config`,
`create_room`, `send_message`, `fetch_threads`, `fetch_chat_history`).

- `ask_kogo` is **no longer wired into `FUNCTIONS`** (removed from the dict literal and the
  override that delegated to `copilot.answer`). The old deterministic `ask_kogo` is kept in
  `functions.py` for reference only and is unregistered; it is never reachable from the UI/API.
- `copilot.py` is **no longer imported** by `functions.py` (the `import copilot as _copilot`
  wiring was removed). The file remains on disk because other code is unaffected by it, but it is
  not wired into `FUNCTIONS`.
- The frontend `AskPanel` (long-prompt input + rendered answer) was retired to `.trash/AskPanel.tsx`
  and replaced by `ChatPanel` → `AgentChat` (thread sidebar + live SSE streaming chat).
- This document (`COPILOT.md`) is kept as the historical design record for the retired path.

See `document.md` → **Chat Module** for the live chat function contract.
