# Cortex Tower as the ERP's agent — architecture

**Written 2026-11-09.** This supersedes the "dashboard over the ERP" framing in `ORDER_TO_SHIP_PLAN.md`. Slices S0–T1 stay (they
are the hands and the senses of this design); everything built from here is judged against this document.

## 0. The correction this document encodes

1. **The product is generic.** The company documents (`Arinox AI ERP Documents - 2.zip`) are *reference material* for
   understanding how an apparel business works. No company, buyer, factory, SAM, efficiency, lead time or calendar value
   may be a default in product code, seeds or tests. Every business value is **data the customer enters or the product
   learns from that customer's own history** (Apparel Settings, masters, learned stats), with an empty/“not set yet”
   state that guides setup. See §8 (audit of what already leaked).
2. **The tower is not a screen over the ERP. It is an agent that runs the order flow for the people.** It watches, works out
   what should happen next, prepares the work, asks a person to approve what is risky, does it, and learns from the result.
   Screens are how humans supervise and correct it.

## 1. How an appster app connects to KOGO (from the skill, so we build on rails)

| Fact (source) | Consequence for us |
|---|---|
| The frontend talks only to the **middleware** (`API_BASE/common_project_api_v1`) with `{project, function, params}`; the backend is **functions run as fresh subprocesses**, no servers, no threads, ~30 s (SKILL.md) | The tower cannot run a loop inside itself. The "brain" and the "clock" must live in KOGO. |
| The middleware only calls functions that have a `### name` heading in `backend/document.md` (core-builder) | `document.md` is the agent's **tool catalogue**. Writing it well *is* designing the agent's tools. |
| **Pattern A** (core-builder): the KOGO agent itself calls the project's functions: `python functions.py <fn> '<json>'` after reading `document.md` | The KOGO agent can use every tower function as a tool, with no extra code. This is how the agent "acts from behind". |
| `_call_agent_tool(name, params)` → agent tools (OCR, web search, …), declared in `tools_used.json` (core-builder) | OCR for scanned tech packs and POs, supplier/web lookups. A missing tool returns `tool_unavailable`; the feature degrades, never breaks. |
| `_llm()` (already in `ai_nextsteps.py`): one message to the KOGO agent over `deployment_stream_kogo_os_stream`, reply streamed back (chat-module) | The tower asks the agent to reason / draft / read documents from inside a function. |
| Chat module: threads with the agent; `kogoos_getChatsAndLogs` returns **`schedule_info { first_run last_run runs_at next_run }`** (chat-module) | KOGO agents can be **scheduled**. This is the heartbeat we need (spike A0). |
| KOGO workspace **Team Tasks** (list → task → subtask, GraphQL, workspace only) (kogo-workspace) | The agent can assign work to *people* (chase a mill, call the buyer) as real KOGO tasks, instead of only showing a red row. |
| KOGO SSO + roles (`kogo_me`, users table) (core-builder rule 0) | Every agent action is attributed to a person or to "agent", and is permission-checked. |

## 2. The shape: sense → understand → decide → (approve) → act → learn

```
                 ┌──────────────────────────── KOGO ────────────────────────────┐
                 │  The Agent (LLM + skills)        Scheduler (agent runs_at)      │
                 │   reasons, drafts, reads docs     wakes the agent: heartbeat    │
                 └───────▲───────────────────────────────┬─────────────────────────┘
                         │ _llm / chat / Pattern A       │ calls functions as tools
                         │                               ▼
 ┌─────────────────── Cortex Tower (hands, senses, memory, guardrails) ───────────────────────┐
 │ SENSE      sync_changes + ERP webhooks + inbox  ──► change ledger                            │
 │ UNDERSTAND order_flow (state of every order), TNA engine (forecast, float), allocation       │
 │            (capacity), material status, risk model  ──► SIGNALS  (typed, de-duplicated)      │
 │ DECIDE     playbooks: signal ──► PROPOSAL {why, evidence, options, actions[], expected effect}│
 │            deterministic first; the LLM ranks options, explains, drafts text                   │
 │ APPROVE    Today queue; autonomy level per action class (§4)                                 │
 │ ACT        pipeline (role → mode → field guard → preview → approval → lock → TSR → ERP REST   │
 │            → journal → audit → ERP comment)   + Outbound Mail + KOGO Team Tasks             │
 │ LEARN      outcome of every proposal + actual-vs-plan → tenant-specific lead times,          │
 │            efficiency, supplier reliability → feeds the next UNDERSTAND                      │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
                         │ REST (only via the pipeline)
                         ▼
                 ERP (system of record: doctypes, Server Scripts, print, accounts)
```

**Division of labour (the rule that keeps this safe and testable):**
- **Deterministic code decides what is true** (state, dates, capacity, shortfalls, gates). It is unit-tested.
- **The LLM decides what to say and which option to prefer**, only over facts the code supplies (the existing
  `copilot.py` grounding validator applies: every number in a reply must trace to evidence).
- **Nothing the LLM writes reaches the ERP except as a Proposal** that goes through the pipeline. Email, attachment
  and ERP free-text are untrusted data (prompt-injection fence, already in the plan §2.4).

