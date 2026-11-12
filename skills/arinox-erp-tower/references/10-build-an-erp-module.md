# 10 Building a new module ("app") inside the ERP, end to end

Use this when someone asks for a new capability that needs **new record types, rules, reports or screens** in the ERP, for example a "Compliance" module, a "Merchandising Plus" module, or a new field plus rule on Sales Order.

Since 2026-11-12, Server Scripts are enabled on the live ERP, and the ERP-connected agent can create DocTypes, Custom Fields, Server Scripts, Client Scripts, Reports, Print Formats, Workspaces, Roles, Workflows and Notifications through the API. That makes a "custom app" possible **as data**: its own Module Def plus 5 to 15 record types plus automations plus reports plus a workspace. It is still **not** a Frappe app package. There is no `bench`, no `hooks.py`, no `.py` files, no Script Reports, no core edits and no Desk JS pages. If a requirement needs one of those, say so and offer either a Server Script or Query Report equivalent, or a Tower screen.

---

## 0. The three agents and who does what

| Actor | Where it runs | What it may do | What it must never do |
|---|---|---|---|
| **ERP agent** | Chat connected to the live ERP, with API + Script Manager rights | Read schema and data; create and update the module's records (DocType, Custom Field, Server Script …) **after sign-off**; run verification on throwaway rows | Touch existing Arinox Apparel doctypes or scripts without an explicit ask; change transactional data outside the test rows; delete anything that it did not create in this change |
| **Cortex Tower** | KOGO project (`cortex-tower/`) | Read the ERP, show work, perform every business write through `pipeline.execute`, register the new module's doctypes for roles and screens | Run a Server Script that the ERP also runs natively (double execution; see §7) |
| **Coding agent** (Claude Code in this repo) | Codespace with git | Keep the source of truth in git: `erp-modules/<slug>/`, tests, the skill, Tower code; push to GitHub | Push live-only changes that are not in git; commit secrets |

**The person** signs off the plan (§2), approves the go-live (§5) and approves any risky Tower write. No agent signs off its own plan.

Any of the three agents can drive the process. The same steps apply whether it runs in Claude Code or entirely in an agent chat (§9).

---

## 1. Intake: turn the ask into a module brief (chat, 5 to 10 minutes)

Ask, or extract from what was said, and write down:

1. **Workflow in one paragraph**: who does what, on which document, in what order.
2. **Records**: the "things" (masters) and the "events" (transactions). Each one becomes a DocType candidate.
3. **Links to existing data**: Sales Order, Item, Customer, Supplier, Tech Pack, Order TNA … (link to them; never copy their data).
4. **Calculations and rules**: what is computed, what is blocked, and when.
5. **Outputs**: reports, print formats, notifications, dashboards.
6. **Roles**: who creates, who approves, who only reads.
7. **Volume and history**: rows per month, and whether existing Excel/CSV data must be imported.

Before designing anything new, **reuse first**. Check whether ERPNext or Arinox Apparel already has it (`arinox-apparel/doctypes/ERPNEXT_OVERLAP_AUDIT.md`, `MODULE_GUIDE.md`). A custom field on an existing doctype is better than a new doctype that mirrors it.

## 2. Plan for sign-off (nothing is created before this is approved)

Fill `assets/module-spec-template.md` and save it as `erp-modules/<slug>/SPEC.md`. It must contain:

- Module name (Title Case, unique, not one of the 34 existing modules) and slug (`snake_case`)
- A **name prefix** for every record the module creates. Default: `<slug>_` for Server Scripts, a `<Module> ` word for DocTypes, and `custom_<slug>_` for custom fields. This prefix is how §8 finds and removes the module.
- DocTypes: the field table (fieldname, type, options, required, in list view), child tables, naming rule, `is_submittable`, permissions per role
- Custom fields on existing doctypes (each one named, with `insert_after`)
- Server Scripts: one row per script with **name · type (DocType Event / API / Scheduler / Permission Query) · doctype + event or api_method or frequency · what it does · what it throws**
- Client Scripts, Reports (Report Builder or Query Report only), Print Formats, Workspace, Notifications, Workflow
- Test plan: the throwaway rows, and for each rule the input and the expected result
- Rollback list: everything §8 will delete if the module is pulled

Show the plan to the person in chat in a short form (tables, not prose) and ask: "Approve this plan? I will build it on the test ERP first." **Wait for yes.**

## 3. Build on the test ERP first (`hosted.localhost:8001`)

When a test ERP is reachable (a Codespace, or the KOGO test site), build there first. If only the live ERP exists, the ERP agent builds there, but **every record is created disabled or unused** (see §5), and the tests use rows named `ZZTEST-<slug>-…`.

Order of creation (the same dependency order as `hosted_bundle/index.json`):

