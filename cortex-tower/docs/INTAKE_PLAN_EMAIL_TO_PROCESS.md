# Inbox → Order — the intake agent

**Status:** **BUILT 2026-11-03** — P0–P3 live, P4 coded and tested (see §9 *As built* for the proof and
the fixtures). The plan below is kept as written so the design decisions stay readable.
**Date:** 2026-11-03.
**Scope:** the Control Tower reads the company mailbox, understands what arrived
(PO · PO revision · enquiry · invoice · remittance · query), and **starts the ERP
process** for it — in the ERP's own shape, at a human gate, draft-only.

Read with `EMAIL_AUTOMATION_PLAN.md` (outbound, P0 live) and `EMAIL_CONNECTOR_SPEC.md`
(send loop). This document covers the **inbound half and what it triggers**.

---

## 0 · One-paragraph summary

The Tower can already fetch mail, classify it, match a PO number to an order and create a
**draft Sales Order** on approval. What it cannot do is **read the attachment**, and so it has
never actually understood an order email: on the one real PO in the connected mailbox today the
line parser returns **zero lines** and cannot resolve the buyer
(`_parse_order_lines(change 6) -> []`, proven 2026-11-03). This plan replaces "guess a Sales
Order out of the email text" with a five-stage intake — **Fetch → Read → Understand → Match →
Route** — that produces a reviewed, field-by-field extraction with confidence, creates the
paper trail (`Client Purchase Order` + lines) and then starts the *right* process: PO → order
chain, enquiry → Opportunity → Cost Sheet → Quotation, revision → amendment path. Everything
stays draft-only and human-approved. The mailbox already contains six perfect test cases.

---

## 1 · Audit — is the Tower the powerhouse it claims to be?

Read live on 2026-11-03 (backend `functions.py` 4,584 lines, 50 documented functions, engine
regression suite green).

### 1.1 What is genuinely strong (keep, do not touch)

| Capability | Evidence |
|---|---|
| **Reads the ERP as it is** | 45 process objects / 8 stages / 808 rows census, 17 KPIs, 23 risks (7 critical), 27 recommendations — every number sourced to an object + filter |
| **Writes are real and gated** | 17 write slugs: 8 create actual ERP records (`Work Order`, `BOM`, `Delivery Note`, `Material Request`, `Item Price`, `Quality Inspection`), 9 raise tracked tasks; mode `off\|safe\|draft\|all`, reversible, audited |
| **Grounded AI** | `ai_nextsteps` builds an evidence pack per risk, validates every number in the answer, falls back to the deterministic action; chat panel streams the agent |
| **Grounded outbound mail** | fact sheet → intent → composer → `validate_grounding`; five block codes (`erp_unavailable`, `ambiguous_buyer`, `no_records`, `mixed_currency`, `ungrounded`); 163-line test file |
| **Inbound plumbing exists** | IMAP fetch, 6-way classifier, PO-ref extraction, order matching, change queue, approve → draft SO, dismiss, audit log |
| **The data model is honest** | the "ERP coverage" card reports 5 built-but-empty objects as empty instead of zero |

### 1.2 What is not yet a powerhouse (verified defects)

| # | Defect | Proof (2026-11-03) | Severity |
|---|---|---|---|
| A1 | **The attachment is never read** — by design ("no OCR, names/sizes only") | `inbound.py` docstring; the parsed record of `PO_AO-5644_AsterOak_new_style.pdf` holds filename + 3,805 bytes and nothing else | **blocker for this feature** |
| A2 | **The line parser finds nothing on a real PO** | `_parse_order_lines(change 6) -> ([], [], [])`; `_ITEM_RE` needs `AB123-…`, the PO says `GGI-26-SS-131` / `FAB-IL220`; `_DATE_RE` needs ISO, the PO says `15 Jan 2027` | **blocker** — approval would create a header-only SO dated today |
| A3 | **The buyer is taken from the email display name, not the paper** | `_resolve_customer_for_change -> ""`; `_derive_buyer_name` would produce `test4user`; the PO says `Aster & Oak GmbH` | critical |
| A4 | **Sync truncates and silently skips the newest mail** | with `limit=30` the AO-5644 message (uid > 183) was **not stored at all**; `limit=300` fetched it — the fetch walks ascending from `since_uid` and stops at `limit` | high |
| A5 | **Email → SO jumps the chain** | approval creates a `Sales Order` for a style that has no pack, no BOM, no cost, no quotation, no TNA — the ERP's own pre-order chain is bypassed | high (design) |
| A6 | **`Client Purchase Order` is header-only** | 10 fields, no lines child: po no, date, customer, revision flag, status, source file, linked SO, notes. Qty, rate, colour, fabric, ship date have **nowhere to go** | high |
| A7 | **No per-field confidence / exception queue** | one integer `confidence` per mail, no reason-per-field, no "what I could not read" | medium |
| A8 | **Duplicate guard is a PO-number string compare** | `AO-5644` vs `AO 5644` vs `AO-5644 R1` will duplicate; no attachment hash, no buyer scope | high |
| A9 | **Classifier is keyword-only and noisy** | of 58 stored messages, `query` 67 % on OpenAI marketing, `other` 40 % on bounces; "Sales contract" from `rohit@cortextextile.com` classified `other` at 40 % | medium |
| A10 | **Dead code / drift** | `copilot.py` (430 lines) unreachable since the streaming chat; `ask_kogo` returns a "hard-refresh the app" string; `ARCHITECTURE.md` still lists `simulate_action` and a deterministic `ask_kogo` | low (cleanup) |
| A11 | **3 functions are bridge-only** | `get_ai_next_steps`, `run_monitor`, `submit_in_erp` are not in the published allowlist — documented in `document.md`, so not a bug, but any new function inherits the same publish gate | note |

### 1.3 Verdict

The **engine** is a powerhouse: live ERP reads, 23 real risk detectors, grounded generation,
gated writes, reversible actions. The **senses** are missing: it cannot read a document, so the
"intelligent" half stops at the email body. Fix the senses (A1–A3, A6–A8) and the same engine
starts driving the process. That is this feature.

---

## 2 · Design — the intake agent

