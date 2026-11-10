# Cortex Control Tower — Email Automation Plan

**Status:** P0 (generation engine + guardrails) **IMPLEMENTED 2026-10-01** in
`backend/email_engine.py` (policy is a Python registry — see §2.1 ②). P1–P4 not started.
**Date:** 2026-10-01
**Scope:** Cortex sends all outbound mail to its customers (buyers) and suppliers. The Control
Tower must (a) generate professional, context-true emails and (b) later ingest the connected
company mailbox so POs, amendments and documents land in the ERP.

---

## 1. Where we are, and why the current code is wrong

You are correct: what I was writing was **instance-typed** — one hard-coded template per action
slug (`email_buyer_delivery`, `email_buyer_statement`, …). That means:

- It only ever works for the exact actions we listed.
- Every new action = new code.
- It still fills a fixed skeleton with a few variables, so it does **not** read the real record.
- Nothing checks that the numbers in the email actually came from the ERP.

**Target:** one **context-driven composer** that receives a structured *fact sheet* built from the
live ERP records, chooses the communication type from the context, writes the email, and then
**verifies every fact in the email against the fact sheet before it can be sent.**

---

## 2. Target architecture

### 2.1 Three layers (no per-instance templates)

```
Live ERP records ──► ① CONTEXT BUILDER ──► fact sheet (typed JSON + provenance)
                                              │
                                              ▼
                        ② COMMUNICATION POLICY (config, not code)
                                              │  picks type, tone, sections, allowed data
                                              ▼
                        ③ COMPOSER (LLM prose) + ④ GROUNDING VALIDATOR
                                              │
                                              ▼
                     Draft email  ──► HITL approval queue ──► send ──► write-back to ERP + audit
```

**① Context Builder** — pure code. Turns the live records into a typed fact sheet. Every value
carries its source doctype + record id.

```json
{
  "context_id": "ctx_...",
  "type": "delivery_plan",
  "audience": { "kind": "buyer", "display": "Bella Dahl",
                "legal_entity": "EMJ Apparel Group, LLC", "po_refs": ["69785", "..."] },
  "sender":   { "company": "CORTEX FASHION (HK) LIMITED", "role": "Customer Service" },
  "facts": [
    { "key": "order_count", "value": 13, "source": "Sales Order docstatus=1" },
    { "key": "order_book",  "value": 281041.66, "unit": "USD", "source": "sum(Sales Order.grand_total)" }
  ],
  "records": [ { "so": "...", "po": "...", "qty": 0, "delivery_date": "...", "value": 0.0 } ],
  "window": { "from": "2025-09-09", "to": "2026-03-09" },
  "provenance": ["Sales Order", "Sales Order Item", "Sales Invoice"]
}
```

**② Communication Policy** — a registry keyed by intent in `backend/email_engine.py`
(`AUDIENCE_BY_INTENT`, `ROLE_BY_INTENT`, `FORBIDDEN_TEXT`, `MAX_ROWS_INLINE`, and the
`_COMPOSERS` dispatch). Adding a new email type = adding one intent + one composer function,
not one hard-coded template per action. (Externalising this to a YAML file is a P1 nicety;
it stays Python today so it is type-checked and has no runtime file dependency.)

```python
AUDIENCE_BY_INTENT = {INTENT_DELIVERY: "buyer", INTENT_STATEMENT: "buyer",
                      INTENT_RFQ: "supplier", INTENT_DATA: "internal", ...}
ROLE_BY_INTENT     = {INTENT_DELIVERY: "Customer Service", INTENT_STATEMENT: "Accounts Receivable", ...}
FORBIDDEN_TEXT     = ("KOGO", "kogo", "Control Tower", "control tower")
```

**③ Composer** — LLM writes the prose, guided by the fact sheet + policy. Deterministic code
renders the tables/totals so arithmetic can never drift. The LLM is *not* allowed to supply
numbers; it only writes sentences around the given facts.

**④ Grounding Validator** — the part that makes the email "based on the context itself".
Before a draft can be approved:

1. Extract every number, date, currency and proper noun from the generated text.
2. Each must appear in the fact sheet (or a small whitelist: `USD`, days of week, etc.).
3. Reject the draft if any fact is unsourced, or if a policy `forbidden_text` appears.
4. Store the fact sheet next to the draft → the email is auditable and reproducible.

