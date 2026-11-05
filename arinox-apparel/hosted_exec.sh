#!/bin/sh
# Run a python file on the hosted test site's console.  Usage: hosted_exec.sh file.py [grep-pattern]
cd /workspaces/frappe-bench || exit 1
printf 'exec(open("%s").read())\n' "$1" | bench --site hosted.localhost console 2>&1 | grep -E "${2:-^(CHK|OUT|RESULT)|Traceback|Error}"
