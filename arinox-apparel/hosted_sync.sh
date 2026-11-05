#!/bin/sh
# Re-export the bundle from the dev site and load the named groups (default: server_scripts) onto the hosted test site.
# Needs the test server on :8001 and the token file written by the setup step.
GROUPS_TO_LOAD="${1:-server_scripts}"
cd /workspaces/frappe-bench || exit 1
bench --site apparel.localhost execute arinox_apparel.portable.export_bundle.export --kwargs "{'out': '/workspaces/Arinox-ERP-Apparel/arinox-apparel/hosted_bundle'}" 2>&1 | grep -E "Traceback|Error"
cd /workspaces/Arinox-ERP-Apparel/arinox-apparel || exit 1
ARINOX_API_TOKEN="$(cat "${ARINOX_TOKEN_FILE:-$HOME/.arinox_hosted_token}")" \
python3 arinox_apparel/arinox_apparel/portable/api_load.py hosted_bundle http://hosted.localhost:8001 --only="$GROUPS_TO_LOAD" 2>&1 | cut -c1-300
