"""Export the app as a bundle of plain records for a site that takes only DocTypes, data and Server Scripts.

    bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '/path/hosted_bundle'}"

Writes `<out>/index.json` and one `NN_<name>.json` per group. `api_load.py` (standard library only) reads that folder and
creates the records through the REST API, so an agent with only API access can load it. The exporter never touches the
hosted site and the files it writes are the only link between the two sides.

What is changed on the way out, and why (each is something Frappe refuses on a site that is not in developer mode):
  * DocType: `custom = 1` (a standard DocType cannot be created without developer mode).
  * Print Format: `standard = No`; Report: `is_standard = No`; Number Card / Dashboard Chart: `is_standard = 0`;
    Desktop Icon: `standard = 0`.
  * DocTypes are ordered so that a doctype comes after every doctype it has a Link or Table field to; where two point at each other
    the field that closes the loop is left out of the first insert and put back by a second pass (`deferred`).
  * Links to the two Page screens (Order Desk, WIP Board) are dropped: a Page needs files on the server.
"""

import json
import os
import re

import frappe

APP_DIR = os.path.dirname(os.path.dirname(__file__))  # .../arinox_apparel/arinox_apparel
MODULE = "Arinox Apparel"
META = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parenttype", "parentfield",
		"_user_tags", "_comments", "_assign", "_liked_by", "doctype_name"}
PAGES = {"apparel-order-desk", "apparel-wip-board"}

# Doctypes whose names the app builds in Python (`autoname()`); on the hosted site a Before Insert Server Script builds the
# name into a hidden field and the doctype names itself from it. See portable/server_scripts/naming.py.
SCRIPT_NAMED = (
	"Buyer Claim", "Fabric Requisition", "Final Inspection", "Packing List", "Factory Allocation", "Finishing Receipt",
	"Production Card", "Sales Contract", "Subcontract Challan", "Subcontract Return", "Subcontract Settlement", "Trim Requisition",
)
NAME_FIELD = "arinox_name"


def _clean(value, top=True):
	"""Drop database bookkeeping from a document (recursively)."""
	if isinstance(value, dict):
		return {k: _clean(v, False) for k, v in value.items() if (k not in META or (k == "name" and top)) and v is not None}
	if isinstance(value, list):
		return [_clean(v, False) for v in value]
	return value


def _read(path):
	with open(path) as f:
		return json.load(f)


def _files(folder, doctype):
	out = []
	base = os.path.join(APP_DIR, "arinox_apparel", folder)       # module folder: workspace, print_format, report ...
	if not os.path.isdir(base):
		base = os.path.join(APP_DIR, folder)                     # package root: workspace_sidebar, desktop_icon
	if not os.path.isdir(base):
		return out
	for d in sorted(os.listdir(base)):
		p = os.path.join(base, d, d + ".json")      # most record types: <folder>/<name>/<name>.json
		if not os.path.exists(p):
			p = os.path.join(base, d)               # sidebars and desktop icons: <folder>/<name>.json
		if os.path.isfile(p) and p.endswith(".json"):
			doc = _read(p)
			if doc.get("doctype") == doctype:
				out.append(doc)
	return out


# ---- DocTypes ------------------------------------------------------------------------------------------------------

ARINOX_NUMBER = {
	"doctype": "DocType", "name": "Arinox Number", "module": MODULE, "autoname": "format:{prefix}{#####}", "naming_rule": "Expression",
	"fields": [{"fieldname": "prefix", "fieldtype": "Data", "label": "Prefix", "reqd": 1, "in_list_view": 1}],
	"field_order": ["prefix"], "sort_field": "creation", "sort_order": "DESC", "editable_grid": 0,
	"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
}   # hosted only: hands out numbers that never repeat, in place of getseries


def doctypes():
	docs = []
	for d in sorted(os.listdir(os.path.join(APP_DIR, "arinox_apparel", "doctype"))):
		p = os.path.join(APP_DIR, "arinox_apparel", "doctype", d, d + ".json")
		if os.path.exists(p):
			docs.append(_read(p))
	docs = [x for x in docs if x.get("doctype") == "DocType"]
	docs.append(ARINOX_NUMBER)
	for d in docs:
		d["custom"] = 1
		_fix_permissions(d)
		if d["name"] in SCRIPT_NAMED:
			_script_named(d)
	return order_doctypes(docs)