```
 mailbox ──► ① FETCH ──► ② READ ──► ③ UNDERSTAND ──► ④ MATCH ──► ⑤ ROUTE ──► ⑥ GATE ──► ⑦ ACT/REPLY
 (IMAP/Gmail)  raw msg     text+att      structured       customer      which       human       ERP drafts
               + bytes     parsed        facts + conf     PO style      process     review      + grounded mail
```

Every stage is a pure function over stored bytes; only ⑦ writes, and only drafts.

### ① Fetch
- Source: the connected mailbox. Two paths, in this order:
  1. **Google Workspace connector** (the account already connected to this workspace) — no app
     password, per-mailbox token. *P0 spike: confirm the backend can obtain the token at request
     time; it works from the agent shell today.*
  2. **IMAP + app password** — already implemented and configured (`mail_settings` row exists,
     `test4user126@gmail.com`), kept as the fallback.
- Incremental by UID / `historyId`; store the raw message **and the attachment bytes** locally
  (`backend/data/mail/<message_id>/<filename>`), never only a name.
- **Fix A4 first:** paginate until the mailbox is drained, newest-first; never stop at `limit`
  with mail still above the high-water mark. Report `fetched / skipped / remaining`.

### ② Read — attachment extraction, no third-party dependency
The runtime has **no** `pypdf`, `openpyxl`, `xlrd` or `pandas` (checked). What it does have is
`zlib`, `zipfile`, `base64`, `re` — which is enough:

| Type | Method | Status |
|---|---|---|
| Text PDF | inflate FlateDecode streams, ASCII85-aware, then scrape `Tj`/`TJ` operators | **proven today** — the AO-5644 PDF extracts clean, all fields readable |
| XLSX | `zipfile` → `xl/worksheets/sheet1.xml` + shared strings | trivial, pure stdlib |
| CSV / TSV / plain | direct | trivial |
| XLS (BIFF) | not stdlib-parseable → route to `needs_ocr`/manual, or ask for XLSX | exception |
| Scanned PDF / photo | **no OCR in the runtime** → `needs_ocr` exception with the page image stored | exception (honest) |

Store: `attachment_text`, `pages`, `parser` (`pdf-text`/`xlsx`/`csv`), `text_chars`,
`parse_ok`. A PDF that yields < 200 chars of text is a **scan**, not a document — say so.

### ③ Understand — one schema, confidence per field
One extraction pass (LLM over body + attachment text, **JSON only**) with a deterministic regex
fallback so the pipeline never depends on the model being up.

```json
{
  "document_type": "purchase_order",
  "buyer":      {"name": "Aster & Oak GmbH", "country": "Germany", "address": "...", "contact": "Jonas Feld", "email": "..."},
  "po":         {"number": "AO-5644", "date": "2026-11-01", "reference": "SS27 programme, first drop"},
  "commercial": {"currency": "INR", "rate": 590.0, "incoterm": "FOB", "named_place": "Chennai",
                 "payment_terms": "60 days from BL", "total_qty": 2000, "total_value": 1180000.0},
  "ship_date":  "2027-01-15",
  "lines": [{"style": "GGI-26-SS-131", "description": "Eucalyptus Wrap Top",
             "fabric": "interlock 220 GSM / FAB-IL220", "colour": "Eucalyptus",
             "shade": "#7C9A86", "size": null, "qty": 1200, "rate": 590.0,
             "cartons": 48, "pack": 25}],
  "claims": ["wrap tie stitched down at the side seam"],
  "quality": {"aql_major": 2.5, "aql_minor": 4.0},
  "asks": ["confirm the ship date today", "lab dip within ten days"],
  "confidence": {"po.number": 0.98, "lines[0].qty": 0.95, "ship_date": 0.9, "lines[0].size": 0.0},
  "missing": ["size grid", "fabric item code", "colour style codes"]
}
```

**Arithmetic gates** (must tie, or the field is unread):
`Σ lines.qty == total_qty` · `rate × qty == total_value` · `Σ colour qty == total_qty` ·
`Σ size qty == colour qty` when a grid is present · `ship_date > po_date`.

**Never invent.** A null plus a reason is a correct answer. `lines[].size = null` on this PO is
the honest reading — the paper carries colours and cartons, not sizes.

### ④ Match — resolve to the ERP, and say how sure you are
| entity | method | on failure |
|---|---|---|
| Customer | exact name → legal-name normalise → email domain → fuzzy (≥ 0.85) | `new_buyer` proposal, never auto-create without approval |
| Client PO | normalised `AO-5644` (strip spaces/dashes, drop `R\d` suffix) + buyer + style hash | duplicate vs revision decision |
| Style | `Item` template by style code; variants by size | `new_style` → template + one SKU per size (blocked if no size grid) |
| Fabric | `Item Mapping` (customer + buyer code → our item); fallback text search on composition/GSM | `unmapped_fabric` exception |
| Currency | `Currency` + `Currency Exchange` for INR→company | **blocked**: INR has no exchange rate row today |
| Country / territory | `Country` + `Territory` | default |

### ⑤ Route — the process that gets started depends on what arrived
| inbound | process started (all drafts) | stops at |
|---|---|---|
| **New PO** | `Client Purchase Order` (+ lines, + attachment) → draft `Sales Order` (contract fields, order grid from colour/size) → `Project` + TNA intake → draft FR/TR **only if** BOM + consumption exist | contract submit, price, quantities |
| **PO revision** | CPO revision chained (`is_revision`, supersedes) → proposed changes to the SO (qty/price/date/size) shown as a **diff**, never applied silently | every changed field |
| **Enquiry / no PO** | `Opportunity` → draft `Cost Sheet` (if the rate card allows) → draft `Quotation` at the locked price (Phase A, A0→A2) | costing gate, margin floor |
| **Invoice / remittance** | match to `Purchase Invoice` / `Payment Entry`; propose reconciliation | posting |
| **Query / other** | change queue + task, as today | — |

Two rules the chain already has and this must respect: **a pack that is superseded blocks
pricing**, and **a non-buyer BOM line must be confirmed before a TR is released**. Intake never
runs around a gate.

### ⑥ Gate — one screen, one decision
The **Intake card** (new tab, or the top of Inbox):

