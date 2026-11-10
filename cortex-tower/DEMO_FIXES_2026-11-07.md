# Cortex Tower — demo-readiness fixes (2026-11-07)

Built with the Appster skill's **Edit Flow** (E0 baseline repair → change → document). The code was
written and compiled (Python AST + pyflakes, `tsc`, `build.sh`), but **not run against the ERP or the
mailbox**. Run the checks in §6 on the platform before the demo.

The ERP on the platform has doctypes, Server Scripts and Client Scripts. **Server Scripts are off.**
The tower already carries its own copy of the 251 server scripts (`backend/tsr/`), and every write it
makes through `pipeline.execute` runs those rules inside the tower. This release routes the order
intake through that path too, so the ERP's rules still apply while the site's scripts are off.

---

## 1. Plan (in priority order)

| # | Problem (from the audit) | Fix | Where |
|---|---|---|---|
| 1 | Mail dead: password sealed with a key that no longer exists; tower said "not configured" | `dec()` now **raises** `SecretUnreadable`; every mail path answers `password_unreadable` with a sentence saying to re-enter it; the key is also written to a non-hidden file `data/secret_key.bin` so it survives zip/upload (the dot-file `.secret.key` is what got lost) | `secret_store.py`, `functions.py` (mail settings, sync, test, send, chain reply), `models.py` |
| 1b | Attachments: `.docx`, `.zip`, `.eml` refused; `.xls` refused | read through the readers `inquiry_v2` already had; `.xls` via `xlrd` when installed | `docread.py`, `inquiry_v2.py` |
| 1c | PO fields wrong when the buyer prints headers on one row and values below (Harbor & Lane) | header row + value row paired by column position from the PDF layout; those pairs are read first | `intake.py` `header_value_pairs()` |
| 1d | Inquiry proposed creating a Customer named "temporary" | plausibility rule: placeholders / mailbox roles / free-mail domains are never proposed; the step says "link or type the buyer" instead | `inquiry_v2.py` `plausible_buyer_name()` |
| 2 | Intake approval bypassed the guardrails; any role could approve; blocked steps never blocked; payloads not editable | **review → edit → confirm**: `intake_review` (every value + `review_hash`), `intake_plan_edit` (any field or row cell), `approve_intake` refuses a stale hash and refuses blocked steps unless explicitly accepted; only Merchandiser / Management / Admin; every create goes through `pipeline.execute` | `functions.py`, `cortex_api.py`, `intake_exec.py`, UI `IntakeReview.tsx` |
| 2b | Plan targeted doctypes this ERP does not have (Client Purchase Order, Buyer Tech Pack, Order Size Colour) | plan adapts to the site's DocType list: Client PO step shown as "not used on this ERP" (PO no./date ride on the Sales Order); pack ingest becomes a **Tech Pack** draft when the builder is absent; unknown `custom_*` fields are dropped | `intake_exec.adapt_to_site()` |
| 3 | Only 28 of 56 doctypes reachable; search covered 12; 3 reports missing; 14 doctypes defaulted to "shop floor" permissions | **All ERP records** menu group built from the live DocType list; search covers 33 doctypes in parallel; the 3 Query Reports are wrapped and run through the tower's SQL layer (20 reports); every doctype has a guardrail group, unknown ones are Management/Admin-only to change | `cortex_api._merged_nav()`, `docs.py`, `tsr/vendor/reports.json`, `tools/vendor_scripts.py`, `guardrails.py`, `catalog.py` |
| 4 | T&A calendar empty; read 5 doctypes that do not exist; edits never reached the ERP | evidence repointed to Sales Contract, Tech Pack, Sample Approval, PP Meeting, Fabric/Trim/Final Inspection, Cut Plan, Packing List + the ERP's own TNA Milestone rows; **draft** Sales Orders are listed (intake makes drafts); a calendar edit is written to the ERP's TNA Milestone when the order has an Order TNA (**decision: the ERP owns the plan when it has one**); with no orders at all, the bundled order is shown labelled **SAMPLE ORDER** | `tna_app/erp.py`, `cortex_api.cx_tna_push_milestone`, `tna/App.tsx` |
| 5 | White screen on an error-shaped dashboard; no error boundary | error-shaped answers are treated as "offline"; an ErrorBoundary wraps the app and each screen | `App.tsx`, `ErrorBoundary.tsx`, `cx/Shell.tsx` |
| E0 | Appster baseline: `kogo_list_users`, `kogo_add_user`, `kogo_set_user_role`, `kogo_remove_user` missing | added as thin wrappers over the tower's user store, plus `kogo_list_roles`; documented | `cortex_api.py`, `document.md` |

Also fixed while there: two names used on error paths but never defined (`json` in the pack-ingest
step, `_set_error` in mail intake), which turned a handled error into a crash.

## 2. UI changes (easier to follow)

* **Today** opens with a four-step strip — *Read the mail → Check & approve → Plan the order → Track
  in the ERP* — each step opens its screen. A **System health** panel says in plain words whether
  the ERP, the mailbox, the business rules and ERP writes are working, with the fix one click away.
  A dead mailbox also shows under "Needs you now".
* **Order intake**: "Approve → create drafts" is now **Review & approve**. The sheet shows every step,
  every field and every row the ERP will receive; any value can be changed in place; blocked steps
  are explained and must be explicitly skipped; a second "Yes, create N drafts" confirms.
  The colour/size table on the card is click-to-correct.
* **Sidebar**: the long *All ERP records* group starts collapsed and shows its count.
* **Mail settings**: a red banner when the saved password can't be unlocked; the field says
  "must be re-entered".
* **T&A**: a **SAMPLE ORDER** badge when the sample is shown; after saving a milestone the message
  says whether it was also written to the ERP.

## 3. What you must do on the platform (5 minutes)

1. Upload/replace the project with this zip (the slug and `config.js` are unchanged).
2. Open **Control → Outbound mail → Settings**, type the **Gmail app password** again, press Save,
   then **Test**.  ✅ **Done 2026-11-07** — the app password was entered through
   `save_mail_settings` and sealed with this project's key. Gmail accepted it for both IMAP
   (inbox read) and SMTP (login), and a 3-message sync completed. Only a live send is unproven. The old sealed password cannot be recovered: its key is gone. From now on the key
   is kept in both `data/.secret.key` and `data/secret_key.bin`. Better still: set the env var
   `CORTEX_SECRET_KEY` (any long random string) so the key never depends on a file.
3. Open **Order intake** and press **Sync** (or wait for the screen to read the mailbox).
4. Optional env: `INTAKE_WRITE_PATH=direct` only if the pipeline refuses a demo order for a reason
   you cannot fix in time (it skips the in-tower rules); `TNA_SAMPLE_WHEN_EMPTY=0` to hide the sample.

## 4. Demo script (suggested)

1. **Today**: show the four steps and System health (ERP live, mailbox reading, N business rules).
2. **Order intake**: open a PO mail → the card shows each value with its confidence → **Review & approve**
   → change a quantity in the Sales Order rows → the plan rebuilds → tick "create the rest" if a step is
   blocked → **Yes, create** → the drafts appear with their ERP names; **Roll back** is available.
3. **T&A Calendar**: the order (or the SAMPLE) with 61 milestones; open one, record an actual date → the
   message says where it was saved.
4. **All ERP records**: open any Arinox doctype (e.g. Size Chart, Order TNA) → list → record. ⌘K search.
5. **Reports**: run *Production summary* / *Fabric lines overdue*.

## 5. Not done / known limits

* **Scanned images (JPG/PNG/TIFF)** are still not OCR'd. The platform's OCR tool name isn't known
  here, and the skill forbids guessing one. Give the tool name and it becomes one `_call_agent_tool` call.
* **Inbound mail still uses IMAP + app password.** Moving it to the Gmail API path your order-tracker
  automation uses removes the shared secret entirely. That's the right next step after the demo.
* `.doc` (Word 97) and `.msg` (Outlook) are still refused with a clear message.
* T&A milestone push matches the ERP milestone by `milestone_type == code`, then by label. If the
  ERP's TNA Milestone Types are named differently, the edit stays in the calendar and says so.
* Running the in-tower rules on intake can refuse an order the direct REST create used to accept. That
  is the rules working, and the message names the rule. `INTAKE_WRITE_PATH=direct` is the escape hatch.
* `tools/ui_preview.py` (EPIPE after the phone pass) was not touched.

## 6. Checks to run on the platform (from `backend/`)