> Result: the email can never invent a quantity, price, date, invoice number or customer name,
> because the validator would fail it.

### 2.2 Connected company mailbox

Two directions, both logged back onto the ERP record.

**Outbound**
| Step | Component | Notes |
|---|---|---|
| Draft | Composer | fact sheet + policy |
| Review | HITL queue | approve / edit / reject, with the fact sheet shown |
| Send | Mail connector (Gmail / Microsoft Graph / IMAP) | from the company identity, threaded |
| Write-back | ERP + local audit | `message_id`, sent-at, approver, fact-sheet id |

**Inbound** (phase 2 — read-only first)
| Step | Component | Notes |
|---|---|---|
| Sync | Mailbox connector | dedicated label/folder, incremental sync |
| Classify | Document classifier | PO / PO amendment / GRN / packing list / remittance / query |
| Extract | OCR + parser (PO PDF, XLSX) | customer, PO no., style, size, qty, price, date, currency |
| Match | Entity resolver | find Client PO Evidence / Sales Order; amendment vs new |
| Diff | Change detector | qty, price, date, size-ratio, cancellation |
| Route | Exception queue | anything low-confidence or conflicting → human |
| Act | Draft response | acknowledgement / revision note → composer → HITL |

### 2.3 Data model additions (local state only — ERP stays read-only for now)
- `email_draft` — draft id, type, fact_sheet_json, subject, body, status, approver, sent_at, message_id.
- `mail_message` — direction, from, to, thread_id, subject, body, attachments, linked SO/PO, parse_confidence.
- `erp_exception` — issue type, source message, proposed change, old→new values, owner, SLA due, status.
- `comms_policy_version` — which policy version generated each email (tone changes are auditable).

---

### 2.4 Guardrails implemented in P0 (from the 2026-10-01 adversarial review)

Generation is **blocked** (returns `blocked: {code, message}` and `email: null`) — never a
best-effort guess — when any of these hold. Tests: `backend/test_email_engine.py`.

| Guard | Rule | Blocks with |
|---|---|---|
| G1 | `live == false` (ERP unreachable / empty snapshot) | `erp_unavailable` |
| G2 | recipient party ambiguous (buyer from SOs **and** invoices; supplier from POs) | `ambiguous_buyer` / `ambiguous_supplier` / `no_buyer` / `no_supplier` |
| G3 | nothing real to write about for the intent | `no_records` |
| G4 | a money total would span >1 currency | `mixed_currency` |
| G5 | draft cannot be traced to the fact sheet, even after fallback | `ungrounded` |

Correctness fixes that are not blocks:
- Receivables total uses **`outstanding_amount`**, paid invoices are excluded, and "overdue" is
  claimed **only** when the invoice `status` is `Overdue`.
- Every statement/plan carries an **`as at <date>`** stamp.
- A single-source supplier is returned with `party_status = "unconfirmed"` so the approver sees it.
- The preview context is cached ~15 s so repeated previews do not re-read the whole ERP.

## 3. Edge-case catalogue

Every row is a real scenario for a full-package apparel manufacturer. **HITL default** = what a
human must do before anything leaves the building.

### 3.1 Order / PO lifecycle
| # | Edge case | Detection | HITL default | Sev |
|---|---|---|---|---|
| 1 | New PO received | no matching PO no. | confirm match, then create SO | MED |
| 2 | Amendment — quantity change | same PO no., qty differs | **always human** (contractual) | HIGH |
| 3 | Amendment — price change | rate differs from costing | **always human** | HIGH |
| 4 | Amendment — delivery date moved | date differs | human if it breaches window | MED |
| 5 | Amendment — style / colour / size ratio | SKU set differs | **always human** | HIGH |
| 6 | PO cancellation (full or line) | cancel wording / zero qty | **always human** | CRIT |
| 7 | Duplicate PO (resend, near-identical) | hash + PO no. + 95% similarity | auto-suppress, notify | MED |
| 8 | Revision chain R1→R2→R3 | same PO no., version field | link chain, human confirms latest | HIGH |
| 9 | One PO split across SOs / factories | line-level factory split | human maps lines | MED |
| 10 | Multiple POs merged into one SO | existing SO with multiple POs | link, don't duplicate | MED |
| 11 | SKU/style not in Item master | no Item match | exception queue (unmapped style) | HIGH |
| 12 | Missing mandatory field (date/currency) | schema check | exception queue | MED |
| 13 | Foreign currency / FX | currency ≠ company currency | human confirms rate | MED |
| 14 | Size breakdown ≠ header qty | sum(sizes) ≠ header | **always human** | HIGH |
| 15 | Tolerance clause (over/under shipment %) | clause parser | store tolerance on SO | MED |
| 16 | Amendment after production started | qty already cut/sewn | **always human** (WIP impact) | CRIT |
| 17 | Amendment after invoice/shipment posted | posted DN/SI exists | **always human** (credit note path) | CRIT |
| 18 | Reference collision — same PO no., different style | PO no. reused | **always human** | HIGH |
| 19 | Customer name variants / brand vs legal entity | fuzzy match | resolve to one canonical party | HIGH |