```
┌ source ──────────────────────┬ extracted (confidence) ────────┬ will create ──────────┐
│ email headers + body         │ Buyer      Aster & Oak GmbH 0.9 │ Customer   (new)      │
│ [ page 1 of the PDF ]        │ PO         AO-5644          0.98│ Client PO  AO-5644    │
│  text layer, searchable      │ Style      GGI-26-SS-131    0.95│  + 2 lines            │
│                              │ Qty        2,000 ✓ = Σ cols     │ Sales Order (draft)   │
│                              │ Rate       INR 590  ⚠ no FX row │ 2 items, 2 colours    │
│                              │ Ship       2027-01-15       0.90│ Project + TNA         │
│                              │ Size grid  — not on the paper   │ blocked: size grid    │
└──────────────────────────────┴────────────────────────────────┴───────────────────────┘
  [ Simulate ]  [ Approve → create drafts ]  [ Edit fields ]  [ Reject + reason ]
```

- **Simulate** shows the exact ERP payloads without writing (dry run).
- **Approve** writes drafts only; every created record carries
  `custom_source_key = mail:<message_id>:<attachment_sha256>` so a re-sync is a no-op.
- **Edit** lets the operator fix a field before creation — and the edit is stored with the
  original value (training data + audit).
- A blocked field (no size grid, unmapped fabric, missing FX) does **not** block the whole item;
  it blocks the specific object and is listed as "needs your answer".

### ⑦ Act / reply
- Create the drafts, then compose the **acknowledgement** through `email_engine` from the fact
  sheet — answering only what the mail asked, with numbers that exist in the ERP (ship date,
  lab-dip lead time from `Item.custom_fabric_lead_time_days` when present, PO echo).
- Send = existing approval queue (L1). On send, stamp the CPO with `message_id`.

---

## 3 · Data model

### 3.1 ERP (additive, `build/o2p_build/` style, idempotent)
`Client Purchase Order` gains:

| field | type | why |
|---|---|---|
| `lines` → **`Client Purchase Order Line`** (new child) | table | style, description, fabric, buyer_colour, shade, size, qty, rate, currency, amount, cartons, pack_size, ship_date, line_no, source_page |
| `buyer_po_date`, `currency`, `incoterm`, `named_place`, `payment_terms_text` | Date/Link/Select/Data/Small Text | the commercial block of the paper |
| `total_qty`, `total_value` | Float/Currency | tie-out against the lines |
| `ship_date` | Date | what the buyer locked |
| `season`, `buyer_reference` | Data | "SS27 programme, first drop" |
| `source_message_id`, `source_attachment`, `parse_confidence`, `intake_status` | Data/Attach/Float/Select | provenance + the gate |
| `supersedes` / `superseded_by` | Link | the revision chain (A8) |

Nothing is written to `Sales Order` that it cannot legally carry (RULES 01 #95: `Sales Order`
refuses new custom fields on this instance — the order grid must use existing
`custom_size_colour` / `Order Size Colour`, and any fact without a home is stated in the report,
never forced).

### 3.2 Local SQLite (decision state only)
| table | holds |
|---|---|
| `mail_attachment` | message_id, filename, mime, bytes_path, sha256, parser, pages, text_chars, text |
| `intake_run` | message_id, attachment_id, route, payload_json (the §3 schema), confidence_json, missing_json, status, created_refs, decided_by, decided_at |
| `mail_message` (extend) | `route`, `parse_json`, `parse_ok`, `needs_ocr` |
| `intake_field_edit` | run_id, field_path, original, corrected, actor — the learning record |

---

## 4 · Guardrails (inherited from the outbound policy, plus intake-specific)

1. **Draft-only.** No submit, no cancel, no amendment of a posted document, ever, from intake.
2. **Nothing invented.** Missing = null + question. Arithmetic gates must tie.
3. **Idempotency.** `source_key` unique; re-sync, re-approve and a duplicate email are all no-ops.
4. **One buyer, one currency.** An order spanning two currencies is split or blocked (`mixed_currency`).
5. **Duplicate vs revision** is decided by PO number **and** buyer **and** style set — never the
   number alone; an identical attachment hash is always a duplicate.
6. **Low confidence never auto-creates.** `< 0.70` on a field that becomes a record field → the
   operator must confirm; `< 0.50` → treated as unread.
7. **Kill switch + autonomy level** as per `EMAIL_AUTOMATION_PLAN.md §4` — start at **L1**
   (human approves every intake), never above L2 for qty/price/date.
8. **Every intake is replayable**: raw mail + bytes + payload + edits + created refs, in one row.

---

## 5 · Test plan — the mailbox is already the fixture set

Six real cases sit in the connected inbox (verified 2026-11-03):

| fixture | teaches |
|---|---|
| **PO AO-5644** `Aster & Oak GmbH`, PDF, new style, INR, colours 1200/800, ship 15 Jan 2027, claims, "confirm today" | new buyer + new style + new currency + colour-only grid + a question to answer |
| **PO-69999** `Nordic Retail AB` FW26 | second new buyer, another currency |
| **PO 69785** `Bella Dahl` SS26 | existing buyer, PO number that exists in the ERP |
| **REVISED PO 69785** | revision chain, qty + date change, "always human" |
| **PO-2026-4480** `Meridian Apparel Group` | third buyer |
| **PO-2026-4471** `Crestfield Fashion House` | fourth buyer |

Harness: `backend/tests/test_intake.py`
- **Extraction** — each fixture → expected JSON (hand-checked once) → field-by-field diff with
  tolerance for formatting, exact for qty/rate/date/PO.
- **Adversarial set** (built by mutating the fixtures): no qty; qty ≠ Σ colours; scanned PDF;
  resend 3 minutes later; revision with same number and no marker; INR with no FX row; unknown
  buyer; PO for a style that exists; amendment after shipment; 40 MB attachment; forwarded mail
  with two POs in the thread.
- **No-write proof** — simulate mode leaves the ERP byte-identical (count every doctype before
  and after).
- **Idempotency proof** — approve twice → one CPO, one SO, one Project.
- **Rollback proof** — every created ref removable in reverse order, verifying each delete.

---

## 6 · Phases and what each one gives you

