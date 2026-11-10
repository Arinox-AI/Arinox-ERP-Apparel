"""Backfill `mail_chain` for mail already in the store, and re-plan the runs that need it.

    python3 backfill_chain.py            # dry run: show what would change
    python3 backfill_chain.py --apply    # write the chain rows and rebuild the plans

Idempotent. It only ever ADDS a chain row or rebuilds a stored PLAN; it never touches
a record the ERP holds and never changes an approval.
"""

from __future__ import annotations

import json
import sys

import chain as C
import database
import functions as F
import intake as _intake
import intake_exec as X
from models import IntakeRunModel, MailChainModel, MailMessageModel


CHAIN_CLASSES = ("new_order", "order_amendment", "invoice", "remittance")


def _is_conversation(db, mail) -> bool:
    """Was anything BUSINESS read out of this mail?

    The signal is the intake run, not the attachment: a screenshot of a bank statement is
    an attachment too, and it is not a deal (2026-11-03).
    """
    if (mail.status or "") == "ignored":
        return False
    if db.query(IntakeRunModel).filter(IntakeRunModel.mail_id == mail.id).first():
        return True
    return (mail.classification or "") in CHAIN_CLASSES


def main() -> int:
    apply = "--apply" in sys.argv
    database.init_db()
    db = database.get_session()

    mails = db.query(MailMessageModel).order_by(MailMessageModel.id).all()
    # A conversation is mail that carries something: an attachment, an order reference, or
    # a business classification. "Money gone on 6th September" is in this mailbox, but it is
    # not a deal and does not deserve a chain (2026-11-03).
    unplaced = [m for m in mails if not m.chain_id and _is_conversation(db, m)]
    print(f"mail rows {len(mails)} · without a chain {len(unplaced)}")
    made = 0
    for mail in unplaced:
        if apply:
            row = C.attach(db, mail)
        else:
            row = C.find(db, references=mail.thread_id, own_id=mail.message_id)
        made += 0 if row else 1
        print(f"  mail {mail.id:<4} {(mail.subject or '')[:52]:54} -> chain {(row.id if row else 'new')}")
    if not apply:
        print("\ndry run — nothing written (add --apply)")

    runs = db.query(IntakeRunModel).order_by(IntakeRunModel.id).all()
    replanned = 0
    for run in runs:
        facts = json.loads(run.facts or "{}")
        matches = json.loads(run.matches or "{}")
        chain_row = C.newest_for_run(db, run)
        if chain_row is not None:
            if apply and run.chain_id != chain_row.id:
                run.chain_id = chain_row.id
                db.commit()
            matches["chain"] = C.context(db, chain_row.id)
            if chain_row.customer and not matches.get("customer"):
                matches["customer"] = chain_row.customer

        # An approved run's plan is HISTORY: re-deriving it against today's ERP would show
        # "create the style" for a style that approval already created. Only runs still
        # waiting for a decision are re-planned here; an approved one is reopened on
        # purpose first (`reopen_intake`), which refuses when real records were made.
        if run.status == "approved":
            continue

        route = _intake.route(facts, matches)
        plan = X.build_plan(facts, matches)
        changed = (route != run.route) or (json.dumps(plan, sort_keys=True) !=
                                           json.dumps(json.loads(run.plan or "[]"), sort_keys=True))
        if changed:
            replanned += 1
            blocked = [s for s in plan if s.get("status") == "blocked"]
            print(f"  run #{run.id} ({run.status}) {run.route} -> {route}: "
                  f"{len(plan)} step(s), {len(blocked)} blocked")
            for s in plan:
                flag = "BLOCKED" if s.get("status") == "blocked" else "ready  "
                print(f"      {flag} {s['label']} {('\u2014 ' + (s.get('reason') or '')) if s.get('reason') else ''}")
            if apply:
                run.route = route
                run.matches = json.dumps(matches, default=str)
                run.plan = json.dumps(plan, default=str)
                db.commit()
    if apply:
        orphans = 0
        for row in db.query(MailChainModel).all():
            if not db.query(MailMessageModel).filter(MailMessageModel.chain_id == row.id).first():
                db.delete(row)
                orphans += 1
        db.commit()
        if orphans:
            print(f"  removed {orphans} chain(s) with no mail in them")
    print(f"\nruns {len(runs)} · re-planned {replanned}"
          + ("" if apply else "  (dry run — nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
