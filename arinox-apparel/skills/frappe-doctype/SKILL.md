---
name: frappe-doctype
description: Build, change, and test Frappe/ERPNext doctypes inside the arinox_apparel custom app. Use when creating a doctype, child table, controller logic, client script, permission rule, naming rule, or fixture for the apparel ERP.
---

# Frappe Doctype Build Skill (arinox_apparel)

Use this skill for any doctype work in the `arinox_apparel` app. Read `../../CLAUDE.md` first for the hard rules (no ERPNext core edits, pinned versions, spec before code).

## 0. Preconditions

- A spec exists in `../../doctypes/<slug>.md` with status **Reviewed**. If not, write it from `../../doctypes/_TEMPLATE.md` and stop for review.
- Dev site is up and `arinox_apparel` is installed on it.
- Check ERPNext first: search `erpnext/` for an existing doctype that already covers the need (`grep -rl "\"name\": \"<Name>\"" erpnext/ --include=*.json`). Extend it with Custom Fields or a controller override instead of duplicating.

## 1. File layout

Doctype names are Title Case in the spec; folders and files use snake_case.

```
arinox_apparel/                       # app root (git repo)
  arinox_apparel/
    modules.txt                       # must contain "Arinox Apparel"
    hooks.py                          # required_apps = ["erpnext"]
    arinox_apparel/                   # module folder (snake_case of module)
      doctype/
        style/                        # doctype "Style"
          style.json                  # definition (source of truth)
          style.py                    # controller
          style.js                    # optional client script
          test_style.py               # tests
        size_chart/
          size_chart.json
          size_chart.py
        size_chart_row/               # child table: istable = 1
          size_chart_row.json
          size_chart_row.py
```

Rules:
- The `module` value in the JSON must be exactly `Arinox Apparel` and must be listed in `modules.txt`.
- The JSON `name` field must equal the Title Case doctype name. The folder must be its snake_case form.
- Never hand-edit the DB. Changes come from the JSON and `migrate`.

## 2. Doctype JSON (minimum shape)

```json
{
  "actions": [],
  "allow_rename": 1,
  "autoname": "format:STY-{#####}",
  "creation": "2026-01-01 00:00:00.000000",
  "doctype": "DocType",
  "engine": "InnoDB",
  "field_order": ["style_name", "buyer"],
  "fields": [
    {
      "fieldname": "style_name",
      "fieldtype": "Data",
      "label": "Style Name",
      "reqd": 1,
      "in_list_view": 1,
      "in_standard_filter": 1
    },
    {
      "fieldname": "buyer",
      "fieldtype": "Link",
      "label": "Buyer",
      "options": "Customer",
      "reqd": 1
    }
  ],
  "modified": "2026-01-01 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Arinox Apparel",
  "name": "Style",
  "owner": "Administrator",
  "permissions": [
    {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "print": 1, "email": 1, "export": 1, "report": 1, "share": 1},
    {"role": "Stock Manager", "read": 1, "write": 1, "create": 1, "report": 1}
  ],
  "sort_field": "modified",
  "sort_order": "DESC",
  "title_field": "style_name",
  "track_changes": 1
}
```

Field rules:
- `fieldname` is snake_case and unique in the doctype. `label` is for humans.
- Link fields need `options` set to an existing doctype (ERPNext or Arinox).
- Child table fields use `fieldtype: "Table"` with `options` set to the child doctype name, and the child JSON has `"istable": 1`.
- Use `Select` with newline-separated `options` for fixed lists; do not hardcode lists in Python.
- Prefer ERPNext field types (`Currency`, `Percent`, `Float`) over `Data` for numbers.
- Naming: `autoname` formats like `format:STY-{YY}-{#####}`. Use `field:<fieldname>` only when the value is guaranteed unique.

## 3. Controller (Python)

```python
import frappe
from frappe.model.document import Document


class Style(Document):
    def validate(self):
        self.validate_sizes()

    def validate_sizes(self):
        if not self.size_chart:
            frappe.throw("Size Chart is required before saving a Style.")
```

Rules:
- Validation goes in `validate`. Side effects that need the saved name go in `after_insert` or `on_update`. Never write to the DB directly; use `self` or `frappe.get_doc`.
- Raise with `frappe.throw(_("..."))` so messages are translatable (`from frappe import _`).
- Do not import from `erpnext` at module top level for things that can change; prefer `frappe.get_doc` or `frappe.get_cached_doc`.
- To extend an ERPNext doctype's behaviour, use `override_doctype_class` in `hooks.py` (subclass ERPNext's controller). Do not edit ERPNext files.

