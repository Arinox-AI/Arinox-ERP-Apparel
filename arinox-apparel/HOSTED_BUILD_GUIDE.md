# Hosted build guide: what is left to build, what each piece does, and how to build it

**Written 2026-11-05 for an AI agent that will finish the port.** Read sections 1 to 5 first (about 15 minutes), then pick work from section 8. Section 9 lists what cannot be built on the hosted site and what to build instead. The appendix is generated from the source and says, file by file, what each unported piece does.

Companion files: `arinox_apparel/portable/HOSTED_STATUS.md` (what is done and tested), `doctypes/HOSTED_CONSTRAINTS.md` (sandbox rules, measured). **Held back from the public repo on purpose:** `COVERAGE_S84_S14.md` (the report on two real orders) and `arinox_apparel/portable/demo/` with `hosted_ingest.sh` (the script that enters them) hold real prices, PO, bill-of-lading and customs numbers. Ask the repo owner for them; section 7 below keeps the lessons without the figures.

---

## 1. The target, in one paragraph

The hosted ERPNext accepts only **DocTypes, data records and Server Scripts** (plus Client Scripts, Print Formats, Reports and the other ordinary records). No `bench`, no app install, no Python files. The agent that works on it is API-only. The Frappe app in this repo (`arinox_apparel`, 198 Python files, 407 passing tests) is the **reference implementation**: it already does everything. This job is to re-express the logic that lives in Python controllers and hooks as **Server Scripts** (restricted Python stored in a record), and to prove each one on a clean ERPNext-only site against the same scenarios the app's tests use.

What is already done and proven on a clean ERPNext-only site: the whole data layer (131 doctypes, 189 custom fields, 195 seeds, print formats, number cards, charts, workspaces, 30 client scripts, 13 reports), and the logic of contract naming, the production ledger and flow engine, Production Adjustment, Production Card, Sales Contract (+ make-order button), Sales Order hooks, Cost Sheet, Packing List, Final Inspection, Delivery Note gates, invoicing (direct and group route), payment follow-up with the daily reminders, a kill switch, and (Tier 1) Tech Pack, Price Negotiation with the Quotation hook, Factory Allocation, Sample Approval, PP Meeting, the bulk gate with the Work Order hooks, Cost Head and Costing Parameter. **the hosted tests pass** (`./hosted_tests.sh`, count in `HOSTED_STATUS.md`); the dev app still passes its own suite. Everything in section 8 is still to build.

## 2. Set up the working environment (about 10 minutes, one time)

You need a local bench with **two** sites: the dev site (the app installed, the reference) and a hosted-like site (ERPNext only, the app NOT installed).

```
cd /workspaces/frappe-bench
docker start apparel-mariadb apparel-redis
# dev site already exists: apparel.localhost  (app installed, server_script_enabled=1)
# hosted-like site: ERPNext only
bench new-site hosted.localhost --install-app erpnext --admin-password <pick one>   # needs the MariaDB root password
bench --site hosted.localhost set-config server_script_enabled 1
bench --site hosted.localhost set-config developer_mode 0        # the hosted site is NOT in developer mode; keep it that way
bench --site hosted.localhost serve --port 8001 &                # the REST API the loader talks to
```

One-time data on the hosted-like site (ERPNext does not work without them): run ERPNext's setup wizard once (`frappe.desk.page.setup_wizard.setup_wizard.setup_complete` with a company, USD, a fiscal year), then create an API key for Administrator and keep it **outside the repo**:

```
# in `bench --site hosted.localhost console`
from frappe.core.doctype.user.user import generate_keys
r = generate_keys("Administrator"); frappe.db.commit()
# write f"{frappe.db.get_value('User','Administrator','api_key')}:{r['api_secret']}" to ~/.arinox_hosted_token  (chmod 600)
```

The four helper scripts (all in `arinox-apparel/`):

| Script | Does |
|---|---|
| `hosted_sync.sh [group,group]` | Exports the bundle from the dev site and loads the named groups (default `server_scripts`) onto the hosted-like site through the REST API. Run after every script change. |
| `hosted_tests.sh [group_or_test]` | Runs the hosted tests on the hosted-like site and prints `ok` / `FAIL` per test and `RESULT passed N failed M`. |
| `hosted_exec.sh file.py [grep]` | Runs a Python file in the hosted-like site's console (use it for quick experiments). |
| `hosted_ingest.sh "<ARINOX ERP DOCS folder>"` | Enters the two sample orders and prints the reconciliation against the papers. **Not in the repo** (see above); ask the owner. |

`bench execute` **refuses** a module from an app that is not installed on the site (that is exactly the hosted case), which is why the tests go through the console. If the site says *Too many queued background jobs (600)*, run `bench worker --burst` once.

**Credentials rule:** API key and secret live in `~/.arinox_hosted_token` only. Never put them, a database password, or a bank/account number from the sample documents into the repo, a script, or a log.

## 3. The sandbox rules (measured, not assumed)

A Server Script is compiled by RestrictedPython. These are the rules that cost time; each was found by running it.

| Plain Python | In a Server Script | Do this |
|---|---|---|
| `class`, `import` | refused | no classes; no imports; see "shared helpers" below |
| a module-level function calling another module-level function | `NameError` (they sit in locals, not globals) | put **everything inside one function** (`def run(doc): ... ; run(doc)`); helpers nested inside it can call each other |
| `a, b = pair` | `NameError: _unpack_sequence_` | `x = pair` then `x[0]`, `x[1]` (a `for a, b in rows` loop **is** fine) |
| `"{0}".format(x)` | refused | `"%s" % (x,)` or an f-string |
| `date.strftime(...)` | `KeyError: '__import__'` | `frappe.utils.formatdate(d, "dd MMM")`, or `str(d.year)`, `d.month` |
| bare `getdate`, `flt`, `cint`, `add_days`, `nowdate` | not defined | `frappe.utils.getdate(...)` etc. |
| names starting with `_`, attributes starting with `_` | refused | rename |
| `d["a"] += 1`, `doc.x += 1` | refused | `d["a"] = d["a"] + 1` (`i += 1` on a plain name is fine) |
| `frappe._dict(...)`, `getattr`, `hasattr`, `type`, `map`, `filter`, `open`, `print` | refused | use a plain `dict`, `.get()`, list comprehensions |
| `frappe.has_permission(...)` | refused | `frappe.get_doc(dt, name).check_permission("read")` on a document that exists |
| Role checks for the Administrator | `Has Role` lists only roles assigned to the user, but Frappe treats the Administrator as holding **every** role | `frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {...}, pluck="role")` (already in `lib_maths.my_roles` and the scripts) |
| `frappe.get_roles()` | refused | `frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")` |
| `frappe.db.sql("update ...")`, `frappe.db.delete`, `frappe.db.set_single_value` | refused (SQL is read-only) | `frappe.db.set_value`, `doc.db_set`, `frappe.delete_doc(..., force=1)` in a loop |
| `frappe.model.naming.getseries` | refused | a number-series doctype (see `Arinox Number`) |
| `random` | not available | a small seeded generator written by hand |
| `re`, `math`, `collections`, `datetime`, `timedelta` | not available | `str` methods and small loops by hand; `frappe.utils.ceil / floor / add_days / date_diff` |
| a dict key that starts with `_` (for example an item code `_ATQ-1`) | `SyntaxError: Key starts with _` | prefix the key (`"k|" + code`) |
| a Server Script argument of `0` read as `form.get("x") or 1` | the integer 0 becomes 1 | test `is None`; the engine's `check` flag had this bug and is fixed |
| `frappe.defaults.get_user_default("Company")` | `TypeError: 'NoneType' object is not callable` | `frappe.db.get_value("DefaultValue", {"parent": frappe.session.user, "defkey": "Company"}, "defvalue")`, then `Global Defaults`, then the first Company |
| `run_script("x")` where x is an API method name | `DoesNotExist` | `run_script` takes the Server Script **record name** (for example `arinox_work_order_api_get_bulk_gate`), not the `api_method` (`arinox_work_order_get_bulk_gate`); `fx.engine_call` accepts either |
| `frappe.get_single(...)` for a child table of Apparel Settings | refused | `frappe.get_all("<child doctype>", filters={"parent": "Apparel Settings", "parenttype": "Apparel Settings"})` (see `lib_samples.py`) |

