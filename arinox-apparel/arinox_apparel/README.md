# Arinox Apparel

Apparel industry layer for ERPNext: styles, tech packs, size charts, colourways, fit samples, size-wise orders, costing, and production.

Requires ERPNext v16.x (see `required_apps` in `arinox_apparel/hooks.py`).

## Install (self-hosted bench)

```bash
bench get-app <repo-url> --branch apparel-app
bench --site <site> install-app arinox_apparel
bench --site <site> migrate
bench restart
```

See the agent docs in the parent workspace (`arinox-apparel/DEPLOY.md`) for the full runbook.