| # | Group | Notes |
|---|---|---|
| 1 | `module_def` | `Module Def` with `custom: 1`, `app_name: frappe` (hosted, no app) |
| 2 | `roles` | Only new roles; reuse Merchandiser, Planner, QC … where they fit |
| 3 | `doctypes` | `custom: 1`, `module: <Module>`. Child tables before parents. Links to doctypes that exist |
| 4 | `custom_fields` | On existing doctypes; always `custom_<slug>_` names |
| 5 | `property_setters` | Only when a script `db_set`s a submitted doc's field (`allow_on_submit`) |
| 6 | `seeds` | Vocabulary or master rows the logic needs, create-only |
| 7 | `server_scripts` | **Created with `disabled: 1`**; enabled in §5 |
| 8 | `client_scripts` | Form behaviour only |
| 9 | `reports` | Report Builder / Query Report. A Query Report is SQL **select** only |
| 10 | `print_formats` | Jinja; Arinox branding orange `#e8590c` and black |
| 11 | `notifications`, `workflows`, `assignment_rules` | Optional |
| 12 | `number_cards`, `dashboard_charts`, `workspaces` | The module's menu |

**Server Script rules.** Write every script to the sandbox rules in `06-erp-setup-and-hosted-constraints.md` §Server Script sandbox: no import or class, one outer function, no tuple unpacking, `frappe.utils.*`, no `+=` on items or attributes, select-only SQL, and so on. Each script starts with a header comment:

```python
# <slug> · <DocType> (<Event>) — what it does in one line.
# Module: <Module>. Spec: erp-modules/<slug>/SPEC.md §<n>. Do not edit on the site without updating git.
```

**Testing on the test ERP.** Enable the scripts there, create the throwaway rows, and run every row of the test plan through the REST API. Record the actual result next to the expected one in `erp-modules/<slug>/TEST_LOG.md`. A failed row means fix and re-run, not "close enough".

## 4. Put it in git, then push (the source of truth)

Layout (one folder per module, same format as `arinox-apparel/hosted_bundle/`, so the existing loader applies it):

```
erp-modules/<slug>/
  SPEC.md                  the signed-off plan (§2), with the date and who approved it
  CHANGELOG.md             one line per change: date · what · by which agent · live? y/n
  TEST_LOG.md              the test plan with actual results
  bundle/
    index.json             [{"file": "01_module_def.json", "group": "module_def", "mode": "create", "count": 1}, …]
    01_module_def.json … 12_workspaces.json
  scripts/                 the Server Script bodies as .py files (readable diffs; the bundle JSON embeds the same text)
  rollback.json            [{"doctype": "Server Script", "name": "<slug>_…"}, …] in reverse creation order
```

Each group file is `{"group": "<group>", "mode": "create", "records": [ {full record with "doctype"}, … ]}`, the same as `arinox-apparel/hosted_bundle/`. The `doctypes` group has two options:
- `"mode": "doctypes"` with records shaped `{"first": <DocType without loop-closing links>, "deferred": true|false, "doc": <full DocType>}` (what the exporter writes)
- `"mode": "create"` with plain DocType records listed child tables first (simplest for a hand-written module without circular links)

`mode: "create"` upserts: a missing record is created, an existing one is updated. Seeds use the same mode but are left alone when they exist (unless `--overwrite-seeds`).

How to get the bundle:

- **Coding agent:** write the JSON by hand from the spec, or export it from the test ERP with `GET /api/resource/<DocType>?filters=[["module","=","<Module>"]]&fields=["*"]` (Custom Field filters by `name like custom_<slug>_%`).
- **ERP agent in chat:** after building, read every record it created with `fields=["*"]` and print them as the JSON files above, one fenced block per file. The person, or a coding agent, saves them under `erp-modules/<slug>/bundle/`. If the chat has GitHub access, it commits them directly.

Apply the bundle to any site (idempotent: it creates missing records and updates existing ones):

```
ARINOX_API_TOKEN="$(cat ~/.arinox_hosted_token)" \
python3 arinox-apparel/arinox_apparel/arinox_apparel/portable/api_load.py erp-modules/<slug>/bundle http://hosted.localhost:8001 [--only=doctypes,server_scripts] [--dry-run]
```