```bash
python3 tests/test_pipeline_guard.py     # structure: single write path, documented functions, vendored scripts
python3 tests/test_tsr_core.py
python3 tests/test_inquiry_v2.py
python3 tests/test_intake.py && python3 tests/test_intake_replay.py
python3 tests/test_engine.py
python3 functions.py get_mail_settings '{}'          # on its own this says "Sign in to use this." (see below)
python3 functions.py sync_inbox '{"limit": 5}'       # same
python3 functions.py intake_review '{"run_id": 12}'  # needs a signed-in caller (KOGO SSO env)
```

Expected test changes: `test_inquiry_v2` may have a case that expected a customer proposal from a
placeholder sender name; that now says "link or type the buyer". Any `approve_intake` test that
called it without a `review_hash` should call `intake_review` first.

**Correction to the three `functions.py` lines above.** Every guarded function now resolves the
caller (`cx_users.require`), so from a bare shell they answer `{"ok": false, "error": "Sign in to use
this."}` — that is the auth gate, not a mail fault. To see the mail state without a browser, call the
core directly from `backend/`:

```bash
python3 -c "import sys;sys.path.insert(0,'.');from database import get_session,init_db;import functions;init_db();db=get_session();r=functions.get_mail_settings(db);print(r['connected'], r.get('problem'));print(r.get('message',''))"
```

## 7. What was run for real (2026-11-07, after the code was placed in the project)

Run from a copy of the project (so the live `data/` was not touched), Python 3.12:

| Check | Result |
|---|---|
| `test_pipeline_guard.py` | 104 assertions, 0 failed |
| `test_tsr_core.py` | 96 assertions, 0 failed |
| `test_inquiry_v2.py` | 55 assertions, 0 failed |
| `test_intake.py` | 160 assertions, 0 failed |
| `test_intake_replay.py` | 29 assertions, 0 failed |
| `test_engine.py` | all regression tests passed |
| `compileall backend/` | clean |
| mail settings core | `connected: False`, `problem: password_unreadable`, message names the fix |
| `sync_inbox` core | refuses with `password_unreadable` **before** opening IMAP; no mailbox traffic |

Two tests legitimately changed, because the behaviour changed on purpose:

* `test_tsr_core` — an unknown doctype (its synthetic `Thing`) is now Management/Admin only for every
  operation, so the pipeline mechanics run as a manager and the shop-floor refusal is asserted.
* `test_intake` — the suite pins the site's DocType list (`adapt_to_site` otherwise reads it live).
  §7 now covers both shapes: a site that has Client Purchase Order, and this ERP, which does not
  (step skipped, reason names the Sales Order).

Not exercised here: anything needing a signed-in caller (`intake_review`, `approve_intake`) or the
ERP itself. The intake suite made no writes; the only instance contact is the DocType list it caches.

---

## Late session (2026-11-07, after the QA pass)

### 1. Invisible (black) inputs — FIXED
`.cx-input / .cx-select / .cx-textarea` (every field in the record workspace: Sales Orders, Sales Contracts,
Tech Packs, settings) were filled `#0c1016` — near black — while the text colour stayed the light-theme ink
`#111827`. Every form field therefore looked like an empty black box with an invisible cursor.
Now: white fill (`--cx-bg-2`), dark ink, explicit `caret-color`, hover/disabled/readonly states, white
`option` backgrounds and `color-scheme: light` on native date/time inputs. Verified in the browser
(computed `rgba(255,255,255)` fill / `#111827` text on the Sales Contract form).

### 2. ERP-driven dropdowns in the intake review sheet
* New read function **`get_intake_options(kind, q, limit)`** — `currency` (enabled currencies),
  `customer` (live search over `name` / `customer_name`), `customer_group`, `territory`. Currencies are
  memoised in-process for 10 min; a failed ERP read falls back to `DEFAULT_CURRENCY` rather than an empty select.
* `intake_review_core` now returns `options.currency` and a `buyer` block (name, email, linked customer,
  candidates), so the sheet needs no extra call to draw the dropdowns.
* `set_intake_customer` gained **`name`**: a person types the real company name and *that* becomes
  `buyer.name`, which is what the Customer step is built from. Returns `note` + the fresh `review`.
* `intake_plan_edit_core`: editing `customer_name` on any step also renames the buyer on the run, so the
  Opportunity and the Customer step can no longer disagree.
* Frontend `IntakeReview.tsx`: currency is a `<select>` of the site's currencies; the buyer is a searchable
  combobox with a pinned "create this Customer" row; a blocked buyer step opens first and shows the picker.
  Both the `party_name` field and the Customer step call the same `set_intake_customer`, so the plan is
  rebuilt against the ERP, never patched by hand.

### 3. Records created in the ERP for the demo
| Record | Value |
|---|---|
| Customer | `Bella Dahl` (Export Buyer / Rest Of The World) |
| Item | `C9043-U70-629` — Finished Garments, UOM Nos |
| Sales Contract | `SC-2026-0001` — Bella Dahl, USD, 1 style × Indigo, **1,000 pcs @ 12.50 = USD 12,500**, sizes XS 100 / S 200 / M 300 / L 250 / XL 150, FOB Nhava Sheva → Los Angeles, sea, 30 transit days, 45 days ROG, AQL 2.5/4.0, 7 clauses in `terms` |

`Sales Contract` autonames on `field:arinox_name` ("Document Name"), so that field is mandatory — there is
no naming series to fall back on.

---

## Bundle (4) merge — 2026-11-07 09:35

`cortex-operations-control-tower (4).zip` (350 files, 25.0 MB) replaced the code of this folder. It is the
same lineage (identical `config.js`, `.secret.key`, `secret_key.bin`, `sas_creds.json`) plus the new
**workspace** layer:

* New backend modules: `deals.py`, `deal_api.py`, `mailbox.py`, `models_deal.py`, `bom_reader.py`, `tests/test_deals.py`.
* **28 new functions** in `document.md` / `functions.FUNCTIONS` (164 documented in total): 17 `deal_*`,
  8 `inbox_*`, 3 `customer_*`. Nothing was removed.
