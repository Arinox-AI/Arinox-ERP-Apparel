#!/bin/sh
# Run the hosted scenarios on the ERPNext-only test site.  Usage: hosted_tests.sh [group_or_test_name]
# The app is not installed on that site; a plain import works, `bench execute` would refuse the module.
cd /workspaces/frappe-bench || exit 1
# nothing consumes the job queue on the test site; ERPNext refuses new work above 600 queued jobs, so drain it first (quick when it is short)
timeout 120 bench worker --burst >/dev/null 2>&1
printf 'from arinox_apparel.portable.hosted_tests.run import run\nrun(%s)\n' "${1:+\"$1\"}" | bench --site hosted.localhost console 2>&1 | grep -E "^ +ok |^ +FAIL|RESULT|Traceback|Error"
