# 06 ERP setup and hosted constraints

## The hosted constraint (why the ERP side looks the way it does)

The hosted ERPNext accepts **only DocTypes, data records and Server Scripts** (plus Client Scripts, Print Formats, Reports and other ordinary records). No `bench get-app`, no app install, no Python files. So:

- Everything shipped to it is a **data bundle** (`arinox-apparel/hosted_bundle/`, 17 ordered groups listed in `index.json`) loaded with `arinox_apparel/portable/api_load.py` using an API key of a user with **System Manager** and **Script Manager**. The loader is idempotent.
- Controllers (Python classes) cannot exist there. Their logic is rewritten as **Server Scripts** (`portable/hosted_scripts/`, registered in `portable/manifest_hosted.json`).
- Two Frappe Page screens cannot exist; the Tower replaces them.
- **Since 2026-11-12 `server_script_enabled` is ON on the live host**, so the scripts run natively in the ERP. Before that, the Tower's TSR executed them itself. The Tower must now run in `erp_scripts_mode: native` (see `10-build-an-erp-module.md` §7 and `cortex-tower/prompts/2026-11-12_erp_native_scripts_and_modules.md`). Otherwise every rule runs twice.
- The ERP agent can now create DocTypes, Custom Fields, Server/Client Scripts, Reports, Print Formats and Workspaces live. It must follow `10-build-an-erp-module.md` (plan → sign-off → disabled scripts → one-by-one enable → git).
- `DEPLOY.md` (install the app with `bench get-app`) does **not** apply to that host. It is for a self-hosted bench only.

## Setup a real site needs (empty screens usually mean one of these is missing)

1. **Property Setters** from `cortex-tower/erp_setup/allow_on_submit.json` (57 fields the scripts `db_set` on submitted documents, mostly `status`). REST cannot write them otherwise; the runtime raises `TSRNeedsSchemaFix` naming the missing one. Regenerate with `tools/gen_allow_on_submit.py --base <site> [--apply]`. Clear the cache after loading.
2. **Apparel Settings** (all must be filled for the suggester and gates):
   - *Where to Produce*: `alloc_finish_pack_days`, `alloc_cut_lead_days`, `alloc_min_batch_qty`, table `alloc_defaults` (SAM and efficiency per Product Type); `work_minutes_per_day`, `planned_efficiency_pct`, `learning_curve`.
   - Warehouses: fabric and trim inspection, fabric and trim store, rejected, Cutting WIP, Finished Goods.
   - Gates: `enforce_bulk_gate`, `require_pp_meeting`, `ship_gate_final_inspection`, `ship_tolerance_basis`, `final_inspection_plan` (an AQL Plan).
   - Stock Settings: Serial and Batch No on; ERPNext over-delivery allowance at least the largest contract tolerance.