* New frontend: `src/app/` — Dashboard, Inbox (threads + reply), Deals board, Deal page (6-stage wizard
  Inquiry → Costing → Quote → Buyer's answer → Contract → Sales order), Customers, Settings, `kit.tsx`, `theme.css`.
* DB: `init_db` migrates in place — `mail_message` gained `thread_key, gm_thrid, in_reply_to, cc_addr,
  direction, deal_id, label`; `email_draft` gained `thread_key, deal_id, cc`; table `deal` is created.
  The live DB was migrated with all data intact (125 mails, 15 intake runs, secrets still sealed).

**One regression in the bundle, re-applied:** its `frontend/src/cx/cx.css` was a snapshot from 08:11,
before the black-input fix, so `.cx-input/.cx-select/.cx-textarea` were `background:#0c1016` again with
dark ink (invisible text). The fixed block (white fill, `caret-color`, hover/disabled/readonly, white
`option`, `color-scheme: light` on date inputs) is restored and the bundle rebuilt. Verified in the
browser on a record form: computed fill `rgb(255,255,255)`, text `rgb(15,23,42)`.

Verified after the merge: typecheck clean, build 2,134,384 bytes, pipeline_guard 106, tsr_core 96,
inquiry 51, inquiry_v2 55, intake 160, intake_replay 29, engine, erp_contract 41, buyer_ref 47,
**test_deals 93** all pass. `test_chain` (1), `test_wip_edges` (1) and `test_wip_plan` fail exactly the same
way on the pre-merge code — they need live ERP orders, and the ERP is empty.

---

## Dead navigation — fixed 2026-11-07 10:05 (the buttons that did nothing)

**Symptom.** The workspace renders (sidebar, Dashboard, even the live Inbox badge), but clicking any
sidebar item, card button or "Open board" does nothing at all. No error, no spinner, no toast.

**Cause.** `app/Workspace.tsx` routed through the URL hash, in this order:

```js
if (location.hash !== h) history.pushState(null, "", h);   // <-- throws in the host frame
setRoute(parse());                                         // <-- never reached
```

`history.pushState` throws `SecurityError` when the document runs in a frame with an **opaque origin**
(served as `srcdoc` / `blob:` / `data:`, or `sandbox` without `allow-same-origin`). The exception aborted
`go()` before `setRoute`, so every click died silently. `parse()` made it worse: the route was re-read
from `location.hash`, so even a silent no-op write would have left the screen unchanged. The previous
shell (`cx/Shell.tsx`) survived only by accident: it called `setActive(key)` *before* `pushState`.

**Fix.** The route is React state first, the hash is a best-effort extra:

```js
const parts = path.replace(/^#?\/?/, "").split("/").filter(Boolean);
setRoute(parts.length ? parts : ["dashboard"]);  // the click always works
writeHash("#/" + ...);                            // try/catch, latches off after one failure
```

`writeHash()` in `app/Workspace.tsx` wraps `pushState` in try/catch and sets `hashWritable = false` after the
first failure, so a blocked host costs one exception, not one per click. `cx/Shell.tsx` got the same
try/catch on `pushState` + `replaceState`, and `cx/api.ts setToken` now guards `localStorage`.

**Proof.** Both builds were driven with `history.pushState`/`replaceState` replaced by throwing stubs:

| | original bundle build | this build |
|---|---|---|
| click Inbox / Deals / Customers / Settings | stays on "Dashboard" (dead) | each one navigates |

Also verified with storage blocked (`localStorage` getter throws) and in a sandboxed iframe: navigation,
the Inbox thread view ("Conversation" + Reply), the "New deal" modal (open, Escape, close) and the
Sales orders screen all work. Normal browsers are unaffected: the hash is still written, Back still works.

## "ERP records: everything comes back as an error" — fixed 2026-11-07 10:32

**Symptom.** The ERP records tab lists the record types, but opening any of them fails with
`Not found: DocType Tech%20Pack not found` (same for Sales%20Order, Purchase%20Receipt, Job%20Card ...).

**Cause.** My own routing change from 10:05 (state-first navigation, see above) split the route string
without decoding it. The cards navigate with `go("records/" + encodeURIComponent(doctype))`, so the
route segment stayed percent-encoded and the screens received `"Tech%20Pack"` as the doctype. Before the
change the route was re-parsed from `location.hash`, which decoded every segment. The same mistake hit
every other encoded route parameter at once:

| route | broken value | effect |
|---|---|---|
| `records/<doctype>` | `Tech%20Pack` | every record type with a space errored |
| `customers/<name>` | `Bella%20Dahl` | customer pages errored |
| `inbox/<thread_key>` | `mid%3A%3CCALc...%40mail.gmail.com%3E` | a conversation opened empty (the header still rendered) |

**Fix.** `go()` decodes each segment before it becomes state, and `writeHash()` re-encodes once for the URL:

```js
const parts = path.replace(/^#?\/?/, "").split("/").filter(Boolean)
  .map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
```

**Verified** (built 2,134,654 bytes, in a harness that calls the real backend functions and blocks
`history.pushState`): Sales Contract list shows SC-2026-0001, Purchase Receipt and Fabric Purchase Contract
open, Inbox conversation renders the real mail body and calls `inbox_thread` with a `mid:...` key,
`#/customers/Bella%20Dahl` shows the customer with its contract. No page errors.

Lesson: when routing moves from "parse the URL" to "route from arguments", the URL CODE/DECODE step moves
with it. Both ends must agree, and every encoded caller must be re-tested.

## BOM: three ways in — 2026-11-07 11:05

The inquiry often arrives with a BOM no machine can read (a photo, a scan, a sheet sent later, nothing at all), and
the BOM editor only let a person type rows. It now has three doors, all landing on the same style:

| door | function | what it does |
|---|---|---|
| **Upload a BOM sheet** | `deal_bom_upload(deal_id, style_key, filename, data)` | reads .xlsx / .xls / .xlsm / CSV / TSV (base64, `data:` URLs accepted, 8 MB cap in the UI) with the same reader that parses the buyer's mail attachment |
| the mail's own attachment | `deal_bom_from_mail(deal_id, style_key, attachment_id)` | the sheets already attached to this deal's mail, listed by `deal_bom_sources` |
| **Read the ERP's BOM** | `deal_bom_from_erp(deal_id, style_key)` | the default active submitted BOM of the style's Item, quantities divided by the BOM batch so they stay per garment; the material type comes off the Item's `item_group` when the description does not say it |

Behaviour worth knowing:
* The sheet's header block fills the style (Style no., Colour, Fabric) **only when those fields are empty**.
* A sheet whose `Style:` line names a different style than the deal's is accepted **and flagged**: "This sheet is for
  C9112-U71-701, but the style on the deal is C9043-U70-629 - check that you picked the right BOM."
* Failures are sentences, not codes: a photo → "photo.jpg could not be opened. Excel (.xlsx, .xls) and CSV/TSV are
  read…"; no table → "the sheet needs a header row with something like Description / Item / Qty / UOM"; no Item in the
  ERP → "The ERP has no Item for X yet…"; no BOM in the ERP → "The ERP has no active submitted BOM for Item X."
* A style already registered as a Tech Pack is refused here (its materials live in the Cost Sheet) - same rule the
  editor already had.
* Every read is written on the deal timeline ("BOM read from <source>: 11 line(s)").

Proven end to end: a real upload through the browser put 11 lines on the style (Fabric / Fusing / Thread / Trim /
Label / Packaging, buyer codes, colours, UOM, per-garment qty); the mail door read the same 11 lines and kept its
warning ("BT234 appears on 2 lines"); the ERP door was exercised against a stub (147 pcs of fabric on a 100-piece BOM
→ 1.47 per garment, rate carried). `test_deals` grew to 104 assertions, all passing.

## BOM read by the model, and the costing that stayed empty — 2026-11-07 12:00

**What happened to deal #1 (C9043-U70-629).** Its own timeline said it: `C9043-U70-629.xls: could not read a BOM
table`, 0 lines. The sheet is a layout the fixed reader's header detection did not match at that moment, so the deal
was created with an empty BOM; the Tech Pack went in with 0 materials and the Cost Sheet copied those 0 materials.
That is why Costing showed no materials - not because the mail was missed (the attachment was right there).

**1. The model door (the user's point: every buyer prints a BOM differently).**
`deal_bom_ai(deal_id, style_key, filename, data)` sends the sheet to the KOGO model as **plain text** - every row, cell
by cell, no column mapping, no interpretation - and asks for JSON only: one line per material, quantity **per garment**,
the buyer's own code, and one of the nine material types. The answer is validated before use: quantities parsed from
text ("1.47 YD" -> 1.47), unknown types mapped or set to Other, rows without a description dropped and counted, a
missing quantity kept as empty with a warning. It reuses `ai_nextsteps._llm`, the same model call the copilot already
uses, so no new key is needed - it rides the signed-in KOGO session.

Also added, because a model is not always available:
* `deal_bom_paste(deal_id, style_key, rows, source)` - paste lines, or the JSON any chat window returned, through the
  same validation (the UI has a "Paste lines" box).
* The BOM modal now reads: **Read it with AI** (primary), **Read the sheet** (the fixed reader), **Read the ERP's BOM**,
  the mail's attachments, and **Paste lines**.

**2. A BOM that arrives after the ERP documents exist now lands in them.**
`apply_bom_to_erp` writes the lines into the style's Tech Pack, then into its cost sheet as a save (deleting a document
is a bigger write than this needs, and the write gate rightly refuses it in `draft` mode). A submitted Tech Pack or a
submitted Cost Sheet is never touched; the answer says which document to amend. `deal_bom_apply` runs the same thing
for lines edited by hand.

**3. The recovery, done on the live deal.** Read the BOM from the mail attachment and applied it:
* Tech Pack `TP-2026-00003` now carries **11 material lines**
* Cost Sheet `CS-2026-00001` now carries the same **11 lines** (contrast 0.03 Yard, self 1.47 Yard, fusing 0.24 Yard,
  button, 3 labels, 2 threads, white size tab, spare button 10 Nos)
* Costing shows the materials. Price is USD 0.000 because the ERP has **no buying rates** for those materials yet -
  the ERP itself says "11 material line(s) have no rate and are costed at 0". Rates are the next human input; nothing
  is invented to fill them.

`test_deals` is now 123 assertions (19 new: model parsing, fences/prose/think traces, multi-style answers, the paste
door, the model door with a stubbed model, a submitted Tech Pack being refused).

## "C9043-U70-629.xls could not be opened" — fixed 2026-11-07 10:20 (a real .xls, and no reader on the runtime)

The user deleted the inquiry so it could be read again, and the re-read said:

    C9043-U70-629.xls could not be opened. Excel (.xlsx, .xls) and CSV/TSV are read; a PDF, a photo or an
    old .xlsb has to be uploaded as a sheet or typed in.

Same sheet produced the same thing at mail-ingest, recorded on the attachment row as
`legacy_xls_not_readable - this server has no .xls reader; ask the buyer for .xlsx or .csv`.

**The diagnosis, from the app's own records, not a guess.** The file is fine (41,984 bytes, OLE2/BIFF8, the buyer's
STY360 "Cost Sheet" export). Both readers imported `xlrd` and nothing else, and **the machine that serves the app
cannot import `xlrd`** - while a developer shell can, which is why `read_bom` returned 11 lines when the same bytes
were read by hand minutes earlier. The attachment error string is emitted only from the `ImportError` branch of
`docread.read_xls`, so the runtime had already told us, in writing, that it has no .xls reader. "Ask the buyer for
.xlsx" is not a fix: the buyer sends what their system prints.

**The fix: read .xls with no third-party package at all.** New module `backend/xlsread.py`:

* `_Cfb` — the Compound File Binary container: header, FAT, DIFAT chain, directory, mini stream, mini FAT. Enough to
  hand back the `Workbook` stream.
* BIFF8 records that carry cells: `LABELSST`, `LABEL`, `NUMBER`, `RK`, `MULRK`, `FORMULA` (+`STRING`), `BOOLERR`,
  `BOUNDSHEET`, and the `SST` shared-string table **including strings split across `CONTINUE` records**, where each
  continuation opens with its own option byte that can flip compressed/UTF-16 mid-string.
* Refuses what it cannot read (BIFF older than 97, a photo, an xlsx renamed .xls) with `XlsError` - never an empty
  sheet, because an empty sheet reads as "no BOM here".

Wiring: `bom_reader.sheet_rows` and `docread.read_xls` now try `xlsread` first (pure Python, so every machine reads
the same file the same way) and fall back to `xlrd` only for a pre-97 BIFF. `docread`'s refusal message now only
appears for those old files, and it names the real reason.

**Verified.** `xlsread` output is compared cell-for-cell against `xlrd` on the real sheet: identical, 54 rows,
including the header block (`Style:` C9043-U70-629, `Color:` CLCPW), the ragged STY360 table, and the numbers
(0.03 / 1.47 / 0.24 per garment). With `import xlrd` forced to fail — the runtime's condition — `read_bom` returns
the same **11 material lines**, and the full "start the inquiry from the inbox" path on a copy of the database gives
"1 style(s), 1 BOM sheet(s) read" instead of "0".

**The live inquiry is right again.** The deal the user re-created was left in place and its BOM read through
`deal_bom_from_mail` (the same function the mail door uses): 11 lines on style C9043-U70-629, `C9043-U70-629.xls`
as the source, the double `BT234` button line flagged (1 + 10 Nos, kept as the buyer wrote it), and the stale note
"could not read a BOM table" cleared. No ERP write happened: the style has no Tech Pack yet, and `apply_bom_to_erp`
returns early in that case. `TP-2026-00003` / `CS-2026-00001` from the deleted inquiry are still drafts in the ERP
and are untouched.

`tests/test_xls.py` is new (32 assertions, fixture `tests/fixtures/BOM_C9043-U70-629.xls`): the container, the cells,
the equality with `xlrd`, the BOM read **with xlrd blocked**, `docread` text, and the three refusals. Whole suite
re-run in both environments — everything passes except the three known data-shape failures (`test_chain` pack builder
absent, `test_wip_edges` / `test_wip_plan`: the ERP holds 0 sales orders).

## "The BOM has all the info — why are you asking the user?" — fixed 2026-11-07 10:35

The user read the inquiry page and asked the obvious question: the buyer's sheet prints the style's description, its
colour, its fabrication and the whole size range, so why is the app offering empty boxes and asking a person to type
them? And why is the BOM only behind a button?

**Two real defects behind it, both in the model path (the reader the user asked for).**

1. **The model was shown a cut-down sheet.** `bom_reader.grid_text` laid every row out into the first **16** columns.
   This buyer's STY360 export puts `UOM` in column 31 and `Quantity Required` in column 33, so the model was asked for
   per-garment consumptions from a sheet in which every consumption had been cut off. It answered `null` for all 11
   lines - honestly - and then the reader had no quantities at all. The grid now **drops columns that are empty on
   every row and keeps the rest** (41 columns -> 21 fields on the widest line, all of them real data).
2. **The style's own facts were never asked for.** The prompt asked only for material rows. It now asks for
   `style_name`, `colour`, `fabric`, `sizes`, `qty` and `product_type` as well, with the rule that the sizes are
   whatever the sheet lists (a row, a column, or an "Available Sizes" heading) and that a product type must be copied
   exactly from the ERP's own list (`Knit Top, Woven Top, Bottom, Dress, Outerwear, Sleepwear`).

**Where it lands.** `deals.read_with_model` runs on the inquiry the moment it is started from the inbox: the sheet goes
to the model, and the answer's fields are merged onto the style. New `_fill_style_from_read` fills **only blanks** - a
value a person typed is never overwritten - and the timeline records which fields the sheet gave. The same merge runs
for the "Read it with AI" door in the BOM editor. `bom_from_ai` and `read_with_model` both validate with
`bom_rows_from_ai`, so nothing off-list is stored: an off-list product type falls back to the app's own
`guess_product_type` on the model's text, and `_sizes_from_ai` accepts a list, "S, M, L", "S-M-L" or a ratio object
and rejects anything that is not a size.

**A third fix, found while testing it live.** The KOGO stream injects short progress notes into the reply text
(`"item_code": "ST022",Hold tight… "material_type"`, and once `"material_typeOn it…"` as a key), which made an
otherwise perfect JSON answer unparseable. `ai_nextsteps._clean` now removes those notes (short generic words only when
they end in an ellipsis, so a description containing "reading" is untouched) and `deals._json_junk_strip` drops any
text that cannot be JSON **outside** string literals - which also repairs a note injected between tokens.

**On the inquiry page the BOM is now shown, not hidden.** The `BOM` column of the styles table is gone; in its place
each style gets a section in a new **Bill of materials** card: style number, description, a `11 lines` badge, the
source file, any warning (the double `BT234` button line), and the lines themselves - Type, Buyer code, Description,
Colour, UOM, Per garment - with **Edit BOM** opening the same editor. Verified in the rebuilt bundle at desktop and
phone widths.

**The live inquiry, read once more by the model:** style `C9043-U70-629`, description `1 POCKET CROPPED BUTTON DOWN`,
colour `CLCPW - COOL CAPRI WASH`, fabric `100% LYOCELL (F85 LIKE QUALITY)`, quantity 1,000, sizes
`XXS, XS, S, M, L, XL, XXL`, product type `Woven Top`, and 11 material lines with UOM and per-garment consumption.
Nothing left for a merchandiser to type. The five duplicate "BOM read" events my verification runs left on the timeline
were collapsed into one.

`tests/test_bom_read.py` is new (41 assertions): the grid keeps far columns, the answer is validated, blanks only are
filled, the stream noise is repaired, and the prompt asks for the style fields. A fresh `from_thread` on a copy of the
database now gives "1 style(s), 1 BOM sheet(s) read by the model" with every field populated.

## "Send the inquiry to the ERP" answered a bare `'doc'` — fixed 2026-11-07 10:55

The user clicked **Send the inquiry to the ERP** on the re-read inquiry and the whole error message was: `'doc'`.

**What it was.** A `KeyError('doc')` escaping to the UI. `pipeline.execute` stores a finished write's result **without the
document body** (`run.result = {k: v for k, v in res.items() if k != "doc"}`) and keeps only
`written: ["insert Opportunity CRM-OPP-2026-00003"]`. A second call with the **same idempotency key** is not a write, it
is a *replay* — `return {**stored, "ok": True, "replayed": True}` — and `deals.register` then read `res["doc"]["name"]`,
which only a fresh write carries.

Why the key repeated: deleting an inquiry and reading it again from the same mail gives the new deal the **same row id**
(SQLite reuses it), so `f"deal{d.id}-opp"` was literally the key of the deal that had just been deleted. Its finished run
was found and replayed, and the replay has no `doc` in it.

**Fixed in three places.**

1. `deals._written_name(res, doctype)` — the one way to read a document name out of a write answer: `doc.name` when
   there is one, otherwise the name inside `written[]`, op-aware and safe for doctypes with spaces (`insert Tech Pack
   TP-2026-00003`) and for `call …` entries. Every `res["doc"]["name"]` in the deal chain now goes through it —
   Opportunity, Tech Pack, Cost Sheet, Quotation, Sales Contract, Sales Order — and says a plain sentence instead of
   raising when a name really cannot be found.
2. `deals._attempt_key(d, what)` — the idempotency key now carries a short hash of the deal's **creation stamp**, so a
   re-created deal (same id) no longer inherits its predecessor's finished runs. Double-clicking the same deal still
   replays, which is the point of the key.
3. **A re-read no longer duplicates ERP documents.** `register` looks up what the ERP already holds for this buyer and
   this style and adopts it: an `Open` Opportunity for the same customer and the same source mail, a draft Tech Pack for
   the same customer and `style_no`, and that pack's draft Cost Sheet. The adopted pack is then **refreshed from the
   sheet we just read** (materials, description, product type, fabric, sizes, colours), and the timeline says "adopted
   … so no second one was made". Also: when the style Item already exists the ERP's "already exists" is no longer
   reported as a warning — the existing Item is simply used.

**The user's click, done for real.** `register` on the live deal: Opportunity `CRM-OPP-2026-00003` adopted, Tech Pack
`TP-2026-00003` adopted **and refreshed** (description `1 POCKET CROPPED BUTTON DOWN`, product type `Woven Top`, fabric
`100% LYOCELL (F85 LIKE QUALITY)`, sizes `XXS – XXL`, colour `CLCPW - COOL CAPRI WASH`, 11 materials), Cost Sheet
`CS-2026-00001` picked up, style Item `C9043-U70-629`, stage moved to **Costing**. ERP counts before and after are
identical: 1 Opportunity, 1 Tech Pack, 1 Cost Sheet — nothing duplicated, so the three "orphans" I kept offering to
delete are now adopted instead. Costing opens on `CS-2026-00001` with 11 materials and 15 charges; prices stay 0.000
because the ERP has no buying rates for those materials, which is the next human input.

`tests/test_register_replay.py` is new (22 assertions): the name recovery (including a doctype with a space in it, a
mismatched doctype and a `call` entry), the key changing on a re-created deal while staying stable for the same one, a
full `register` whose writes all come back replayed — the exact crash — and a full `register` that must adopt rather
than duplicate.

## "Why is everything a draft, why is the BOM in the Tech Pack, and can I confirm in the ERP?" — 2026-11-07 11:15

Three questions from the user, and one of them was a design question rather than a bug.

**1. Why everything is a draft.** Every document the tower creates is created as a draft on purpose: the write mode is
`draft`, drafts are reversible, and submitting is the step where a person takes responsibility for the numbers. The
tower can submit the **Cost Sheet** itself (Costing → *Save & submit*, `deal_cost_submit`); the **Tech Pack** it could
not submit at all — there was no door for it, and no way to reach the ERP's own screen for a document.

**2. "Why did the BOM go to the Tech Pack — the Tech Pack is different, right?"** In this ERP the Tech Pack is exactly
where the buyer's material list belongs, and the module says so itself. Read from the live site:

* `Tech Pack` has a tab **Colours & Materials** with a section break literally labelled **"Buyer BOM"** holding the child
  table `materials` (`Tech Pack Material`: material type, description, consumption, UOM, colour, buyer item code).
* The same doctype has a field **`buyer_bom_file`** ("Buyer BOM File", Attach) — the buyer's own sheet lives there.
* Costing is built from it: `arinox_tech_pack_make_cost_sheet` copies the Tech Pack's materials onto the Cost Sheet, and
  the Cost Sheet is where rates and margins go.

ERPNext's own `BOM` / `BOM Item` doctype is a **different** thing — the manufacturing BOM (per SKU, with rates and
operations, submitted, what a Work Order consumes). This site has **0** of them, and creating one now would be wrong:
there are no buying rates yet, so a manufacturing BOM would be a document full of zeroes pretending to be a recipe.

So nothing was moved. What changed is that the tower now *says* it: the Bill-of-materials card reads "These are the
ERP's Buyer BOM lines, held on each style's Tech Pack", the registered note explains the same in one sentence, and the
Costing step says "Materials come from the Tech Pack's Buyer BOM".

**3. "Can we have a Confirm in ERP button that redirects to the ERP?"** Yes, and that is now the shape of the whole
confirmation story: the tower links, the ERP confirms.

* `erp.doc_url(doctype, name)` builds the site's own page — this site serves the desk at `/desk/<slug>/<name>`
  (`/app/...` 301s to it), e.g. `https://apps.kogo.ai:9446/desk/tech-pack/TP-2026-00003`. Verified against the live
  host: unauthenticated it redirects to `/login?redirect-to=/desk/tech-pack/TP-2026-00003`, so a signed-in person lands
  on the document.
* **Inquiry step:** a green note after registration with a primary **"Confirm TP-2026-00003 in the ERP"** button per
  style, plus **Open the ERP**.
* **Costing step:** a **Confirm in the ERP** button on every style row whose Cost Sheet is still a draft, and **Open the
  ERP** in the card head. (The Cost Sheet can also be submitted from inside the tower.)
* **"In the ERP" panel:** each row now shows the live status (draft / submitted / cancelled) and an **ERP ↗** link that
  opens that document in the ERP without leaving the deal page. The row itself still opens the read-only view in the app.
* **The status comes back.** `deals.erp_status(d, db)` now writes the ERP's `docstatus` back onto the style
  (`cost_status`, new `tech_pack_status`), so after confirming in the ERP, a refresh in the tower shows *submitted* and
  the next action moves on. The ERP stays the truth; the tower only mirrors it.

Dashboard note: the confirmation is a plain link with no credentials in it (the ERP asks for its own session), so
nothing secret is put in a URL.

`tests/test_register_replay.py` gained 9 assertions (31 total): the URL rule for one- and two-word doctypes, no link
when there is no document, every document in `erp_status` carrying its page, and a document submitted in the (fake) ERP
coming back as *submitted* on the style.

## "A BOM is not a Tech Pack" — the distinction, made visible in the app (2026-11-07 11:40)

The user, correctly: *"tech pack has all the cuttings required and measurements, that is different; BOM is just what
items are required to make and how much it could require."* Right on both counts, and the app was blurring it.

**Checked against the live site, not assumed.**

* `Tech Pack` = the specification: `measurements` (Tech Pack Measurement), `sizes`, `construction_notes`, `wash_care`,
  `packing_notes`, `images`, `fit_rounds`, `tech_pack_file`. The tower never writes any of these — the buyer's sheet has
  no measurements on it, so they stay a person's job.
* The material lines go to the Tech Pack's child table `materials`, under a section break the ERP labels **"Buyer BOM"**.
  That is the ERP's home for "what the buyer says is needed" — there is **no separate Buyer BOM doctype** on this site
  (checked all 947 doctypes: the only BOM family is `BOM` / `BOM Item` / `BOM Operation` / `BOM Creator`, i.e. ERPNext's
  manufacturing BOM).
* That manufacturing `BOM` is a **different document and a later one**: submittable, one per `Item to Manufacture`, rows
  of `BOM Item` with quantity/UOM, and it is what `Work Order.bom_no` and `Job Card.bom_no` consume. The site has **0**
  BOMs and 0 Work Orders — nothing has reached production, and a BOM built now would be a recipe of zero rates.

**So the flow, in the ERP's own terms:** Tech Pack (spec + the buyer's requirement lines) → Cost Sheet (rates, charges,
price) → at production, a real `BOM` per style item, which the Work Order consumes.

