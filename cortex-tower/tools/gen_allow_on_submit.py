#!/usr/bin/env python3
"""Which fields do the Arinox scripts write on SUBMITTED documents that the ERP will not let a REST client change?

On a site with Server Scripts, ``doc.db_set`` is a raw SQL update and ignores ``allow_on_submit``. Over REST it does not.
This finds every (doctype, field) the vendored scripts write that way, checks the live DocType meta, and writes the
Property Setters (plain data, loadable with api_load.py) that make exactly those fields editable after submission.

    python3 tools/gen_allow_on_submit.py --base http://hosted.localhost:8001 [--apply]

--apply creates the Property Setters on that site (only ever point it at a TEST site unless the owner approved it).
Without --base it uses the bundle's DocType definitions only (ERPNext's own doctypes are then not checked).
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "backend", "tsr", "vendor", "server_scripts.json")
OUT = os.path.join(ROOT, "erp_setup", "allow_on_submit.json")


def targets(recs):
    t = {}
    for r in recs:
        s, dt = r["script"], r.get("reference_doctype")
        if dt:
            for m in re.finditer(r"\b(?:doc|self|d)\.db_set\(\s*[\"'](\w+)[\"']", s):
                t.setdefault(dt, {}).setdefault(m.group(1), set()).add(r["name"])
        if dt:                                      # dict form: doc.db_set({"a": 1, "b": 2}) (found in S5: Fabric Inspection quality_inspection / stock_entry)
            for m in re.finditer(r"\b(?:doc|self|d)\.db_set\(\s*\{([^}]*)\}", s):
                for f in re.findall(r"[\"'](\w+)[\"']\s*:", m.group(1)):
                    t.setdefault(dt, {}).setdefault(f, set()).add(r["name"])
        for m in re.finditer(r"frappe\.db\.set_value\(\s*[\"']([^\"']+)[\"']\s*,[^,]+,\s*[\"'](\w+)[\"']", s):
            t.setdefault(m.group(1), {}).setdefault(m.group(2), set()).add(r["name"])
        for m in re.finditer(r"frappe\.db\.set_value\(\s*[\"']([^\"']+)[\"']\s*,[^,]+,\s*\{([^}]*)\}", s):
            for f in re.findall(r"[\"'](\w+)[\"']\s*:", m.group(2)):
                t.setdefault(m.group(1), {}).setdefault(f, set()).add(r["name"])
        # API scripts (no reference doctype): `x = frappe.get_doc("Dt", ...)` then `x.db_set(...)` (found in S7: Subcontract Settlement purchase_invoice / debit_note,
        # Subcontract Challan / Cut Plan status)
        for var, dtn in re.findall(r"\b(\w+)\s*=\s*frappe\.get_doc\(\s*[\"']([^\"']+)[\"']", s):
            for m in re.finditer(r"\b" + var + r"\.db_set\(\s*[\"'](\w+)[\"']", s):
                t.setdefault(dtn, {}).setdefault(m.group(1), set()).add(r["name"])
            for m in re.finditer(r"\b" + var + r"\.db_set\(\s*\{([^}]*)\}", s):
                for f in re.findall(r"[\"'](\w+)[\"']\s*:", m.group(1)):
                    t.setdefault(dtn, {}).setdefault(f, set()).add(r["name"])
    return t


#: child-row writes (`r.db_set({...})` on a row of a submitted parent) the regex above cannot attribute to a doctype. Found in S5 (lib_purchasing.refresh_requisition).
CHILD_DB_SET = {"Fabric Requisition Item": ["ordered_qty", "received_qty", "accepted_qty", "rejected_qty"], "Trim Requisition Item": ["ordered_qty", "received_qty", "accepted_qty", "rejected_qty"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--token", default=os.environ.get("ARINOX_API_TOKEN") or "")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    recs = json.load(open(VENDOR))["records"]
    t = targets(recs)
    for cdt, fs in CHILD_DB_SET.items():
        for f in fs:
            t.setdefault(cdt, {}).setdefault(f, set()).add("lib_purchasing.refresh_requisition")
    token = a.token or (open(os.path.expanduser("~/.arinox_hosted_token")).read().strip() if a.base and os.path.exists(os.path.expanduser("~/.arinox_hosted_token")) else "")

    def get(path, **q):
        url = a.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, headers={"Authorization": "token " + token})
        return json.load(urllib.request.urlopen(req, timeout=30))

    out, skipped = [], []
    for dt, fields in sorted(t.items()):
        if a.base:
            try:
                docs = get("/api/method/frappe.desk.form.load.getdoctype", doctype=dt)["docs"]
            except Exception:
                skipped.append((dt, "doctype not on this site"))
                continue
            main_ = next(d for d in docs if d["name"] == dt)
            if not main_.get("is_submittable") and not main_.get("istable"):
                continue
            meta = {f["fieldname"]: f for f in main_["fields"]}
        else:
            meta = None
        for f, scripts in sorted(fields.items()):
            if f in ("docstatus", "modified", "creation"):
                continue
            if meta is not None:
                fd = meta.get(f)
                if fd is None:
                    skipped.append((f"{dt}.{f}", "no such field in the meta (the script writes a column the doctype does not define)"))
                    continue
                if fd.get("allow_on_submit"):
                    ps = get("/api/method/frappe.client.get_count", doctype="Property Setter",
                             filters=json.dumps({"doc_type": dt, "field_name": f, "property": "allow_on_submit"})).get("message")
                    if not ps:
                        continue          # natively allow_on_submit, nothing to load
                    # a Property Setter of ours (already applied here): keep it in the fragment for the real site
            out.append({"doctype": "Property Setter", "name": f"{dt}-{f}-allow_on_submit", "doctype_or_field": "DocField", "doc_type": dt,
                        "field_name": f, "property": "allow_on_submit", "property_type": "Check", "value": "1",
                        "_scripts": sorted(scripts)[:4]})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"note": "Property Setters that let the tower (REST) write what the Arinox scripts db_set on submitted documents. Load with arinox-apparel/.../portable/api_load.py or create by hand.",
               "records": out, "skipped": skipped}, open(OUT, "w"), indent=1)
    print(f"{len(out)} fields need allow_on_submit; {len(skipped)} skipped -> {os.path.relpath(OUT, ROOT)}")
    for r in out:
        print("  ", r["doc_type"], r["field_name"])
    for s in skipped:
        print("   skipped:", *s)
    if a.apply:
        for r in out:
            body = {k: v for k, v in r.items() if not k.startswith("_")}
            req = urllib.request.Request(a.base + "/api/resource/Property%20Setter", data=json.dumps(body).encode(),
                                         headers={"Authorization": "token " + token, "Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=30)
            except urllib.error.HTTPError as e:
                if e.code != 409 and b"Duplicate" not in e.read():
                    print("   !", r["name"], e.code)
        print("applied. clear the site cache (bench clear-cache) so the meta is re-read.")


if __name__ == "__main__":
    main()