3. **Masters**: factories (Plant Floor), lines (Workstation, type Sewing, default operators/helpers), Product Types (with an Item Group or a Tech Pack naming the type), Subcontract Processes, suppliers (mill, trims, wash house), a Tech Pack per style (materials with consumption), customers, Cost Heads and ideally a Costing Parameter with the company's rates. Style Item Group in Apparel Settings (or one per Product Type) so the Tower can make each style's Item. A FG warehouse for the Sales Order.
4. **Vocabulary seeds**: the 33 `TNA Milestone Type` checkpoints, TNA calendars (seeded as 7-day, no holidays), reason codes, sample type rules, Product Type list. Seeded by `setup/install.py` / `setup/production.py` and exported into `hosted_bundle/06_seeds.json`.
5. **Server Scripts** added after the base bundle: `arinox_tna_api_apply_plan`, `arinox_fabric_requisition_refresh_quantities`, the zero-quantity fix in `arinox_sales_contract_api_make_order`, `packing_list_validate` (carton row tied to its own style's order line). The KOGO loader bundle (`cortex-tower2/apparel-modules.zip` → `v2/hosted_bundle`) does **not** yet contain the doctype `Allocation Default`, the new Apparel Settings fields, the seeds, the Property Setters or these scripts. Without them the Order page degrades: allocation save, T&A apply, inspection refresh and packing refuse or no-op.
6. **API user** for the Tower: System Manager role. The ERP records its `owner`/`modified_by` as that user; the Tower's audit log and trace comment name the person.

**The empty-state rule:** the Tower says what is missing ("No SAM for …", "Capacity is unknown …"). Report that sentence; do not invent a number to fill the gap. Business values are never defaulted in code.

## Server Script sandbox (when you write or port one)

A script is compiled by RestrictedPython. Measured rules:

| Plain Python | In a Server Script | Do this |
|---|---|---|
| `class`, `import` | refused | no classes; shared helpers are copied in at export (`# include: lib_x.py`) |
| a module function calling another module function | `NameError` | put everything inside **one function** (`def run(doc): ...; run(doc)`); nested helpers can call each other |
| `a, b = pair` | refused | `x = pair; x[0]` (a `for a, b in rows` loop is fine) |
| `"{0}".format(x)` | refused | `"%s" % (x,)` or an f-string |
| `date.strftime`, `re`, `math`, `random`, `datetime` | refused / absent | `frappe.utils.formatdate`, `frappe.utils.ceil/floor/add_days/date_diff`, hand-written loops |
| bare `getdate`, `flt`, `cint`, `add_days`, `nowdate` | undefined | `frappe.utils.getdate(...)` etc. |
| names or attributes starting `_`, dict keys starting `_` | refused | rename; prefix keys |
| `d["a"] += 1`, `doc.x += 1` | refused | `d["a"] = d["a"] + 1` |
| `frappe._dict`, `getattr`, `hasattr`, `type`, `map`, `filter`, `open`, `print` | refused | plain `dict`, `.get()`, comprehensions |
| `frappe.has_permission`, `frappe.get_roles` | refused | `frappe.get_doc(dt, name).check_permission("read")`; read `Has Role` (Administrator holds every role) |
| `frappe.db.sql("update ...")`, `frappe.db.delete`, `frappe.db.set_single_value` | refused (read-only SQL) | `frappe.db.set_value`, `doc.db_set`, `frappe.delete_doc(..., force=1)` |
| `frappe.model.naming.getseries` | refused | the `Arinox Number` series doctype |
| `frappe.defaults.get_user_default` | breaks | read `DefaultValue`, then `Global Defaults`, then the first Company |
| `run_script("x")` | takes the **record name** not the `api_method` | e.g. `arinox_work_order_api_get_bulk_gate` |
| script argument `0` read as `form.get("x") or 1` | 0 becomes 1 | test `is None` |

Events: one script = one doctype + one event (Before Validate/Save/Submit/Cancel, After Save/Submit/Cancel, …) or one API method or one scheduler frequency. A throw in a Before/After event aborts the whole save or submit. At module level `doc` is a local, so a helper must receive it as a parameter. Hosted-only scripts go in `manifest_hosted.json`, **never** `manifest.json` (that is installed on the dev site too and would run twice).

**Port recipe** (full text: `HOSTED_BUILD_GUIDE.md` §4): read the controller and its test (the tests are the spec) → map methods to events → one file per event → register in `manifest_hosted.json` → write hosted tests in `portable/hosted_tests/` with `@test("group")` → `./hosted_sync.sh server_scripts && ./hosted_tests.sh <group>` → then run all. Never edit the dev app to make a port easier; report an app bug and carry the corrected rule in the hosted script with a comment.

After any Server Script change: re-run the hosted tests, then `python3 tools/vendor_scripts.py` in `cortex-tower` so the Tower's vendored copy matches the repo bundle (a drift test enforces this; vendoring from the wrong source silently dropped a fix once).

## Hard rules for the ERP layer (from `arinox-apparel/CLAUDE.md`)

1. Never edit `erpnext/` core. Extend with hooks, doctype JS, Custom Fields, Property Setters.
2. One app, one transfer unit: only the `arinox_apparel` app moves; never site DBs, `sites/`, or ERPNext source.
3. Pin versions: ERPNext v16.34.1 (branch `erpnext-16.34.1`); check `required_apps` before release.
4. Small vertical slices; reuse ERPNext before inventing (size × colour are Item Variants).
5. Every doctype gets a spec in `doctypes/` before code.
6. No destructive commands on any shared or hosted site. `bench migrate`, `install-app`, `export-*` only on the local dev site unless the user says otherwise.
7. Never commit or push without asking. Arinox print/letterhead branding: orange and black header, primary orange `#e8590c`.