| Phase | Work | Result you can show |
|---|---|---|
| **P0 · senses** (½ day) | fix A4 (pagination), attachment bytes + text extraction (PDF/XLSX/CSV), `mail_attachment`, mailbox token spike, fixture replay prints extracted text | "it read the PDF" |
| **P1 · understanding** (1 day) | the §3 schema extraction (LLM + regex fallback), arithmetic gates, confidence, missing list, the Intake card read-only | "it understood the order — 14 of 16 fields, here are the 2 it won't guess" |
| **P2 · process** (1 day) | `Client Purchase Order` + lines, route table, simulate → approve → draft CPO + draft SO (+ Project/TNA), idempotency, rollback, audit | "one click, the order exists in the ERP, correctly" |
| **P3 · the loop closes** (½ day) | grounded acknowledgement for the mail's own questions, send through the existing queue, stamp CPO | "it replied, and the reply only says what the ERP knows" |
| **P4 · the other routes** (1 day) | enquiry → Opportunity → Cost Sheet → Quotation; revision → diff → amendment proposal; invoice/remittance matching | the whole mailbox, not just POs |

**P0–P2 is the demo.** P3 makes it a conversation. P4 makes it a system.

---

## 7 · Decisions only you can make

1. **Which mailbox is the intake inbox** — the connected `test4user126@gmail.com` (it holds the six
   fixtures), or Cortex's real `orders@` / `cs@`? And may I use the Google connection instead of
   the stored IMAP app password?
2. **How far does a new PO go on approval?** (a) CPO + draft Sales Order — the short path;
   (b) the same **plus** draft BOMs/FR when a size grid and fabric mapping exist; (c) full chain
   including TNA. My recommendation: **(b)** — it is the difference between "a record" and "the
   process started".
3. **Extend `Client Purchase Order` with a lines child** (§3.1)? Without it the paper's qty, rate,
   colour and ship date have no home and every one of them lives only in the PDF — which breaks
   RULE 03. Recommendation: **yes**.
4. **Who approves intake** (one named role), and is L1 (everything approved) the launch state?
5. **Size grid policy** — when a PO arrives with colours only (like AO-5644), do we (i) block the
   BOM path and ask the buyer, (ii) create the style at template level and fill sizes later, or
   (iii) split the order by colour at 1 SKU per colour? Recommendation: **(i) + (ii)**: order the
   header and colour grid now, block only the per-size BOM.

---

## 8 · Not in scope (stated so it is not assumed)

- OCR of scans and photos (no OCR in the runtime; the page is stored and flagged).
- Auto-sending anything (L2+ is a later trust decision).
- Reading `.xls` (BIFF) BOM workbooks in-app — needs a converter or XLSX from the buyer.
- Purchasing-side intake (mill confirmations, GRNs) — same pattern, later.
- Multi-PO threads, split shipments, and price-revision after invoice — routed to exception, not
  automated, until the diff path is proven.

---

## 9 · As built — 2026-11-03

Everything in P0–P3 is live in the app; P4 (enquiry / revision / finance routes) is coded and
tested but only the revision and finance paths have been exercised on the real mailbox.

### What exists now

| piece | file | state |
|---|---|---|
| Document reader — PDF (text layer), XLSX, CSV, TXT/HTML; scans flagged | `backend/docread.py` | **live**, no third-party dependency |
| Understanding — deterministic extractor + LLM merge, per-field confidence, arithmetic gates | `backend/intake.py` | **live** |
| Matching — buyer (name → domain → fuzzy, free-mail excluded), PO duplicate/revision, style, fabric via `Item Mapping`, FX | `backend/intake.py :: match()` | **live** |
| Router + plan (7 routes, ready/blocked per step) | `backend/intake.py :: route()`, `intake_exec.build_plan()` | **live** |
| Executor — drafts only, ordered, stops dependants on failure, records refs | `backend/intake_exec.py` | **live** |
| Grounded acknowledgement | `intake_exec.ack_draft()` → `email_engine.validate_grounding` | **live** |
| Storage — `mail_attachment`, `intake_run`, `intake_edit`, new columns on `mail_message` | `backend/models.py`, `database.py` | **live** |
| Mailbox — drain in batches + `full=1` sweep for gaps below the high-water mark | `backend/inbound.py`, `sync_inbox` | **live** |
| 12 API functions + `sync_intake_mail` | `backend/functions.py`, documented in `document.md` | **live** |
| `Client Purchase Order` + `Client Purchase Order Line` (21 header fields, 14 line fields) | `build/o2p_build/build_cpo_intake.py` | **applied to the ERP** |
| UI — Order intake tab: queue, "what it read" (editable, confidence per field), "what it will create", the document, the reply | `frontend/src/components/IntakePanel.tsx` | **built** |
| Tests | `backend/tests/test_intake.py` | **104 assertions** |

### Proven on the real mailbox (the six fixtures)

| mail | read as | result |
|---|---|---|
| PO AO-5644 · Aster & Oak · PDF | new order · 2,000 pcs · INR 590 · 2 colour lines · ships 2027-01-15 · FOB Chennai · 60 days from BL | **approved** → Customer + CPO-01240 + Project + Task; Sales Order **blocked** (no size grid) |
| PO 69785 · Bella Dahl | new order · 1,520 pcs · USD | **approved** → CPO-01241 + Project + Task (customer reused); acknowledgement grounded |
| REVISED PO 69785 | revision · 1,860 pcs · ships 2026-12-05 | diff printed against the earlier reading (1,520 → 1,860); CPO blocked until the currency is confirmed by hand |
| PO-69999 · Nordic Retail AB | new order · 2,400 pcs · new buyer · new style | buyer and style proposed as new; **document is a scan** → flagged, not guessed |

### Edge cases that are handled (each one found by a real fixture, not imagined)

1. A PDF with **no newline before `endstream`** (ReportLab) — the first regex missed every stream.
2. A **loose row pattern** read `Purchase Order | AO-5644` as a colour line with qty 5,644.
3. **`_ITEM_RE`-style guessing**: `GGI-26-SS-131` and `FAB-IL220` are not `AB123-…`, so the old parser returned zero lines.
4. **Buyer from a display name**: `Bella Dahl Order Desk` → `Bella Dahl`; an email address is never a company.
5. **Free-mail identity**: a shared `gmail.com` sender must not resolve every buyer to the last one created.
6. **`Rs` inside "orders"** turned a USD order into INR — currency codes are now matched as words.
7. **Truncated sync**: mail below the high-water mark was invisible for ever; `full=1` sweeps the gaps.
8. **Every attachment created a card** (newsletters, logos): a run opens only for a real business document.
9. **Self-comparison in the revision diff** — a re-read compared the run with itself.
10. **Two orders from one mail**: approving the old change-queue item after the intake now points at the intake instead of creating a second header-only Sales Order.