NOTES = []


def _fix_permissions(d):
	"""A custom DocType is validated as it is saved (a standard one is not): a role that may submit, cancel or amend must be able
	to write. The app has one such row (PP Meeting, Sales User). Take the three rights away rather than grant write, and record it."""
	merged, seen = [], {}
	for i, p in enumerate(d.get("permissions", []), 1):
		key = (p["role"], p.get("permlevel", 0), p.get("if_owner", 0))
		if key in seen:   # Frappe allows one rule per role, level and if-owner; the effective right is the union
			first = seen[key]
			for k, v in p.items():
				if k in ("role", "permlevel", "if_owner") or not isinstance(v, int):
					continue
				first[k] = first.get(k, 0) or v
			NOTES.append(f"{d['name']} permission row {i} ({p['role']}): duplicate of an earlier row, merged")
			continue
		seen[key] = p
		merged.append(p)
	d["permissions"] = merged
	for i, p in enumerate(d.get("permissions", []), 1):
		if (p.get("submit") or p.get("cancel") or p.get("amend")) and not p.get("write"):
			for k in ("submit", "cancel", "amend"):
				p[k] = 0
			NOTES.append(f"{d['name']} permission row {i} ({p['role']}): submit, cancel, amend removed because the row had no write")


def _script_named(d):
	"""Give the doctype a hidden field that a Before Insert script fills with the contract-based name."""
	if any(f["fieldname"] == NAME_FIELD for f in d["fields"]):
		return
	d["fields"].append({"fieldname": NAME_FIELD, "fieldtype": "Data", "label": "Document Name", "hidden": 1, "read_only": 1,
						"no_copy": 1, "print_hide": 1, "report_hide": 1})
	d["field_order"] = list(d.get("field_order") or [f["fieldname"] for f in d["fields"][:-1]]) + [NAME_FIELD]
	d["autoname"] = f"field:{NAME_FIELD}"
	d.pop("naming_rule", None)


def order_doctypes(docs):
	"""Return [{'doc': full doctype, 'first': doctype without the fields that close a loop, 'deferred': bool}] dependency-first."""
	by = {d["name"]: d for d in docs}

	def deps(d):
		out = []
		for f in d["fields"]:
			t = f.get("options")
			if f["fieldtype"] in ("Link", "Table", "Table MultiSelect") and t in by and t != d["name"]:
				out.append((t, f["fieldtype"] != "Link"))
		return out

	state, order, back = {}, [], {}   # state: 1 visiting, 2 done

	def visit(name, path):
		if state.get(name) == 2:
			return
		if state.get(name) == 1:
			return
		state[name] = 1
		for t, is_table in sorted(deps(by[name])):
			if state.get(t) == 1:                      # a loop: this field cannot be satisfied on the first insert
				back.setdefault(name, set()).add(t)
				continue
			visit(t, path + [name])
		state[name] = 2
		order.append(name)

	# children (tables) first, then everything else, each alphabetically: stable output
	for n in sorted(by, key=lambda n: (not by[n].get("istable"), n)):
		visit(n, [])
	out = []
	for n in order:
		doc = by[n]
		drop = back.get(n, set())
		first = dict(doc)
		if drop:
			first["fields"] = [f for f in doc["fields"] if not (f["fieldtype"] in ("Link", "Table", "Table MultiSelect") and f.get("options") in drop)]
			first["field_order"] = [x for x in doc.get("field_order", []) if x in {f["fieldname"] for f in first["fields"]}]
		out.append({"doc": _clean(doc), "first": _clean(first), "deferred": bool(drop)})
	return out


# ---- Custom Fields and Property Setters (read from the dev database: Python builds them at migrate) -----------------

def custom_fields():
	from arinox_apparel.setup import install, materials, shipping

	want = set()
	for m in (install, materials, shipping):
		for dts, fields in m.get_custom_fields().items():
			for dt in ([dts] if isinstance(dts, str) else dts):
				for f in fields:
					want.add((dt, f["fieldname"]))
	rows = frappe.get_all("Custom Field", fields=["name"], filters={"dt": ["in", sorted({a for a, _ in want})]})
	out = []
	for r in rows:
		doc = frappe.get_doc("Custom Field", r.name)
		if (doc.dt, doc.fieldname) in want:
			out.append(_clean(doc.as_dict(no_nulls=True, convert_dates_to_str=True)))
	return sorted(out, key=lambda d: (d["dt"], d.get("insert_after", ""), d["fieldname"]))


