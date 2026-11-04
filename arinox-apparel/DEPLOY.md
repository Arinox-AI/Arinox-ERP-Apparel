# Deploy — Moving only the Arinox Apparel doctypes to your hosted ERPNext

The transfer unit is the **`arinox_apparel` app**, delivered from a git repo. No database, no ERPNext source, no `sites/` folder moves. The hosted site pulls the app, runs migrate, and the doctypes appear.

## Prerequisites

- Hosted ERPNext is on the **same major.minor** as dev (ERPNext v16.x). Confirm in the site's About page or Frappe Cloud dashboard.
- `arinox_apparel` lives in its own git repo (e.g. `github.com/Arinox-AI/arinox_apparel`), with a tag per release (`v0.1.0`, ...).
- `hooks.py` declares the ERPNext dependency:
  ```python
  required_apps = ["erpnext"]
  ```

## Option A — Self-hosted bench (your own server)

Run on the server, as the bench user:

```bash
cd ~/frappe-bench
bench get-app https://github.com/Arinox-AI/arinox_apparel --branch v0.1.0
bench --site <your-site> install-app arinox_apparel
bench --site <your-site> migrate
bench --site <your-site> clear-cache
bench restart
```

For later releases:

```bash
cd ~/frappe-bench/apps/arinox_apparel && git fetch --tags && git checkout v0.2.0
cd ~/frappe-bench && bench --site <your-site> migrate && bench restart
```

Take a backup first: `bench --site <your-site> backup --with-files`.

## Option B — Frappe Cloud

1. Give Frappe Cloud access to the private repo (GitHub app authorisation).
2. In the Frappe Cloud dashboard: **Benches → Apps → Add app**, choose the repo and tag.
3. Deploy the new app to a bench, then **Install** it on the site.
4. Trigger a site migrate from the dashboard.

Note: Frappe Cloud only lets you install apps on benches it builds, so the app's bench must include `erpnext` at the matching version.

## What gets transferred vs. not

| Item | Transferred? |
|---|---|
| `arinox_apparel` app code (doctype JSON, controllers, JS, print formats in fixtures) | Yes |
| ERPNext core | No. Already on hosted site. |
| Site data (customers, items, orders) | No. Stays on hosted site. |
| Dev site database / `sites/` | No |
| Test data created during dev | No, unless you choose to export it as a fixture |

## Release checklist

- [ ] Doctype specs in `doctypes/` match the code.
- [ ] `bench --site apparel.localhost run-tests --app arinox_apparel` passes.
- [ ] `migrate` runs clean on a fresh dev site.
- [ ] Version bumped in `arinox_apparel/__init__.py` and `pyproject.toml`.
- [ ] Git tag created (`vX.Y.Z`) and pushed (only after user approval).
- [ ] Backup taken on the hosted site.
- [ ] Staging test on a copy of the hosted site before production.

## Rollback

Checkout the previous tag in `apps/arinox_apparel`, run `bench migrate`, restart. Doctype removals are not automatic: destructive migrations must be reviewed by hand.
