"""Portability check: how much of the app could run as Server Scripts on a site that cannot install an app.

`bench --site <site> execute arinox_apparel.portable.check.report` prints, per area, the lines of Python and the constructs the
Server Script sandbox refuses (found by probing the sandbox itself, see doctypes/HOSTED_CONSTRAINTS.md)."""

import ast
import os

import frappe

ROOT = os.path.dirname(os.path.dirname(__file__))
BANNED_NAMES = {"hasattr", "getattr", "setattr", "type", "map", "filter", "reversed", "open", "eval", "exec", "super", "print"}
EXTRA_FRAPPE = set()


def allowed_frappe():
	from frappe.utils.safe_exec import get_safe_globals

	g = get_safe_globals()
	return set(g["frappe"].keys()), set(g["frappe"]["db"].keys())


def scan_source(src):
	"""{construct: count} of what the sandbox refuses in `src`."""
	top, db = allowed_frappe()
	found = {}

	def add(k):
		found[k] = found.get(k, 0) + 1

	try:
		tree = ast.parse(src)
	except SyntaxError:
		return {"unparseable": 1}
	for n in ast.walk(tree):
		if isinstance(n, ast.ClassDef):
			add("class")
		elif isinstance(n, (ast.Import, ast.ImportFrom)):
			add("import")
		elif isinstance(n, ast.Attribute):
			if n.attr.startswith("_"):
				add("underscore attribute")
			if n.attr == "format" and isinstance(n.value, ast.Constant):
				add(".format")
			if isinstance(n.value, ast.Name) and n.value.id == "frappe" and n.attr not in top:
				add(f"frappe.{n.attr}")
			if isinstance(n.value, ast.Attribute) and n.value.attr == "db" and isinstance(n.value.value, ast.Name) and n.value.value.id == "frappe" and n.attr not in db:
				add(f"frappe.db.{n.attr}")
		elif isinstance(n, ast.AugAssign) and isinstance(n.target, (ast.Subscript, ast.Attribute)):
			add("+= on item or attribute")
		elif isinstance(n, ast.Name) and n.id in BANNED_NAMES and isinstance(n.ctx, ast.Load):
			add(f"builtin {n.id}")
		elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("int", "float") and False:
			pass
	return found


def area(path):
	rel = os.path.relpath(path, ROOT)
	parts = rel.split(os.sep)
	if "tests" in parts:
		return None
	if parts[0] == "portable":
		return None
	if "doctype" in parts:
		return "controllers (one per doctype)"
	if "report" in parts:
		return "script reports"
	if parts[0] in ("production", "shipping", "tna", "materials", "overrides", "setup", "patches"):
		return parts[0]
	return "other"


def collect():
	out = {}
	for dirpath, _d, files in os.walk(ROOT):
		if "__pycache__" in dirpath:
			continue
		for f in files:
			if not f.endswith(".py") or f == "__init__.py":
				continue
			p = os.path.join(dirpath, f)
			a = area(p)
			if not a:
				continue
			src = open(p).read()
			lines = len([l for l in src.splitlines() if l.strip() and not l.strip().startswith("#")])
			row = out.setdefault(a, {"files": 0, "lines": 0, "blocked_files": 0, "constructs": {}, "trivial": 0})
			row["files"] += 1
			row["lines"] += lines
			found = scan_source(src)
			real = {k: v for k, v in found.items() if k != "import" or v}
			if lines <= 6 and "class" in found and len(found) == 2:
				row["trivial"] += 1   # an empty controller: `class X(Document): pass`
				continue
			if found:
				row["blocked_files"] += 1
				for k, v in found.items():
					row["constructs"][k] = row["constructs"].get(k, 0) + v
	return out


def report():
	data = collect()
	tot = {"files": 0, "lines": 0, "blocked": 0}
	for a, r in sorted(data.items()):
		top = sorted(r["constructs"].items(), key=lambda kv: -kv[1])[:6]
		print(f"{a:34} files {r['files']:3}  lines {r['lines']:5}  empty controllers {r['trivial']:3}  files the sandbox refuses {r['blocked_files']:3}   " + ", ".join(f"{k} x{v}" for k, v in top))
		tot["files"] += r["files"]
		tot["lines"] += r["lines"]
		tot["blocked"] += r["blocked_files"]
	print(f"TOTAL files {tot['files']}, lines {tot['lines']}, files the sandbox refuses {tot['blocked']}")
