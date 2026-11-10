#!/usr/bin/env python3
"""Seed the intake queue from a real document — for a demo, and for re-testing.

It puts a mail into the local inbox **exactly as IMAP would have left it** (same
row shape, same attachment bytes, same storage path), then runs the production
pipeline on it: read the attachment → understand → match → plan.

It does **not** send an email and does **not** write to the ERP. Approval stays
where it belongs: in the app, by a human.

    # a real client PO from Drive
    python3 seed_intake_demo.py \
        --pdf "../../data/arinox_new/ARINOX ERP DOCS/1 - Merchandising/10 - Client Purchase Order/EM92420 12.11.25 CTX C7540-S99-304 PO70465.pdf" \
        --from-name "EMJ Apparel Group — Order Desk" \
        --from-addr "customerservice@belladahl.com" \
        --subject "PO 70465 — C7540-S99-304 WRAP SKORT" \
        --body "Please find our PO 70465 attached. Ship window is on the PO."

    python3 seed_intake_demo.py --list        # what is already in the queue
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import database                                                            # noqa: E402
import functions                                                           # noqa: E402
import inbound                                                             # noqa: E402
from models import MailMessageModel                                        # noqa: E402

DEFAULT_BODY = """Dear Team,

Please find our purchase order attached.

Kindly confirm the ship window and the lab dip date.

Regards,
Order Desk
"""


def seed(pdf: str, from_name: str, from_addr: str, subject: str, body: str,
         use_llm: bool = True) -> dict:
    data = open(pdf, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    db = database.SessionLocal()

    uid = f"demo-{sha[:12]}"
    mail = db.query(MailMessageModel).filter(MailMessageModel.uid == uid).first()
    if not mail:
        mail = MailMessageModel(
            uid=uid,
            message_id=f"<demo.{sha[:16]}@intake.local>",
            thread_id="",
            from_name=from_name,
            from_addr=from_addr,
            to_addr="cortex@gmail.com",
            subject=subject,
            snippet=(body or "")[:280],
            body_text=body,
            received_at=datetime.now(timezone.utc).isoformat(),
            has_attachments=1,
            attachments=json.dumps([{"filename": os.path.basename(pdf),
                                     "mime": "application/pdf", "size": len(data)}]),
            classification=inbound.CLASS_NEW_ORDER,
            confidence=90,
            reasons=json.dumps(["seeded from a real document (demo)"]),
            po_refs=json.dumps([]),
            status="new",
        )
        db.add(mail)
        db.commit()
        db.refresh(mail)

    import base64
    att = {"filename": os.path.basename(pdf), "mime": "application/pdf",
           "size": len(data), "data": base64.b64encode(data).decode("ascii")}
    stored = functions._store_attachment(db, mail, att)
    run = functions._understand_mail(db, mail, [stored], use_llm=use_llm)
    mail.route = run.route if run else ""
    mail.intake_status = run.status if run else "skipped"
    db.commit()
    return {"mail_id": mail.id, "run_id": run.id if run else None,
            "attachment": stored.to_dict(), "run": run}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--from-name", default="Order Desk")
    ap.add_argument("--from-addr", default="orders@example.com")
    ap.add_argument("--subject", default="New purchase order")
    ap.add_argument("--body", default=DEFAULT_BODY)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        db = database.SessionLocal()
        out = functions.get_intake_queue(db, limit=50)
        print(f"{out['count']} intake card(s)")
        for i in out["items"]:
            print(f"  #{i['id']:<3} {i['route']:<10} {i['status']:<12} {i['summary']}")
        return

    if not args.pdf:
        ap.error("--pdf is required (or use --list)")
    res = seed(os.path.abspath(args.pdf), args.from_name, args.from_addr,
               args.subject, args.body, use_llm=not args.no_llm)
    a = res["attachment"]
    print(f"mail #{res['mail_id']} → run #{res['run_id']}")
    print(f"  attachment : {a['filename']} · {a['parser']} · {a['chars']} chars "
          f"· ok={a['ok']} needs_ocr={a['needs_ocr']} {a['error'] or ''}")
    run = res["run"]
    if not run:
        print("  no intake card opened (not an order document)")
        return
    d = json.loads(run.facts or "{}")
    m = json.loads(run.matches or "{}")
    print(f"  route      : {run.route} ({run.document_type})")
    print(f"  summary    : {run.summary}")
    print(f"  buyer      : {(d.get('buyer') or {}).get('name')} → matched {m.get('customer')}")
    print(f"  po         : {(d.get('po') or {}).get('number')} dated {(d.get('po') or {}).get('date')}")
    c = d.get("commercial") or {}
    print(f"  commercial : {c.get('total_qty')} pcs · {c.get('currency')} {c.get('rate')} "
          f"· {c.get('incoterm') or ''} · value {c.get('total_value')}")
    print(f"  ship       : {d.get('ship_date')}")
    print(f"  missing    : {d.get('missing')}")
    for s in json.loads(run.plan or "[]"):
        print(f"    {s['seq']}. {s['label']}  [{s['status']}]  {(s.get('reason') or '')[:80]}")


if __name__ == "__main__":
    main()
