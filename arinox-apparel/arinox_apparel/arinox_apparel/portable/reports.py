"""Reports as records. A Query Report is SQL. A Script Report is stored in the record (`report_script`) and runs in the same
sandbox as a Server Script; its source lives in `script_reports/<slug>.py` and is listed in `script_reports/manifest.json`."""

import json
import os

HERE = os.path.dirname(__file__)
APP = os.path.dirname(HERE)
DIR = os.path.join(HERE, "script_reports")
CLEAN = {"creation", "modified", "modified_by", "owner", "docstatus", "idx", "module"}


def _strip(d):
	if isinstance(d, dict):
		return {k: _strip(v) for k, v in d.items() if k not in CLEAN and v is not None}
	if isinstance(d, list):
		return [_strip(x) for x in d]
	return d


def query_reports():
	out = []
	base = os.path.join(APP, "arinox_apparel", "report")
	for d in sorted(os.listdir(base)):
		p = os.path.join(base, d, d + ".json")
		if os.path.exists(p):
			doc = json.load(open(p))
			if doc.get("report_type") == "Query Report":
				doc["is_standard"] = "No"
				out.append(_strip(doc))
	return out


def manifest():
	p = os.path.join(DIR, "manifest.json")
	return json.load(open(p))["reports"] if os.path.exists(p) else []


def script_reports():
	"""Reports whose Python was rewritten for the sandbox. Metadata (filters, roles, ref doctype) is taken from the app's
	own report JSON so the two cannot drift; only the code comes from the sandbox-safe file."""
	out = []
	for e in manifest():
		src = open(os.path.join(DIR, e["file"])).read()
		if "# include:" in src:
			from arinox_apparel.portable.export_bundle import expand_includes

			src = expand_includes(src)           # the sandbox cannot import, so shared helpers are copied in
		meta = json.load(open(os.path.join(APP, "arinox_apparel", "report", e["slug"], e["slug"] + ".json")))
		meta.update({"is_standard": "No", "report_type": "Script Report", "report_script": src, "javascript": None})
		out.append(_strip(meta))
	return out


ROLES = [{"role": r} for r in ("System Manager", "Apparel Merchandising Manager", "Apparel Merchandiser", "Apparel Production Manager")]

# Two number cards call app Python and count something a plain filter cannot say (a field compared with another, the parent's status). Each is rebuilt as a one-row
# Query Report; the exporter turns the card into a Report-type card on its `lines` column (export_bundle.CARD_REPORTS).
CARD_QUERY_REPORTS = [
	{"doctype": "Report", "name": "Fabric Overdue Lines", "report_name": "Fabric Overdue Lines", "ref_doctype": "Fabric Requisition", "report_type": "Query Report", "is_standard": "No", "roles": ROLES,
	 "query": "select count(*) as \"Lines:Int:80\" from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent where p.docstatus = 1 "
			  "and p.status not in ('Superseded', 'Cancelled') and c.net_qty > 0 and c.required_by < curdate() and c.accepted_qty < c.net_qty"},
	{"doctype": "Report", "name": "Trim Lines On Hold Count", "report_name": "Trim Lines On Hold Count", "ref_doctype": "Trim Requisition", "report_type": "Query Report", "is_standard": "No", "roles": ROLES,
	 "query": "select count(*) as \"Lines:Int:80\" from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent where p.docstatus = 1 "
			  "and p.status not in ('Superseded', 'Cancelled') and c.hold = 1 and c.ordered_qty = 0"},
]


def export_reports():
	records = query_reports() + script_reports() + [dict(r) for r in CARD_QUERY_REPORTS]
	return records, {r["name"] for r in records}
