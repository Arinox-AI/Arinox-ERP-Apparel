"""Re-open the intake cards for mail that carries MORE THAN ONE document.

    python3 backfill_documents.py            # dry run: say what each mail carries
    python3 backfill_documents.py --apply    # open one card per document

Why: until 2026-11-03 the intake read the single biggest attachment of a mail, so a mail
carrying three POs and three BOMs produced one card and dropped two orders and every BOM
without saying anything. The reader is fixed; this re-opens the cards on mail that is
already stored.

Idempotent — a run is keyed on (mail, document hash), so re-running cannot duplicate one.
It writes intake runs only; nothing is sent to the ERP.
"""

from __future__ import annotations

import json
import sys

import database
import functions as F
import intake as I
from models import IntakeRunModel, MailAttachmentModel, MailMessageModel


def main() -> int:
    apply = "--apply" in sys.argv
    database.init_db()
    db = database.get_session()

    mails = db.query(MailMessageModel).order_by(MailMessageModel.id).all()
    multi = 0
    for mail in mails:
        atts = db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == mail.id).all()
        readable = [a for a in atts if a.ok and a.text and a.chars >= 120]
        if not readable:
            continue
        kinds = {a.id: I.doc_kind(a.text or "", a.filename or "") for a in readable}
        docs = [k for k in kinds.values() if k != "other"]
        if len(docs) < 2:
            continue
        multi += 1
        print(f"\nmail {mail.id}: {(mail.subject or '')[:60]}")
        for a in readable:
            print(f"    {kinds[a.id]:14} {a.filename}")
        if not apply:
            continue
        made = F._open_document_runs(db, mail, atts, use_llm=False)
        mail.document_count = len(made)
        db.commit()
        for r in made:
            print(f"    -> run {r.id}: {r.route:11} {r.summary}")

    if not apply:
        print(f"\n{multi} mail(s) carry more than one document — dry run, nothing written "
              "(add --apply)")
    else:
        runs = db.query(IntakeRunModel).count()
        print(f"\n{multi} mail(s) re-read · {runs} intake run(s) in the queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