**What changed in the tower (so nobody has to hold that in their head):**

* The Bill-of-materials card now says what it is: *"the requirement list: what is needed and how much … In the ERP these
  go into each style's Tech Pack on the 'Buyer BOM' tab; the pack's own spec (measurements, construction, wash & care) is
  a separate part of that document and is not touched here."*
* **A BOM now shows what an order needs, not only what a garment needs.** New column **"For 1,000 pcs"** (consumption ×
  order quantity) on every line, and a footer total per unit: for this inquiry — **1,740 Yard · 15,000 Nos · 2,000 (no
  unit on the sheet)**. The last one is honest: the buyer's sheet prints the two thread consumptions with no UOM, so the
  app says so rather than inventing "Nos".
* The registered note states the same in one paragraph, next to the **Confirm in the ERP** button.

`tests/` unchanged for this one — it is presentation over numbers already covered (`test_bom_read`, `test_deals`); the
arithmetic was checked against the ERP: 0.03+1.47+0.24 = 1.74 Yard per garment, and the Tech Pack's 11 material lines
carry the same values.

## Cleared for a re-run, and a mail with TWO documents — 2026-11-07 12:00

The user: *"remove everything of this order: C9043 — I will re-run to test it. Before that, the idea is in the mail: I
will send both tech pack and BOM. So based on that please make changes."*

