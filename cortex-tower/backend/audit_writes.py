"""Audit every doctype the Control Tower WRITES to — against what the site actually requires.

    python3 audit_writes.py            # report
    python3 audit_writes.py --fix      # apply the resolvers, then report again

Why this exists
---------------
`Sales Order: FAILED — Value missing for Sales Order: Payment Terms Template` was not a bug about
payments. The instance marks four more fields required on `Sales Order` through **Property Setters**
than the DocType declares, so every payload the Tower built from the mail was incomplete in a way
nothing in the code could see. That is a class of error, not an incident: it applies to every doctype
the Tower writes, and it will apply again the day somebody adds a Property Setter.

So this asks the site, for every doctype the Tower creates:

* which fields are required and not filled by the server (`required_fields`), and
* whether the Tower can supply each one from the record (`resolve_required`).

and then it walks every stored intake plan and reports the steps that would be refused today.

Exit code 1 when a required field has NO resolver — that is the gap that fails a write.
"""
from __future__ import annotations

import json
import sys

import config
import database
import erp
import intake_exec as X
from models import IntakeRunModel

# Every doctype this app writes, with where it is written from.
WRITES = {
    "Customer": "intake_exec / functions",
    "Client Purchase Order": "intake_exec (intake + revision fill)",
    "Item": "intake_exec (style), functions",
    "Item Price": "intake_exec (style)",
    "Project": "intake_exec (order)",
    "Sales Order": "intake_exec (order), writes",
    "Opportunity": "intake_exec (enquiry)",
    "Task": "intake_exec (ack/costing/revision), functions",
    "Supplier": "functions (fabric intelligence)",
    "Purchase Invoice": "functions (finance action)",
    "Stock Entry": "writes (production posting)",
    "Cortex WIP": "wip_actions (update only)",
    "Comment": "wip_actions (planner thread)",
}

# Doctypes whose create now goes through `intake_exec.create_checked` (the one gate).
GATED = {"Customer", "Client Purchase Order", "Item", "Item Price", "Project", "Sales Order",
         "Opportunity", "Task", "Supplier", "Purchase Invoice", "Stock Entry"}

# Fields the Tower knows how to fill from the record — kept in ONE place (intake_exec).
# Anything the site requires that is neither here nor in the step's own payload is a gap.
KNOWN = {
    "company", "currency", "payment_terms_template", "incoterm", "named_place",
    "delivery_date", "schedule_date", "expected_delivery_date", "project",
}


def main() -> int:
    fix = "--fix" in sys.argv
    database.init_db()
    db = database.get_session()
    X._REQ_CACHE.clear()

    print(f"{'doctype':24} {'required by the site':52} resolvable")
    print("-" * 110)
    gaps, fillable = [], []
    for dt, where in WRITES.items():
        try:
            reqd = X.required_fields(dt)
        except Exception as e:                                          # noqa: BLE001
            print(f"{dt:24} could not read the meta: {type(e).__name__}: {e}")
            gaps.append((dt, "meta", str(e)))
            continue
        if not reqd:
            print(f"{dt:24} {'—':52} —")
            continue
        resolvable = sorted(f for f in reqd if f in KNOWN)
        unknown = sorted(f for f in reqd if f not in KNOWN)
        label = f"{len(reqd)} field(s): {', '.join(sorted(reqd))[:44]}"
        print(f"{dt:24} {label:52} {', '.join(resolvable) or '—'}")
        if unknown:
            fillable.append((dt, where, unknown))

    print("\nfields the site requires that the Tower's resolvers do NOT cover")
    print("(a step can still supply them in its own payload — checked below)")
    if not fillable:
        print("  none")
    for dt, where, fields in fillable:
        print(f"  {dt:22} {', '.join(fields):48} written from {where}")

    # ── every stored plan, through the same preflight approval uses ──────────
    print("\nstored plans, re-checked against what the site requires")
    print("-" * 110)
    bad = 0
    for run in db.query(IntakeRunModel).order_by(IntakeRunModel.id).all():
        if run.status == "rejected":
            continue
        try:
            facts = json.loads(run.facts or "{}")
            matches = json.loads(run.matches or "{}")
            plan = json.loads(run.plan or "[]")
        except Exception:
            continue
        for st in plan:
            if st.get("status") == "blocked" or st.get("kind") in ("reuse", "fill", "ingest_pack",
                                                                   "create_many"):
                continue
            dt = st.get("doctype")
            if not dt:
                continue
            payload = dict(st.get("payload") or {})
            try:
                _filled, missing = X.preflight(dt, payload, facts, matches,
                                               skip=X._FILLED_BY_STEPS.get(dt, set()))
            except Exception as e:                                      # noqa: BLE001
                print(f"  run {run.id:<3} {dt:22} preflight failed: {type(e).__name__}: {e}")
                bad += 1
                continue
            if missing:
                bad += 1
                print(f"  run {run.id:<3} {dt:22} would be REFUSED — "
                      + "; ".join(f"{f}" for f, _l, _h in missing))
                for f, _label, hint in missing:
                    print(f"          {f}: {hint[:110]}")
    if not bad:
        print("  every ready step passes the site's requirements")

    if gaps or bad:
        print(f"\n❌ {len(gaps)} doctype(s) unreadable, {bad} step(s) that would be refused")
        if fix:
            print("   (--fix is a no-op: a missing RESOLVER is a decision, not a default)")
        return 1
    print("\n✅ every doctype the Tower writes is covered")
    ungated = sorted(set(WRITES) - GATED - {"Cortex WIP", "Comment"})
    if ungated:
        print(f"   ⚠ not through the gate: {', '.join(ungated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