### Deliberately not done

- **OCR** of scans and photos (no OCR in the runtime): the page is stored, flagged `needs_ocr`, and the operator types or the buyer resends.
- **`.xls` (BIFF)** workbooks: flagged with the reason and a request for `.xlsx`/`.csv`.
- **Submitting** anything, or amending a posted document — the intake stops at drafts by design.
- **Purchasing-side** intake (mill confirmations, GRNs) — same pattern, next round.

---

## 10 · Demo — a real order from Drive, end to end (2026-11-03)

The document is the client's own file, untouched:
`data/arinox_new/ARINOX ERP DOCS/1 – Merchandising/10 – Client Purchase Order/EM92420 12.11.25 CTX C7540-S99-304 PO70465.pdf`
(EMJ Apparel Group, 2 pages, 2,238 characters of text layer).

It was put into the inbox as if it had arrived by mail (`backend/seed_intake_demo.py` — same row
shape and attachment bytes an IMAP fetch produces; nothing sent, nothing written to the ERP).

### What the readers got

| | pattern reader | + the model | truth on the paper |
|---|---|---|---|
| PO / date | `EM92420` (the ref, not the PO) | **70465 · 2025-12-11** | 70465 · 12/11/2025 |
| buyer | none | **EMJ APPAREL GROUP, LLC** → `EMJ Apparel Group` | same |
| quantity | none | **250** | 250 |
| rate | **3.80** (the *fabric* price) | **USD 23.00** | GARMENT PRICE $23.00 |
| value | 950 | **5,750** | $5,750.00 |
| ship date | 2025-11-12 (the PO date, mis-read) | 2026-04-26 at 50 % → **edited by the operator** | X-Factory 04/26/2026 |
| **size grid** | 44/84/68/54 with no sizes attached | — | XS 44 · S 84 · M 68 · L 54 = 250 |
| incoterm | none | `D` (bad regex) | **DDP** (printed "DD P") |
| terms | none | 15 DAYS ROG | same |
| instructions | 1 | 8 | 8 |