## 3. Signals and playbooks (the agent's actual work along the order flow)

A **signal** is a typed, de-duplicated finding with an owner, evidence and a due-by. A **playbook** turns a signal into a
proposal. Each is a small pure module under `backend/agent/playbooks/`, listed in a registry, each with tests. Initial set,
following the flow from the order onward (build order in §7):

| Stage | Signal (examples) | Proposal the agent prepares |
|---|---|---|
| Order confirmed | SO submitted, no Factory Allocation / no T&A | Draft allocation (allocation suggester) + draft Order TNA; one approval creates both |
| Plan | allocation infeasible vs ex-factory; PCD earlier than materials can support | the feasible alternatives (move line, split, ask buyer for new ex-factory) with the effect of each on dates |
| Samples / PP | required approval missing N days before gate; buyer comment unanswered | draft reply to buyer; resubmission task; replan if the gate will slip PCD |
| Materials | PO not placed vs requisition; ETA after PCD; inspection failed; short receipt | chase email to supplier (drafted), alternative supplier/stock from ERP, replan, **KOGO task** to the buyer-side owner |
| Production | line output below plan N days running; cut/sew imbalance; QC defect spike | reallocate to a line with free capacity, overtime/split proposal, re-forecast ex-factory, notify merchandiser |
| Subcontract | out past expected return; balance mismatch | chase draft, short-close proposal |
| Pack / inspect | final inspection fail; carton plan ≠ order qty | re-inspection / recut request, repack plan |
| Ship | cut-off in N days and packing incomplete; documents due and not given | priority list, booking change draft, document checklist tasks |
| Invoice / collect | invoice unissued after ship; payment overdue; claim opened | invoice prepare (approval), reminder draft, claim response draft |
| Cross-order | two orders overload one line; one supplier late on several orders | one proposal that resolves both, not two |
| Inbox | new inquiry / PO / revision mail | already built (intake); becomes a playbook on the same rails |

Every proposal carries: `signal`, `why` (1–3 sentences from facts), `evidence` (document refs, clickable), `options` (with
the computed effect on ex-factory / cost), `recommended`, `actions` (the exact pipeline calls), `reversibility`, and
`confidence`. The person can approve, edit, choose another option, snooze, or reject **with a reason** (the reason is data
for learning).

## 4. Autonomy and trust (configurable, safe by default)

Per **action class** and per role, an admin sets the level (Apparel Settings → Agent):

| Level | Meaning | Default for |
|---|---|---|
| L0 Inform | agent only raises the signal | everything not listed below |
| L1 Propose | agent prepares, a person approves (**the default for all writes**) | drafts, replans, allocations, emails |
| L2 Act and tell | agent performs a *safe, reversible* action and notifies | internal notes, task creation, ack replies already approved as templates, refreshing forecasts |
| L3 Autonomous | no notification | never enabled by default; admin opt-in per class, with value limits |

Hard stops regardless of level: ledger-posting submits and cancels (risky class), anything above a value limit, changes to
the buyer-facing dates, deleting. Self-approval refused. A kill switch (`agent_off`) stops all agent actions at once;
every agent write is journalled and one-click undoable where the pipeline supports it. Trust is earned from data: the
Agent screen shows acceptance rate per playbook, so an admin raises a level on evidence.

## 5. State the tower keeps (SQLite, `backend/agent/`)

`signal` (id, kind, subject doc, severity, first/last seen, state, owner) · `proposal` (id, signal, payload, state, decided
by/at, reason) · `agent_run` (id, trigger = schedule|event|manual|chat, started/finished, signals raised, proposals made,
tokens, errors) · `outcome` (proposal → what actually happened, measured later) · `learned` (tenant stats: lead time per
milestone, line efficiency per style type, supplier lateness, with sample counts) · `agent_setting` (autonomy matrix, quiet
hours, channels). `agent_run` makes the loop observable and resumable (a run is chunked to fit 30 s: sense → understand →
decide each be their own bounded call; state in SQLite).

## 6. Functions (new, all in `document.md`, all through `guarded`)

`agent_tick` (one bounded step of the loop; what the scheduler calls) · `agent_signals` · `agent_proposals` ·
`agent_decide` (approve/edit/reject → pipeline) · `agent_run_playbook` (manual, for testing a playbook on one order) ·
`agent_explain` (why this signal / proposal, with evidence) · `agent_settings_get/set` · `agent_stats` (acceptance, outcome,
accuracy of forecasts) · `agent_ask` (chat entry with page context; replaces the ERP-only copilot) · `agent_kogo_task`
(create a KOGO workspace task for a human, when SWARM_ID exists; otherwise a Today item).

The KOGO agent is also told, in `document.md`'s opening section, *how to use the tools* (read signals first, never write
without `agent_decide`, cite evidence) so Pattern A chat use behaves like the scheduled loop.

## 7. Build order (supersedes the slice order after T1; S0–T1 are done)

