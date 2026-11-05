# Arinox Apparel — Agent Instructions

This folder is the working context for building the **Arinox apparel ERP layer** on top of ERPNext using the Frappe framework.

## Goal

Build custom Frappe doctypes and small extensions for the apparel industry (styles, tech packs, size charts, colorways, fit samples, size-wise orders, costing, cutting/sewing production, packing). Ship them as a **separate Frappe app** named `arinox_apparel` that depends on ERPNext. Never modify ERPNext core.

## Hard rules

1. **Do not edit `erpnext/` core code.** All apparel logic lives in the `arinox_apparel` app. Extend ERPNext via `hooks.py`, `doctype_js`, `override_doctype_class`, or Custom Fields / Property Setters, in that order of preference.
2. **One app, one transfer unit.** The only thing that moves to the hosted ERPNext is the `arinox_apparel` app (git repo). Do not copy site databases, `sites/` folders, or ERPNext source into the hosted instance.
3. **Pin versions.** ERPNext and Frappe must match the hosted site's major.minor. Current target: ERPNext `v16.34.1` (branch `erpnext-16.34.1`). Check `hooks.py` `required_apps` before every release.
4. **Build in small vertical slices.** One flow works end to end (desk form → validation → list/report) before starting the next. See `BUILD_PLAN.md`.
5. **Reuse ERPNext before inventing.** Size × colour is Item Variants (attributes `Size`, `Colour`). Sales Order, Work Order, Job Card, Packing Slip, Item, Warehouse, Stock Entry already exist. Check the ERPNext doctype before creating a new one.
6. **Every doctype gets a spec.** Copy `doctypes/_TEMPLATE.md` to `doctypes/<doctype-slug>.md`, fill it in, get it reviewed, then build. No spec → no code.
7. **No destructive commands on any shared or hosted site.** Only run `bench migrate`, `install-app`, or `export-*` on the local dev site unless the user explicitly says otherwise.
8. **Never commit or push without asking.** Git commits in this repo follow the user's attribution instructions.

## Stack

- Frappe / ERPNext v16.x (Python 3.11+, Node 20+, MariaDB 10.6+, Redis)
- Dev environment: bench at `/workspaces/frappe-bench`, site `apparel.localhost`, MariaDB and Redis in Docker (`docker start apparel-mariadb apparel-redis` after a Codespace restart)
- Doctype JSON + Python controller + optional client JS per doctype
- Naming: app `arinox_apparel`, module `Arinox Apparel`, doctype prefix none (use clean names like `Style`, `Size Chart`)

## Branding

Arinox document and print formats use an **orange and black header**. Primary orange `#e8590c`. Apply this to Print Formats, Letter Heads, and any Arinox-branded PDF/HTML output.

## Folder map

- `CLAUDE.md` — this file (agent rules)
- `BUILD_PLAN.md` — how we build, slice by slice
- `DEPLOY.md` — how the app moves to the hosted ERPNext
- `doctypes/` — one spec per doctype (`_TEMPLATE.md` is the blank form). `PHASE1_ORDER_WIN.md` is the built Phase 1; `PHASE1_ORDER_BACKBONE_PLAN.md` is the plan from the reference documents; `PHASE_B_PLAN_AND_APPROVE.md` is Phase B (factory allocation, sample approvals, PP meeting, bulk gate); `PHASE_C_MATERIALS_PLAN.md` is Phase C (fabric and trim requisitions, purchasing, inspection, in-house, T&A / WIP chart); `PHASE_D_PRODUCTION_PLAN.md` is Phase D (production card, pilot run, cutting, sewing, subcontracting, finishing, packing, final inspection) and `PHASE_D_BUILD_STATUS.md` records what of it is built; `PHASE_E_SHIP_AND_COLLECT_PLAN.md` is Phase E (subcontract round trip, finishing, packing, final inspection, shipment and freight, invoicing, payment follow-up, claims) and its status log says what was built (built on the dev site, reuse-first: ERPNext Shipment, Supplier Quotation and Sales Invoice are extended, not replaced)
- `reference/DOCUMENT_INDEX.md` — index of the 176 Cortex sample documents (what each is, key fields, where it maps). Read this before opening the zip
- `doctypes/HOSTED_CONSTRAINTS.md` — what fits on a site that takes only DocTypes, data and Server Scripts, and what does not. `doctypes/ERPNEXT_OVERLAP_AUDIT.md` — what we reuse from ERPNext and what overlaps. `arinox_apparel/portable/` — Server Scripts written for that constraint (manifest, loader, checker). **New logic should be written to fit the constraint first.**
- `skills/frappe-doctype/SKILL.md` — how to build, change, and test doctypes in the `arinox_apparel` app. Load it before any doctype work.

## Working style

- Ask before making decisions that change scope (which slice next, whether a field exists in ERPNext already, hosting target).
- When unsure whether an ERPNext feature covers something, read the ERPNext source in `erpnext/` first and cite the file path.
- Report test/migrate output faithfully. If a step was skipped, say so.