## 4. Client script (JavaScript)

```javascript
frappe.ui.form.on("Style", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Generate Variants"), () => {
                frappe.call({
                    method: "arinox_apparel.arinox_apparel.doctype.style.style.generate_variants",
                    args: { style: frm.doc.name },
                    callback: () => frm.reload_doc(),
                });
            });
        }
    },
});
```

- Server methods used from JS must be whitelisted with `@frappe.whitelist()`.
- Never trust client values for permissions or totals; recalc in the controller.

## 5. Permissions and roles

- Define permissions in the JSON. Add `if_owner` rules only when the spec says so.
- Create roles for apparel users (e.g. `Apparel Designer`, `Apparel Merchandiser`) through a fixture, not by hand, so they ship with the app.

## 6. Build and test loop

```bash
# after editing JSON or Python
bench --site apparel.localhost migrate
bench --site apparel.localhost clear-cache

# tests for this app
bench --site apparel.localhost run-tests --app arinox_apparel
bench --site apparel.localhost run-tests --app arinox_apparel --module arinox_apparel.arinox_apparel.doctype.style.test_style

# quick check in a Python shell
bench --site apparel.localhost console
```

Test file pattern:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestStyle(FrappeTestCase):
    def test_size_chart_required(self):
        doc = frappe.get_doc({"doctype": "Style", "style_name": "Tee 01", "buyer": "_Test Customer"})
        self.assertRaises(frappe.ValidationError, doc.insert)
```

Every doctype gets at least: a valid-create test, a required-field test, and one test per business rule in the spec.

## 7. Fixtures (seed data that ships with the app)

Use fixtures only for config that must exist on the hosted site: roles, workspace, print formats, custom fields.

In `hooks.py`:

```python
fixtures = [
    {"dt": "Role", "filters": [["name", "like", "Apparel%"]]},
    {"dt": "Custom Field", "filters": [["dt", "in", ["Sales Order"]], ["module", "=", "Arinox Apparel"]]},
]
```

Export with `bench --site apparel.localhost export-fixtures`, then review the JSON before committing. Do not export test records.

## 8. Checklist before saying a doctype is done

- [ ] Spec status updated to **Built**
- [ ] `migrate` runs clean on the dev site
- [ ] Doctype opens in the desk, list view shows the columns in the spec
- [ ] Tests pass
- [ ] Each permission role tested (log in as that role or use `as_level` checks in tests)
- [ ] No edits under `erpnext/`
- [ ] Changes reported to the user with command output. Nothing committed without approval.

## Common mistakes

- Editing the DB table or using `frappe.db.sql` to add columns. Use the JSON.
- Forgetting `modules.txt` or setting the wrong `module` in the JSON, so the doctype is missing from the desk.
- Changing `fieldname` of a field that already has data. Add a new field and write a patch instead.
- Writing a patch under `patches/` without adding it to `patches.txt`.
- Using `frappe.get_all` without `ignore_permissions` consideration in server code that runs for other users.
- Naming a controller class after a doctype with an acronym (`Packing List SSCC`): the class must be `PackingListSSCC` (the doctype name with spaces removed, case kept). A wrong class makes `bench migrate` treat the doctype as an orphan and **delete it** ("Orphaned DocType(s) found"). Read the migrate output for that line every time.
- `frappe.get_doc({...}).insert()` does not apply a field's `default` (only the desk form does). Anything a controller or test relies on must be set in the controller or passed explicitly.
- After a failed `save()` or `submit()` the in-memory document is stale; `reload()` before reusing it, or you get `TimestampMismatchError`.
- A report folder named like a standard-library module (`collections`) breaks any `python3` run started inside its parent folder. Name report folders for what they are (`receivables_follow_up`).
- Prefer extending an ERPNext doctype with Custom Fields (and a `doc_events` hook) over a new doctype when ERPNext already holds the object: Shipment, Supplier Quotation, Sales Invoice and Customer are extended this way in Phase E. Mandatory fields that do not fit can be relaxed with a Property Setter (`setup/shipping.py`).
- Names that carry the contract: `common.next_serial(root, code)` gives `<contract>-<code>-<nn>`; call it from `autoname`.

