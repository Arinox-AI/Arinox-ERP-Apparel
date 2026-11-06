"""Run the generated Tech Pack form script in Node against a stub of Frappe's client and check how calls are routed:
ERPNext's own frm.call / open_mapped_doc calls must go to Frappe untouched; ported controller methods must go to their API Server Script;
the Create > Cost Sheet button must call the API and open the document it returns.

    python3 -I check_client_routing.py        (needs `node`; prints OK or the first wrong line, exits 1 on a failure)
"""

import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = r"""
const log = [];
const handlers = [];
global.__ = (s) => s;
global.window = {};
const resolved = (v) => ({ then: (f) => { const r = f(v); return r && r.then ? r : resolved(r); } });
global.frappe = {
  call: (o) => { log.push("frappe.call|" + o.method + "|" + JSON.stringify(o.args || null)); return resolved({ message: o.method.startsWith("arinox_tech_pack_make_cost_sheet") ? { doctype: "Cost Sheet", name: "new-cost-sheet-1" } : { ok: 1 } }); },
  ui: { form: { on: (dt, h) => handlers.push(h) } },
  model: { open_mapped_doc: (o) => log.push("ORIGINAL open_mapped_doc|" + o.method), sync: (d) => log.push("sync|" + d.name) },
  set_route: (...a) => log.push("set_route|" + a.join("/")),
  throw: (m) => { throw new Error(m); }, show_alert: () => {}, db: {}, meta: {},
};
const frm = new Proxy({ doc: { name: "TP-1", __unsaved: 0 }, call: function (o) { log.push("ORIGINAL frm.call|" + (typeof o === "string" ? o : o.method)); return resolved({}); } },
  { get: (t, k) => (k in t ? t[k] : () => {}) });
%SCRIPT%
handlers.forEach((h) => h.setup && h.setup(frm));
frm.call({ doc: frm.doc, method: "erpnext.stock.get_item_details.get_item_tax_info", args: {} });
frm.call({ doc: frm.doc, method: "something_not_ours" });
frm.call("make_cost_sheet");
frappe.model.open_mapped_doc({ method: "arinox_tech_pack_make_cost_sheet", frm });
frappe.model.open_mapped_doc({ method: "erpnext.x.y", frm });
console.log(log.join("\n"));
"""
EXPECT = [
	"ORIGINAL frm.call|erpnext.stock.get_item_details.get_item_tax_info",
	"ORIGINAL frm.call|something_not_ours",
	'frappe.call|arinox_tech_pack_make_cost_sheet|{"name":"TP-1","doc":"{\\"name\\":\\"TP-1\\",\\"__unsaved\\":0}"}',
	'frappe.call|arinox_tech_pack_make_cost_sheet|{"source_name":"TP-1"}',
	"sync|new-cost-sheet-1",
	"set_route|Form/Cost Sheet/new-cost-sheet-1",
	"ORIGINAL open_mapped_doc|erpnext.x.y",
]


def main():
	spec = importlib.util.spec_from_file_location("client_scripts", os.path.join(HERE, "client_scripts.py"))
	cs = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(cs)
	script = next(x["script"] for x in cs.export_client_scripts() if x["name"] == "Arinox Tech Pack")
	with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
		f.write(HARNESS.replace("%SCRIPT%", script))
		path = f.name
	try:
		out = subprocess.run(["node", path], capture_output=True, text=True)
	finally:
		os.unlink(path)
	got = out.stdout.strip().splitlines()
	if got != EXPECT:
		print("WRONG ROUTING\nexpected:\n  " + "\n  ".join(EXPECT) + "\ngot:\n  " + "\n  ".join(got) + out.stderr[:500])
		sys.exit(1)
	print("OK: %d routing checks" % len(EXPECT))


if __name__ == "__main__":
	main()