def property_setters():
	out = []
	for name in frappe.get_all("Property Setter", {"doc_type": "Shipment", "property": "reqd"}, pluck="name"):
		doc = frappe.get_doc("Property Setter", name)
		out.append(_clean(doc.as_dict(no_nulls=True, convert_dates_to_str=True)))
	return out


# ---- other records stored as files in the app -------------------------------------------------------------------------

def print_formats():
	out = []
	for d in _files("print_format", "Print Format"):
		d["standard"] = "No"
		d.pop("module", None)
		out.append(_clean(d))
	return out


def number_cards():
	"""Document Type cards load as they are. A Custom card calls app Python, so it is rebuilt as a Document Type card with
	the same filter where the count is a plain filtered count (see CARD_REPLACEMENTS), and left out otherwise."""
	out = []
	for d in _files("number_card", "Number Card"):
		d["is_standard"] = 0
		d.pop("module", None)
		if d.get("type") == "Custom":
			if d["name"] in CARD_REPORTS:
				d.update({"type": "Report", "report_name": CARD_REPORTS[d["name"]], "report_field": "lines", "report_function": "Sum"})
				d.pop("method", None)
				d.pop("document_type", None)
				out.append(_clean(d))
				continue
			rep = CARD_REPLACEMENTS.get(d["name"])
			if not rep:
				continue
			d.update(rep)
			d["type"] = "Document Type"
			d.pop("method", None)
		out.append(_clean(d))
	return out


CARD_REPORTS = {"Fabric Overdue": "Fabric Overdue Lines", "TR Lines On Hold": "Trim Lines On Hold Count"}    # reports.CARD_QUERY_REPORTS

CARD_REPLACEMENTS = {
	"Rolls Awaiting Inspection": {"document_type": "Batch", "function": "Count",
								  "filters_json": json.dumps([["Batch", "apparel_inspection_status", "=", "Uninspected"], ["Batch", "apparel_roll_no", "!=", ""], ["Batch", "disabled", "=", 0]])},
	"Rejected Lots 30 Days": {"document_type": "Fabric Inspection", "function": "Count",
							  "filters_json": json.dumps([["Fabric Inspection", "docstatus", "=", 1], ["Fabric Inspection", "lot_result", "=", "Fail"], ["Fabric Inspection", "creation", "Timespan", "last month"]])},
}


def dashboard_charts():
	out = []
	for d in _files("dashboard_chart", "Dashboard Chart"):
		d["is_standard"] = 0
		d.pop("module", None)
		out.append(_clean(d))
	return out


def dashboards():
	out = []
	for d in _files("arinox_apparel_dashboard", "Dashboard"):
		d.pop("module", None)
		d["is_standard"] = 0
		out.append(_clean(d))
	return out


def workspaces(report_names, card_names):
	out = []
	for d in _files("workspace", "Workspace"):
		d["module"] = MODULE
		for key in ("shortcuts", "links"):
			keep = []
			for r in d.get(key) or []:
				kind = r.get("type") if key == "shortcuts" else r.get("link_type")
				if kind == "Page" or r.get("link_to") in PAGES:
					continue
				if kind == "Report" and r.get("link_to") not in report_names:
					continue
				keep.append(r)
			d[key] = keep
		d["number_cards"] = [c for c in d.get("number_cards") or [] if c.get("number_card_name") in card_names]
		d["content"] = _filter_content(d.get("content") or "[]", report_names, card_names)
		out.append(_clean(d))
	return out


def _filter_content(content, report_names, card_names):
	"""The workspace page body is a JSON list of blocks; drop the ones that point at something this site will not have."""
	try:
		blocks = json.loads(content)
	except ValueError:
		return content
	keep = []
	for b in blocks:
		data = b.get("data") or {}
		if b.get("type") == "shortcut" and data.get("shortcut_name") in {"Order Desk", "WIP Board"}:
			continue
		if b.get("type") == "shortcut" and data.get("shortcut_name") in ALL_REPORT_LABELS and data.get("shortcut_name") not in report_names:
			continue
		if b.get("type") == "number_card" and data.get("number_card_name") not in card_names:
			continue
		keep.append(b)
	return json.dumps(keep)


