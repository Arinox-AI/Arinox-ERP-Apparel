"""Tower Script Runtime (TSR): runs the Arinox hosted Server Scripts inside the tower.

The hosted ERPNext site will not get Server Script access, so the same script text that
``arinox-apparel/hosted_bundle/17_server_scripts.json`` would load there is executed here,
against a ``frappe`` stand-in that talks to the ERP over REST. See ``CORTEX_TOWER_PLAN.md`` §3 Phase 1.
"""