### 1. Everything for that order is gone

| what | how |
|---|---|
| Cost Sheet `CS-2026-00001`, Tech Pack `TP-2026-00003`, Opportunity `CRM-OPP-2026-00003` | deleted in the ERP (children first) |
| Item `C9043-U70-629` | could not be deleted at first: *"linked with Size Chart SC-C9043-U70-629"* — the size chart was made by the Tech Pack's own style-item script. Deleted the Size Chart, then the Item. |
| the inquiry in the tower (deal #1) and the mail's link to it | deleted, with a JSON + database backup first (`backend/data/backup/deal1_cleanup_*`, `cortex_before_cleanup_*`) |

The pipeline's own `delete` op refuses without a second approver ("A manager must approve this before it runs"), and there
is one signed-in person, so these four deletions went through `erp.erp_delete_checked` and were written to `audit_log`
as `erp_delete` rows with the reason. ERP now holds 0 Opportunities, 0 Tech Packs, 0 Cost Sheets, no C9043 item.

### 2. Two documents in one mail, two different homes

The user's correction from the previous entry is now the design: **the Tech Pack is the specification** (measurement
chart, construction/cutting, wash & care, packing, size range) and **the BOM is the requirement list** (materials and how
much per garment). A real inquiry mail carries both.

* `deals.attachment_text()` — a spreadsheet keeps its columns (`bom_reader.grid_text`), anything else (PDF text layer,
  docx, csv, txt) is read by `docread`.
