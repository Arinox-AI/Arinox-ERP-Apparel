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
		meta = json.load(open(os.path.join(APP, "arinox_apparel", "report", e["slug"], e["slug"] + ".json")))
		meta.update({"is_standard": "No", "report_type": "Script Report", "report_script": src, "javascript": None})
		out.append(_strip(meta))
	return out


def export_reports():
	records = query_reports() + script_reports()
	return records, {r["name"] for r in records}
