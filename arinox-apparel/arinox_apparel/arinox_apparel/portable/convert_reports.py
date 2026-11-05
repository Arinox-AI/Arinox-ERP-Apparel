"""Mechanical first pass: turn a Script Report's Python file into sandbox source. Run once by hand, then fix what the sandbox
refuses; the converted files in script_reports/ are the source of truth afterwards.

    python3 convert_reports.py   (from this folder)
"""

import ast
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(os.path.dirname(HERE), "arinox_apparel", "report")
OUT = os.path.join(HERE, "script_reports")
SKIP = {
	"wip_report": "needs the T&A board code; the WIP view is being built separately",
	"sample_approval_tracker": "uses get_order_lines and get_bulk_gate (engine work)",
	"fabric_consumption": "uses production.summary.fabric_usage and materials.common (engine work)",
	"material_status": "uses materials.status.material_rows (engine work)",
	"freight_allocation": "uses shipping.freight (engine work)",
	"running_fabric_stock": "uses production.stock.moved and materials.common (engine work)",
}


def convert(src):
	utils = set()
	for m in re.finditer(r"from frappe\.utils import ([^\n(]+)", src):
		utils.update(x.strip() for x in m.group(1).split(","))
	for m in re.finditer(r"from frappe\.utils import \(([^)]*)\)", src):
		utils.update(x.strip() for x in m.group(1).split(",") if x.strip())
	lines = []
	in_doc = False
	for ln in src.splitlines():
		s = ln.strip()
		if re.match(r"(from [A-Za-z_][\w.]* import |import [A-Za-z_][\w., ]*$)", s) or s.startswith("# Copyright"):
			continue
		lines.append(ln)
	body = "\n".join(lines)
	body = re.sub(r'^"""[\s\S]*?"""\n', "", body.lstrip("\n"), count=1)
	body = re.sub(r"\b_\((\"[^\"]*\"|'[^']*')\)", r"\1", body)       # _("Text") -> "Text"
	body = re.sub(r"frappe\._dict\(filters or \{\}\)", "filters", body)
	body = re.sub(r"frappe\._dict\(filters\)", "filters", body)
	for name in sorted(utils):
		body = re.sub(rf"(?<![\w.]){name}\(", f"frappe.utils.{name}(", body)       # names imported from frappe.utils are not globals
	body = body.replace("def execute(filters=None):", "def execute(filters):")
	body = "\n".join(("    " + l if l.strip() else l) for l in body.splitlines())
	code = f"def main(filters):\n{body}\n    return execute(filters)\n\n\ndata = list(main(filters))\n"
	return sandbox_safe(code)


class Fix(ast.NodeTransformer):
	"""Two things the sandbox refuses that plain Python allows: names that start with an underscore, and `a, b = pair`."""

	def __init__(self):
		self.n = 0

	def visit_Name(self, node):
		if node.id.startswith("_") and not node.id.startswith("__"):
			node.id = "x" + node.id
		return node

	def visit_arg(self, node):
		if node.arg.startswith("_") and not node.arg.startswith("__"):
			node.arg = "x" + node.arg
		return node

	def visit_FunctionDef(self, node):
		if node.name.startswith("_") and not node.name.startswith("__"):
			node.name = "x" + node.name
		self.generic_visit(node)
		return node

	def visit_Call(self, node):
		"""'{0} of {1}'.format(a, b) -> '%s of %s' % (a, b): str.format is refused by the sandbox."""
		self.generic_visit(node)
		f = node.func
		if isinstance(f, ast.Attribute) and f.attr == "strftime" and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
			# date.strftime needs an import the sandbox lacks; frappe.utils.formatdate takes the same date with a different format code
			fmt = node.args[0].value
			for a, b in (("%Y", "yyyy"), ("%y", "yy"), ("%b", "MMM"), ("%B", "MMMM"), ("%m", "mm"), ("%d", "dd")):
				fmt = fmt.replace(a, b)
			call = ast.Call(ast.parse("frappe.utils.formatdate", mode="eval").body, [f.value, ast.Constant(fmt)], [])
			return ast.copy_location(call, node)
		if isinstance(f, ast.Attribute) and f.attr == "format" and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str) and not node.keywords:
			text = f.value.value
			found = re.findall(r"\{(\d*)\}", text)
			idx = [int(x) if x else i for i, x in enumerate(found)]
			if idx == list(range(len(node.args))) and "{" not in re.sub(r"\{\d*\}", "", text):
				new = re.sub(r"\{\d*\}", "%s", text.replace("%", "%%"))
				return ast.copy_location(ast.BinOp(ast.Constant(new), ast.Mod(), ast.Tuple(node.args, ast.Load())), node)
		return node

	def visit_Assign(self, node):
		self.generic_visit(node)
		if len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
			targets = node.targets[0].elts
			if isinstance(node.value, (ast.Tuple, ast.List)) and len(node.value.elts) == len(targets) and not any(isinstance(t, ast.Starred) for t in targets):
				return [ast.copy_location(ast.Assign(targets=[t], value=v), node) for t, v in zip(targets, node.value.elts)]
			self.n += 1
			tmp = f"pair{self.n}"
			out = [ast.copy_location(ast.Assign(targets=[ast.Name(tmp, ast.Store())], value=node.value), node)]
			for i, t in enumerate(targets):
				out.append(ast.copy_location(ast.Assign(targets=[t], value=ast.Subscript(ast.Name(tmp, ast.Load()), ast.Constant(i), ast.Load())), node))
			return out
		return node


def sandbox_safe(code):
	tree = Fix().visit(ast.parse(code))
	ast.fix_missing_locations(tree)
	return ast.unparse(tree) + "\n"


def main():
	os.makedirs(OUT, exist_ok=True)
	entries = []
	for slug in sorted(os.listdir(REPORTS)):
		p = os.path.join(REPORTS, slug, slug + ".py")
		j = os.path.join(REPORTS, slug, slug + ".json")
		if slug in SKIP or not os.path.exists(p) or not os.path.exists(j):
			continue
		meta = json.load(open(j))
		if meta.get("report_type") != "Script Report":
			continue
		open(os.path.join(OUT, slug + ".py"), "w").write(convert(open(p).read()))
		entries.append({"slug": slug, "file": slug + ".py"})
	json.dump({"reports": entries}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
	print(len(entries), "converted")


if __name__ == "__main__":
	main()