* `deals.documents_ai_prompt()` — **one prompt per attachment**: say what kind of document it is (`tech_pack`, `bom`,
  `spec_and_bom`, `other`) and read whichever parts are there: style fields, BOM rows, a measurement chart as
  point-of-measure → size → number, and the construction / wash & care / packing notes.
* `deals.read_with_model()` now walks **every** readable attachment and splits the answer: rows → the style's BOM
  (Tech Pack's *Buyer BOM* tab at registration), specification → `style["spec"]`.
* `deals.spec_from_ai()` validates the specification (sizes normalised, numbers only, notes with their line breaks).
* At registration the specification goes onto the **Tech Pack's own fields**: `measurements` (the ERP child table has a
  column per size — `xxs … xxl`), `construction_notes`, `wash_care`, `packing_notes`, `size_range`. Sizes the chart has no
  column for (2, 4, 6 …) are **reported, never dropped silently**.

**A defect found while testing this against the live model:** a model writing `construction_notes` emits **raw newlines
inside a JSON string**, which is invalid JSON, and the whole answer was being lost ("The model did not answer with
JSON"). `deals._json_junk_strip` now escapes control characters inside string literals (a correctly escaped `\n` is left
alone), so multi-line notes survive.

### 3. Both documents are visible on the inquiry page

New **Tech pack** card next to the **Bill of materials** card: the measurement chart (point of measure · tolerance ·
XXS … XXL), the size range, how many measurement rows, the source file, and three note blocks (construction & cutting,
wash & care, packing). The BOM card keeps the requirement view (per garment and for the order, with unit totals). Card
titles no longer get squeezed by long sub-lines.

`tests/test_tech_pack_read.py` is new (32 assertions): the control-character repair, the specification validation, the
XXS–XXL chart mapping (including sizes that cannot be charted), a mail with **two** attachments split into their two
homes, and a registration that puts the chart and the notes on the Tech Pack while leaving the BOM on its Buyer BOM tab.

## "It only read the BOM, not the tech pack" — the mail sync threw the tech pack away — 2026-11-07 12:40

Report: *"I sent an email at 04:20 pm and it only read the BOM, not tech pack. I repeat: do not please hardcode any code
or stuff or anything."*

**The tech pack was there.** Fetched the message over IMAP and looked at the raw MIME: two attachments.

| file | size |
|---|---|
| `C9043-U70-629.xls` (the BOM) | 41,984 bytes |
| `C9043-U70-629 - GRADE 06.02.26 UPDT.xlsx` (the tech pack) | **18,425,282 bytes (17.6 MB)** — the measurement specification sheet |

**Why only one arrived.** `inbound.MAX_ATTACHMENT_BYTES` was a **hardcoded 12 MB**. Over that, `parse_message` marked the
part `too_large`, and `functions.sync_inbox` did `if att.get("too_large"): continue` — the document was **skipped without
leaving a row**, so the mail looked like it had always carried one attachment. Nothing was wrong with the model, the
readers, or the tech pack: the file never reached the tower.

**Fixed, without hardcoding anything.**

1. The limit is a **setting**: `config.MAX_ATTACHMENT_MB` (env `MAX_ATTACHMENT_MB`, default 40 MB) → `config.MAX_ATTACHMENT_BYTES`.
   `inbound` reads it from config; the literal is gone (`tests/test_mail_documents.py` asserts that).
2. A document over the limit **keeps a row** with its name, size and the reason:
   *"too_large — 17.6 MB is over the 40 MB limit this mailbox keeps, so it was not read. Ask for a smaller file, or upload
   it on the deal."* A mail can never again show one attachment where the buyer sent two.
3. The base64 copy of every attachment is **no longer written into the mail row** (an 18 MB file became ~25 MB of base64
   inside SQLite on every sync; the bytes already live as one file each under `data/mail/<id>/`).
4. **New `deal_documents(deal_id)`** — what the conversation carries, file by file: name, mime, size, `readable`,
   `parsed`, and `error`. And **new `deal_read_documents(deal_id)`** — read every document on the conversation again,
   with the model deciding per file what it is (BOM / tech pack / both / other).
5. **No more silent skips in the read.** `read_with_model` used `except Exception: continue` per document; it now retries
   a malformed answer once and records an outcome per file (`kind`, `rows`, `measurements`, `error`), which
   `read_documents_again` returns and writes on the timeline: *"Read the conversation's documents: 2 file(s) … tech pack
   read for C9043-U70-629. Could not read — X: the model did not answer in time."*

**The user's mail, read properly now** (re-fetched UID 199, stored the 17.6 MB sheet, then read):

* `C9043-U70-629.xls` → kind **bom**, **11** material lines
* `C9043-U70-629 - GRADE 06.02.26 UPDT.xlsx` → kind **tech_pack**, **42** measurement rows, POM codes `T100 … T398`,
  e.g. `T100 SHOULDER WIDTH SEAM-SEAM` XXS 15 / XS 15.5 / S 16 / M 16.5 / L 17 / XL 17.5, size range `xXS-XL`,
  fabric `100% LYOCELL`, colour `COOL CAPRI`. (This pack prints no construction/wash/packing text, so those stay empty —
  the model is not asked to invent them.)

**On the inquiry page** there is now a **Documents in this mail** card: each file with its size and state (`read` /
`kept, not parsed` / `not kept` + the reason) and one **Read them again** button, which re-reads Tech Pack and BOM and
says what each one turned out to be. Plus the **Tech pack** card with the whole 42-row chart.

A **dry run** (pipeline `preview`, nothing written) of the Tech Pack save confirms the ERP accepts the payload:
42 measurement rows, 11 materials, 7 sizes, size range — so the next click on *Send the inquiry to the ERP* carries the
specification, not just the BOM.

## "Not able to save, recalculate or do anything" — the costing sent the ERP's own bookkeeping back — 2026-11-07 13:10

    Not saved: materials row 1: docstatus changes only through Submit / Cancel; materials row 2: … row 3: … row 4: …

The Costing screen was dead for every style: no save, no recalculate, no submit.

**What was wrong.** `deals.cost_save` merged the browser's edits **onto the ERP's stored child row**
(`base = dict(by_idx[idx])`). Those rows carry Frappe's bookkeeping — `docstatus`, `doctype`, `parent`, `parentfield`,
`modified`, `owner` — and sending them back is refused: `docstatus` may only move through Submit / Cancel. Only rows that
already existed hit it, which is why the message named exactly five rows on a ten-line sheet (the five the Cost Sheet
had; the extra five were lines added in the browser, with no `idx`, so they passed). It also explains why the earlier
BOM-apply saves worked: those build fresh rows and never inherit a stored one.

**The fix.** A row payload is now built from the app's whitelist only (`_MAT_FIELDS` / `_CHG_FIELDS`):
no system fields, no child `name`, **no `amount`** (the ERP computes it), numbers coerced from whatever the browser sent
(the screen showed `00.06`, `03.5`, which are strings), and a UOM that is not a real unit — the sheets print `—` for
thread — left out instead of being sent as a broken link.

**Two more things found on the way.**

* **The ERP's submit rule, in plain words.** Submitting a sheet that leaves a head at 0 without N/A answers
  *"Zero rate without N/A: Freight, Overhead, Profit, …"*. That is correct behaviour (the screen has an N/A checkbox and
  says so), but the message is now rewritten for a person: *"The ERP needs a rate for every cost head, or N/A ticked:
  Freight, Overhead, Profit… Give them a rate, or tick N/A for the ones this style does not use, then save."*
