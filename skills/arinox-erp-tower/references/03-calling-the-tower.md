# 03 Calling the Tower

## Two ways in

| Pattern | How | Use when |
|---|---|---|
| **A. You are the KOGO agent** | `cd cortex-tower/backend && python3 functions.py <function_name> '<json params>'` prints one JSON object. Read `backend/document.md` first: a function is callable only if it has a `### \`name\`` heading there. | Chat, operator requests, automated checks. |
| **B. The app** | React calls the middleware: `POST {project: "cortex_operations_control_tower", function, params}`. | You do not do this; it is how humans use the UI. |

Every call is a **fresh subprocess**: no memory between calls, about 30 s budget, no threads, no servers. Keep each call bounded; chunk big jobs (the heavy ones, such as carton generation for a very large order, are untested at scale).

## Identity

Every `guarded` function resolves the caller (KOGO SSO, or a Tower password login) to a registered, active Tower user with roles. If not: `{"ok": false, "error": "Sign in to use this.", "auth": false}`. A client-supplied `actor` is **ignored**; the audit trail names the real user. Without KOGO SSO env (`KOGO_AUTH_VERIFIED=1`) or a login, the whole app is locked by design. Do not try to work around this; ask the user to sign in or register you.

`kogo_me` tells you who you are acting as and your Tower roles.

## The result contract

Always check `ok` first. Never read `written` or a document name from a result whose `ok` is false.

| Result | Meaning | What you do |
|---|---|---|
| `{ok: true, preview: ..., class}` | A **preview** (dry run of the Arinox Before-scripts). Nothing was written. | Read it. Show the person what would be created. Then call again without `preview`. |
| `{ok: true, run_id, class, doc, written: ["insert X name", ...], messages, scripts}` | A real write succeeded. `run_id` is the journal id (used to undo). | Report `written` and the document names. |
| `{ok: true, replayed: true, ...}` | Same `idem_key` was already done. Nothing was written again. | Treat as success. |
| `{ok: false, needs_approval: true, approval_id, class: "risky", preview}` | A human must approve. | Stop. Report `approval_id` + what it would do + the ERP page. Do **not** retry in a loop. After a manager approves, repeat the **identical** call with `approval_id`. |
| `{ok: false, denied: true, error}` | Your role may not do this. | Say which role is needed (`05`). Do not retry. |
| `{ok: false, error: "Writes of this kind are off (mode 'draft', needs 'all')", mode}` | Global write mode too low. | Tell the user; only the platform administrator changes the mode (it is the `ERP_WRITE_MODE` setting). |
| `{ok: false, conflict: true, theirs}` | Someone changed the document after you read it (optimistic lock on `modified`). | Re-read, re-plan, ask before retrying. |
| `{ok: false, locked_by}` | Another user is editing that document. | Wait or ask. |
| `{ok: false, rate_limited: true}` | More than `MAX_WRITES_PER_MINUTE` (default 120) in a minute. | Slow down. |
| `{ok: false, in_progress: true}` | The same `idem_key` is running now. | Wait, then re-read; do not duplicate. |
| `{ok: false, error, technical, run_id, undone, attention}` | The write failed and was compensated (undone). `attention` lists anything that could not be undone. | Report the sentence in `error`; surface `attention` loudly (a breach is opened for a person). |
| `{ok: false, stale: true}` | ERP unreachable. | Say the ERP is down; give no figures from memory. |
| `{ok: false, auth: false}` | Not signed in. | Ask the user to sign in. |

## The write cycle (preview → confirm → approval)

```
1. READ     order_get / deal_get / cx_doc_get            (state, blockers, doc names, `modified`)
2. PREVIEW  <write fn> {..., "preview": true}            (ok:true + preview; nothing written)
3. SHOW     tell the person what will be created/changed, in one or two lines. Wait for a yes if the action is non-trivial.
4. CONFIRM  <write fn> {..., "preview": false, "idem_key": "<stable unique key>"}
5. IF needs_approval:
            report approval_id + ERP page. STOP.
            later, after a manager decides: repeat step 4 with "approval_id": <id>
            (the request must be byte-for-byte equivalent: a changed request invalidates the approval)
6. VERIFY   re-read the order (order_get) and confirm the step state moved. Report what you saw.
```

- **Idempotency:** pass an `idem_key` on any create. A retry with the same key replays instead of duplicating. Use something stable such as `<sales_order>:<action>:<style>:<colour>`.
- **Self-approval is refused** ("The person who approves cannot be the person who asked").
- **Approvals are decided in the ERP**: `cx_approvals` lists held writes with the ERP page each belongs to; `cx_decide(approval_id, decision, in_erp=1)` records a decision that was taken in the ERP. Nobody takes their own decision inside the Tower.
- **Undo:** `cx_rollback_run(run_id)` (managers) undoes a finished run from its journal and lists what cannot be undone. Intake runs have `rollback_intake`; earlier recommendation actions have `rollback_action`.
- **Caps:** one execution creates at most 60 records (`MAX_WRITES_PER_RUN`). If you need more, split the work.

## Generic writes (when no order function fits)

| Function | Use |
|---|---|
| `cx_doc_meta(doctype)` | Fields, child tables, required and read-only fields, filtered to your role. Read it before building a payload. |
| `cx_doc_get(doctype, name)` | One document with child tables and the action buttons that apply. |
| `cx_doc_list(doctype, ...)` | A page of records with search and status filter. |
| `cx_write(op, doctype, name, data, modified, preview, approval_id, idem_key)` | `op` = `insert \| save \| submit \| cancel \| delete`. The one way a form writes. Pass `modified` from your read so a clash is detected. |
| `cx_run_script(method, params, doctype, name, preview, ...)` | Run one of the Arinox API scripts (the buttons on ERP forms). Allow-listed from the script registry; an unknown method is refused. |

Prefer the specific `order_*` and `deal_*` functions: they build the right payloads, call the right ERP script, and return the step-level answer. Use `cx_write` only when none exists.

## Field guard

You cannot set `owner, creation, modified, modified_by, amended_from, naming_series, arinox_name, idx, parent, parenttype, parentfield`. Quantity, rate, price, amount, pcs, pieces, consumption and wastage fields cannot be negative. Numbered doctypes (names built by the `arinox_name` rule, e.g. `<contract no>-<code>-<nn>`) must be created through the Tower or a script, never typed.

## Reading the ERP

Reads are GET-only. ERP `owner` / `modified_by` on records the Tower writes are the API user; the real person is in the Tower audit log and in the trace comment the Tower leaves on the document. `cx_search` is global search across documents you may read. `cx_today` is "my queue": approvals, breaches, failed syncs, inquiries waiting, overdue T&A milestones; call it first when asked "what should I do now?".

## Time and money you may state

Only state figures that came from a function result in this conversation. The Tower's chat helper (`ask_kogo`) is grounded: every number in a reply must trace to evidence. Hold yourself to the same standard.
