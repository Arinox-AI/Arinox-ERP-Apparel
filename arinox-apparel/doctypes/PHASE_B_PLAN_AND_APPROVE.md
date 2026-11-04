# Phase B — Plan and approve (order confirmed → factory allocation → sampling and approvals → bulk gate)

**Status:** Built on the dev site (migrate clean, 72 tests pass, 1 pre-existing skip) — pending user review
**Module:** Arinox Apparel
**Spec form:** one consolidated spec for the phase (user asked to research, plan and build in one pass, 2026-11-04).
**Sources:** "Garment Flow on Frappe" brief (stages 5 and 6), `../reference/DOCUMENT_INDEX.md` (PP Meeting Format, Pilot Run, GPT report, T&A WIP milestones, PO PP/TOP rules), the business rules pasted by the user on 2026-11-04.

## Decisions (answered 2026-11-04)

1. **Bulk gate:** a Work Order cannot be submitted until every *required* approval is in for its style × colour and the PP Meeting is held with every cutting-related comment closed. Which sample types are required is a table in Apparel Settings. A manager can override per Work Order with a reason.
2. **Factory and line:** reuse ERPNext **Plant Floor** (factory: company + warehouse) and **Workstation** (sewing line, carries `plant_floor`).
3. **Garment physical test (GPT):** lives in the sample log as sample type *Garment Test (GPT)*, with a Pass/Fail row per test property and the lab PDF attached. Quality Inspection is not used because its `reference_type` only accepts stock documents (`erpnext/stock/doctype/quality_inspection/quality_inspection.json`).
4. **Production planning is data storage only.** The AI agent decides which factory gets what. The ERP stores the allocation, checks it is consistent, and gives the agent one call with everything it needs.

## The flow

```
Sales Contract ──► Sales Order (submitted = order confirmed, built in Phase A)
                        │
          ┌─────────────┼──────────────────────────────┐
          ▼             ▼                              ▼
 Factory Allocation   Sample Approval (one per type ×   PP Meeting (per style)
 style × colour →     style × colour × material; rounds  participants, fabric/trim
 Plant Floor,         until the buyer approves; buyer    readiness, tech notes,
 Workstation, PCD     comments; measurements; GPT)      every buyer comment → owner + date
          │             │                              │
          └──── PCD feeds sample due dates ────────────┘
                        │
                        ▼
              Work Order submit ── Bulk gate (G3) ──► blocked until approvals + PP meeting
```

## What ERPNext already has, and how it is used

| Need | ERPNext object | Decision |
|---|---|---|
| Factory | Plant Floor | **Reuse** (company, warehouse) |
| Sewing line | Workstation (`plant_floor`, `production_capacity`) | **Reuse** |
| Bulk production order | Work Order (`sales_order`, `production_item` = variant) | **Reuse** + gate on `before_submit` + override custom fields |
| Planning | Production Plan | **Not used.** It plans material and work orders per item; it has no factory per line and no PCD. The agent needs a plain store |
| Meeting minutes | Quality Meeting | **Not used.** Minutes have no owner, target date, or link to the buyer comment they close |
| Lab test | Quality Inspection | **Not used** for GPT (see decision 3). Kept for receiving and in-line QC in later phases |

## New doctypes

| Doctype | Kind | Purpose |
|---|---|---|
| Factory Allocation (+ Line) | Plain, one per Sales Order (`FA-<SO>`) | Which factory and line makes which style × colour, how many, PCD and sewing window. Written by the agent or a planner |
| Sample Approval (+ Round, Comment, Measurement, Test Result) | Plain, status driven by rounds | One approval item: type, style, colour, material. Every submission round, buyer decision and comment |
| PP Meeting (+ Participant, Colour, Action) | Submittable | The pre-production meeting. Submit = minutes issued. Action rows stay editable to close them |
| Apparel Sample Rule | Child of Apparel Settings | Per sample type: gate (Required / If Raised / No), per colour, due basis (PCD / Ex-Factory), days before |

New role: **Apparel Merchandising Manager** (waive an approval, override the bulk gate). Planning and PP meeting are open to Apparel Merchandiser and Manufacturing User / Manager.

## Factory Allocation