ALL_REPORT_LABELS = set()


def sidebars(report_names):
	out = []
	for d in _files("workspace_sidebar", "Workspace Sidebar"):
		d["items"] = [i for i in d.get("items", []) if i.get("link_type") != "Page" and i.get("link_to") not in PAGES
					  and not (i.get("link_type") == "Report" and i.get("link_to") not in report_names)]
		d.pop("app", None)
		d["name"] = d["title"]      # a site-made sidebar is named by its title; the app's file name is only a folder name
		out.append(_clean(d))
	return out


SIDEBAR_TITLE = {}


def desktop_icons():
	for d in _files("workspace_sidebar", "Workspace Sidebar"):
		SIDEBAR_TITLE[d["name"]] = d["title"]
	out = []
	for d in _files("desktop_icon", "Desktop Icon"):
		d["standard"] = 0
		d["app"] = ""
		if d.get("link_type") == "Workspace Sidebar":
			d["link_to"] = SIDEBAR_TITLE.get(d["link_to"], d["link_to"])
		out.append(_clean(d))
	return out


# ---- seeds: records the app makes at migrate time, read from the dev database ----------------------------------------

SEED_DOCTYPES = [
	"Cost Head", "Product Type", "Apparel Defect Code", "Subcontract Process", "Production Check Item", "Trim Category",
	"Material Allowance Rule", "Fabric Defect Code", "Trim Defect Type", "Material Purchase Terms", "Trim Sampling Plan",
	"AQL Plan", "Destination Filing Rule", "TNA Milestone Type", "TNA Template",
]
SEED_SKIP = {"Quality Inspection Parameter": {"_Test Param"}}
MATCH_BY = {"Material Allowance Rule": ("material_type", "trim_category", "customer")}
ROLES = ["Apparel QA", "Apparel Production User", "Apparel Production Manager", "Apparel Merchandising Manager", "Apparel Costing Manager", "Apparel Merchandiser"]


def roles():
	return [{"doctype": "Role", "role_name": r, "desk_access": 1} for r in ROLES]


def seeds():
	out = []
	for dt in SEED_DOCTYPES:
		for name in frappe.get_all(dt, pluck="name", order_by="creation asc"):
			if name.startswith("_"):      # left behind by the test suite on the dev site
				continue
			rec = _clean(frappe.get_doc(dt, name).as_dict(no_nulls=True, convert_dates_to_str=True))
			rec["__create_only"] = True   # a seed already on the site may have been edited by the people who use it
			if dt in MATCH_BY:            # named by a random hash: the loader finds an existing one by these fields instead
				rec["__match"] = {f: rec.get(f, "") for f in MATCH_BY[dt]}
				rec.pop("name", None)
			out.append(rec)
	for name in frappe.get_all("Quality Inspection Parameter", pluck="name"):
		if name not in SEED_SKIP["Quality Inspection Parameter"]:
			rec = _clean(frappe.get_doc("Quality Inspection Parameter", name).as_dict(no_nulls=True, convert_dates_to_str=True))
			rec["__create_only"] = True
			out.append(rec)
	for name in ("Colour", "Size"):
		if frappe.db.exists("Item Attribute", name):
			rec = _clean(frappe.get_doc("Item Attribute", name).as_dict(no_nulls=True, convert_dates_to_str=True))
			rec["__create_only"] = True    # merchandisers add colours and sizes all the time; never replace the list
			out.append(rec)
	return out


def settings():
	"""Apparel Settings (a Single): its defaults and seeded child rows. Warehouse links are site-specific and are left out."""
	doc = _clean(frappe.get_doc("Apparel Settings").as_dict(no_nulls=True, convert_dates_to_str=True))
	for k in list(doc):
		if k.endswith("warehouse") or k.endswith("_warehouse_fabric") or k.endswith("_warehouse_trim") or k in ("fg_warehouse",):
			doc.pop(k)
	own = {d["name"] for d in _all_doctype_docs()} | {"Item Attribute"}
	for df in frappe.get_meta("Apparel Settings").fields:
		if df.fieldtype == "Link" and df.options not in own:   # an Item Group, Item, Price List ... of the dev site
			doc.pop(df.fieldname, None)
	doc["doctype"] = "Apparel Settings"
	return doc