> Real precedents already in this ERP: BTSE-00444 (C9307-U70-630 whose workbook header says
> C1619-U44302) is an unresolved source conflict; `Bella Dahl` vs `EMJ Apparel Group, LLC`; and
> three spelling variants `BELLA DAHL / BELLADAHL / BELLADHAL`.

### 3.2 Shipment / delivery
| # | Edge case | Detection | HITL default | Sev |
|---|---|---|---|---|
| 20 | Partial shipment | multiple DN vs one SO | auto-draft, human approves | MED |
| 21 | Over-shipment beyond tolerance | shipped > ordered + tol | **always human** (approval email) | HIGH |
| 22 | Under-shipment | shipped < ordered − tol | human decides short-close vs re-run | HIGH |
| 23 | Split across vessels/dates | >1 ship_via / date | track per shipment | LOW |
| 24 | Delivery date slip | plan date > promised date | draft delay notice → human | HIGH |
| 25 | Buyer requests expedite | inbound keyword | human + production check | MED |
| 26 | Buyer requests hold/defer | inbound keyword | **always human** | HIGH |
| 27 | Packing list qty ≠ shipped qty | doc vs record | exception queue | HIGH |
| 28 | Shipment doc set incomplete | manifest check | exception queue | MED |
| 29 | Wrong style shipped | DN item ≠ SO item | **always human** | CRIT |

### 3.3 Finance
| # | Edge case | Detection | HITL default | Sev |
|---|---|---|---|---|
| 30 | Invoice ≠ PO price | SI rate vs PO rate | **always human** | HIGH |
| 31 | Short / partial payment | paid < invoice | human decides chase vs allowance | HIGH |
| 32 | Payment in different currency | currency mismatch | human confirms | MED |
| 33 | Remittance with no / unknown reference | no invoice match | exception queue | MED |
| 34 | Overdue reminder cadence | ageing buckets | L2 auto after policy set | LOW |
| 35 | Credit / debit note, discount | document type | **always human** | HIGH |
| 36 | Duplicate payment | same ref twice | auto-flag, no auto-reverse | HIGH |
| 37 | Invoice dispute from buyer | inbound keyword | **always human** | HIGH |

### 3.4 Quality / fabric / production
| # | Edge case | Detection | HITL default | Sev |
|---|---|---|---|---|
| 38 | Fabric inspection FAIL | result = FAIL | draft claim, human sends | HIGH |
| 39 | Inconclusive lab test | result not stated | data-request email → human | MED |
| 40 | Production shortfall vs plan | packed < plan | human decides re-plan | MED |
| 41 | Trim / material shortage | MR not converted | reorder draft | HIGH |
| 42 | Fabric/trim substitution | BOM consumption mismatch | **always human** (buyer approval) | HIGH |

### 3.5 Mailbox / communication mechanics
| # | Edge case | Handling |
|---|---|---|
| 43 | Reply arrives in an existing thread | append to thread, never start a new mail |
| 44 | Multiple recipients / CC (buyer + agent + forwarder) | recipient rules per policy, CC only if on the record |
| 45 | Bounce / wrong recipient | suppress + exception queue |
| 46 | Auto-reply / out-of-office loop | detect headers, do not loop |
| 47 | Non-English inbound | detect language, human-approved translation |
| 48 | Buyer answers an automated mail with a question | route to human, never auto-answer |
| 49 | Reference collision between two buyers | party-scoped matching, never global |
| 50 | Phishing / spam in the mailbox | quarantine, never parse into ERP |
| 51 | Large / PII attachment | size + sensitivity guard, store by reference |
| 52 | Send at wrong local time / holiday | send-window + buyer time-zone guard |