| Slice | Content | Gate |
|---|---|---|
| **A0 Spikes** (2 d) | (1) Can a KOGO agent be **scheduled** to call a project function (the `schedule_info` field)? How is it created, what is the minimum interval, is the call authenticated as a user? (2) Does Pattern A work for our function volume/size limits? (3) Does `SWARM_ID` exist for the real deployment (Team Tasks)? (4) Which agent tools exist (OCR)? Write `docs/SPIKES_AGENT.md`; **ask the user** where KOGO needs their action (creating the schedule is a platform step). | written answers; fallback if (1) fails = tick on open + 60 s timer + ERP webhook |
| **A1 Genericity audit** (2 d) | §8: remove company-derived defaults; empty-state setup; synthetic fixtures | `grep` gate (§8) green |
| **A2 Agent core** (5 d) | tables, `agent_tick`, signal/proposal lifecycle, Today queue = proposals, settings, kill switch, `agent_run` log, autonomy matrix enforced in the pipeline | tests: lifecycle, dedupe, L0–L3, hard stops, self-approval refused, kill switch, run resumes after a forced timeout |
| **A3 Playbooks, wave 1** (6 d) | order confirmed → allocation + T&A; T&A slip → replan options; allocation infeasible; material late vs PCD; using what S0–T1 built | each playbook: unit tests on synthetic orders + one live run on `hosted.localhost` producing a proposal and, on approval, the ERP write |
| **A4 Agent surface** (4 d) | Today = "what the agent did / needs from you"; proposal card (why, evidence, options, effect, approve/edit/reject); Agent screen (runs, acceptance, settings); Order page shows the agent's open signals and its last actions | Playwright 1440/390; no console errors |
| **A5 LLM layer** (3 d) | `_llm` wrapper with grounding validator, untrusted-text fence, drafting (supplier chase, buyer reply), `agent_ask` with page context; injection fixtures create nothing | eval set ≥ 25 questions, 0 ungrounded numbers, injection fixtures pass |
| **A6 Outcomes and learning** (4 d) | outcome capture, `learned` stats (lead times, efficiency, supplier reliability) replace static template/defaults **per tenant, once enough samples**; shown with sample counts | back-test on synthetic histories; learned values never applied below the sample threshold |
| then | the remaining order-flow steps (samples/PP, materials, cut/sew, subcontract, pack, ship, invoice) **as playbook + screen pairs**, then T&A phases T2–T6 | as in `ORDER_TO_SHIP_PLAN.md` |

## 8. Genericity audit (A1) — what is known to have leaked, and the rule

Known today (from the S0–T1 report and a grep, 2026-11-09):
- `setup/production.py` seeds **Allocation Default** with Knit Top 17.2 SAM and Woven Top 24.4 SAM taken from the company's
  bulletins, and a 65 % planning efficiency. → Seeds become **empty**; the allocation board's setup checklist asks for them;
  a "suggest from my history" action fills them from the tenant's own Operation Bulletins once they exist.
- `tests/fixtures/real_order_a.json`, `test_real_order.py` and the buyer-like strings in pre-existing tests/docs
  (`EM9xxxx`, `PO70xxx`, `CTXG…`) → replaced with **synthetic** orders (invented buyer, styles, numbers).
- Template offsets and the 33 seeded milestone types are **industry-standard defaults** (acceptable as a starting template),
  but must be marked "default template — edit to your process"; no value in them may come from one company's sheet.
- `buyer_ref.py`, `intake.py`, `inquiry.py` contain one buyer's reference formats. → turned into **configurable buyer
  reference patterns** (data in Settings), with a generic fallback.
- `tna_app/config.py` defaults (company name, currency, calendars) → empty/Settings-driven.

**Gate (automatable, in the test suite):** a test greps product code, seeds, settings JSON and fixtures for a deny-list kept
*outside* the repo (a local file listing the real buyer, factory, company, PO-number and customs-number patterns); it must
find zero hits. Real data may exist only under git-ignored `cortex-tower/backend/data/`.

## 9. Not in this design on purpose

- No autonomous writes to the ERP without the pipeline, ever. No L3 by default.
- No second source of truth for ERP data; the agent's memory holds signals, proposals, outcomes and learned stats only.
- No reliance on the agent being awake: if the scheduler is unavailable the product still works as a supervised tool
  (sync on open + timer), and says so on the Agent screen ("last agent run: 3 h ago").

## 10. Questions that need the user (recommendation first)

1. **Agent autonomy default:** L1 (propose, human approves) for all writes, L2 only for internal notes and KOGO tasks. *Recommended.*
2. **Heartbeat:** schedule the KOGO agent to run `agent_tick` every 15 min on working days (24 h for a 7-day factory; quiet hours configurable). Needs the user to create the schedule in KOGO (spike A0 tells how). *Recommended.*
3. **Human tasks:** when a signal needs a person, create a **KOGO workspace Team Task** (assignee from the document owner) as well as the Today item. Only works inside a workspace. *Recommended.*
4. **Outbound messages:** the agent may draft supplier/buyer emails; sending always needs approval (existing Outbound Mail rule). *Recommended; confirm no auto-send.*
5. **Tenant model:** answered 2026-11-09: one ERP, one tenant per install. No scheduler exists in KOGO (heartbeat is ours); Team Tasks need a workspace. See `cortex-tower/docs/SPIKES_AGENT.md`.
