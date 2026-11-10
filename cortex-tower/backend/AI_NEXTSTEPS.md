# AI next-step layer (Phase 3) — grounded, live, generic

`backend/ai_nextsteps.py` turns each live risk into a **reasoned, cited plan** using an
LLM (reached through the KOGO agent stream — the same contract the chat module uses),
with guard-rails so it is trustworthy on real ERP data.

## Why it's trustworthy

| Guard-rail | How |
|---|---|
| **Grounded** | the model receives a closed **evidence pack** — only the numbers the engine computed for that risk (+ real reference ids). It is told to use nothing else. |
| **Validated** | every number in the model's **narrative** is checked against the evidence pack; unsourced numbers are recorded and the suggestion is flagged (`grounded:false`, `unsourced:[…]`). Numeric-only fields (confidence) and cross-reference ids are handled explicitly. |
| **Cached** | one row per `risk_key` in the `ai_suggestion` table, keyed by an `evidence_hash` — regenerated automatically when the live facts change. |
| **Fallback** | if the model is unreachable or returns junk, the engine's deterministic action is used instead (`source:"fallback"`). Never blocks the dashboard. |
| **No write** | it only reads the ERP. |

## Data flow

```
rulebook.live_facts()  ──►  build_risks()  ──►  evidence_pack(risk)  ──►  LLM
        │                                             │                    │
       live ERP                                   closed facts         JSON plan
                                                                           │
                          AISuggestionModel  ◄── validate + cache  ◄────────┘
                                   │
                        get_dashboard attaches risk["ai"] (cached, no LLM call)
```

## Output shape (per risk)

```jsonc
"ai": {
  "risk_key": "PAYMENT_OVERDUE#ACC-SINV-2026-00001",
  "reasoning": "…why this is happening, citing the live figures…",
  "actions": [ { "action": "…", "why": "…", "owner": "Finance / Collections",
                 "priority": "high", "confidence": 0.85 } ],
  "predicted_impact": "…",
  "watch_outs": "…",
  "grounded": true, "unsourced": [], "source": "ai"
}
```

The Tower's **risk drawer** renders this automatically when `risk.ai` is present
(a "Sparkles · AI next steps" card with the *Grounded* badge, actions, owners,
confidence, predicted impact and watch-outs).

## Functions

- `get_ai_next_steps(db, risk_id=None, risk_key=None, limit=8, refresh=0)`
  — generate for one risk, or the top `limit` risks. Registered in `FUNCTIONS`.
- `ai_nextsteps.generate(db, risk_keys=None, limit=8, refresh=False)`
  — batch generate (one LLM call for the set).
- `ai_nextsteps.cached(db)` — read cache only (no LLM).
- `ai_nextsteps.attach_to_dashboard(db, risks)` — attach cached suggestions (used by `get_dashboard`).

## Genericity

The evidence pack and the prompt are built from **rule metadata**, so a brand-new
risk (a new style/order/supplier) is enriched with AI next-steps automatically —
nothing is tailored to today's data.

## Operational note

`get_dashboard` (an already-published function) serves the **cached** suggestions,
so AI next-steps appear in the Tower with no new API surface. Generating fresh
suggestions is an out-of-band call (already run; a scheduled task can refresh it).
`get_ai_next_steps` is registered for when the project is next published.

## Output hygiene — never leak the model's reasoning (2026-10-05)

The KOGO agent stream does **not** return the answer alone: it wraps the model's
private chain-of-thought in a `<think>…</think>` block (with `<starttime>` /
`<endtime>` stamps) *before* the real answer, e.g.

```
<think><starttime>…</starttime>question analysis / planning…<endtime>…</endtime></think>The actual answer.
```

The old `_clean()` only stripped tags (`<[^>]+>`), so it deleted `<think>` but
**left the reasoning text**, which then rendered in the UI in front of the answer
("Ask KOGO" / copilot). Two fixes in `ai_nextsteps.py`:

- `_clean()` now **discards the whole `<think>…</think>` block** (plus safety nets
  for unclosed / stray tags and a leading "KOGO analysis" heading) — only the
  final answer survives.
- `_llm()` no longer uses `iter_content(decode_unicode=True)`. The stream sends
  UTF-8 with no charset in the `Content-Type`, so `requests` fell back to
  ISO-8859-1 and mangled every non-ASCII character (`â€”` instead of `—`). Bytes
  are now decoded as UTF-8 explicitly.

This applies to both the grounded copilot (`ask_kogo`) and AI next-steps
generation (cleaner JSON parsing). Verified live via the project API:
`ask_kogo("what are my high intensity orders?")` returns the plain answer with
no reasoning and no mojibake.