Commit and push from the repo root (only the module's files):

```
git checkout apparel-app            # or a feature branch: git checkout -b module/<slug>
git add erp-modules/<slug> skills/arinox-erp-tower
git commit -m "feat(<slug>): <what> — spec, bundle, tests"
git push origin HEAD
```

Rules: never `git add -A` (the repo root holds private zips and test folders); never commit tokens, real prices, buyer PO numbers or bank details; ask the person before pushing to `main`.

## 5. Go live (the person approves this step)

1. Tell the person exactly what will be created live (counts per group, from `bundle/index.json`) and ask for a go. **Wait for yes.**
2. Load groups 1 to 6 and 8 to 12 (`--only=module_def,roles,doctypes,custom_fields,property_setters,seeds,client_scripts,reports,print_formats,workspaces …`).
3. Load the Server Scripts **disabled**. Then enable them **one at a time**. After each one, run its test row on `ZZTEST-` data and check the result.
4. If a script misbehaves, set `disabled: 1` again at once. Disabling stops it; nothing else has to be undone.
5. Delete the `ZZTEST-` rows. The person decides whether real data should be imported (Data Import) now.
6. Append to `CHANGELOG.md`: `2026-mm-dd · live · <counts> · approved by <person>`. Push.

## 6. Register the module with Cortex Tower

The Tower does not know about the new doctypes until it is told. Until then, unknown doctypes are readable by every role and writable only by Management and Admin (`guardrails.group_of` returns `"other"`).

Send the Tower the **module registration** below, either through Tower chat or by pasting it into the Tower builder prompt in `cortex-tower/prompts/`:

```json
{
  "module": "<Module>",
  "slug": "<slug>",
  "doctypes": {"<DocType A>": {"group": "<slug>", "write_roles": ["Merchandiser"], "submit_roles": ["Management"], "ledger": false}},
  "api_methods": [{"name": "<slug>_api_…", "risky": false, "doctype": "<DocType A>"}],
  "scripts_run_on": "erp",
  "spec": "erp-modules/<slug>/SPEC.md"
}
```

`scripts_run_on: "erp"` is the important line. The Tower must **not** vendor or run these scripts in its runtime. The ERP runs them natively. The Tower writes through REST and reads the result. A submittable doctype that posts stock or ledger entries gets `"ledger": true`, so its submit is classed risky and needs approval.

## 7. Native scripts vs Tower Script Runtime (read before writing anything)

| `erp_scripts_mode` (Tower setting) | Who runs Arinox Server Scripts | When |
|---|---|---|
| `tower` | The Tower's TSR, around a plain REST write | Live ERP with `server_script_enabled` **off** (before 2026-11-12) |
| `native` | The ERP itself | Live ERP with scripts **on**. The Tower's TSR may still *preview* (dry run, nothing written) but executes as a plain REST call |

With scripts on in the ERP, **and** the Tower in `tower` mode, every Arinox rule runs twice: numbers jump by two, ledger rows double, and gates can throw twice. That includes `arinox_naming_*` and `arinox_engine*`, which the Tower's kill switch keeps on. Before any write after scripts are switched on, check `tsr_status`. It must report `erp_scripts_mode: native` (the Tower change in `cortex-tower/prompts/2026-11-12_erp_native_scripts_and_modules.md`). If it does not report that, **stop and tell the person**. Do not write.

New modules are always `scripts_run_on: "erp"`, in either mode.

## 8. Change, roll back, retire

- **Change:** edit in git first (`scripts/*.py`, then rebuild the bundle JSON), re-test on the test ERP, apply only the changed group live, then append to the CHANGELOG. A hot-fix made live in chat must be copied back into git the same day.
- **Roll back one script:** set `disabled: 1`.
- **Retire the module:** walk `rollback.json` in order. Disable the scripts, then delete the workspace, reports, print formats, client scripts, server scripts, custom fields and doctypes, then the Module Def. A doctype with real rows is **not** deleted without the person's explicit yes. Frappe has no trash, and the rows go with it.

## 9. Doing it all through agent chat (no Codespace)

The whole process works in chat with only the ERP agent and the person. These are the turns:

1. **Person:** "I need <capability>." **ERP agent:** asks the §1 questions it cannot answer from the ERP, reads the existing doctypes that matter, and reports what already exists.
2. **ERP agent:** posts the §2 plan as tables. **Person:** approves or edits it. Repeat until the person says yes.
3. **ERP agent:** builds with every script disabled (§3 order), creates `ZZTEST-` rows, enables one script at a time, and posts a result table (rule · input · expected · actual · ✅/❌).
4. **ERP agent:** exports what it built as the §4 JSON blocks plus `SPEC.md` and `rollback.json`. **Person**, or a coding agent, commits them. *Live but not in git counts as not done.*
5. **Person:** approves go-live (if step 3 ran on live, this is "remove the test rows and open it to users").
6. **ERP agent:** posts the §6 registration JSON. **Person** pastes it into Tower chat. **Tower** confirms that the doctypes are registered and that `scripts_run_on` is `erp`.
7. **ERP agent:** writes the last CHANGELOG line and the person-facing "how to use it" note (one screen: the menu, the first record to create, who approves).

Copy-paste prompts for each turn are in `11-chat-prompts.md`.

## Definition of done

- [ ] SPEC.md signed off (date + person)
- [ ] Every test row passed and was recorded in TEST_LOG.md
- [ ] Bundle in `erp-modules/<slug>/bundle/` loads cleanly with `--dry-run` on the test ERP
- [ ] Pushed to GitHub; CHANGELOG says live = y
- [ ] Tower registration accepted; `tsr_status` shows `erp_scripts_mode: native` and the new doctypes under their group
- [ ] No `ZZTEST-` rows left live
- [ ] The person has the "how to use it" note