---

## 4. HITL (Human-In-The-Loop) model

**Yes — HITL is mandatory, and it is tiered by consequence, not by email type.**

### 4.1 Autonomy ladder
| Level | Name | Behaviour | Applies to |
|---|---|---|---|
| **L0** | Observe | read-only, no drafts | everything today |
| **L1** | Draft & approve | every email human-approved before send | **default start state** |
| **L2** | Approve-on-exception | low-risk types auto-send; money/qty/date/cancel always human | after trust ramp |
| **L3** | Auto with guardrails | auto-send inside policy + limits, human reads log | mature types only |
| **L4** | Autonomous | no human | **not proposed** for customer mail |

### 4.2 Hard rules (never auto-send, at any level)
- Any change to **quantity, price, delivery date, or cancellation**.
- Any email that **admits fault, offers a discount, or commits a date** not already in the ERP.
- Any **first-time** email of a new type (trust ramp: first N sends are human-approved).
- Any draft whose **grounding validator fails** or whose **parse confidence < threshold**.
- Any draft involving a **new customer or unmatched PO/reference**.
- Anything over a **value threshold** (suggest USD 50,000 per order).

### 4.3 Approval UX
- One **Approval Queue** screen: draft + fact sheet side by side, `Approve / Edit / Reject`.
- Editing sends it back through the validator before sending.
- Rejection requires a reason → feeds the classifier.
- **Maker–checker** for contractual changes (one drafts, one approves).
- **Send window** (buyer business hours), **idempotency key** (never send twice), **global kill switch**.

### 4.4 Exception queue
Every low-confidence or conflicting inbound item becomes an `erp_exception` with an owner, an SLA
date and an ageing alert. Nothing silently disappears.

### 4.5 Audit
Every email stores: fact sheet, policy version, draft, edits, approver, timestamp, message id —
so any outbound mail can be reconstructed and defended.

---

## 5. Phased roadmap

| Phase | Goal | Deliverable | Autonomy |
|---|---|---|---|
| **P0 (1–2 d)** | Replace instance templates | context builder + policy config + composer + grounding validator; emails contain no internal branding | L1 |
| **P1 (2–3 d)** | Outbound, human-approved | Approval Queue, edit, send via company mailbox, write-back to ERP + audit | L1 |
| **P2 (3–5 d)** | Inbound, read-only | mailbox sync, classify, extract, match, diff, exception queue — **no auto-replies** | L0 |
| **P3 (2–3 d)** | Threaded replies + follow-ups | acknowledgement/delay/reminder emails under L2 for a whitelist; send-window + guards | L1→L2 |
| **P4 (ongoing)** | Earn autonomy | track approval/edit rate per type; promote types to L3 only on evidence | L2→L3 |

---

## 6. Decisions needed from you

1. **Mailbox & identity** — which account sends? (Gmail / Microsoft 365 / IMAP) and what "From"
   name/address should buyers see (e.g. `Customer Service <cs@cortex…>`).
2. **Start autonomy level** — confirm L1 (everything human-approved) as the launch state.
3. **The approver** — who sits on the Approval Queue, and who is the checker for qty/price changes?
4. **Contractual rules** — shipment tolerance %, which changes must never be auto-acknowledged,
   escalation contact names.
5. **Brand & tone** — any signature block, disclaimers, or language rules Cortex wants on all mail.
6. **Scope of mailbox ingestion** — all Cortex mail, or a dedicated `operations@` / `orders@` inbox.

---

## 7. What I would do next (if you approve)

1. Build the **context builder + policy config + grounding validator** and prove it on the 7
   current action types — no new email types added, just correct generation.
2. Stand up the **Approval Queue** as an L1 draft → approve → send loop against a test mailbox.
3. Only then start **inbound parsing** on the PO PDFs already in Drive, into the exception queue.