| Field | Type | Notes |
|---|---|---|
| sales_order | Link Sales Order | reqd, submitted, unique (name `FA-<SO>`) |
| sales_contract, customer, company | fetched | read only |
| status | Select Unplanned / Partly Planned / Planned | computed from allocated vs order qty |
| planned_by | Select Manual / AI Agent | |
| agent_notes | Small Text | the agent's reasoning |
| order_qty, allocated_qty | Int | computed |
| lines | Table Factory Allocation Line | style_item, style_no, colour, order_qty (ro), qty, factory (Plant Floor, reqd), line (Workstation), pcd, sewing_start, sewing_end, ex_factory_date (ro), reason |

Rules (Python):
- Sales Order must be submitted.
- Allocated qty per style × colour ≤ order qty × (1 + contract tolerance %).
- Line (Workstation) must belong to the row's factory (Plant Floor).
- PCD ≤ sewing start ≤ sewing end ≤ ex-factory date.
- Style × colour must be on the Sales Order.

Agent API (whitelisted): `get_planning_context(sales_order)` returns the order lines, the factories with lines and capacity, and other orders' allocations in the same window. `save_allocation(sales_order, lines, agent_notes)` creates or replaces the allocation (validation still runs).

## Sample Approval

Sample types: Proto, Fit, Size Set, Lab Dip, Strike Off, Desk Loom, Bulk Fabric, Bulk Trim, PP, Garment Test (GPT), TOP, Salesman, Photo Sample.

| Field | Type | Notes |
|---|---|---|
| sample_type | Select | reqd |
| status | Select Open / Submitted / Approved / Approved with Comments / Rejected / Resubmit / Not Required | read only, from the last round or the waiver |
| sales_order | Link | optional (fit and proto can come before the order). Empty = applies to the style on every order |
| sales_contract, customer | fetched | |
| style_item | Link Item (template) | reqd |
| style_no, tech_pack | | |
| colour | Data | blank = all colours. Required when the rule says per colour |
| material_type, material_item, material_description, supplier, buyer_reference | | material types need a description or item |
| is_washed, wash_description | | |
| in_bulk_fabric | Check | PP must be in bulk fabric |
| sample_size, sample_qty | | |
| pcd, ex_factory_date, due_date | Date | due date = basis date − rule days (editable) |
| submitted_on, approved_on | Date | from rounds |
| rounds | Table Sample Approval Round | round_no, sent_on, courier, awb_no, buyer_received_on, decision (Pending / Approved / Approved with Comments / Rejected / Resubmit), decision_on, shade_option, tested_after_wash, attachment, photo, remarks |
| comments | Table Sample Approval Comment | round_no, category, comment, relevant_to_cutting, status (Open / Closed), closed_in (PP Meeting) |
| measurements | Table Sample Measurement | pom_code, point_of_measure, size, spec, tol_plus, tol_minus, actual, deviation, in_tolerance. "Load Spec from Tech Pack" fills the sample size |
| tests | Table Sample Test Result | test_property, requirement, result (Pass / Fail / N/A / Data), value, remarks. "Load Standard GPT Tests" fills the list from the GPT report |
| lab_name, lab_report_no, lab_report | | GPT |
| waived, waiver_reason, waived_by | | manager only |

Rules (Python):
- Status follows the last round; no rounds = Open; waived = Not Required.
- Rounds are numbered in order; sent ≤ decision date; decision date not in the future; a decision needs a decision date.
- **Bulk Fabric / Bulk Trim on a washed garment can only be approved on a round tested after wash** (the approval follows the process, not the calendar).
- **PP can only be approved when made in bulk fabric.**
- **GPT cannot be approved while any test row is Fail.**
- *Approved with Comments*, *Rejected* and *Resubmit* need at least one comment on that round.
- Measurements: deviation and in-tolerance computed; out-of-tolerance rows warn on approval.
- Waiving (Not Required) needs Apparel Merchandising Manager or System Manager, and a reason.

## PP Meeting

From `PP Meeting Format.pdf` (Zhangjiagang Cortex Textile).

