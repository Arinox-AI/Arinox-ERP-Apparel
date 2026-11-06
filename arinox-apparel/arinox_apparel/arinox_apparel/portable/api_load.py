#!/usr/bin/env python3
"""Load an exported bundle onto a site through its REST API. Standard library only, so an agent with nothing but API access
can run it.

    python3 api_load.py BUNDLE_DIR https://site.example KEY:SECRET [--only group,group] [--dry-run]

Idempotent: a record that exists is updated, a record that does not is created. Seed records and the Apparel Settings single are create-only (an existing one is left as people have set it; pass --overwrite-seeds to replace it). DocTypes are inserted in dependency order; a
doctype whose first insert had to leave out a field that closes a loop is updated with its full definition afterwards. Prints one
line per group and every failure with the server's own message; exit code 1 if anything failed. Credentials are taken from the
command line or the ARINOX_API_TOKEN environment variable and are never printed."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


class Site:
	def __init__(self, url, token):
		self.url, self.token = url.rstrip("/"), token

	def call(self, method, path, body=None):
		req = urllib.request.Request(self.url + path, method=method)
		req.add_header("Authorization", "token " + self.token)
		req.add_header("Accept", "application/json")
		data = None
		if body is not None:
			data = json.dumps(body).encode()
			req.add_header("Content-Type", "application/json")
		try:
			with urllib.request.urlopen(req, data=data, timeout=120) as r:
				return r.status, json.loads(r.read() or b"{}")
		except urllib.error.HTTPError as e:
			raw = e.read().decode(errors="replace")
			try:
				return e.code, json.loads(raw)
			except ValueError:
				return e.code, {"raw": raw[:500]}


def message(resp):
	"""The readable reason out of a Frappe error body."""
	if "_server_messages" in resp:
		try:
			return "; ".join(json.loads(m).get("message", "") for m in json.loads(resp["_server_messages"]))[:400]
		except Exception:
			pass
	for k in ("exception", "message", "raw"):
		if resp.get(k):
			return str(resp[k])[-400:]
	return str(resp)[:400]


def key_of(rec):
	"""The name a record is expected to get, for the existence check; None when it must be searched for."""
	dt = rec["doctype"]
	for f in ("name", "role_name", "module_name", "report_name", "label", "chart_name", "dashboard_name"):
		if rec.get(f):
			return rec[f]
	return None


def exists(site, dt, name):
	st, resp = site.call("GET", f"/api/resource/{urllib.parse.quote(dt)}/{urllib.parse.quote(name, safe='')}")
	return st == 200


def find_by(site, dt, match):
	"""Name of the record whose fields equal `match` (for records named by a random hash)."""
	filters = json.dumps([[dt, k, "=", v] for k, v in match.items()])
	st, resp = site.call("GET", f"/api/resource/{urllib.parse.quote(dt)}?filters={urllib.parse.quote(filters)}&limit_page_length=1")
	rows = resp.get("data") or [] if st == 200 else []
	return rows[0]["name"] if rows else None


def upsert(site, rec, name=None, overwrite=False):
	dt = rec["doctype"]
	create_only = rec.pop("__create_only", False) and not overwrite
	match = rec.pop("__match", None)
	if match is not None:
		name = find_by(site, dt, match) or "\0none"
	name = name or key_of(rec)
	if name and name != "\0none" and exists(site, dt, name):
		if create_only:        # a seed that is already there may have been edited by the people who use it
			return "skipped", 200, {}
		body = {k: v for k, v in rec.items() if k not in ("doctype", "name")}
		st, resp = site.call("PUT", f"/api/resource/{urllib.parse.quote(dt)}/{urllib.parse.quote(name, safe='')}", body)
		return "updated", st, resp
	st, resp = site.call("POST", f"/api/resource/{urllib.parse.quote(dt)}", rec)
	return "created", st, resp


def load_group(site, path, dry=False, overwrite=False):
	g = json.load(open(path))
	done, failed = {"created": 0, "updated": 0, "skipped": 0}, []
	if g["mode"] == "doctypes":
		pass2 = []
		for item in g["records"]:
			rec = dict(item["first"])
			rec["doctype"] = "DocType"
			if dry:
				continue
			what, st, resp = upsert(site, rec)
			if st >= 400:
				failed.append((rec["name"], message(resp)))
				continue
			done[what] += 1
			if item["deferred"] or what == "updated":
				pass2.append(item["doc"])
		for doc in pass2:
			rec = dict(doc)
			rec["doctype"] = "DocType"
			what, st, resp = upsert(site, rec)
			if st >= 400:
				failed.append((rec["name"] + " (second pass)", message(resp)))
	elif g["mode"] == "single":
		for rec in g["records"]:
			if dry:
				continue
			dt = urllib.parse.quote(rec["doctype"])
			body = {k: v for k, v in rec.items() if k != "doctype"}
			if not overwrite:      # settings people have already set stay as they are; only blanks are filled
				st, cur = site.call("GET", f"/api/resource/{dt}/{dt}")
				cur = cur.get("data", {}) if st == 200 else {}
				body = {k: v for k, v in body.items() if cur.get(k) in (None, "", 0, [], ())}
			st, resp = site.call("PUT", f"/api/resource/{dt}/{dt}", body)
			if st >= 400:
				failed.append((rec["doctype"], message(resp)))
			else:
				done["updated"] += 1
	else:
		for rec in g["records"]:
			if dry:
				continue
			what, st, resp = upsert(site, rec, overwrite=overwrite)
			if st >= 400:
				failed.append((str(key_of(rec) or rec.get("dt") or rec["doctype"]), message(resp)))
			else:
				done[what] += 1
	return g, done, failed


def main(argv):
	args = [a for a in argv if not a.startswith("--")]
	flags = {a.split("=")[0]: (a.split("=", 1) + [""])[1] for a in argv if a.startswith("--")}
	if len(args) < 2:
		print(__doc__)
		return 2
	bundle, url = args[0], args[1]
	token = args[2] if len(args) > 2 else os.environ.get("ARINOX_API_TOKEN", "")
	site = Site(url, token)
	only = set(flags["--only"].split(",")) if flags.get("--only") else None
	bad = 0
	for entry in json.load(open(os.path.join(bundle, "index.json"))):
		if only and entry["group"] not in only:
			continue
		g, done, failed = load_group(site, os.path.join(bundle, entry["file"]), dry="--dry-run" in flags, overwrite="--overwrite-seeds" in flags)
		print(f"{entry['group']:20} created {done['created']:4} updated {done['updated']:4} skipped {done['skipped']:4} failed {len(failed):3} of {entry['count']}")
		for name, why in failed:
			print(f"    FAILED {name}: {why}")
		bad += len(failed)
	return 1 if bad else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