Allowed and useful: `frappe.get_doc / get_all / get_value / new_doc / delete_doc`, `doc.insert / save / submit / cancel / append / db_set / set`, `frappe.db.get_value / exists / count / sql` (select only), `frappe.call("dotted.path", **kw)` for any **whitelisted** function (ERPNext's `make_delivery_note`, `make_sales_invoice`, `create_variant` ...), `run_script("name", **kw)` to run another **API** script (arguments arrive in `frappe.form_dict`, results are read from `frappe.flags`), `json.loads/dumps`, `any/all/bool/sorted/min/max/sum/enumerate/zip/set`.

Events: a script is one record bound to **one doctype and one event** (Before Insert, Before Validate, Before Save, After Save, Before Submit, After Submit, Before Cancel, After Cancel, Before/After Save (Submitted Document), Before Delete ...), or one API method, or one scheduler frequency. A doctype with five hooks is five records.

**Shared helpers** cannot be imported. They are written once in `portable/hosted_scripts/lib_*.py` and copied into each script at export time by a line `    # include: lib_maths.py` (indented to where the helpers should sit, inside the script's one function). Existing libs: `lib_maths.py` (planned cut, max ship qty, unit conversion, role check), `lib_orders.py` (order matrix, planned cut date, settings reader).

**Shared state** that several documents need goes in the engine API script (`arinox_engine`, `hosted_scripts/engine.py`): `post`, `unpost`, `check`, `total`, `transfer` on the production ledger. Add new actions there instead of copying logic into many scripts.

## 4. How to port one document (the recipe)

Use the Delivery Note port as the model (`portable/hosted_scripts/delivery_*.py`, `portable/hosted_tests/test_delivery.py`).

1. **Read the source** controller (`arinox_apparel/arinox_apparel/doctype/<name>/<name>.py` or the hook module) and the app's test for it (`arinox_apparel/arinox_apparel/tests/test_*.py`). The tests are the specification.
2. **Map the methods to events** (table in the appendix): `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel, `autoname` -> already handled by `naming.py`, `@frappe.whitelist()` methods -> API scripts (section 6).
3. **Write one file per event** in `portable/hosted_scripts/`, wrapped in one function, e.g. `delivery_before_submit.py`. Translate with section 3 open. Replace `frappe.throw(_("..").format(..))` by `frappe.throw("..." % (...))`.
4. **Register it** in `portable/manifest_hosted.json`:
   `{"name": "arinox_delivery_gate", "script_type": "DocType Event", "reference_doctype": "Delivery Note", "doctype_event": "Before Submit", "file": "delivery_before_submit.py"}`.
   Hosted-only scripts go in `manifest_hosted.json`, **never** in `manifest.json` (that one is also installed on the dev site by the app's migrate and would run twice there).
5. **Write the hosted tests** in `portable/hosted_tests/test_<name>.py` with `@test("group")`. Reuse `fixtures.py` (`card()`, `colour_so()`, `delivery_chain()`, `engine()`). Mirror the app test names. Cover: the happy path, every `frappe.throw`, the override paths, and cancel.
6. **Load and run:** `./hosted_sync.sh server_scripts && ./hosted_tests.sh <group>`. Fix until green, then run `./hosted_tests.sh` (all) to check you broke nothing.
7. **Never edit the dev app to make a port easier.** If the app has a bug (section 7), report it; the hosted script may carry the corrected rule and say so in a comment.

Things that always trip a port:
- A document-event script gets `doc` as a **local**; a nested helper cannot see it unless you pass it in.
- `doc.has_value_changed("x")` and `doc.is_new()` work; `doc.flags.x = ...` works; `self.` becomes `doc.`.
- Child-table loops: `for r in doc.items:`; set values with `r.field = ...`; `doc.set("rows", [...])` replaces a table.
- A throw inside a Before/After event aborts the whole save or submit (the transaction is rolled back). Test failure paths by calling the operation inside `throws(lambda: ...)` and **reloading the document** afterwards (`doc = frappe.get_doc(doc.doctype, doc.name)`), or you get a `TimestampMismatchError`.
- A Scheduler Event script is run by the scheduler, not called; in tests use `fx.run_scheduled(name)`. An API script is called with `fx.engine_call(api_method_or_record_name, **form_values)`, and its answer is `result["arinox_result"]`.
- Do not call `frappe.flags.x` after `run_script` to read an answer; use `run_script`'s return value (`res.get("arinox_result")`).
- ERPNext has its own guards that sit in front of ours (for example over-delivery allowance, fiscal year, currency accounts). In tests raise ERPNext's limits so that your script is what is being tested (see `fixtures.delivery_chain`).

## 5. Loading onto the real hosted site

The loader is `portable/api_load.py` (standard library only). With an API key and secret of a user holding **System Manager** and **Script Manager**:

```
python3 arinox_apparel/arinox_apparel/portable/api_load.py hosted_bundle https://<site> [--only=group,group] [--dry-run]
```
(the key:secret goes in the `ARINOX_API_TOKEN` environment variable). It is idempotent: records that exist are updated. Group order is fixed in `hosted_bundle/index.json`: module, roles, doctypes (dependency order, loop-closing fields added in a second pass), custom fields, property setters, seeds, settings, print formats, reports, number cards, charts, dashboards, workspaces, sidebars, icons, client scripts, server scripts. It prints every failure with the server's message and exits 1 if anything failed.

The bundle is regenerated from the app by `bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '<dir>'}"`. What the exporter changes for a site without developer mode is listed in `HOSTED_CONSTRAINTS.md` section 6 (custom=1 on every DocType, "not standard" flags, permission tables fixed, sidebar names, Page links removed). **The kill switch is built:** the API script `arinox_scripts_switch` (`state` = `off`, `on` or `status`; needs System Manager or Script Manager) turns every Arinox *rule* script off or on in one call. It leaves the naming scripts, the ledger engine and itself on, because without them the numbered documents could not even be created. Test it on the real site before relying on it, and know the by-hand route too: Server Script list, select, Disable.

Not yet tried on the real hosted site: the Script Manager / System Manager rights of the API user, the Server Script time limit (the ledger and the carton plan loop over many rows), and creating each record type there. All were proven only on the ERPNext-only local site.

## 6. The API scripts the form buttons expect

The 30 generated Client Scripts (`hosted_bundle/16_client_scripts.json`) call these names. An **API Server Script** with exactly this `api_method` must exist for each, or the button shows "method not found". Arguments arrive in `frappe.form_dict`.

**Return convention:** an API Server Script returns the whole `frappe.flags` dict (there is no `frappe.response`). Put the answer in `frappe.flags.arinox_result` (any JSON-safe value). The generated client scripts unwrap `arinox_result` before the form code reads `r.message`, so the form code sees the plain answer. Set nothing else you need the client to read.

`frm.call("x")` on a form is rewritten to a call to `arinox_<doctype_slug>_x` with `name` (the document name) and `doc` (the document as JSON) in `form_dict`.

| API script name | Called from | What it does (from the source) |
|---|---|---|
| `arinox_sales_contract_apply_template` | Sales Contract | copy the template's terms and tolerance bands onto the contract |
| `arinox_sales_contract_make_sales_contract` | Quotation | Quotation -> Sales Contract: one line per quoted style and tech-pack colour, size rows pre-filled |
| `arinox_sales_contract_make_sales_order` | Sales Contract | contract -> Sales Order: one row per style x colour x size variant (creates variants with ERPNext `create_variant`) |
| `arinox_tech_pack_make_tech_pack` | Opportunity | start a Tech Pack from an inquiry |
| `arinox_tech_pack_make_cost_sheet` | Tech Pack | Tech Pack -> Cost Sheet |
| `arinox_tech_pack_create_style_item` | Tech Pack | create the style template Item and its colour x size variants |
| `arinox_cost_sheet_set_charges_from_parameter` | Cost Sheet | fill one charge row per enabled non-material cost head from the Costing Parameter |
| `arinox_cost_sheet_get_margin_at_price` | Price Negotiation | margin if the garment sells at a given price |
| `arinox_price_negotiation_make_quotation` | Price Negotiation | agreed price -> Quotation |
| `arinox_factory_allocation_get_lines_from_order` | Factory Allocation | one row per style x colour of the Sales Order |
| `arinox_sample_approval_load_spec_from_tech_pack`, `..._load_standard_tests` | Sample Approval | load measurements / the standard GPT tests |
| `arinox_pp_meeting_load_from_requisitions`, `..._get_buyer_comments`, `..._add_standard_participants` | PP Meeting | fill the meeting from FR/TR, buyer comments and the standard attendees |
| `arinox_fabric_requisition_get_lines_from_sales_orders`, `..._create_fabric_items`, `..._revise_fabric_requisition` | Fabric Requisition | build lines from orders, create fabric Items, make a revision |
| `arinox_trim_requisition_get_lines_from_sales_orders`, `..._create_trim_items`, `..._revise_trim_requisition` | Trim Requisition | same for trims |
| `arinox_purchase_order_make_purchase_orders` | FR and TR | approved requisition -> Purchase Orders grouped by supplier |
| `arinox_rolls_import_roll_list` | Purchase Receipt | import a fabric roll list (one Batch per roll, one Serial and Batch Bundle per receipt row) |
| `arinox_fabric_inspection_make_inspection`, `arinox_trim_inspection_make_inspection` | Purchase Receipt | start an inspection from a receipt row (the name is built from the doctype at run time) |
| `arinox_fabric_inspection_load_rolls`, `..._make_purchase_return` | Fabric Inspection | load the receipt's rolls; return rejected fabric |
| `arinox_production_card_get_summary`, `..._revise_production_card`, `..._get_order_styles`, `..._get_card_lines` | Production Card | stage totals; revise a card; list the order's styles; colour x size rows from the order |
| `arinox_cutting_get_issuable_rolls`, `arinox_cutting_issue_fabric` | Production Card | rolls that can go to the cutting floor; issue them (Stock Entry) |
| `arinox_cut_plan_suggest_rolls` | Cut Plan | allocate accepted rolls to the lays of a plan |
| `arinox_work_order_get_bulk_gate` | Work Order | the bulk-gate result for a style and colour |
| `arinox_subcontract_challan_short_close` | Subcontract Challan | close a challan with pieces still out |
| `arinox_subcontract_settlement_make_invoices` | Subcontract Settlement | draft the vendor's Purchase Invoice and the debit note |
| `arinox_packing_list_generate_cartons` | Packing List | plan the carton rows from the pack rule |
| `arinox_final_inspection_pick_cartons` | Final Inspection | draw the cartons to open (random, with a stored seed) |
| `arinox_shipment_get_available_packing_lists`, `arinox_shipment_make_delivery_notes`, `arinox_invoicing_prepare_invoices`, `arinox_invoicing_submit_invoices` | Shipment | list packing lists not yet on a shipment; one Delivery Note per Sales Order; draft and submit the commercial invoices (direct or group route) |
| `arinox_followup_log_follow_up` | Sales Invoice | write a payment follow-up note and promise date |
| `arinox_buyer_claim_make_credit_note` | Buyer Claim | draft the credit note for a decided claim |
| `arinox_close_get_checklist`, `arinox_close_commercial_close` | Sales Order | the commercial-close checklist; close the order |
| `arinox_planner_make_order_tnas` | Sales Order | build the T&A plans of an order |
| `arinox_order_tna_lock_baseline`, `..._unlock_baseline`, `..._replan` | Order TNA | freeze / unfreeze / recompute a plan |

**Built and tested:** `arinox_sales_contract_make_sales_order`, `arinox_sales_contract_apply_template`, `arinox_production_card_get_card_lines` / `get_order_styles` / `get_summary` / `revise_production_card`, the five Cost Sheet scripts (`set_charges_from_parameter`, `get_margin_at_price`, `sign_off`, `approve`, `reject`), `arinox_packing_list_generate_cartons`, `arinox_final_inspection_pick_cartons`, `arinox_invoicing_prepare_invoices` / `submit_invoices`, `arinox_followup_log_follow_up`, the kill switch, and all the Tier 1 buttons (`make_tech_pack`, `make_cost_sheet`, `create_style_item`, Cost Sheet `make_price_negotiation` / `make_quotation`, `price_negotiation_make_quotation`, `sales_contract_make_sales_contract`, the three Factory Allocation scripts, the four Sample Approval scripts, the three PP Meeting scripts, `work_order_get_bulk_gate`). **Not built:** every other row of the table above.

## 7. What the real papers showed (decisions taken and fixes made)

Two real orders were entered end to end and reconciled against the papers (the report is held back from the public repo; the lessons are here without the figures). Each item says what the papers showed, what was decided, and where it stands.

1. **A contract line is style x colour x buyer PO.** A real contract has several lines for the same style and colour, one per PO. **Fixed in both the app (`sales_contract.py`) and the hosted scripts**; a size row finds its line by style, colour and PO (a size row with no PO belongs to the only line of that style and colour, and is refused when there are several).
2. **The over-ship gate caught a real over-shipment** (one piece above the per-size allowance of the 7.5% band, rounded down). Ported and tested; keep this behaviour.
3. **Sales Order rows filled by hand have blank colour, size, PO, dates and tolerance.** Fixed on the hosted side: `sales_order_validate.py` fills them from the item's Colour/Size variant attributes and from the contract line when it is unambiguous. (Not done in the app: the app fills them only in the make-order button.)
4. **Packing List header totals** (cartons, pieces, net/gross kg, CBM, size summary, over/short %) were not computed on the hosted site. **Ported** (`packing_list_validate.py`).
5. **Two invoices, one number** (factory bills the group trader at a transfer price, the trader bills the buyer at the selling price). **Ported and tested** (`invoicing_api_prepare.py`, group route with a second company). Correction to an earlier version of this guide: the app does **not** itself refuse an invoice priced above the order. ERPNext does, but only when the invoice is *linked* to its order (Selling Settings "same rate"); the group route's second leg is not linked, so a price above the order passes on both sides. Decide whether to add a rule.
6. **One invoice may cover several contracts** (decision: allowed, default applied). The invoice keeps the first contract in the existing link and lists all of them in the new field `apparel_all_contracts` ("All Contracts On This Invoice"). Change it if the business wants one invoice per contract.
7. **Setup the real site needs** (not code): a fiscal year per year of the papers; ERPNext's *Over Delivery/Receipt Allowance* at least as large as the largest contract tolerance (15%); the Finished Goods warehouse in Apparel Settings (the make-order button now says so when it is missing); a receivable account in the invoice currency per company, named on the customer, and an exchange rate on each invoice; the freight forwarder as a Supplier; currency code CNY for the papers' "RMB"; in Stock Settings the box *Activate Serial and Batch No for Item* (fabric rolls are Batches in a bundle); the five warehouses named in Apparel Settings (inspection fabric and trim, store fabric and trim, rejected) plus Cutting WIP and Finished Goods. The hosted inspection script switches *Inspection Required before Purchase* on an item only while it makes the Quality Inspection (ERPNext checks that flag outside test mode).
8. **Seed added:** the costing sheets charge *Depreciation 2.5%*. The cost head is now in the app's seeds (`setup/install.py`) and the bundle.
9. **Legacy numbers.** Set `arinox_name` before insert to keep a number from the paper; `naming.py` leaves a pre-set name alone. Counters are drawn on every insert attempt, so a failed save leaves a gap (this matches `getseries`).
10. **Shipping marks may stay TBA** (decision: yes). Fixed in both the app and the hosted script; every other field is still refused when left as TBA/TBC/N/A.
11. **Measurements:** a grade sheet can have rows with no POM code, a LINING section repeating the same POM codes, and dated (revised) rows. New fields added in the app and bundle: Tech Pack `buyer_created_on`, `buyer_revised_on`; Tech Pack Measurement `section`, `revised_on`; Trim Requisition Item `stock_decision`; Sales Contract `production_lead_days`.
12. **Two latent errors in the app's permission tables** (PP Meeting: Sales User could submit/cancel/amend without write; Fabric and Trim Inspection listed three roles twice) are corrected in the app JSON, so the exporter no longer has to patch them.
13. **App bug found and fixed:** `shipping/invoicing.py` stored the Sales Order's *name* in the "Contract" link when an order had no contract, which fails link validation. It now links only a contract that exists.
14. **Seeds and settings are create-only on load.** A live site's merchandisers add colours and sizes and edit defaults; a reload must not remove or overwrite them. `api_load.py` skips existing seeds and fills only blank fields of Apparel Settings; `--overwrite-seeds` forces a replace.

## 8. What to build, in order

Dependency order for a hosted pilot. "Tests to mirror" are the app's test files. **Done and tested on the hosted-like site (see HOSTED_STATUS.md for the count):** naming, the ledger engine, Production Adjustment, Production Card (+ its helper buttons), Sales Contract (+ make-order and apply-template buttons), Sales Order hooks, **Cost Sheet** (maths, approval, sign-off, margin button), **Packing List** (carton planning, totals, SSCC, needle gate, ledger, finished-goods receipt, Generate Cartons button), **Final Inspection** (AQL decision, re-inspection chain, seeded carton draw, Pick Cartons button), Delivery Note gates, **invoicing** (direct and group route, Prepare/Submit buttons), **payment follow-up** (expected due date, daily reminders, Log Follow-up button), the shipment-to-invoice due-date refresh, and the **kill switch**.

**Tier 1: merchandising backbone: DONE and tested (72 hosted tests).** Tech Pack, Price Negotiation + Quotation hook, Cost Head / Costing Parameter, Factory Allocation, Sample Approval, PP Meeting, the bulk gate (engine action `bulk_gate`, Work Order hooks), and the buttons of all of them. Left over from this tier: the Cost Sheet agent helpers `get_costing_context` / `get_previous_costing`; the pilot-run *approved* path of the gate is not covered by a hosted test (Pilot Run is Tier 3). The gate already reads `material_gate` from `materials/status.py` (ported into `lib_materials.py`), so the Tier 2 status port should reuse that file.

**Tier 2 (materials), Tier 3 (production floor), Tier 4 (subcontract and finishing), Tier 5 (ship and collect), Tier 6 (time and action) and Tier 7 (the remainder): DONE and tested on the hosted-like site.**
- *Tier 2:* Fabric and Trim Requisition (+ revise, save, items, lines, context buttons), Purchase Order and Purchase Receipt hooks, roll import, Fabric and Trim Inspection (+ load rolls, make inspection, purchase return), material status (`lib_material_status.py`) and gate.
- *Tier 3:* Cut Plan, Lay Report, Recut Request, Cut Bundle, fabric issue and remnant return, Operation Bulletin, Line Input, Daily Line Report, Line QC Report, Pilot Run, Finishing Receipt, Needle Detector Log.
- *Tier 4:* Subcontract Challan, Return and Settlement (+ short close, make invoices).
- *Tier 5:* Shipment hooks and buttons, freight (forwarder bills against the quote, allocation), Buyer Claim (+ credit note), commercial close, the EX_FACTORY stamp and shipment status on Delivery Notes.
- *Tier 6:* the whole T&A cluster: `arinox_tna` (stamp, unstamp, refresh, samples, refind), the planner (`lib_tna_plan.py`), Order TNA, TNA Milestone, TNA Template, the board / update / agent endpoints, and the hooks that stamp from Tech Pack, Sample Approval, PP Meeting, Work Order, Sales Order, requisitions, purchase, receipt, inspections, lay, pilot, shipment and delivery.
- *Tier 7:* the 5 script reports (`script_reports/`, shared helpers copied in by `reports.py`), the 2 number cards (Report-type cards over two one-row Query Reports, `reports.CARD_QUERY_REPORTS`), the ledger repair (`arinox_ledger_rebuild_movements`), and the agent endpoints.
- **Not portable:** the OB workbook importer (`import_ob_workbook`, needs `openpyxl` to read an uploaded file) and the file-based pages. Not built here: the WIP *screen* and the `wip_report` Script Report (being built separately; it reads the same `arinox_api_wip_board_data`).

## 9. What cannot be done on the hosted site, and what to build instead

| Cannot | Why | Build instead |
|---|---|---|
| Order Desk and WIP Board screens | file-based Pages need files on the server | being built as a separate app by the team; meanwhile Kanban view on Sales Order, Report Views, the number cards and the four decks |
| `override_doctype_class`, subclassing an ERPNext controller | no classes, no app code | event scripts only (Before/After Save, Submit, Cancel) |
| `override_doctype_dashboards` (Connections tab links) | a hook, not a record | Number Cards / workspace shortcuts; or Customize Form "Links" (data) on Opportunity, Quotation, Customer, Sales Order |
| Raw SQL writes, transaction control | read-only SQL | `db.set_value`, `doc.db_set`, `delete_doc` in loops |
| Libraries, PDFs rendered on the server, server-side barcode images | no imports | print formats rendered in the browser (the SSCC barcode already works this way) |
| Seeding at migrate time | scripts do not run during install | the bundle's seed records, loaded once by `api_load.py` |
| Automated tests on the real hosted site | no bench | the ERPNext-only local site and `hosted_tests.sh` |
| A script time limit | unknown, set by the host | keep loops small; use `frappe.enqueue` for ledger rebuilds; ask the host for the limit |

## 10. Definition of done, and the checks before anything is pushed

A port is done when:
- the script file is in `portable/hosted_scripts/`, registered in `manifest_hosted.json`, and uses only sandbox-safe constructs (the loader compiles with Frappe's own restricted compiler and refuses otherwise);
- it has hosted tests covering the happy path, every throw, the override and the cancel path, and `./hosted_tests.sh` is fully green;
- the bundle reloads onto the hosted-like site with **0 failures and nothing newly created** on a second run;
- `bench --site apparel.localhost run-tests --app arinox_apparel` is still green (407 tests, 2 skipped as of 2026-11-05) - the dev app must not change behaviour because of a port;
- the item is ticked in `HOSTED_STATUS.md` and removed from section 8 here.
- **a DocType layout change comes with a data conversion.** Loading a changed DocType adds the new columns but never converts or drops the old ones, so records saved before the change look empty or repeated (this happened to Tech Pack Measurement: one row per size became one row per point, and old Tech Packs showed every point once per size at 0). Ship an API Server Script that converts the old rows (see `tech_pack_api_merge_measurements.py`) and a hosted test that builds old-layout rows, runs it, and runs it twice.
- **a form button must name an API script that exists.** `client_scripts.unknown_methods()` is run by the exporter and fails the export on a name no API Server Script answers (the browser would say "App ... is not installed"). `frappe.model.open_mapped_doc` is handled by a shim in the generated prelude; do not call `frappe.model.mapper` from a hosted form script. The generated `frm.call` only redirects a method when `arinox_<doctype>_<method>` is a registered API script, so ERPNext's own `frm.call({method: "erpnext...."})` is never hijacked; `portable/check_client_routing.py` runs the generated script in Node against a stub and checks both.
- **rows loaded from outside (ingest, import, API) must go through the same save scripts.** A record inserted before its scripts were loaded keeps its zeros (the saved Cost Sheets had every amount at 0 until re-saved). Re-save loaded records after loading scripts, and load a Tech Pack's whole BOM into the Cost Sheet, not a summary.
- **the Cost Sheet save script now guards the common data mistakes:** a mandatory Cost Head missing from the charges is put back (rate from the Costing Parameter if it has one), a rate in another currency with the exchange rate the wrong way round is refused, and unpriced lines or BOM lines missing from the sheet produce an orange warning (never a block).

Before a push: do not commit the sample-document zip, `erpnext-test/`, any token, or any bank/account number. `hosted_bundle/` is generated output (about 1.4 MB): commit it only if the hosted agent will load from the repo; otherwise regenerate it.

---

## Appendix: every unported file, from the source

Generated from the code (`ast`), so the descriptions are the app's own docstrings. `Lines` counts non-comment lines. 
`Events` are the controller or hook methods and the Server Script event each becomes. `Buttons / API` are the `@frappe.whitelist()` functions, each of which becomes an API Server Script (see section 6 for naming).

### A. Document controllers (one script set per doctype)

**Cost Sheet** (488 lines)  
Status: PORTED and tested (`cost_sheet_validate/submit` + 5 API scripts); `get_costing_context` and `make_price_negotiation` / `make_quotation` are not  
Garment cost build-up.  
Events: `validate` -> Before Save, `before_submit` -> Before Submit  
Buttons / API: `set_charges_from_parameter` (Fill one charge row per enabled, non-material cost head, with rates from the parameter.); `sign_off` (Record the current user against one costing sign-off step. Steps are signed in order.); `approve`; `reject`; `get_margin_at_price`; `get_costing_context` (One call for the AI costing agent: the parameter that applies, its rates, the cost head library, and); `get_previous_costing` (Materials and charges of an earlier Cost Sheet, for copying into a new one.); `make_price_negotiation` (Add this costing to the customer's open negotiation for the inquiry, or start one.); `make_quotation`  
Rules inside: `check_cost_heads_complete`: G1: a cost left out comes straight out of margin.; `margin_at_price`: Margin if the garment sells at `price`. Price-based charges other than profit scale with it.  

**Fabric Requisition** (383 lines)  
Fabric Requisition (FR): the merchandiser's request to buy fabric, one line per style x colour x fabric. Submit = approved. Submitting creates Material Requests (grouped by supplier). Totals are always computed here, never trusted from the client.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  
Buttons / API: `get_lines_from_sales_orders` (One row per style x colour x fabric of the Tech Pack, quantities from the Sales Order.); `create_fabric_items` (Create the template and colour variant for every row that has none.); `get_requisition_context` (Everything an agent needs to draft the FR and TR for an order.); `save_fabric_requisition` (Create or update a DRAFT fabric requisition. Validation runs. Never submits.); `revise_fabric_requisition` (A new draft revision of an approved FR. Quantities are refreshed from the order on save; only the in)  

**Trim Requisition** (378 lines)  
Trim Requisition (TR): labels, thread, fusing, buttons, tags, packaging for an order. Quantities depend on the basis: per garment, per size, per colour, per carton, by length or a fixed quantity. Submit = approved.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  
Buttons / API: `get_lines_from_sales_orders`; `create_trim_items`; `save_trim_requisition` (Create or update a DRAFT trim requisition. Validation runs. Never submits.); `revise_trim_requisition`  
Rules inside: `order_qty_for`: Garment qty for the row's scope: a size, a colour, or the whole style.  

**Sales Contract** (359 lines)  
Status: events PORTED and tested (5 scripts, line rule corrected to style x colour x PO); the API buttons are not  
The legal garment contract. Freezes price, colours, quantities and three dates per SKU. A SKU here is one style x colour line; the size breakdown becomes variant lines on the Sales Order.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  
Buttons / API: `apply_template`; `make_sales_contract` (Quotation -> Sales Contract (unsaved). One line per quoted style and tech-pack colour, with the size); `make_sales_order` (Sales Contract -> Sales Order (unsaved): one line per style x colour x size variant.)  
Rules inside: `set_bank_account`: The Company's own default bank account prints on the contract. Bank details are never stored here.; `validate_price_lock`: G2: the price agreed on the quotation is the price on the contract.; `check_placeholders`: Nothing is left TBA on a signed contract.  

**Sample Approval** (348 lines)  
One approval item: a sample type for a style (and colour, and material) with every submission round, the buyer's decision and comments. Status follows the last round. The bulk gate reads these records.  
Events: `validate` -> Before Save, `on_update` -> After Save  
Buttons / API: `load_spec_from_tech_pack` (Fill the measurement table with the tech pack spec for the sample size.); `load_standard_tests` (Add the standard test list from Apparel Settings (one test per line).); `get_sample_rules`; `get_sampling_milestones` (Sampling dates and status per style x colour, for the T&A / WIP sheet or the planning agent: for eac)  
Rules inside: `compute_measurements`: Up to five sample readings per point; in tolerance only when every reading is.; `set_chargeback`: Exposure = the rule's chargeback when the sample went out late, or is overdue and still not sent.  

**Production Card** (338 lines)  
Status: events PORTED and tested (5 scripts); the API buttons are not  
Production Card: the order sheet issued to cutting. One per Sales Order x style x ex-factory date, one line per colour x size. Submit = issue. Issuing needs no bulk gate (the PP meeting asks for an issued card, so the gate cannot come first); the gate is checked at the first bulk lay. The card never creates purchase requests: fa  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `get_summary`; `get_card_lines` (Colour x size rows for a new card, straight from the Sales Order.); `revise_production_card` (New draft from an issued card, quantities refreshed from the current Sales Order. Cancel-and-amend i); `get_production_context` (Everything an agent needs to draft production cards for an order.); `save_production_card` (Create or update a DRAFT production card (validation runs). Never submits.); `get_production_status`; `get_order_styles` (Style templates on a Sales Order, for the style picker.)  
Rules inside: `refresh_status`: Status follows the furthest stage that has quantities (never moves backwards past Issued).; `check_unique`: One live card per order x style x ex-factory date. A revision chain shares the key.; `link_pp_meeting`: The PP meeting asks for an issued production card; hand it the reference on any draft meeting.  

**Fabric Inspection** (279 lines)  
Fabric Inspection: the 4-point inspection of the rolls received on one Purchase Receipt row. Submit writes the result to every roll (Batch), makes the Quality Inspection and the Stock Entry that releases accepted rolls to the store and moves rejected rolls to the rejected warehouse.  
Events: `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `load_rolls` (One roll row per batch received on the receipt row.); `make_inspection` (A new Fabric Inspection for one received fabric row, with its rolls loaded.); `make_purchase_return` (Purchase return of the rejected rolls, taken from the rejected warehouse. Returns the draft return.)  

**Lay Report** (265 lines)  
Lay Report: one lay (a stack of plies under one marker) cut at one table. Submitting posts the cut pieces to the production ledger, numbers the plies into Cut Bundles and returns what is left of each roll to the store.  
Events: `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Rules inside: `available`: Metres of a roll still free for a lay: what is in the Cutting WIP warehouse less what submitted lays already u  

**Packing List** (259 lines)  
Status: PORTED and tested (5 event scripts + the Generate Cartons button)  
Packing List: cartons of a Sales Order's pieces for one buyer PO and ship-to. Replaces ERPNext's Packing Slip, which needs a draft Delivery Note and has no carton range, ratio, CBM or SSCC. Posts PACKED to the production ledger and drafts the finished-goods receipt. Cartons are numbered as a run of identical cartons (`1~11`) lik  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  
Buttons / API: `generate_cartons` (Build the carton rows from `quantities` ({'colour|size': pieces}); default is everything packable fo)  
Rules inside: `packable`: Pieces that can still go into cartons: A-grade not sampled or packed, less pieces on other draft lists, kept i; `check_pack_finished`: PACK_FINISHED is complete when every colour and size with A-grade pieces has them all packed (less samples).; `make_sscc`: One SSCC per carton number from a counter that never goes back, so a cancelled list keeps its numbers retired.; `make_fg_receipt`: Draft Material Receipt of the packed pieces into Finished Goods, so the Delivery Note has stock. The accountan  

**Tech Pack** (205 lines)  
What the buyer sent for one style: images, sizes, measurements, colourways and their BOM.  
Events: `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `make_tech_pack` (Opportunity -> new Tech Pack (unsaved).); `make_cost_sheet` (Tech Pack -> new Cost Sheet (unsaved), materials copied from the buyer BOM with buying rates.); `create_style_item` (Create the style as an Item template with Colour and Size attributes, adding any of this Tech Pack's)  
Rules inside: `validate_fit_rounds`: The header shows the result of the latest round.  

**Pp Meeting** (189 lines)  
Pre-production meeting, held after the production card is issued. Planning, purchasing, cutting, sewing, (washing) and QC attend, and every open buyer comment is turned into an action with an owner and a date. Submitting the meeting issues the minutes; action rows stay editable so they can be closed later.  
Events: `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_update_after_submit` -> After Save (Submitted Document), `on_cancel` -> After Cancel  
Buttons / API: `load_from_requisitions` (Fabric required and received, shade count and trim readiness from the requisitions of this order and); `get_buyer_comments`; `add_standard_participants`  
Rules inside: `check_pp_sample`: A PP sample is needed when the rules require one (or one was named). Buyers that waive PP skip it.  

**Price Negotiation** (175 lines)  
Every offer and counter on a style, with the margin each price would leave.  
Events: `validate` -> Before Save  
Buttons / API: `make_quotation`  

**Factory Allocation** (171 lines)  
Which factory and line makes which style x colour of a Sales Order. Decided by the AI agent or a planner; the ERP stores it and checks it is consistent. One allocation per Sales Order, named FA-<Sales Order>.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save  
Buttons / API: `get_planning_context` (Everything the planning agent needs in one call: the order lines, the factories and their lines, and); `save_allocation` (Create or replace the allocation of a Sales Order. `lines` is a list (or JSON) of {style_item, colou); `get_lines_from_order` (One blank allocation row per style x colour of the order, for the form's Get Order Lines button.)  
Rules inside: `validate_lines`: A row is for a style x colour, optionally narrowed to a ship-to and/or buyer PO. Blank = the whole colour.  

**Final Inspection** (167 lines)  
Status: PORTED and tested (4 event scripts + the Pick Cartons button; the T&A FINAL_INSPECTION stamp is left out)  
Final Inspection: AQL inspection of a packed lot (one or more Packing Lists of one order). Follows the company's form. Sample size and accept/reject numbers come from the AQL Plan; a row that QA has not confirmed cannot be used. Any critical defect fails. The Delivery Note will not submit unless every packing list on it is in a  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `pick_cartons` (Draw the cartons to open, at random from the lot's own carton numbers. The seed is stored so the dra)  
Rules inside: `check_chain`: A re-inspection follows a rejected or on-hold inspection of the same lot; too many needs a manager.  

**Buyer Claim** (101 lines)  
Buyer Claim: a complaint, short-shipment claim, chargeback or concession against a customer invoice. The contract sets the window (quality 60 days, quantity 30 days after arrival) and caps what is payable at the CIF value of the pieces. Settling drafts a credit note; a deduction is recorded on the payment. Nothing is submitted f  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit, `on_update` -> After Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `make_credit_note` (Draft the credit note for an accepted claim against the customer invoice (the accountant submits it))  
Rules inside: `sync_invoice`: While a claim is undecided or being settled, the invoice is Disputed so no reminders go out.  

**Daily Line Report** (100 lines)  
Daily Line Report: what a sewing line passed at the end of the line in a day, with the manpower and time. Efficiency is always computed from the operation bulletin: produced minutes = output x SAM, available minutes = operators x (shift + overtime - downtime). Submitting posts SEW_OUT to the ledger.  
Events: `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  

**Cut Plan** (99 lines)  
Cut Plan (lay plan): which markers, size ratios and plies make up the cut quantity of one colour and fabric. A plan whose marker consumption differs from the card's by more than the setting needs a manager before it is released.  
Events: `validate` -> Before Save  
Buttons / API: `release` (Release the plan. A variance above the limit sends it to a manager instead.); `approve`; `reopen`; `suggest_rolls`  

**Line Qc Report** (98 lines)  
Line QC Report: the end-line audit and the finishing inspection are the same hourly form (checked, passed, defects by code), plus the inline traffic-light rounds. DHU = defects x 100 / checked. RFT = pieces passed first time / checked; a repaired piece never counts toward RFT. Rejects and B-grade post to the production ledger.  
Events: `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  

**Subcontract Settlement** (96 lines)  
Subcontract Settlement: what the vendor is owed for one challan. Vendor-damaged and missing pieces are not paid; vendor damage above the process's limit attracts a penalty. Drafts the vendor's invoice and a debit note for the accountant; nothing is submitted here.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `before_submit` -> Before Submit  
Buttons / API: `make_invoices` (Draft the vendor's Purchase Invoice (and a debit note for the penalty). Accounts submits them.)  

**Trim Inspection** (95 lines)  
Trim Inspection: the visual inspection of a trim received on one Purchase Receipt row (labels, buttons, tags ...). A sampling plan sets how many pieces are checked; submit makes the Quality Inspection and releases or rejects the stock.  
Events: `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Buttons / API: `make_inspection`  

**Subcontract Challan** (94 lines)  
Subcontract Challan: pieces sent to a vendor for a process (wash, embroidery, print, appliqué). Posts SC_OUT to the production ledger against the process on the card's route. The vendor's work is priced on a Purchase Order.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  
Buttons / API: `short_close` (Accept that the rest will not come back. Production Manager only; the gap shows as Short on the sett)  
Rules inside: `check_order`: Warn when the pieces sent on all challans against one order exceed what the order allows.  

**Pilot Run** (93 lines)  
Pilot Run: the production record that releases bulk cutting. The pieces are not typed here; they come from the movement ledger (purpose Pilot). The PP Meeting of type Pilot Run stays the review meeting (Phase B).  
Events: `validate` -> Before Save, `before_submit` -> Before Submit, `on_submit` -> After Submit, `on_cancel` -> After Cancel  
Rules inside: `fill_pieces`: Cut, sewn, washed and rejected pilot pieces per colour, read from the ledger.  

**Line Input** (86 lines)  
Line Input: cut bundles loaded onto a sewing line (the company's line loading). Submitting posts SEW_IN to the ledger and marks the bundles Issued.  
Events: `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  

**Subcontract Return** (81 lines)  
Subcontract Return: pieces that came back from the vendor, split into good, vendor fault and factory fault. A vendor cannot return more than was sent on the challan. Posts SC_BACK_* to the production ledger.  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `on_submit` -> After Submit, `before_cancel` -> Before Cancel, `on_cancel` -> After Cancel  

**Operation Bulletin** (46 lines)  
Operation Bulletin (OB): the operations of a style with their times (SAM). It sets the daily target of a line and the capacity used to load orders. Targets are computed from the working minutes stored here; the company's sheet divides the hourly target by 9.5 hours whatever the working time, which this does not copy.  
Events: `validate` -> Before Save  
Buttons / API: `activate`  

**Tna Milestone** (46 lines)  
One milestone of one Order TNA. A plain doctype (not a child table) so the Calendar, Gantt, Kanban and Report views work on it.  
Events: `validate` -> Before Save, `on_update` -> After Save, `on_trash` -> Before Delete  
Buttons / API: `get_events` (Calendar events for the Calendar view: one per milestone, coloured by its current status.)  

**Recut Request** (44 lines)  
Recut Request: replacement panels for pieces rejected at cutting or sewing. The re-cut itself is a Lay Report with purpose Re-cut that names this request. Panels are cut from the same roll, or from the same dye lot only when a manager approves.  
Events: `validate` -> Before Save, `on_cancel` -> After Cancel  

**Costing Parameter** (42 lines)  
Effective-dated costing rates for a customer x product type. Nothing in costing is hardcoded.  
Events: `validate` -> Before Save  

**Finishing Receipt** (36 lines)  
Finishing Receipt: pieces that arrived in finishing from sewing or from a vendor process. Posts FIN_IN, which the flow rules cap at what the previous route step released (a washed style cannot receive more than came back).  
Events: `autoname` -> Before Insert (name), `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  

**Order Tna** (36 lines)  
The time-and-action plan of one style x colour x ex-factory date of a Sales Order.  
Events: `validate` -> Before Save  
Buttons / API: `lock_baseline` (Freeze the planned dates. From now on a change goes in the Revised Date with a reason.); `unlock_baseline`; `replan`  

**Production Adjustment** (34 lines)  
Status: PORTED and tested  
Production Adjustment: a manager's correction of a counting mistake. The ledger is append-only through documents, so a wrong count is fixed by a signed adjustment with a reason, never by editing history.  
Events: `validate` -> Before Save, `on_submit` -> After Submit, `on_cancel` -> After Cancel  

**Tna Template** (32 lines)  
Events: `validate` -> Before Save  

**Needle Detector Log** (29 lines)  
Status: its gate rule is used by the packing list (`packing_list_submit.py`); the log document's own validation is not ported  
Needle Detector Log: one row per calibration check of the metal detector. A failed check means everything passed since the last good check is scanned again; until that is logged, nothing from the line may be packed.  
Events: `validate` -> Before Save  

**Sales Contract Template** (23 lines)  
Events: `validate` -> Before Save  

**Cost Head** (20 lines)  
Events: `validate` -> Before Save  

**Cost Sheet** (15 lines)  

**Apparel Settings** (10 lines)  
Events: `validate` -> Before Save  

**Cut Bundle** (9 lines)  
Cut Bundle: a ticketed group of panels (one size, consecutive plies, one component). Made by the Lay Report; the line input, the subcontract challans and the daily line report move its status.  
Events: `validate` -> Before Save  

### B. `production/` helpers

**production/cutting.py** (160 lines)  
Cutting: roll suggestion for a cut plan, bundle numbering for a lay, kit components. Rules live here so the Lay Report, the agent API and the tests share them.  
Buttons / API: `get_issuable_rolls` (Accepted rolls in the fabric store for the fabrics of a production card, with their free length.); `issue_fabric` (Issue rolls to the cutting floor. `rolls` = [{batch_no, qty}] (JSON).); `suggest_rolls_for_plan`  
Functions: `required_components`: Fabric roles that make up a garment of this colour on the production card (Shell, Lining, ...).; `suggest_rolls`: Allocate the rolls in the Cutting WIP warehouse to the lays of a cut plan: group by shade band, then; `next_ply`: First free ply number on a production card (sticker numbers never repeat on a card).; `chunks`: Ply ranges [(from, to)] of at most `size` plies covering first..last.; `make_bundles`: Create the Cut Bundles of a submitted Lay Report. A paired (lining, pocketing) lay mirrors the ply r; `void_bundles`: Cancel of a lay: bundles are voided (their numbers are never reused). Blocked once any bundle left t; `kit_missing`: For shell bundles about to go to a line: the kit keys whose lining / pocketing bundles are missing.  

**production/maths.py** (138 lines)  
Status: `planned_cut`, `max_ship_qty` PORTED (`lib_maths.py`); the rest is not  
Pure production maths. No database access, so every function is tested directly with the numbers from the company's own sheets (see doctypes/PHASE_D_PRODUCTION_PLAN.md section 12).  
Functions: `planned_cut`: Cut quantity for one colour x size: order quantity plus the extra cut, rounded UP to whole pieces. T; `max_ship_qty`: Largest shipment the contract tolerance allows (floor: never ship above the band).; `ratio`: Safe division; None when the denominator is zero so a report shows a blank, not an error.; `lay_consumption`: Fabric laid per garment cut: sum(marker length x plies) / pieces cut.; `actual_consumption`: Fabric actually drawn from the store per good garment cut, end bits and waste included.; `weighted_marker_efficiency`: rows: iterable of (efficiency_pct, plies). Weighted by plies.; `day_target`: Garments per day = operators x working minutes x efficiency / SAM. (The company's OB sheet agrees wi; `operation_target_per_hour`: Pieces per hour one operator can do on an operation of `sam` minutes.; `learning_factor`: curve: list of (day_no, pct_of_target). Day beyond the table uses the last row; no table = 100 %.  

**production/packing.py** (132 lines)  
Carton planning and the packing-list checks that need no database (plan sections 6 and 10.2).  
Functions: `plan_cartons`: qty: {(colour, size): pieces} in the order they should be packed. ratio: {size: pieces per pack}. Re; `check_ranges`: ranges: [(from, to)] in any order. Returns a list of problems: not contiguous from the first number,; `sscc_number`: 18-digit SSCC: extension digit + company prefix + serial, padded to 17 digits, then the GS1 check di; `size_summary`: Lines 'colour size: packed vs ordered (+x %)' and the total, like the company's OVERAGES / SHORTAGES; `draw_cartons`: Pick `how_many` cartons at random from `cartons` = [(packing_list, carton_no, is_tail)], the same dr  

**production/ledger.py** (128 lines)  
Status: PORTED as `engine.py` (post, unpost, total, check, transfer); `rebuild_movements` is not  
The Production Movement ledger: every stage document writes its quantities here, and reports sum them.  
Functions: `post`: Write `rows` (dicts: stage, colour, size, qty, purpose, process, line, supplier, shade_band, fault_s; `unpost`: A source document was cancelled: remove what it wrote.; `refresh_card_status`: Card status follows the furthest stage that has quantities. Closed, Superseded and Cancelled cards a; `totals`: {(colour, size): {stage: qty}} for one card.; `rebuild_movements`: Recompute the ledger of one card from its submitted source documents (a repair tool). Returns the nu; `transfer_card`: A revision of a production card keeps the history: every ledger row and stage document that points a  

**production/flow.py** (122 lines)  
Status: PORTED inside `engine.py`  
Loads the ledger totals of one production card once, then answers `limit()` and absorbs `apply()` so several rows of one document are checked cumulatively.  
Rules inside: `after_output`: Pieces that have finished every garment process and sewing: what finishing may receive.; `limit`: (max qty this row may add, 'block' or 'warn'), or (None, None) when no rule applies.; `check`: Raise if any row exceeds its limit. Rows of the same document accumulate.  
Functions: `repair_accepted`: Factory-fault rejects the factory decided to repair and take back into finishing (plan 9.4). Filled   

**production/sewing.py** (115 lines)  
Sewing helpers: the active operation bulletin of a style, the learning-curve day on a line, and the import of the company's OB workbook layout. Rules are data (Apparel Settings); no buyer or line is named here.  
Buttons / API: `import_ob_workbook` (Make a DRAFT Operation Bulletin from an uploaded OB workbook (one sheet per style).)  
Functions: `active_ob`: The Operation Bulletin in force for a style (newest Active one), or None.; `learning_day`: Day number of a style on a line, counted from its first Line Input there (1 on the first day).; `parse_ob_rows`: Rows of cells (lists) from one OB sheet -> {'header': {...}, 'operations': [...]}. Quirks of the she  

**production/stock.py** (84 lines)  
The few ERPNext Stock Entries Phase D makes (plan section 3.3): fabric issue to the cutting floor, remnant return, trim issue. Production tracking itself is quantity based; stock only moves where a physical store hands goods over.  
Functions: `roll_available`: Metres of a roll (Batch) in a warehouse. 0 when the warehouse is unknown.; `make_transfer`: Material Transfer for `rows` = dicts(item_code, qty, s_warehouse, t_warehouse, batch_no=None). Retur; `moved`: Quantity moved by submitted entries of this kind for a production card (optionally one item).; `issue_fabric_entry`: Issue rolls from the fabric store to Cutting WIP. rolls = [{batch_no, qty}]. Only accepted rolls lea; `refresh_issued`: Write the issued metres onto the fabric rows of an issued card (an issued card is not re-validated,   

**production/gate.py** (76 lines)  
The bulk gate, as a plain function so the Work Order hook, the Production Card and the first bulk lay all use the same rules. `stage` is "pilot" (PP meeting, buyer approvals, materials) or "bulk" (all of that plus an approved pilot run when the production card says one is required).  
Functions: `active_card`: The live (issued, not superseded) production card for an order and style, or None.; `pilot_blockers`: Blockers from the pilot run. Only applies when a live production card exists and requires a pilot.; `bulk_gate_for`: {'applies', 'style', 'colour', 'blockers', 'warnings'} for bulk production of this style x colour on  

**production/summary.py** (38 lines)  
Quantities read back from the ledger for reports: one place so the WIP report, the stock report and the production summary agree.  
Functions: `stage_qty`: Sum of ledger quantity for stages of one order x style x colour across its live cards.; `fabric_usage`: (good garments cut, metres drawn net of remnants returned, actual consumption per garment) for one f  

**production/measurements.py** (13 lines)  
Garment measurement checks shared by the pilot run and later inspections. Same rule as Phase B's Sample Approval: up to five readings per point, in tolerance only when every reading is.  

### C. `shipping/` (Phase E)

**shipping/shipment.py** (204 lines)  
The export shipment: ERPNext's Shipment, extended with the booking, vessel or flight, bill of lading, customs declarations and the packing lists on board. Nothing new is invented for what Shipment already holds (forwarder, AWB, incoterm, delivery notes, parcels); the apparel fields are custom fields on it (setup/shipping.py).  
Buttons / API: `get_available_packing_lists` (Submitted packing lists not on any shipment, with the state of their final inspection.); `make_delivery_notes` (One draft Delivery Note per Sales Order on the shipment, quantities exactly as packed, each row tied)  
Functions: `before_validate`: Shipment insists on pickup details a freight forwarder booking does not have; give them sensible def; `fill_parcels`: One parcel line per carton size and weight, with the number of cartons: ERPNext's own way to say 'th; `goods_value`: Order value of the pieces on the packing lists (the commercial invoice value, before the invoices ex; `check_measures`: Declared, booked, carrier and customs figures are kept apart; a big difference is shown, never overw; `on_update`: Tie the packing lists to this shipment, and release any that were taken off.  

**shipping/invoicing.py** (152 lines)  
Status: PORTED and tested (`invoicing_api_prepare`, `invoicing_api_submit`)  
Commercial invoices from a shipment's Delivery Notes.  
Buttons / API: `prepare_invoices` (Draft the invoices of a shipment. Re-running replaces drafts and keeps the invoice numbers; submitte); `submit_invoices` (Submit the drafts leg by leg (the factory's invoice first). Needs the bill of lading date when the c)  
Functions: `transfer_rate`: Price of one piece between the group companies, by the customer's transfer-price basis.; `build_leg`: A draft Sales Invoice for the pieces on `dn`. `rates` maps a DN row name to the unit price to bill.  

**shipping/delivery.py** (128 lines)  
Status: PORTED and tested (5 scripts); the T&A EX_FACTORY stamp and the shipment status refresh are left out  
Delivery Note hooks: the final-inspection ship gate, the over-ship check, and the SHIPPED posting.  
Functions: `validate`: Copy the production card and contract down from the packing list on each row.; `check_over_ship`: Pieces shipped against each Sales Order line, with this note, must stay inside the contract's allowa  

**shipping/followup.py** (122 lines)  
Status: PORTED and tested (`lib_followup.py`, `followup_daily.py`, `followup_api_log.py`, `shipment_refresh_invoices.py`)  
Payment follow-up on the customer's Sales Invoice. ERPNext keeps the due date fixed once an invoice is submitted, and the contract may count the days from the bill of lading, the arrival or the receipt of goods. So the *expected* due date lives in custom fields on the invoice, recomputed whenever the shipment's dates change, and  
Buttons / API: `log_follow_up` (Record a call or a promise on a customer invoice. The note becomes a comment; the promise and the ne)  
Functions: `expected_due`: (basis date, where it came from, expected due date). ROG counts from the recorded delivery; until th; `refresh_invoice`: Recompute the expected due date of one invoice from its contract terms and its shipment's dates.; `status_for`: Follow-up status for one invoice. Pure, so it can be tested with fixed dates.; `daily`: Scheduler: refresh every open customer invoice, and raise a ToDo when it crosses a reminder or escal  

**shipping/close.py** (65 lines)  
Commercial close of an order: production done, everything shipped is invoiced, every customer invoice paid, no claim open and every claim window over (or waived with a reason). Closing sets the Sales Order to Closed.  
Buttons / API: `get_checklist`; `commercial_close`  
Functions: `checklist`: [(label, ok, detail)]. Pure reading; nothing is changed.  

**shipping/common.py** (51 lines)  
Status: naming helpers PORTED (`naming.py`); `stamp_card` / `unstamp_doc` are not  
Shared helpers for Phase E: the contract-wide serial and the plain lookups every shipping document needs.  
Functions: `serial_root`: The number the whole trail hangs on: the contract, or the order when it has none.; `next_serial`: `<root>-<code>-<nn>`; the counter is per root and code and never goes back, so a number is not reuse; `card_context`: The fields every document copies from its production card.; `stamp_card`: Stamp a T&A milestone for every colour of the card's order. Never raises: a T&A fault must not stop   

**shipping/freight.py** (43 lines)  
Freight cost of a shipment. The forwarder's quote is an ERPNext Supplier Quotation; the forwarder's bills are Purchase Invoices; both are tagged with the Shipment. This module adds them up, compares them, and shares the cost out over the orders on board. It writes no accounting entries.  
Functions: `refresh_costs`: Estimate (the chosen quote), actual (the forwarder's invoices not cancelled) and the gap, written on; `allocation_basis`: Share of a shipment's cost per order: by CBM at sea, by chargeable weight by air, by invoice value f; `allocated_costs`: [(contract, share, cost)] with the shipment's actual cost (estimate while no bill has arrived) share  

### D. `tna/` (time and action)

**tna/planner.py** (257 lines)  
Planning dates for an Order TNA. `plan_dates` is pure (dates in, dates out) so each rule is easy to test; `make_order_tnas` builds the documents from a Sales Order.  
Buttons / API: `make_order_tnas` (One Order TNA per style x colour x ex-factory date of a submitted Sales Order. Existing ones are lef)  
Functions: `holiday_dates`: Set of non-working dates from the Company's default Holiday List; None when the company has no list.; `working_day`: Move `d` to the next (direction 1) or previous (-1) working day. With no Holiday List only Sundays a; `plan_dates`: rows: dicts with code, basis, after, offset_days, duration_rule, daily_output (in template order). R; `feasibility`: (feasible, note): the last milestone before Ex-Factory must not land after the ex-factory date.; `applies`: Whether a milestone type applies to this style on this order.; `pick_template`: Most specific template: customer + product type, customer, product type, then the default.; `order_groups`: Sales Order lines grouped to style x colour x ex-factory date.; `allocation_for`: (factory, pcd, sewing_end) from the Factory Allocation for a style x colour.; `compute_plan`: Planned dates for an Order TNA document (or dict) from its template. Returns (dates, na_codes, unres  

**tna/events.py** (179 lines)  
Auto-stamping of milestone actuals from the documents that prove them. One place, never raises into the caller: a T&A problem must not block a purchase, a receipt or an approval.  
Functions: `stamp`: Record that `code` happened on `date` for every Order TNA of this style x colour. An existing actual; `unstamp`: A source document was cancelled: clear what it stamped, then look for another document that proves t; `refind`: Best-effort: set `ms` from another live document of the right kind.; `sync_samples`: Set the approval milestones of one Order TNA from the Sample Approvals that apply to it.; `backfill`: A T&A made after the fact picks up what already happened.  

**tna/seed.py** (97 lines)  
T&A milestone types and the default template. The day offsets come from the company's own T&A sheet (the `T & A` sheet inside the trim requisition workbooks); rows marked 'assumed' were not on that sheet. Seeds are inserted only when missing.  
Functions: `remove_shipping_rows`: ON_BOARD and IN_WAREHOUSE exist as milestone types, but are not in the default template: with assume  

**tna/status.py** (87 lines)  
Status of milestones and orders. Always computed from today's date, never trusted from a stored value, so the board is right even when the site's scheduler is off. The stored values are refreshed on every change and by a daily job.  
Functions: `milestone_state`: (status, delay_days, progress). Late = the current target (revised, else planned) has passed and it ; `order_state`: (status, critical_delay_days) of an order from its milestone dicts.; `refresh_order_tna`: Recompute and store every milestone's status and the order's status.; `refresh_all`: Daily job: refresh every open order and tell owners about milestones due tomorrow or overdue. Option  

**tna/api.py** (85 lines)  
Whitelisted calls: the WIP board's data, milestone updates, and the agent API for the T&A.  
Buttons / API: `wip_board_data` (One Order TNA per row and one milestone per column. Two queries in total (orders, then every milesto); `update_milestone` (Set the revised or actual date of a milestone, with the same rules as the form.); `get_tna` (Agent API: every Order TNA of a Sales Order with its milestones.)  
Functions: `cell_class`: done / done_late / soon / late / na / future, from the dates alone.  

### E. `materials/` (Phase C)

**materials/common.py** (236 lines)  
Shared helpers for the Phase C requisitions: unit conversion, allowance rules, numbering, approvals lookup, stock claims, Material Request creation, roll-ups. No company or buyer is named here; rules are data.  
Functions: `to_metres`: Quantity of fabric in `uom` to metres. kg needs GSM and cuttable width: m = kg*1000 / (gsm * width_m; `parse_width_cm`: '132CM', 'CW 152 cm', '57"', '56in' -> cm. None when no width is found.; `next_number`: PREFIX + YY.MM.### with a counter that restarts each month (the same pattern as the contract number); `get_allowance`: Most specific enabled Material Allowance Rule: customer 4, trim category 2, material type 1, item gr; `colour_matches`: A Tech Pack material row with a colour belongs to that garment colour only; blank belongs to all.; `approval_info`: (status text, ok) for one sample type of a style x colour on an order. ok = the gate would let it pa; `free_stock`: Actual stock minus the stock already claimed by other approved requisitions (not superseded, not can; `mr_line`: (qty, uom, conversion_factor) for a Material Request row: the order UOM when the item has it, else s; `company_warehouse`: The warehouse named in Apparel Settings `field`, or its equivalent in `company` (created when missin  

**materials/inspection.py** (178 lines)  
Inspection rules as small pure functions (4-point fabric system, sampling, lot decision, trim AQL), plus the shared steps both inspections use: the receipt context, the Quality Inspection record and the Stock Entry.  
Functions: `defect_points`: Points for one defect by its length in inches: up to 3 = 1, over 3 to 6 = 2, over 6 to 9 = 3, over 9; `roll_points`: Total points of one roll. `defects` = list of (yard_position, points). No more than 4 points count i; `points_per_100_square`: points x 3600 / (inspected yards x width in inches).; `sampling_pct`: Inspect % for a lot of `total_m` metres. Band to_length 0 = no upper limit. 100 when no band matches; `lot_decision`: Pass / Fail / Re-inspect 100% / Hold. A sample that fails sends the lot to 100% inspection; once eve; `roll_disposition`: What happens to a roll's stock: Accepted, Accepted by Lot, Rejected or Hold.; `width_impact`: Extra metres needed when the fabric is narrower than the cuttable width the consumption was based on; `trim_sample`: (sample size, accept max, reject min) of a Trim Sampling Plan for a lot. Percent plans have no accep; `trim_result`: Pass or Fail. A size mix-up always fails. AQL: fail at the reject number. Percent: fail above the pl  

**materials/rolls.py** (115 lines)  
Fabric roll list import: one Batch per roll, one Serial and Batch Bundle per Purchase Receipt row.  
Buttons / API: `import_roll_list` (Make a Batch per roll and the bundle for one row of a draft Purchase Receipt. `rolls` is a JSON list)  
Functions: `parse_roll_text`: Lines of 'roll no, dye lot, length[, width]' (tab, comma or semicolon separated) -> list of dicts. A; `forget_previous_import`: A re-import replaces the draft bundle and the batches this receipt made.; `check_rolls_before_submit`: A fabric row from an FR needs its roll list before the receipt can be submitted.  

**materials/status.py** (111 lines)  
Material status of every approved FR / TR line, and the material gate that holds bulk production.  
Functions: `line_status`: Status of one requisition line. `r` carries net, ordered, received, accepted, rejected, hold, eta/et; `material_rows`: One dict per approved, current FR / TR line, with purchase order, receipt and inspection facts.; `material_gate`: (blockers, warnings) for bulk production of a style x colour: every requisition line must have its a; `trim_readiness`: Available / Partial / Not Available for the trims of one need (Sewing or Packing).  

**materials/purchasing.py** (91 lines)  
Pure rules for supplier terms (quantity bands, late-delivery penalties) and the roll-up of purchase and receipt quantities back to the requisitions. Kept free of document state so each rule is easy to test.  
Functions: `pick_band`: The Purchase Qty Band row covering `qty` (to_qty 0 = no upper limit); None when no band applies.; `qty_tolerance`: Tolerance % allowed on `ordered_qty` under `terms` (a Material Purchase Terms doc); 0 when none appl; `delay_penalty`: (penalty %, action) for a delay under `terms`. Days <= 0 or inside a 0% band return 0.; `terms_for`: The terms doc: the explicit one, else the supplier's, else the default in Apparel Settings.; `key_totals`: (ordered, received) in stock units for a line key across a revision chain, from the purchase orders ; `inspection_totals`: (accepted, rejected) in stock units for a line key, from the submitted inspections of the goods rece; `refresh_requisition`: Recompute ordered and received quantities and the status of one requisition.; `refresh_for_documents`: Refresh every requisition referenced by the items of a PO, PR or inspection document.  

**materials/items.py** (75 lines)  
Fabric and trim item set-up: a template per fabric quality with the Colour attribute, a variant per colour.  
Functions: `add_uom_rows`: Yard always (1 yd = 0.9144 m); Kg when GSM and width are known (1 kg = 1000 / (gsm x width_m) m).; `ensure_fabric_item`: Template `quality_code` (stock UOM Meter, batch tracked, Colour attribute) and its colour variant. R; `ensure_trim_item`: A plain stock item per trim code. Buyer code goes on Item Customer Detail.  

**materials/cards.py** (23 lines)  
Number card queries for the Materials workspace.  
Buttons / API: `fabric_overdue`; `rolls_awaiting_inspection`; `rejected_lots`; `trim_lines_on_hold`  

### F. `overrides/` (hooks on ERPNext documents)

**overrides/purchase_order.py** (155 lines)  
Purchase Order extensions: link back to the requisition, supplier terms, approval hold, costing check, ETD dates.  
Buttons / API: `make_purchase_orders` (Draft Purchase Orders from an approved FR / TR: one per supplier, for the Material Request rows not )  
Functions: `requisition_row`: The FR / TR row behind a PO row (or None).; `hold_blockers`: Messages for rows whose lab dip (FR) or trim approval (TR) is still missing, re-checked now.; `cost_warnings`: PO rate against the Cost Sheet material rate, when currency and unit are comparable.; `stamp_po`: Booked / PI / ETD milestones for every style x colour on the order.  

**overrides/purchase_receipt.py** (98 lines)  
Purchase Receipt extensions: receive into the inspection warehouse, quantity bands, delay penalty, roll-ups.  
Functions: `check_band`: Cumulative received (incl. this row) against the ordered quantity and its tolerance band.; `apply_delay_penalty`: Late delivery under the PO terms: store the delay, the penalty % and the amount. No accounting entry  

**overrides/work_order.py** (48 lines)  
Bulk gate (G3): a Work Order for an apparel style cannot be submitted until the buyer has approved what the rules require, and the PP meeting is held with every cutting-related action closed.  
Buttons / API: `get_bulk_gate` (List of blockers (empty = the gate is open) for bulk production of this item on this order.)  
Functions: `style_and_colour`: (style template, colour) of a variant item; (None, None) when the item is not an apparel style varia  

**overrides/quotation.py** (30 lines)  
Quotation joins the apparel flow: lines carrying a Cost Sheet are held to its margin floor.  

**overrides/dashboards.py** (22 lines)  
Show the apparel documents in the Connections tab of ERPNext forms.  

**overrides/sales_order.py** (20 lines)  
Status: PORTED and tested (`sales_order_validate/submit/cancel`, including the row fill)  
A Sales Order made from a Sales Contract keeps its link, and a contract has at most one live order.  

