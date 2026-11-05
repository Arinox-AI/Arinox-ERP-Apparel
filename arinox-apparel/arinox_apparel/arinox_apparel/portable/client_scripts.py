"""Form scripts as Client Script records. The app's `*.js` files call Python on the server (`frm.call("x")` runs a controller
method, `frappe.call({method: "arinox_apparel.x.y.fn"})` runs a function). A hosted site has neither, so every such call is
pointed at an API Server Script named by `api_name`."""

import json
import os
import re

HERE = os.path.dirname(__file__)
APP = os.path.dirname(HERE)
SKIP = {"tna_milestone_calendar.js"}   # a calendar view settings file, not a form script
PORTED = os.path.join(HERE, "server_scripts", "api_manifest.json")


def api_name(dotted):
	"""arinox_apparel.arinox_apparel.doctype.sales_contract.sales_contract.make_sales_order -> arinox_sales_contract_make_sales_order"""
	parts = dotted.split(".")
	return f"arinox_{parts[-2]}_{parts[-1]}"


def ported():
	return set(json.load(open(PORTED))["names"]) if os.path.exists(PORTED) else set()


PRELUDE = """// Hosted site: controller methods are API Server Scripts named arinox_<doctype>_<method>.
// An API Server Script returns the whole frappe.flags dict; the answer is in frappe.flags.arinox_result, unwrapped here so the
// form code below can keep reading r.message as the plain result.
if (!window.__arinox_call_patched) {
	window.__arinox_call_patched = true;
	const orig_call = frappe.call.bind(frappe);
	const unwrap = (r) => { if (r && r.message && typeof r.message === "object" && "arinox_result" in r.message) r.message = r.message.arinox_result; return r; };
	frappe.call = function (opts) {
		if (opts && typeof opts === "object" && typeof opts.method === "string" && opts.method.startsWith("arinox_")) {
			const cb = opts.callback;
			if (cb) opts = Object.assign({}, opts, { callback: (r) => cb(unwrap(r)) });
			return orig_call(opts).then(unwrap);
		}
		return orig_call.apply(null, arguments);
	};
}
frappe.ui.form.on("%(dt)s", {
	setup(frm) {
		frm.call = function (opts, args) {
			if (typeof opts === "string") opts = { method: opts, args: args };
			const method = "arinox_%(slug)s_" + opts.method;
			return frappe.call({
				method, freeze: opts.freeze, freeze_message: opts.freeze_message, callback: opts.callback,
				args: Object.assign({ name: frm.doc.name, doc: JSON.stringify(frm.doc) }, opts.args || {}),
			});
		};
	},
});
"""


def rewrite(js):
	"""Point every dotted app method at its API Server Script name. Handles the three dynamic forms the form scripts use:
	`arinox_apparel.shipping.${method}` (method is "module.function"), `...doctype.${dt}.${dt}.make_inspection`, and a constant
	holding a module path that is used as `${PC}.function`."""
	# 1. constants that hold a module path: const PC = "...doctype.production_card.production_card"; used as `${PC}.fn`
	for name, mod in re.findall(r'const (\w+) = "arinox_apparel(?:\.[a-z_0-9]+)*?\.([a-z_0-9]+)\.\2";', js):
		js = re.sub(r'const %s = "[^"]+";' % name, 'const %s = "arinox_%s";' % (name, mod), js)
		js = js.replace("${%s}." % name, "${%s}_" % name)
	# 2. `arinox_apparel.shipping.${method}`  with method "module.function"
	js = js.replace("`arinox_apparel.shipping.${method}`", "`arinox_${method.replace(\".\", \"_\")}`")
	# 3. `arinox_apparel.arinox_apparel.doctype.${dt}.${dt}.make_inspection`
	js = js.replace("`arinox_apparel.arinox_apparel.doctype.${dt}.${dt}.make_inspection`", "`arinox_${dt}_make_inspection`")
	# 4. plain dotted strings
	js = re.sub(r"arinox_apparel(?:\.[a-z_0-9]+)+", lambda m: api_name(m.group(0)), js)
	bad = re.findall(r"arinox_arinox\w*", js)
	if bad:
		raise ValueError("client script rewrite left a mangled name: %s" % bad[:3])
	return js


def export_client_scripts():
	out = []
	base = os.path.join(APP, "arinox_apparel", "doctype")
	for d in sorted(os.listdir(base)):
		for f in sorted(os.listdir(os.path.join(base, d))) if os.path.isdir(os.path.join(base, d)) else []:
			if not f.endswith(".js") or f.startswith("test_") or f in SKIP or f.endswith("_calendar.js") or f.endswith("_list.js") and False:
				continue
			js = open(os.path.join(base, d, f)).read()
			m = re.search(r'frappe\.ui\.form\.on\(\s*"([^"]+)"', js)
			if not m:
				continue
			dt = m.group(1)
			out.append({"doctype": "Client Script", "name": f"Arinox {dt}", "dt": dt, "view": "Form", "enabled": 1,
						"script": PRELUDE % {"dt": dt, "slug": d} + "\n" + rewrite(js)})
	pj = os.path.join(APP, "public", "js")
	for f in sorted(os.listdir(pj)):
		js = open(os.path.join(pj, f)).read()
		m = re.search(r'frappe\.ui\.form\.on\(\s*"([^"]+)"', js)
		if m:
			dt = m.group(1)
			slug = f[:-3]
			out.append({"doctype": "Client Script", "name": f"Arinox {dt}", "dt": dt, "view": "Form", "enabled": 1,
						"script": PRELUDE % {"dt": dt, "slug": slug} + "\n" + rewrite(js)})
	return out
