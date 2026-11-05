# What fits on a site that takes only DocTypes, data and Server Scripts

**Written 2026-11-05.** The user's constraint: the hosted ERPNext accepts **DocTypes, other data records, and Server Scripts (enabled)**, and nothing else. No `bench get-app`, no app code. This file says, with evidence, what of Phases A to E fits, what must be rewritten, and what cannot be done at all.

The evidence is two probes of Frappe's real Server Script sandbox on the dev bench (`frappe/utils/safe_exec.py`, Frappe 16.33) and a static scan of the whole app (`arinox_apparel/portable/check.py`, run it with `bench --site <site> execute arinox_apparel.portable.check.report`).

## 1. What a Server Script can and cannot do (measured)

| Works | Refused |
|---|---|
| Functions, closures, lambdas, `try/except`, `while`, f-strings, `%` formatting | **`class`** (so no controllers as written), **`import`** (so no sharing code between scripts) |
| `len int float str round abs min max sum sorted range enumerate zip set dict list tuple isinstance ord chr`, `**` | `.format()`, `hasattr getattr setattr type map filter reversed open print`, any `_name` or `__name__` attribute, `+=` on an item or attribute (`d["a"] += 1`, `doc.x += 1`; `i += 1` on a plain name is fine) |
| `frappe.utils`: `flt cint getdate add_days add_months add_to_date date_diff nowdate now_datetime get_datetime money_in_words fmt_money get_first_day get_last_day ceil floor cstr` and about 200 more | `frappe.get_roles`, `frappe.generate_hash`, `frappe.get_attr`, `frappe._dict`, `frappe.model.naming.getseries`, `frappe.db.delete`, `frappe.db.set_single_value`, `frappe.get_single`, `frappe.has_permission`, `frappe.db.sql_list`, `frappe.get_traceback` |
| `frappe.get_doc / new_doc / get_all / get_list / get_cached_doc / copy_doc / get_mapped_doc / delete_doc / rename_doc / sendmail / get_print / enqueue`; `doc.insert / save / submit / cancel / append / add_comment` | `frappe.db.sql` for anything but `select` / `with` |
| `frappe.db.get_value / set_value / get_single_value / exists / count / get_all`, read-only `frappe.db.sql` | A script cannot import another script's functions |
| **`frappe.call("dotted.path", **kwargs)`**: any *whitelisted* function, so ERPNext's `make_delivery_note`, `make_sales_invoice`, `make_sales_return`, `update_status`, `make_inter_company_purchase_invoice` work, and another **API** Server Script by name | |
| `run_script("name", **kwargs)`: run another Server Script and read what it left in `frappe.flags` | |
| Roles of the user: `frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")` | |

Other facts that shape the design:
- A script is one record bound to **one doctype and one event** (Before Validate, Before Save, After Save, Before Submit, After Submit, Before Cancel, After Cancel, Before Save/After Save of a submitted document, and a few more), or one API method, or one scheduler frequency, or one permission query. A doctype with five hooks is five records.
- At module level the document is a **local**, not a global, so a helper function cannot see `doc`: pass it as a parameter.
- An API script returns `frappe.flags`; it does not use `frappe.response`.
- Creating or editing a Server Script needs the **Script Manager** role; the hosting admin must set `server_script_enabled` in `common_site_config.json` (the user says it is on).
- Scripts do not run during `migrate` or install (`frappe.flags.in_install`, `in_migrate`).

## 2. What the app is made of

| Area | Python files | Lines | Empty controllers | Files the sandbox refuses | Main reasons |
|---|---:|---:|---:|---:|---|
| Doctype controllers (136 doctypes with files) | 136 | 5,695 | **93** | 43 | `class` (every controller), `import` (241), `@frappe.whitelist` (60), `frappe.get_roles`, `frappe.has_permission` |
| `production/` (ledger, flow, maths, cutting, sewing) | 10 | 1,006 | 0 | 10 | imports, `sql_list`, `db.delete`, whitelisted methods |
| `shipping/` (delivery, shipment, invoicing, follow-up, freight, close) | 7 | 765 | 0 | 7 | imports, whitelisted methods, `get_roles` |
| `tna/` (planner, events, status) | 5 | 710 | 0 | 5 | imports, `_dict`, underscore names |
| `materials/` | 7 | 829 | 0 | 7 | imports, `_dict`, underscore names |
| `overrides/` (hooks on Sales Order, PO, PR, Work Order) | 6 | 373 | 0 | 6 | imports, `get_roles` |
| `report/` script reports | 18 | 868 | 0 | 18 | imports, `_dict`, underscore names |
| `setup/` (custom fields, seeds, warehouses) | 4 | 751 | 0 | 4 | `db.set_single_value`, imports |
| **Total** | **198** | **11,168** | **93** | **103** | |

So: **93 doctypes are pure definition and import as they are. About 9,000 lines of logic live in 103 files that the sandbox refuses as written.**

## 3. Verdict by kind of thing

