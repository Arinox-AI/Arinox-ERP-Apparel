#!/usr/bin/env python3
"""Copy the hosted Server Scripts into the tower: one source of truth (the repo's bundle), never edited here.

    python3 tools/vendor_scripts.py [path/to/17_server_scripts.json]

Writes backend/tsr/vendor/server_scripts.json and CHECKSUMS.json. ``backend/tests/test_tsr_vendor.py`` fails if the
vendored copy no longer matches the bundle it came from.
"""
import hashlib, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "arinox-apparel", "hosted_bundle", "17_server_scripts.json")
DST = os.path.join(ROOT, "backend", "tsr", "vendor")


def query_report_script(r: dict) -> str:
    """A Query Report (raw SQL) wrapped as a Script Report, so the tower runs it through tsr.sql (2026-11-07).
    The column labels are the query's own ``as "Label:Type:width"`` aliases, in order."""
    import re as _re
    q = r.get("query") or ""
    cols = _re.findall(r'\bas\s+"([^"]+)"', q, _re.I) or [c.get("label") if isinstance(c, dict) else str(c) for c in (r.get("columns") or [])]
    return ("q = " + json.dumps(q) + "\n"
            "rows = frappe.db.sql(q, filters, as_dict=False)\n"
            "data = [" + json.dumps(cols) + ", [list(x) for x in (rows or [])]]\n")


def main():
    data = json.load(open(SRC))
    keep = ("name", "script_type", "reference_doctype", "doctype_event", "api_method", "event_frequency", "script", "disabled")
    recs = [{k: r.get(k) for k in keep} for r in data["records"]]
    os.makedirs(DST, exist_ok=True)
    with open(os.path.join(DST, "server_scripts.json"), "w") as f:
        json.dump({"source": os.path.relpath(SRC, os.path.dirname(ROOT)), "records": recs}, f, indent=1, sort_keys=True)
    sums = {r["name"]: hashlib.sha256(r["script"].encode()).hexdigest() for r in recs}
    with open(os.path.join(DST, "CHECKSUMS.json"), "w") as f:
        json.dump(sums, f, indent=1, sort_keys=True)
    rep_src = os.path.join(os.path.dirname(SRC), "09_reports.json")
    reps = []
    for r in json.load(open(rep_src))["records"]:
        if r.get("report_type") == "Script Report":
            reps.append({k: r.get(k) for k in ("name", "ref_doctype", "report_script", "filters", "roles", "add_total_row")})
        elif r.get("report_type") == "Query Report" and r.get("query"):
            rec = {k: r.get(k) for k in ("name", "ref_doctype", "filters", "roles", "add_total_row")}
            rec["report_script"] = query_report_script(r)
            rec["filters"] = rec.get("filters") or []
            rec["wrapped_query_report"] = True
            reps.append(rec)
    with open(os.path.join(DST, "reports.json"), "w") as f:
        json.dump({"source": os.path.relpath(rep_src, os.path.dirname(ROOT)), "records": reps}, f, indent=1, sort_keys=True)
    sums.update({"report:" + r["name"]: hashlib.sha256((r["report_script"] or "").encode()).hexdigest() for r in reps})
    with open(os.path.join(DST, "CHECKSUMS.json"), "w") as f:
        json.dump(sums, f, indent=1, sort_keys=True)
    print(f"vendored {len(recs)} scripts and {len(reps)} script reports from {SRC}")


if __name__ == "__main__":
    main()
