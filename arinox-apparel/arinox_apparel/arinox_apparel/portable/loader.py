"""Create or update the Server Script records listed in manifest.json (idempotent). Run on a site with
`bench --site <site> execute arinox_apparel.portable.loader.install`, or let the app's after_migrate do it.
Each script is compiled with Frappe's own restricted compiler first, so a script that would be refused at run time is
refused here."""

import json
import os

import frappe

HERE = os.path.dirname(__file__)


def manifest():
	return json.load(open(os.path.join(HERE, "manifest.json")))["server_scripts"]


def source(entry):
	return open(os.path.join(HERE, "server_scripts", entry["file"])).read()


def compile_problem(entry):
	"""None when the sandbox accepts the script, otherwise the reason."""
	from frappe.utils.safe_exec import _compile_code

	try:
		_compile_code(source(entry), filename=entry["name"])
	except Exception as e:  # SyntaxError from RestrictedPython carries the reason
		return f"{type(e).__name__}: {e}"
	return None


def install():
	made = []
	for entry in manifest():
		bad = compile_problem(entry)
		if bad:
			frappe.throw(f"Server Script {entry['name']} is not valid in the sandbox: {bad}")
		values = {k: v for k, v in entry.items() if k != "file"}
		values.update({"script": source(entry), "disabled": 0})
		if frappe.db.exists("Server Script", entry["name"]):
			doc = frappe.get_doc("Server Script", entry["name"])
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc({"doctype": "Server Script", "__newname": entry["name"], **values})
			doc.insert(ignore_permissions=True)
		made.append(entry["name"])
	frappe.clear_cache()
	return made