### Fits as it is (data)
- **DocType definitions** (all 130 JSON files, including child tables) as *custom* doctypes, with module `Arinox Apparel` created as a Module Def. The 93 empty controllers add nothing.
- **Custom Fields and Property Setters** (`setup/*.py` build them; export them as records).
- **Print formats** (Jinja; the ones here use only `frappe.db.get_value`, `frappe.format`, `_()` and the document), **Number Cards**, **Dashboard Charts**, **Workspaces, Workspace Sidebars, Desktop Icons** (the four decks), **Query Reports** (SQL only: Production Summary).
- **Client Scripts**: the form scripts (the `*.js` files next to each doctype and in `public/js`, 51 files, minus the two page scripts) become Client Script records for their doctype. Not yet generated or tried.
- **Seeds** (defect codes, processes, check items, T&A types and template, AQL plan, settings defaults): plain records.
- **The eight Server Scripts written this round** (`portable/server_scripts`, manifest in `portable/manifest.json`, loader `portable/loader.py` compiles each with Frappe's own restricted compiler before saving): shipment checks (ISO 6346, chargeable weight and volume, destination filings), freight quote lines, sample invoice follow-up, letter of credit, letter of credit reminders, T&A stamping of on-board and delivery, close production. Tested through the real sandbox (`TestPortableScripts`, 11 tests).

### Fits only after a rewrite as Server Scripts (about 9,000 lines)
Every rule that is a controller method or a hook module today. Each maps to a script type:

| Today | As a Server Script |
|---|---|
| `validate`, `before_submit`, `on_submit`, `on_cancel` of a controller | DocType Event scripts (Before Save, Before Submit, After Submit, After Cancel) |
| `doc_events` on ERPNext doctypes (Delivery Note, Shipment, Purchase Invoice, Sales Order, Purchase Order, Purchase Receipt, Work Order, Quotation) | DocType Event scripts on those doctypes |
| `autoname()` (the contract-based names) | a **Before Insert** script that sets the contract field, plus the doctype's `format:{sales_contract}-PL-{##}` naming rule |
| `@frappe.whitelist()` buttons (`generate_cartons`, `pick_cartons`, `make_delivery_notes`, `prepare_invoices`, `submit_invoices`, `log_follow_up`, `commercial_close`, `make_credit_note`, ...) | API scripts, one per endpoint (or one dispatcher script with an `action` argument) |
| `scheduler_events` daily | Scheduler Event scripts |
| `production/ledger.py`, `flow.py`, `maths.py` shared by about 12 doctypes | **no imports**, so either each script carries a copy, or one **API script is the engine** and the event scripts call it with `run_script` |
| `class Flow` | functions over dicts |
| `getseries` counters (SSCC, contract serials) | the doctype naming series itself (a doctype whose only job is to hand out numbers) |
| `frappe.get_roles()` | the `Has Role` query above |
| `setup/*.py` seeding at migrate | data records, loaded once |

Honest size: this is a rewrite of roughly 9,000 lines into sandbox Python with the tests re-run against it, not a mechanical translation. The design that keeps it manageable is **one engine API script** (functions for ledger post, flow check, maths, carton plan) plus thin per-doctype event scripts of a few lines each. It is not done yet.

### Cannot be done on such a site
1. **File-based Pages**: the *Order Desk* kanban (`apparel-order-desk`) and the *WIP Board* (`apparel-wip-board`) are Page doctypes with JavaScript files in the app. A site without developer access cannot hold them. Replacements: number cards and reports (already built), a Kanban view on Sales Order, a Report View.
2. **Script reports as Python files** (18 reports, 868 lines, `execute()` functions). A hosted site can hold a Query Report (SQL). Frappe can also store a Script Report's script in the record and run it in the sandbox, but **I have not tested that**; each report would need rewriting either way. Until then use SQL Query Reports (Production Summary is one).
3. **The Work Order gate / `override_doctype_class` style overrides**: none are used, but nothing that subclasses an ERPNext controller can be done; hooks only through events.
4. **Anything that needs a database transaction control or raw SQL writes**: `frappe.db.delete`, `sql` updates (used in `transfer_card` and the ledger rebuild). Use `delete_doc` and `set_value` in a loop; slower, and a ledger rebuild over thousands of rows may hit the script time limit.
5. **Barcode scanning of the carton label**: the label is a print format that draws a Code 128 / GS1-128 barcode in the browser (JsBarcode). Whether the printed result scans has not been tested by anyone.
6. **Server-side rendering of a barcode, PDF, or any library**: no imports.

### Things the hosting admin must confirm
- `server_script_enabled` is on, and the API user has **Script Manager** (to create scripts) and **System Manager** (to create custom doctypes).
- The API user can create Module Def, DocType (custom), Custom Field, Property Setter, Print Format, Report, Number Card, Workspace, Workspace Sidebar, Desktop Icon, Client Script, Server Script. All are ordinary records; none was tried on the hosted site.
- Running time limit of a Server Script on that site (unknown); the ledger and the cut plan loop over many rows.

## 4. Recommended next step

Build the **engine script** and port Phase D and E logic onto it in the order of dependency: ledger and flow, then Production Card rules, then cutting and sewing documents, then subcontract, finishing, packing, inspection, shipment, invoicing, follow-up, claims. Phase A to C follow. Keep the app code as the reference implementation and its 400 tests as the specification: run the same scenarios against the scripts on a second local site that has ERPNext only (no `arinox_apparel` app) to prove the hosted case. That second site does not exist yet.

## 5. What can be a Server Script, what cannot, and how to build it with the hosted agent

**Can be rewritten as Server Scripts:** rules that run on save, submit and cancel (DocType Event scripts, also on ERPNext's own documents); contract-based names (Before Insert script plus the doctype's naming format); buttons (API scripts called from a Client Script button, using `frappe.call` for ERPNext's whitelisted helpers such as make delivery note, sales invoice, credit note); daily jobs (Scheduler Event scripts); the production ledger and flow checks (one shared "engine" API script that thin event scripts call with `run_script`); role checks (query `Has Role`); never-repeating counters (a doctype whose naming series hands out the numbers).

**Cannot be done, and what to build instead:**

| Cannot | Build instead |
|---|---|
| The Order Desk and WIP Board pages (file-based) | Kanban view on Sales Order, Report Views, number cards and the four decks |
| The 18 Python script reports | SQL Query Reports (Production Summary is one). A script report stored in the record is possible in Frappe but untested here |
| Bulk ledger rebuild or mass delete | Delete in a loop or through `frappe.enqueue`; slower on large orders |
| `random` (carton draw) | A small seeded pseudo-random routine written by hand |
| Libraries, PDFs, any `import` | Print formats rendered in the browser (the carton barcode already works this way) |
| Seeding at migrate | One-off imports by the agent |
| Automated tests on the hosted site | Run them on a second local site with ERPNext only |

**Order of work with an API-only agent** (it can create records but cannot run bench or read the server):
1. Ask the hosting admin to confirm: server scripts enabled; the API user has Script Manager and System Manager; it can create custom DocTypes, Custom Fields, Property Setters, Print Formats, Reports, Number Cards, Workspaces, Sidebars, Desktop Icons, Client Scripts and Server Scripts; and the Server Script time limit.
2. Load the data first, in this order: Module Def, child DocTypes, parent DocTypes, Custom Fields and Property Setters, print formats, query reports, number cards, workspaces/sidebars/icons, seed records. This gives the structure with no scripts. The loader that turns the app's files into these records is **not written yet**.
3. Build the engine script (ledger, flow, maths, carton plan) and prove it on a second local site that has ERPNext only, using the existing tests as the specification.
4. Port document by document in flow order: cutting and sewing, subcontract, finishing, packing, inspection, shipment, invoicing, follow-up, claims; Phases A to C last.
5. Keep a switch (a setting that makes every script return at once). A faulty Before Save script on Shipment or Sales Invoice would otherwise stop everyone saving, and the agent cannot fix a server.

## 6. Measured on a clean ERPNext-only site (2026-11-05, `hosted.localhost`, app not installed)

The bundle in `hosted_bundle/` was loaded through the REST API (`portable/api_load.py`) and scripts were run on that site. New limits found by running, not reading:

| Refused in the sandbox | Use instead |
|---|---|
| A function calling another module-level function (they sit in locals, not globals) | Put everything inside one enclosing function and call it at the end (`def run(doc): ... ; run(doc)`) |
| `a, b = pair` (no `_unpack_sequence_`); `for a, b in rows` **is** fine | `x = pair` then `x[0]`, `x[1]` |
| `"{0}".format(x)` | `"%s" % (x,)` or an f-string |
| `date.strftime(...)` (`KeyError: '__import__'`) | `frappe.utils.formatdate(d, "dd MMM")`, or `str(d.year)` / `d.month` |
| Bare `getdate`, `flt`, `cint`, `add_days`, `nowdate` | `frappe.utils.getdate(...)` etc. (or `u = frappe.utils`) |
| Names that start with `_` | rename |
| A line in a SQL string that starts with `from ` when stripping imports by hand | (converter bug, fixed) |

What Frappe refuses on a site without developer mode, and how the exporter handles it (`portable/export_bundle.py`):
- A standard DocType (`custom = 0`) cannot be created: every DocType is exported with `custom = 1`.
- Print Format `standard`, Report `is_standard`, Number Card / Dashboard Chart `is_standard`, Desktop Icon `standard` must be off.
- A custom DocType's permission table is validated, a standard one is not. The app had two latent errors that only show now: **PP Meeting** gives *Sales User* submit/cancel/amend without write (the three rights are removed in the bundle), and **Fabric Inspection** and **Trim Inspection** list *Quality Manager* (and two stock roles) twice (merged). Fix them in the app's JSON when convenient.
- Doctypes must be created after the doctypes they link to; five point at each other (PP Meeting, PP Meeting Action, Recut Request, Final Inspection, Final Inspection Lot) and need a second pass.
- A Workspace Sidebar is named by its *title* on such a site (not by the app's file name).
- `bench execute` refuses a module from an app that is not installed on the site; the hosted tests run through `bench console` (`hosted_tests.sh`).

Status of what was ported and tested is in `portable/HOSTED_STATUS.md`.