| Field | Type | Notes |
|---|---|---|
| sales_order, style_item | Link | reqd |
| sales_contract, customer, style_no, tech_pack | fetched | |
| factory, line | Plant Floor, Workstation | defaulted from the Factory Allocation |
| meeting_date, delivery_date, pcd | Date | |
| production_card_ref, production_card_issued_on | Data, Date | issued date required on submit; meeting on or after it |
| pp_sample, size_set_sample | Link Sample Approval | PP must be approved to submit |
| is_washed | Check | Washing must attend only when washed |
| participants | Table PP Meeting Participant | department, participant_name, user, designation, attended |
| colours | Table PP Meeting Colour | colour, order_qty, fabric_required_m, fabric_received_m, no_of_shades |
| sewing_trims, packing_trims | Select Available / Partial / Not Available | |
| prewashed_trims, predyed_trims | Select Yes / No / N/A | |
| line_setting_checklist | Check | |
| critical_operations, expected_problems, preventive_actions, spi, needle_size, needle_type, needle_change_frequency, marking_method, checkpoints, washing_method, finishing_instructions, ironing, packing, special_requirements | Small Text / Data | |
| pp_corrections_for_cutting, size_set_corrections_for_cutting | Check | |
| actions | Table PP Meeting Action | sample_approval, comment_ref, source (Buyer Comment / Meeting), category, comment, relevant_to_cutting, action_taken, action_owner (User), target_date, status (Open / Closed), closed_on. Status, action, closed_on editable after submit |
| status | Select Draft / Open Actions / Closed | computed |

Rules (Python):
- Submit needs: PP sample approved; every **open buyer comment** on the style's samples present in the action table; every action row has action, owner and target date; departments Planning, Purchasing, Cutting, Sewing, QC (and Washing if washed) attended; production card issued on or before the meeting date.
- Closing an action stamps `closed_on` and closes the source comment on the Sample Approval.

## Bulk gate (G3) on Work Order

`before_submit` hook. Skipped when Apparel Settings → Enforce Bulk Gate is off, when the Work Order has no Sales Order, or when the item is not an apparel style (no template with a Tech Pack or contract line).

For the Work Order's style × colour (colour from the variant's colour attribute), the gate lists every blocker:
1. For each sample type with gate **Required**: at least one Sample Approval for the style (and colour, when per colour) on this Sales Order or with no Sales Order.
2. Every Sample Approval of a **Required** or **If Raised** type in that scope must be Approved, Approved with Comments, or Not Required.
3. When Require PP Meeting is on: a submitted PP Meeting for the Sales Order × style, with every cutting-related action Closed.

Override: custom fields `apparel_gate_override` and `apparel_gate_override_reason` on Work Order; only the Apparel Merchandising Manager or System Manager can set them; the reason is required.

Default rules (seeded once, editable):

| Type | Gate | Per colour | Due basis | Days before |
|---|---|---|---|---|
| Proto | No | No | PCD | 90 |
| Fit | Required | No | PCD | 45 |
| Size Set | If Raised | No | PCD | 30 |
| Lab Dip | Required | Yes | PCD | 60 |
| Strike Off | If Raised | Yes | PCD | 60 |
| Desk Loom | If Raised | Yes | PCD | 60 |
| Bulk Fabric | Required | Yes | PCD | 25 |
| Bulk Trim | Required | No | PCD | 25 |
| PP | Required | No | PCD | 14 |
| Garment Test (GPT) | If Raised | No | PCD | 14 |
| TOP | No | Yes | Ex-Factory | 10 |
| Salesman | No | No | PCD | 30 |
| Photo Sample | No | No | PCD | 30 |

TOP "due 10 days before X-factory" is from the buyer PO notes.

## Desk

- **Sales Order**: Create → Factory Allocation, Sample Approval, PP Meeting; indicator with the bulk gate state; Connections show the three.
- **Work Order**: indicator listing the gate blockers.
- **Report "Sample Approval Tracker"**: one row per Sales Order × style × colour, a column per gating type (status), next due date, overdue count, gate ready Yes/No.
- **Report "Factory Load"**: allocated qty per factory and line per week of PCD.
- **Workspace "Apparel"**: new "Plan and Approve" card, two number cards (Samples with Buyer, Overdue Samples).

## Tests (`tests/test_plan_approve.py`)

- Allocation: lines pulled from the order; over-allocation rejected; line from another factory rejected; date order enforced; status Planned when complete; agent `save_allocation` round trip.
- Sample: status follows rounds; washed bulk fabric needs after-wash test; PP needs bulk fabric; GPT with a Fail row cannot pass; decision with comments needs a comment; waiver needs the manager role; due date from PCD.
- PP Meeting: submit blocked while a buyer comment is missing, an owner/date is missing, or a department is absent; closing an action closes the comment.
- Gate: Work Order blocked with the list of blockers; passes once approvals and meeting are in; manager override with reason passes.