def _all_doctype_docs():
	base = os.path.join(APP_DIR, "arinox_apparel", "doctype")
	return [_read(os.path.join(base, d, d + ".json")) for d in sorted(os.listdir(base)) if os.path.exists(os.path.join(base, d, d + ".json"))]


# ---- Server Scripts -------------------------------------------------------------------------------------------------

def expand_includes(src):
	"""A line `    # include: lib_x.py` is replaced by that file, indented to the line. The sandbox cannot import, and module-level
	functions cannot see each other, so shared helpers are written once in hosted_scripts/lib_*.py and copied into each script
	(inside its one enclosing function) at export time."""
	out = []
	for line in src.splitlines():
		m = re.match(r"^(\s*)# include: (\S+)\s*$", line)
		if not m:
			out.append(line)
			continue
		body = open(os.path.join(os.path.dirname(__file__), "hosted_scripts", m.group(2))).read().splitlines()
		out.extend((m.group(1) + b) if b.strip() else "" for b in body)
	return "\n".join(out) + "\n"


def server_scripts():
	from arinox_apparel.portable import loader

	out = []
	for e in loader.manifest():
		d = {k: v for k, v in e.items() if k != "file"}
		d.update({"doctype": "Server Script", "script": loader.source(e), "disabled": 0})
		out.append(d)
	hm = os.path.join(os.path.dirname(__file__), "manifest_hosted.json")
	if os.path.exists(hm):
		for e in json.load(open(hm))["server_scripts"]:
			src = expand_includes(open(os.path.join(os.path.dirname(__file__), "hosted_scripts", e["file"])).read())
			d = {k: v for k, v in e.items() if k != "file"}
			d.update({"doctype": "Server Script", "script": src, "disabled": 0})
			out.append(d)
	return out


# ---- run ------------------------------------------------------------------------------------------------------------

def export(out="hosted_bundle"):
	os.makedirs(out, exist_ok=True)
	from arinox_apparel.portable import reports

	query_reports, report_names = reports.export_reports()
	cards = number_cards()
	global ALL_REPORT_LABELS
	ALL_REPORT_LABELS = {d["name"] for d in _files("report", "Report")}
	groups = [
		("module_def", "create", [{"doctype": "Module Def", "module_name": MODULE, "app_name": "frappe"}]),
		("roles", "create", roles()),
		("doctypes", "doctypes", doctypes()),
		("custom_fields", "create", custom_fields()),
		("property_setters", "create", property_setters()),
		("seeds", "create", seeds()),
		("apparel_settings", "single", [settings()]),
		("print_formats", "create", print_formats()),
		("reports", "create", query_reports),
		("number_cards", "create", cards),
		("dashboard_charts", "create", dashboard_charts()),
		("dashboards", "create", dashboards()),
		("workspaces", "create", workspaces(report_names, {c["name"] for c in cards})),
		("workspace_sidebars", "create", sidebars(report_names)),
		("desktop_icons", "create", desktop_icons()),
	]
	from arinox_apparel.portable import client_scripts

	client_records = client_scripts.export_client_scripts()
	unknown = client_scripts.unknown_methods(client_records)
	if unknown:
		# a button that calls a name no API Server Script answers fails in the browser with "App ... is not installed"
		raise ValueError("Client scripts call API methods that do not exist: %s" % ", ".join(f"{s} -> {m}" for s, m in unknown[:10]))
	groups.append(("client_scripts", "create", client_records))
	groups.append(("server_scripts", "create", server_scripts()))
	index = []
	for i, (name, mode, records) in enumerate(groups, 1):
		fn = f"{i:02d}_{name}.json"
		with open(os.path.join(out, fn), "w") as f:
			json.dump({"group": name, "mode": mode, "records": records}, f, indent=1, sort_keys=True)
		index.append({"file": fn, "group": name, "mode": mode, "count": len(records)})
	with open(os.path.join(out, "index.json"), "w") as f:
		json.dump(index, f, indent=1)
	for r in index:
		print(f"{r['file']:32} {r['mode']:9} {r['count']:5}")
	for n in NOTES:
		print("NOTE", n)
	with open(os.path.join(out, "NOTES.txt"), "w") as f:
		f.write("\n".join(NOTES) + "\n")
	return index