* **A stream note inside a value.** A description had arrived as `18L 2 HOLE SHELL BUTTONCrunching…S (ART # B56-0213)` —
  the live stream dropped `Crunching…` mid-word. `_clean` now removes a capitalised word ending in an ellipsis when it is
  **glued** to the text before it (`BUTTONCrunching…S` → `BUTTONS`), while leaving `HPS ...` and `DETAILING…` alone.

**Verified on the live sheet** (`CS-2026-00001`, style `C2027-S84-304`, 10 materials + 15 charges): preview, save and
submit all answer; the quoted price persists; a submitted sheet refuses further edits with a sentence that says so. My
save used an invented 6.5 to prove the path and was immediately put back to the value that was there (0).

`tests/test_cost_save.py` is new (16 assertions): no system field in any row, no `amount` sent, text numbers coerced, a
dash UOM dropped, and save → submit → locked round trip on the fake site.

## "Not recorded in the negotiation: rounds row 1: docstatus changes only through Submit / Cancel" — 2026-11-07 13:45

Same defect as the costing, two hours later, in a different screen: the buyer's answer.

`deals.record_reply` read the stored negotiation (`rounds = list(cur.get("rounds") or [])`), appended the new round and
sent **the whole list** back. The stored round arrives from the ERP carrying `docstatus`, `doctype`, `parent`,
`parentfield`, `modified`, `owner`, its child `name` — and a client may not send those. On the *first* answer there is no
stored round to inherit, so it worked; on the second one it failed. That is also why the whole suite was green while both
screens were dead: the fake ERP does not police those fields the way Frappe does.

**Fixed once, for every screen.** The stripping now happens in `deals._ex` — the single door every write goes through —
via `_writable()`, which removes the read-only set (`docstatus`, `doctype`, `parent`, `parentfield`, `parenttype`,
`owner`, `creation`, `modified`, `modified_by`, `amended_from`, `name`) at **every level** of the document: parent, child
tables, nested dicts. No screen can make this mistake again, and `cost_save`'s own whitelist stays as a second belt.

Everything else in those rows is kept — a stored negotiation round's `margin_pct`, `below_far`, `style_no`, `recorded_by`
survive, so history is not damaged by the cleanup.

**Verified against the live negotiation** (`PN-2026-00001`, round 1 = *Our Offer* 17.0) with a **preview** (nothing
written): the save is accepted and would store two rounds — `Our Offer 17.0` and the new `Buyer Counter` — with no
`docstatus` refusal. The user can press it for real.

`tests/test_write_payload.py` is new (11 assertions): the stripping rule at every depth, a negotiation answered **twice**
(the second answer is the one that used to fail) with the outgoing payload inspected to prove no read-only key leaves the
app, and the stored round plus both new rounds present afterwards.

## The merchandiser's own costing sheet, on the Costing screen — 2026-11-07 14:30

The user: *"in the costing, we have 2 documents in the drive … one document called apparel costing detailed revised … who
not have another page where these are recorded and when I click the button on calculate or add values based on rules it
adds it and then any changes manually required we can do it."*

Found it in Drive: `APPAREL_COSTING_DETAILED_REVISED.xlsx` (plus `INTERNAL COSTING.xlsx`). Its `DETAILED COSTING` sheet is
a real cost model — header (style, buyer, season, order qty, FOB port, pcs/carton, version, sign-offs), 18 raw-material
lines (usage/pc, unit, **wastage %**, rate, cost/pc), 5 processing lines with an apply 1/0 flag, 6 other expenses as
percentages, profit, and the FOB/order totals.

**A new panel on the Costing screen: "Costing sheet".**

* **Read it.** Upload the sheet, or pick it from the mail's own attachments. It goes to the model — every factory lays a
  costing out differently, so a fixed column map would be the wrong tool — and the ERP's **own `Cost Head` list is put in
  the prompt**, so each charge line is mapped to a real head (`MAKING CHARGES (CMT)` → `Stitching (CMT)`, `REJECTION` →
  `Rejection Allowance`, `FABRIC EXPORT COST PER METER` → `Fabric Export Cost`, …). Every number is validated
  (`wastage 5` → `0.05`), a line with no head is **reported**, never dropped, and nothing is written to the ERP by the
  read. The sheet is **recorded on the style** (`cost_doc`), so it is still there after a refresh.
* **Look at it.** The panel shows the header it read, every material line (usage, UOM, waste %, rate, cost/pc) with the
  raw-material total, every charge line with the ERP head it was mapped to and whether the sheet applies it or turned it
  off, and the sheet's own totals (processing, other expenses, FOB before profit, profit, FOB/pc, order value).
* **Apply it.** One button writes it into the ERP Cost Sheet **as a draft**: materials matched by description (updated,
  or added when the sheet has a line the BOM did not), charges set on their cost head (a line the sheet turns off is
  marked N/A), the sheet's FOB becomes the quoted price, and the ERP's own rules recompute the price. The answer says
  what it did: *"7 line(s) updated, 4 added, 9 cost head(s) set, quoted 14.3748"*.
* **Then edit by hand.** The ordinary editor owns the numbers afterwards — a hand edit saves and wins (verified).
* **A submitted costing is refused** with a sentence, and *"replace the material lines with the sheet's"* is offered for
  when the sheet, not the BOM, is the material list of record.

**Two rules the ERP demanded on the way, now handled:** a material line with a wastage % needs a `wastage_reason`
(*"Wastage is set per order, never by default"*) — the sheet's own note is used, else the figure is recorded as coming
from that sheet; and matching a costing line to a Cost Sheet line is a **union** overlap, because with a "minimum"
overlap the shared word "main" made `MAIN LABEL` match `MAIN FABRIC 100% COTTON` and silently overwrite the fabric's
usage and rate.

**Verified with the real sheet** through the live model: 16 material lines, 14 charge lines (all mapped), totals
`raw 5.24575 / processing 5.0 / other 2.254065 / FOB before profit 12.499815 / profit 1.87497225 / FOB 14.37478725 /
order 79,061.33`. `tests/test_costing_sheet.py` is new (26 assertions): read records but writes nothing, apply fills the
materials/charges/quoted price as a draft, a hand edit afterwards wins, a submitted sheet is refused, and no sheet means
no apply. Screenshot of the panel on the live deal: `/tmp/ui5/costing-sheet.png`.

## The costing sheet is a module of the app now — 2026-11-07 15:10

The user, after the first attempt: *"no no the costing sheet should be a built in module where it is already maybe saved in
a db or something and then on a click u transfer the prices, that is what i had asked."*

Right — the first version *imported* a spreadsheet and left it at that. Now the sheet is a document this app owns.

**Its own tables.** `models_costing.py`: `costing_sheet` (per deal + style: order qty, pcs/carton, profit %, currency,
FOB port, version, where the numbers came from, last totals, when it was transferred) and `costing_line` (kind
`material` / `processing` / `expense`, label, material type, ERP cost head, usage, UOM, wastage % + reason, rate, share,
apply, per-metre flag). Created on `init_db`, additive-only migration, nothing else touched.

**Already there when you open it.** `costing_sheet.open_sheet()` seeds the sheet from `TEMPLATE` — 14 raw-material lines,
7 processing charges, 8 percentage expenses including profit — with:
* the order quantity from the style,
* material usage from the **buyer's BOM** (a `Fabric` line for MAIN FABRIC, the contrast one for the contrast row, each
  BOM line used once: a generic "Trim" row is never grabbed by the first trim-like template line, so the BUTTON keeps its
  quantity instead of a ZIPPER line taking it),
* the ERP's own **cost heads** already on every charge line.

**The rules are the app's.** `costing_sheet.compute()` — pure, no database, no ERP:
`usage × (1 + wastage) × rate` per material; the two per-metre charges priced on the **fabric metres** (the sum of the
fabric usages with their wastage); a carton at **1 per `pcs_per_carton`** by rule; percentage expenses on the product
cost; profit on cost; FOB = product + other + profit; order value = FOB × quantity. Press **Calculate** (`deal_cost_sheet_save`),
and the totals on the screen are the app's own answer.

**One click transfers.** `deal_cost_sheet_transfer` → `deals.cost_sheet_transfer` → the same guarded merge: materials
matched by name (or all replaced), charges by the ERP's own `Cost Head`, the sheet's FOB as the quoted price, the ERP's
rules recomputing the price — **as a draft**, never submitted. Every value stays editable afterwards. A submitted Cost
Sheet is refused with a sentence, and the sheet then shows read-only with that sentence on it.