## Open questions

1. The hosted site has a UI-made **Sample Request** doctype (6 demo records). This app uses the name **Sample Approval** so the two do not collide. Decide whether to migrate the demo records or drop them.
2. Production Card is not built (Phase C, "Make"). The PP Meeting stores its reference and issue date as plain fields for now.
3. T&A calendar is not built. Sample due dates come from the PCD in the Factory Allocation (or the contract line PCD) and the rule table. When T&A arrives, it should own these dates.
4. Tech Pack fit rounds (Phase A) overlap with Fit Sample Approvals. The Tech Pack table stays as the AI-extracted history; Sample Approval is the formal log the gate reads.

## Verification (2026-11-04)

- `bench --site apparel.localhost migrate`: clean. Seeds present: 13 sample rules, role *Apparel Merchandising Manager*, Work Order override fields.
- `bench --site apparel.localhost run-tests --app arinox_apparel`: 72 run, all pass, 1 skipped (the existing company-bank-account test).
- **Not verified:** the form scripts and the desk screens were not opened in a browser. The gate is tested by calling `before_submit` and `validate` with a stand-in Work Order document; no real Work Order (it needs a BOM) was submitted. Do this once on the dev site before relying on it.
- One change outside Phase B: `set_settings_defaults` in `setup/install.py` no longer resets a Check you turned off (it used to treat 0 as "unset" on every migrate).

## Round 2 — checked against the reference documents (2026-11-04)

The sample documents were read directly (PP Meeting format, Pilot Run, GPT report, before-wash spec sheet, shrinkage form, trims inspection, a buyer PO, fit PDFs). Gaps found and fixed. **Nothing is tied to one company**: every buyer-specific rule below is data, not code.

| Gap | Fix |
|---|---|
| PP not always required (PO: "only if requested"; fit files named `NO PP`) | New doctype **Sample Requirement**: overrides the Apparel Settings rules per Customer, Sales Order and/or Style. Most specific wins (SO+Style, SO, Customer+Style, Customer, Style), field by field; blank keeps the default. A customer rule `PP → No` removes PP from the gate and from the PP Meeting |
| TOP: in-warehouse basis, split-PO exemption, chargeback, customer samples | Due basis now PCD / Ex-Factory / **In-Warehouse** / **After Fit Approval** (offset in days). **Not Required on Split PO** (order ships to more than one destination). **Late Chargeback** amount: Sample Approval shows *Chargeback Exposure* when the sample is overdue or went out late. New type **Customer Sample**, with qty and size mix on the rule or requirement |
| Before-wash spec sheet with five samples | Sample Measurement holds Sample 1–5 per point; in tolerance only when every reading is; worst deviation shown. *Measured* stage: Before Wash / After Wash / Final |
| Shrinkage report | Bulk Fabric approvals carry **Shrinkage Readings** (per roll: before / after warp, weft, bias; % computed; torque). Settings → *Fabric Shrinkage Warning Above %* |
| Allocation grain | Factory Allocation rows can be narrowed to a **Ship To** and/or **Buyer PO** (blank = whole colour). Caps are checked per colour and per ship-to/PO. *Get Order Lines* makes one row per ship-to/PO |
| PP Meeting detail | Order qty, work order / job no, description; colour rows carry the buyer PO. **Departments are free text and set in Apparel Settings** (PP and Pilot lists), so any factory's roles work |
| Pilot Run | PP Meeting has a **Meeting Type** (PP Meeting / Pilot Run). A pilot run needs its own departments, no PP sample and no buyer comments; its open cutting actions still block bulk, but it does not count as the PP meeting being held |
| WIP milestone feed | `get_sampling_milestones(sales_order)`: per style × colour, every sample type with due date, rounds (sent / decision dates, status), chargeback exposure. For the T&A / WIP phase and the planning agent |
| Generic, not Cortex | Standard garment-test list is a setting. Phase A defaults made neutral: contract prefix `SC` (was a company prefix), no default country of origin, neutral examples |

Still not built (own phases): trims inspection report, fabric inspection (4-point), the fabric test report PDF contents (no text layer, unread), and a customer-level screen to enter requirements from the contract (they are entered in Sample Requirement).
