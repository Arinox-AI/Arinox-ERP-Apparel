# Build Plan — Arinox Apparel

## Phase 0 — Dev environment (one time)

1. Install a local Frappe bench using `frappe_docker` (MariaDB, Redis, Frappe containers).
2. Create a dev site, e.g. `apparel.localhost`.
3. Install ERPNext from the `erpnext-16.34.1` branch so the dev version matches the hosted one.
4. Scaffold the app:
   ```bash
   bench new-app arinox_apparel
   bench --site apparel.localhost install-app arinox_apparel
   ```
5. Commit the empty app to its own git repo (`arinox_apparel`). This repo is what gets transferred later.

Exit check: the desk loads, the Arinox Apparel module appears, and `bench --site apparel.localhost migrate` runs clean.

## Phase 1 — Core catalogue (first slice)

Doctypes: **Style**, **Size Chart**, **Colorway**.

- Style: style number, name, season, buyer (Customer), category, status, linked Item template.
- Size Chart: sizes (S–XXL) × measurement points (chest, length, sleeve…), with tolerance.
- Colorway: colour name, Pantone code, linked ERPNext Colour attribute value.

Exit check: create a Style, attach a Size Chart and two Colourways, see them in list view, and generate Item Variants for each size × colour.

## Phase 2 — Design and sampling

- Tech Pack (versioned; each revision is a row or a child doctype)
- Fit Sample (revisions, approval status, comments)

## Phase 3 — Orders and costing

- Size-colour matrix on Sales Order (custom child table or grid, writes to Sales Order Item rows)
- Style Costing (fabric, trims, CMT, overhead, margin → selling price)

## Phase 4 — Production

- Cutting plan per style/size/colour, linked to Work Order
- Sewing bundles and line output, extending Job Card
- Packing list with size breakdown per carton, extending Packing Slip

## Phase 5 — Reports and print formats

- Style status report, size-wise order report, production vs order
- Arinox-branded print formats (orange/black header)

## How every slice runs

1. Write or update the spec in `doctypes/`.
2. Build JSON + controller in `arinox_apparel/arinox_apparel/doctype/<name>/`.
3. `bench --site apparel.localhost migrate`
4. Test in the desk. Add a Python test (`bench --site apparel.localhost run-tests --app arinox_apparel`).
5. Export fixtures only if the slice needs seed data (roles, workspace, print formats).
6. Review with the user before starting the next slice.