**A sheet somebody sent still fits.** "Import numbers" (upload, or pick the mail's attachment) reads the document and
fills **this** sheet through `apply_import` — the numbers come from the document, the arithmetic stays the app's own, so
what the screen shows is what this app can defend.

**Screen.** Inside the Costing editor: header fields (order qty, pcs/carton, profit %, currency), three grouped tables —
Raw materials (`usage × (1 + wastage) × rate`), Processing charges (`per mtr` tick-box for the fabric charges), Other
expenses & profit (`share`) — each line editable with an `On` switch and a cost/pc column, then the running totals
(raw material, product cost, fabric metres, other expenses, profit, FOB/pc, order value), an **Calculate**, a
**Transfer to the ERP**, and an **Import numbers** door.

`tests/test_costing_sheet.py` rewritten for the module (39 assertions): the sheet is there without an upload, seeded with
the BOM's usage and the ERP's heads; the rules (fabric metres, per-metre charges, carton rule, percentages, profit, FOB,
order value); edits survive a round trip **in the database**; a deleted line is deleted; transfer writes the rates into
the ERP as a draft with the sheet's FOB as the quoted price; a submitted sheet is refused; and an imported document fills
the module while the arithmetic stays the app's.

## "Each style needs its Item in the ERP before the contract" — two missing ERP defaults — 2026-11-07 15:45

The user pressed **Sales Contract** and got:

    Each style needs its Item in the ERP before the contract (C2027-S84-304: Set an Item Group on Product Type Woven Top
    or a Style Item Group in Apparel Settings.). Fix it in ERP records → Product Type (set the Item Group), then press again.

Both halves of that message are true, and both are **configuration this site lost when it was rebuilt after the wipe**:

| what the ERP wanted | what the site had |
|---|---|
| `Product Type.item_group` (or an Apparel Settings style group) | **all six Product Types: empty** — and this site's Apparel Settings has no style-group field at all, so the "or" is a dead end |
| the warehouses in **Apparel Settings** | pointing at the **previous company's** records: `Finished Goods - GGI`, `Fabric Inspection - GGI`, `Fabric Store - GGI`, `Trim Inspection - GGI`, `Trim Store - GGI`, `Rejected Material - GGI`, `Cutting WIP - GGI`, `Line WIP - GGI`, `Seconds (B-Grade) - GGI`, `Scrap - GGI` — none of them on a site whose company is **Cortex International (CI)** |

**Repaired in the ERP (this site):** the ten settings links now point at records that exist — `… - CI`, with eight
warehouses created under the company (fabric and trim kept separate, never one warehouse for both) — and `Woven Top`
carries `item_group = Finished Garments`. The audit log has an `erp_setup` row for it.

**And the tower now does this itself.** `deals.erp_setup()` walks the **Apparel Settings' own Link fields** (no hardcoded
list), asks the ERP whether each record exists, makes a missing **Warehouse** under the company's own abbreviation, points
the setting at the name the site actually gave it, and reports anything it will not invent (here: the T&A template link).
`deals._ensure_item_group()` picks a real Item Group from the ERP's own list for the Product Type it is about to need.
And `deals._ex` — the single write door — catches **"could not find"**, runs the repair **once**, and retries the same
write; a genuine business refusal is never retried.

**The user's click, done again:** `contract_prepare` now answers **ok** — quotation `SAL-QTN-2026-00002` created and
submitted at the agreed prices, style Item `C2027-S84-304` made, contract draft built (1 line, 5 size rows). What is left
is what a person must type in the **Contract** step: **Incoterm, Port of loading, Payment terms (basis + days)** — the
readiness list says exactly that, and the buyer PO once it arrives.

`tests/test_erp_setup.py` is new (18 assertions): the name rule for a rebuilt company, the settings repair (each broken
Link found from the meta, warehouses created, settings saved, fabric/trim kept apart, an unfixable link reported instead of
invented, idempotent on a second run), the Item Group choice, and the one-shot retry after a "could not find" refusal.
`test_deals` was updated where the old behaviour (a warning and a dead end) is now a repair.

## Two tabs on one costing page, and the ERP cost sheet fills itself — 2026-11-07 (evening)

The user, with the workbook pasted in full and a screenshot of what the Deals page opened:

> *"in costing tab of cortex tower in separate tab and one more tab where everything is shown ... so when i click it in
> deals page that is this page ... The ERP refuses to submit a costing that leaves a mandatory head at 0 without ticking
> N/A. based on the given stuff it should auto populate, when required i do changes here in deals page and move forward."*

Three things were wrong under that:

1. **The costing opened in a modal on the Deals page**, showing only the ERP's material rows and cost heads — half of the
   costing, no totals, nothing like the sheet the user actually costs from.
2. **The ERP's cost sheet started at zero on every line**, so the ERP refused to submit it
   (*"Zero rate without N/A"*) and the same fifteen numbers had to be typed twice.
3. **The app's own sheet had no working figures either**: the template carried the line labels and the percentages, but
   not the rates the workbook prints on every row, so a new sheet opened as thirty empty rows.

### What is there now

**One page, two tabs** (`#/costing/<deal>/<style>`):

| tab | what it is |
|---|---|
| **Cost sheet** | the ERP's own Cost Sheet for this style: the Buyer BOM's material rows and the ERP's cost heads, N/A per head, Recalculate / Save draft / Save & submit. This is the page that used to be a modal on the Deals page (`frontend/src/app/CostSheetTab.tsx`). |
| **Everything** | the whole workbook: raw materials, processing charges, other expenses, profit, FOB per piece in USD and VND, order value (unchanged from this afternoon's page), with Save and *Apply prices to the BOM*. |

The Deals page's costing step no longer opens a modal: a style row goes to that page (`go('costing/<deal>/<style>')`), and
`CostEditor` (196 lines of duplicated editor) is gone from `DealPage.tsx`.

**The workbook's own figures are the template's defaults** (`models_costing.TEMPLATE`: `usage_default`,
`wastage_default`, `rate_default` on all 18 material rows and the 5 processing rows — main fabric 0.600 m × 5 % × 3.000,
main label 0.050, tissue 6 × 0.020, thread 200 × 0.001, carton by pcs-per-carton at 0.150, making 5.000, washing 0.500).
`costing_sheet.apply_defaults` fills **blanks only**, after `link_items`, so a usage that came from the buyer's BOM and
anything a person typed (a deliberate 0 included) always wins. `seed()` and `open_sheet()` both run it, so the two live
sheets filled themselves the first time they were opened.

**The ERP cost sheet fills itself on one click** — `deals.cost_autofill` / API `deal_cost_autofill`, behind the
**Fill from the costing sheet** button on the Cost sheet tab. Nothing is written when the tab is opened (the user's rule:
*"do not auto put, have a button which when clicked it does"*):

* a material row with **no price** takes the price of the sheet line carrying the same item (by item code, then by
  description), then the app's price book; a wastage that comes with it brings a `wastage_reason`, because the ERP
  refuses a wastage % without one;
* a cost head at 0 takes the sheet's figure for that head — a processing rate per piece, a percentage for the expense
  heads — and the sheet's **APPLY 1/0 becomes the ERP's N/A tick**, which is exactly what the ERP demands before it will
  submit (Washing, Printing, Embellishment, Testing, and a 0 % head like Buying Agent Commission);
* a head the sheet does not cost at all (this site's **Depreciation**) is *reported*, not guessed or silently N/A'd —
  whoever costs the style decides;
* nothing else is touched: no consumption, no quoted price, no submit, the document stays a **draft**; blanks only, and an
  N/A a person ticked is never cleared, so it is idempotent. A submitted sheet is left as it is and says so.

Live, on deal 1 (C9043-U70-629, 11 material rows, 15 cost heads): 15 lines priced, 5 heads N/A on the first open; 4 items
still without a price (fusing, size label, second thread, white size tab) are listed instead of invented.

Tests: new `tests/test_cost_autofill.py` (27 assertions: the fill, the N/A ticks, the price book fallback, the reported
head, the untouched quoted price, idempotence, a hand-typed rate standing, a submitted sheet left alone, the API being
documented). `test_costing_sheet` 80, `test_deals` 128, `test_pipeline_guard` 106, `test_cost_save` 16,
`test_write_payload` 11, `test_register_replay` 31 — all green; `test_chain` / `test_wip_edges` / `test_wip_plan` are the
same three known data-shape failures as before.

**Mistake made and repaired:** the new test first set `KOGO_DB`, which `database.py` does not read (it reads
`DB_PATH_OVERRIDE`), so seven runs wrote 17 test deals (`Fill it`, style Z1001-A10-100) into the user's live database.
Deleted them (and their 9 costing sheets, 270 lines and 101 test audit rows) from a backup-verified copy; the test now
uses its own temp database like every other one. Lesson: an env var that nothing reads looks exactly like isolation.