The size grid is read **by column position** (`docread` keeps every string's x/y; a number 1 pt
under `XS` is XS's quantity). On this PO: 44@135 ↔ XS@136.

### What approval created

```
linked   Client Purchase Order CPO-00854   (migration already had it — NOT duplicated)
created  Item  C7540-S99-304 + -XS -S -M -L      (the style did not exist)
created  Item Price ×4 at USD 23.00
created  Project PROJ-0042
created  Sales Order SAL-ORD-2026-00055
           250 pcs · USD 23.00 · 5,750.00 · base HKD 45,141.52 @ 7.8507
           XS 44 · S 84 · M 68 · L 54   (4 lines + the size×colour grid)
           DDP Los Angeles · 15 Days ROG · dated on the PO's own date (2025-12-11)
created  Task — answer the buyer's question
blocked  BOM per size — the fabric (S99) is not mapped to one of our items
```

### What this demo exposed and fixed (each was a real defect, not a polish item)

1. **A migrated CPO would have been duplicated** — the link action did not exist.
2. **Rollback could not delete the order** — the CPO's `linked_sales_order` blocked it; rollback now unlinks first.
3. **A past ship date crashed the order** ("Expected Delivery Date should be after Sales Order Date") —
   the order is now dated on the PO's own date, and blocked when the PO date was not read.
4. **`project`, `incoterm`, `named_place`, `payment_terms_template` are mandatory** on this instance —
   the plan fills them from the paper (place = the printed ship-to city) or blocks with the reason.
5. **`set_warehouse` is mandatory for a stock line** — taken from the company's finished-goods store.
6. **FX used the app default instead of the company's ledger currency** — a USD order under CTXHK
   (HKD) was posting at 1.0; it now uses USD→HKD 7.8507 from Currency Exchange, and blocks if absent.
7. **Operators' edits were wiped by a re-read** — corrections are now re-applied.
8. **The line rate followed the header rate after a model re-read** — line prices are re-based too.

---

## 11 · The card, redesigned for the way documents actually arrive (2026-11-03)

Feedback: *"99 % of the time these come from the customer, in their format."* The first version showed
our schema and a wall of extracted text. That is the wrong way round. What a merchandiser needs is:
**what the paper says, where it says it, and what that will create** — for any layout.

**Header (always visible, no clicking):** buyer · PO · PO date · ship/X-factory date · qty · rate ·
value — then a date chain `received → PO dated → ships`, with `days PO → ship`, the lead time the paper
prints, and a warning when the ship date is already behind us. Any field a human corrected is named.

**Four tabs**
| tab | what it is |
|---|---|
| **Summary** | the facts, grouped (buyer · order · commercials · style & fabric · quality) with a confidence chip per field and click-to-correct; plus the colour/size lines and the size grid as chips; the buyer's questions and the instructions that bind production |
| **Their document** | **the customer's sheet put back where it was printed** — every string returned to its x position, page by page, with a pager and a switch to the **original PDF** |
| **What it will create** | the ordered plan, ready/blocked with reasons, and the records the approval made |
| **The reply** | the grounded acknowledgement |

**How "their format" is handled:** the reader keeps `[page, y, x, text]` for every string it extracts, so
the page can be rebuilt as the customer laid it out (columns intact) and so a size grid can be read by
*position* rather than by order. Nothing is re-flowed into a form we invented, and nothing is inferred
from a layout we do not recognise.

New in this pass, all from real documents: `lead_time_days` ("PRODUCTION LEAD TIME 40 DAYS"),
`style.yield_per_cpc` ("YIELD 3.68") and `commercial.fabric_rate` ("FABRIC PRICE $3.80") are read
separately from the garment rate — the earlier reader took the fabric price *as* the garment price.

**The original file** is fetched on demand (`get_intake_document`) as an embeddable `data:` URL, so the
card stays light and the operator can still see the buyer's own page.

---

## 12 · The chain — intake that follows a conversation (2026-11-03)

Intake used to read one mail and decide what it was. Right for the first mail, wrong for the twelfth:
a real deal is *enquiry → our offer → the pack → the BOM → go ahead*. Read as separate documents the
third mail starts a second Opportunity and the deal forks. It forked for real on 2026-11-03 — the
HARBOR & LANE enquiry approved into **one Task** because its Opportunity could not be created (the
buyer was not a Customer) and the `enquiry` plan had no Customer step to make it creatable.

### 12.1 The unit is the thread

`mail_chain` (new table) is one conversation. It is identified by the **root Message-ID** — the first
id in `References`, else `In-Reply-To`, else the message's own id — and it holds every Message-ID seen
**in or out**. Matching is on those ids: never the subject (two buyers share subjects), never the buyer
name (a buyer mails from a shared desk for a different legal entity).

```sql
mail_chain(key, subject, buyer_name, buyer_email, customer, customer_name, opportunity,
           client_po, sales_order, style_code, status, message_ids, ingested,
           reply_count, last_in_at, last_out_at)
```

`mail_message.chain_id`, `intake_run.chain_id`, `email_draft.chain_id` point into it, so "where did this
enquiry go?" is one hop from either end.

**Only mail a business document was read out of becomes a chain** — 119 mail rows produced **8** chains.
A screenshot of a bank statement is an attachment; it is not a conversation.

### 12.2 The routes now

| route | plan |
|---|---|
| `new_order` | Customer → Client PO → Style → Project → Sales Order → BOM → ack (unchanged) |
| `revision` | Client PO → revision task (unchanged) |
| **`enquiry`** | **Customer (create or reuse) → Opportunity → costing Task** |
| **`chain_reply`** | **Ingest the pack (when one is attached) → answer the buyer** |
| `finance` / `other` | as before |

`route()` hangs the chain *below* the documents: a PO or an invoice inside a live thread is still a PO
or an invoice; only mail that is not a document of its own becomes a `chain_reply`.

### 12.3 The buyer gate

* not on file at all → **create** (the step existed on `new_order` and was missing here)
* **60-85 %** like one on file → **stop and ask**. `set_intake_customer(run_id, customer=… | create=1)`
  links it or declares a different company, and re-plans. Two Customers for one buyer is how one order
  became two Client POs on the same day.

### 12.4 Replying from the Tower

`send_chain_reply` (`POST confirm=1`) sends the answer over the existing SMTP connector with
`In-Reply-To` (the last mail held) and `References` (the whole thread, oldest first). Without those two
headers a reply is a *new conversation* to every client and the chain breaks at the first answer —
proved against a stub SMTP server in `tests/test_chain.py` §I.

Grounding: every number in the text must come from the chain's records. A refusal names the offending
numbers. `enforce_grounding=0` sends anyway and stores `grounding_ok=0` plus the tokens, so the record
says which numbers were unsourced and who insisted.

The UI puts this in the card's **The thread** tab: the timeline in and out, the composer with the
recipient and the threading state, and — above it — the pack banner.

### 12.5 The pack

`chain_reply` plans **Ingest the pack** first: ready when the attachment reads as a tech pack or a BOM
(a measurement, a material list, a size spec, or a name that says so), blocked with a reason otherwise.
Pressing it (or approving the run) calls `ingest_chain_pack`, which resolves the stored file and runs
`build/phaseA/techpack.py` → `Buyer Tech Pack`, then `bom_from_pack.py` → one BOM per size, recording
every name it gets back on both the run and the chain.

It refuses — with the reason — when there is no file, no Customer, or the builder is not on disk
(`PACK_BUILDER_DIR` overrides the location), and it treats "builder said ok but named no record" as a
failure. A pack already ingested in that chain is skipped, not read twice.

Live proof: `BTP-2026-00007` created from `C2027-S84-304 - GRADE-11.05.25.xlsx`; `bom_from_pack` refused
it with *"this pack carries no fabric line — a BOM without fabric is a trim list"*; the pack was then
deleted (6 → 5).

### 12.6 Re-opening a dead end

`reopen_intake` puts an approved run back to `understood` **only when everything it created was a
`Task`** — an approval whose ERP steps were all blocked left the deal where it was. It refuses with
`has_erp_records` when a Customer, PO, order or style was made, because a second approval would double
it. `backfill_chain.py` re-plans only undecided runs for the same reason: an approved run's plan is
history, not a forecast.

---

## 13 · The buyer-enquiry register — and what we already know about an "old" style (2026-11-03)

The complaint that started this: *"this was a buyer inquiry email, it did not even sit in buyer
inquiry"*. Correct. An enquiry opened a card, was approved into an Opportunity, and then existed
nowhere a merchandiser would look. And every style in it was read as if it were new — when a buyer
re-asking for a style we made two seasons ago is the **easiest** enquiry there is, because the cost
sheet, the BOM, the pack and the last price are already on file.

### 13.1 Where an enquiry sits

New table `buyer_inquiry` and a new page, **Buyer enquiries** (under *Order intake* in the Tower):
one row per enquiry — buyer, quantity, the date they want the quote by, the styles, and where it
stands (`new → costing → quoted → won | lost`). It is built from the intake runs themselves
(`sync_buyer_inquiries`), so an enquiry appears as soon as the mail is read, not when it is approved,
and a follow-up in the same chain **adds to** the row instead of forking a second enquiry.

Per style, a verdict a merchandiser can act on:

| verdict | means | what it carries |
|---|---|---|
| **made before** | there is a `Sales Order` line for the style | last price, last order, date, plus cost sheet / BOM / pack |
| **costed** | a `Cost Sheet` or an `Item Price` exists, never ordered | the last FOB, the price list |
| **on file** | the style is in the `Item` master, never costed | item, size SKUs |
| **new** | nothing on file | nothing — price it from costing |

Sources, read live: `Sales Order` (+ its item lines), `Cost Sheet` by `buyer_style_ref`, `Item Price`,
`BOM` per size, `Buyer Tech Pack` by `style_no`, `Item` and its variants. **A read that fails is
reported in that line's `errors`** — an unreadable source must never look like "we have none".

### 13.2 Two things this had to get right

**The styles the buyer is ASKING about are the ones they wrote.** The first cut scanned the whole
attachment and read nine trim codes (`FUS004`, `TH000`, `BT301`…) and a button reference
(`#J5031-FL`) as styles — twelve "styles" on a three-style enquiry. Now the ask comes from the
subject and the body only, and the attachment is used for one thing: **completing a bare code**
(`C9533` → `C9533-U71-725`), because only the full code reaches the item master, the cost sheet and
the sales history.

**`11/09/2026` is two different days.** `intake._date_iso` defaults to day-first for every buyer, which
read this enquiry's quote-by date as 11 Sep when the buyer is in Los Angeles and meant 9 Nov — six days
away, not two months late. The convention now comes from the buyer's own country, which is on the
record, and **both readings are kept** so the card can print *"as written 11/09/2026 — m/d/y; it also
reads 2026-09-11"*.

### 13.3 The ask reaches the Opportunity

An enquiry can name three styles and the Opportunity was created with none of them on it. Now
`Opportunity.items` is filled — one `Opportunity Item` per style, with the style's `item_code` when the
item exists, and the **rate from history** when we have made it before (so `opportunity_amount` is a
real number instead of zero). A new style sits at rate 0 and waits for costing, which is the honest
state.

Live proof on the real enquiry (`HARBOR & LANE`, 3,100 pcs): `facts.styles` =
`C9112-U71-701 / C9208-U71-712 / C9533-U71-725`, three Opportunity lines, all three verdict **new** —
nothing on file. On styles we do hold: `C2027-S84-304` → **made before**, 16.30 USD, 3 orders,
5 BOMs, `CS-2026-00069`, `BTP-2026-00002`, sizes L/M/S/XL/XS; `C7540-S99-304` → **made**, 23.00 USD,
1 order, and no BOM at all (reported as none, not invented).

Tests: `backend/tests/test_inquiry.py` — **46 assertions**.

---

## 14 · One mail, many documents — and the model reads it (2026-11-03, later)

The buyer answered our quotation with **one mail carrying three POs and three BOMs**. The intake read
"the biggest attachment": one card about one PDF, two orders and every BOM dropped, silently. And the
card it did make read the PO number as `SAMPLE REQUIREMENTS: S/1 REQUIRED` — the heading at the top of
the buyer's template.

### 14.1 One run per document

`intake.doc_kind(text, filename)` classifies each attachment — from the **file name first** (buyers name
their files `HL93312 PO71242 … PO.pdf`, `… BOM.xlsx`, `… tech pack.pdf`) and from the paper when the
name says nothing. Then `_open_document_runs()`:

* every **order** document (PO / revision / invoice / remittance) gets **its own run** — an order is a
  document, and each must be able to become its own Client PO, style and Sales Order;
* the **pack** documents (BOM / tech pack) ride together on **one** card, because they are evidence for
  the styles rather than orders, with **one ingest step per file**;
* a mail with no documents still opens one body-only card (a question, a confirmation, a one-line reply);
* **one pack card per conversation**: the same three BOMs arrived twice (a forward and a re-send) and two
  cards offering the same ingest is noise — matched on the attachments' sha256.

Live, on the buyer's own mail:

```
PO cards   #9  71242 · 1,000 pcs · USD 3.20 · ships 2026-11-18
           #12 71241 · 1,800 pcs · USD 3.45 · ships 2026-11-18
           #13 71240 · 1,200 pcs · USD 3.10 · ships 2026-11-18
pack card  #14 Ingest the pack ×3 — ENQ-2027-001/002/003 …BOM.xlsx
enquiry    #7  (approved earlier) 3,100 pcs · ships 2027-02-11
```

### 14.2 The PO number can come from the file name

`HL93312 PO71242 …pdf` is the buyer naming the order, so when the paper yields no number the name is
used (confidence 0.6, `po_source: filename`). Without it a real order sits blocked on *"no PO number"*
until somebody types it.

### 14.3 The ERP's Customer name beats the page heading

The same PDF opens with `SAMPLE REQUIREMENTS: S/1 REQUIRED`, which became the buyer's name — and then the
Project name and the register line. The matched Customer now overwrites the read name, with the raw
value kept in `buyer.name_as_read`.

### 14.4 The model reads, the card is opened

The sync stays **deterministic** (four model calls inside one sync would blow the call's time budget);
the model reads the document when the card is **opened** (`get_intake` enriches, one document at a time,
`attachment_id` pinned to that run). On the same PO the model turns

```
deterministic   SAMPLE REQUIREMENTS: S/1 REQUIRED · no PO   →  Client PO blocked
model           PO 71242 · ref HL93312 · C9533-U71-725 · 2,000 pcs · USD 3.20  →  Client PO ready, 1 blocked step
```

### 14.5 The queue says which thread a card belongs to

A reply in a live conversation used to look like a brand-new deal at the top of the queue. Each card now
carries `chain_id`, `chain_mails`, `chain_customer` and `document_count`, and prints
*"in the thread HARBOR & LANE APPAREL CO. · 3 mail(s)"*.

---

## 15 · The queue is a list of conversations, not documents (2026-11-03, later)

One buyer reply carrying **three POs and three BOMs** opened six cards. Read as a queue, that is six
unrelated deals with the same subject — the kind of screen where somebody approves the wrong one.

The card is now the **mail thread**:

```
HARBOR & LANE APPAREL CO.           3 mails · 8 docs · 4 to decide · 1 approved · 2 blocked
  ├ new_order    understood    HL93312 PO71242 C9533-U71-725 PO.pdf        ⚠ 1
  ├ new_order    understood    HL93311 PO71241 C9208-U71-712 PO.pdf        ⚠ 1
  ├ new_order    understood    HL93310 PO71240 C9112-U71-701 PO.pdf        ⚠ 1
  ├ enquiry      approved      ENQ-2027-003 C9533-U71-725 BOM.xlsx
  ├ chain_reply  understood    ENQ-2027-003 C9533-U71-725 BOM.xlsx
  └ + 3 dismissed
```

* `get_intake_queue(group=1)` groups the documents by chain (`group=0` still returns the flat list).
* Opening a thread opens its **first document still waiting** — the pane is never blank.
* A dismissed duplicate stays in the thread as history, struck through, and is hidden behind
  *"+ N dismissed"* — history is not a decision waiting for you.
* The thread line also carries `mails`, `documents`, `waiting`, `approved`, `blocked steps`.

**And the top bar stopped shouting.** The `N critical risks` badge is a fact about the order book, not
about the mail in front of you; it no longer appears on *Order intake*, *Buyer enquiries*, *Inbox*,
*Outbound Mail* or *Activity*.

### 15.1 The card is a list item; the thread belongs on the right

First cut put the thread's documents *inside* the left card. That made the left column do two jobs at
once — scan and inspect — and read as noise. It is now a **master–detail** (the appster design system's
list/detail pattern, kept in the app's own tokens):

* **left** — one plain card per thread: `N mails` · `N to decide` · `N approved` · `⚠ blocked`, the buyer,
  the address, `N docs · date`. Nothing expands inside it.
* **right** — a **thread bar**: buyer, address, `N mails · N documents · last date`, and a
  `N document(s)` button that opens the list of documents *in the pane*, each row showing its route, file,
  status and blocked count. Picking one loads that document's detail below it (Summary · Their document ·
  What it will create · The thread · The reply).

---

## 16 · The site decides what is required, and nothing is made twice (2026-11-03)

The approval failed with:

```
created Client Purchase Order CPO-01242 · created 13 item(s) · created Project PROJ-0043
Sales Order: FAILED — Error: Value missing for Sales Order: Payment Terms Template
```

Two defects behind that line, both structural.

### 16.1 A required field is a fact about the DOCTYPE, not about the order

`Sales Order` marks four more fields required through **Property Setters** than the DocType
declares: `delivery_date`, `incoterm`, `named_place`, `payment_terms_template` (and `project`). The
planner did not know, so it built a payload the site then refused — **after** the CPO, the style and the
project were already created.

`required_fields(doctype)` now reads the site: DocType meta + Property Setters, minus fields with a
server default and minus the ones the framework fills (`naming_series` is assigned by Frappe even though
it is marked required — treating it as missing blocked every Project). `preflight()` then fills each one
from the record — `company`, `currency`, `incoterm`, `named_place`, `delivery_date`, `project` — and
**blocks the step with the field and the reason** when nobody can supply it:

> *payment_terms_template: the paper says "5 days from RECEIPT" and no Payment Terms Template matches it
> (the site has: 15 Days ROG). Add the template, or set it on the Customer, then approve again*

This is the difference between a Tower built for buyer 71242 and one that works for the next order:
nothing here knows the order.

Payment terms are matched on **(days, event)**: `15 Days from ROG` ↔ `15 Days ROG` is the same term;
`5 days from RECEIPT` is not. A template states when money is due, so it is never invented — the block
names the words the buyer used and the templates on file.

### 16.2 Nothing is made twice — checked against the SITE, not against a list

`find_existing()` asks the ERP whether the record already exists before any create:

| doctype | its identity |
|---|---|
| `Client Purchase Order` | the **PO number** (`po_core`, so "PO 69785" = "69785") |
| `Sales Order` | `custom_client_po` |
| `Project` | `project_name` |
| `Customer` | `customer_name` |
| `Item` | `item_code` |
| `Item Price` | **SKU + price list** (its `name` is a hash) |
| `Task` | **subject AND description** (two buyers legitimately share a subject) |

That covers a re-approval after a failure, the same PO arriving in a second mail, and the same style
being created by two orders. Re-running the failed approval now reports:

```
Client Purchase Order CPO-01242 already exists — linked, not duplicated
created 0 record(s) for the style, 13 already on file
Project PROJ-0043 already exists — linked, not duplicated
Sales Order (draft): payment_terms_template: the paper says "5 days from RECEIPT" …
Task TASK-2026-00007 already exists — linked, not duplicated
```

**zero creates.** And the card says it before the click: a step the site already holds reads
`will link CPO-01242` instead of `will create`.

---

## 17 · The whole write surface, audited (2026-11-03)

`Value missing for Sales Order: Payment Terms Template` was a class of error, so the answer is not one
patch — it is a gate every create passes, and an audit that can be re-run.

### 17.1 `backend/audit_writes.py`

It asks the site, for **every doctype the Tower writes**, which fields are required and whether the
Tower can supply them:

```
doctype                  required by the site                          resolvable
Customer                 1 field(s): customer_name                    —
Client Purchase Order    1 field(s): client_po_no                       —
Item                     3 field(s): item_code, item_group, stock_uom   —
Item Price               4 field(s): item_code, price_list, price_list_rate, uom
Project                  2 field(s): company, project_name             company
Sales Order             13 field(s) …                                  company, currency, delivery_date,
                                                                       incoterm, named_place,
                                                                       payment_terms_template, project
Opportunity              3 field(s): company, opportunity_from, party_name
Task / Supplier / Purchase Invoice / Stock Entry / Cortex WIP …
```

then walks **every stored intake plan** through the same `preflight` that approval uses, and exits 1 if a
ready step would be refused. Today: *"every ready step passes the site's requirements."*

The fields the audit lists but the resolvers do not cover are the ones each **step** supplies from the
paper (`client_po_no`, `items`, `supplier_name` …) — that is correct, and the plan walk is what proves it.

### 17.2 One gate in front of every create

`intake_exec.create_checked(doctype, payload, facts, matches)` → required fields (filled from the record,
or refused with the field named) → duplicate check (link, never twin) → create. It now sits under:

* **intake_exec** — the approval path (Customer, Client PO, Item, Item Price, Project, Sales Order,
  Opportunity, Task, and every `create_many` row);
* **writes.py** — the risk-action path, including Stock Entry and the receipt steps;
* **functions.py** — Supplier, Item, Customer, Purchase Invoice, Sales Order, Task.

And `Company` is only ever resolved to a Company that **exists on the site**: `config.DEFAULT_COMPANY` is
a label, and a Stock Entry against a company that does not exist is worse than a blocked step.

### 17.3 The one record the paper demanded

The buyer's three POs say *5 days from RECEIPT*; the site had only *15 Days ROG*. Created, by
transcription of the buyer's own words (same convention the existing template already uses):

* `Payment Term` **5 Days from Receipt** — 100 %, `Day(s) after invoice date`, credit days 5
* `Payment Terms Template` **5 Days from Receipt** — the same shape

`_payment_terms("5 days from RECEIPT")` now resolves, and all three PO cards dropped to **one** blocked
step each — the fabric map, which is real data the client owes:

```
run  9  7 steps · 1 blocked · links CPO-01242, PROJ-0043
run 12  7 steps · 1 blocked
run 13  7 steps · 1 blocked
```
