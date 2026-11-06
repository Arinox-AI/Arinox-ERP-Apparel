#!/bin/sh
# Ingest the two sample orders (S84, S14) into the ERPNext-only test site and print the reconciliation against the papers.
# Usage: hosted_ingest.sh "/path/to/unzipped/ARINOX ERP DOCS"
# Needs the test site (see HOSTED_BUILD_GUIDE.md section 2). Run `bench worker --burst` first if it says "Too many queued background jobs".
cd /workspaces/frappe-bench || exit 1
printf 'from arinox_apparel.portable.demo import ingest_orders as i\nR = "%s"\ni.run(R)\ni.report()\ni.verify()\ni.verify_tech_packs(R)\n' "$1" \
  | bench --site hosted.localhost console 2>&1 | grep -E "^(In \[[0-9]+\]: )?(MADE|FAIL|GAP|OBS|CHECK|OUT made)|Traceback|Error" | sed 's/^In \[[0-9]*\]: //'
