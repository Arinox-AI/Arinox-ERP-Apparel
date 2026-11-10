#!/usr/bin/env python3
"""A mail's documents are read — all of them (2026-11-07).

The user's report: *"I sent an email at 04:20 pm and it only read the BOM, not the tech pack."*

The tech pack was in the mail: 18.4 MB, `C9043-U70-629 - GRADE 06.02.26 UPDT.xlsx`. It never reached the tower, because
`inbound.MAX_ATTACHMENT_BYTES` was a **hardcoded 12 MB**: anything bigger was flagged `too_large` and `sync_inbox`
**skipped it without leaving a row** — so the mail looked like it had never carried a second document. Two things were
wrong and both are locked down here:

1. **The cap was a literal in the code.** It now comes from `config.MAX_ATTACHMENT_MB` (env-overridable, 40 MB default),
   because a photo-heavy tech pack is routinely 15–25 MB.
2. **A document over the cap disappeared.** It now keeps a row with its name, size and the reason, so the mail page says
   *"too large — … MB is over the N MB limit …"* instead of showing one attachment where the buyer sent two.

Also here: the file bytes are no longer duplicated into the mail row as base64 (18 MB became ~25 MB of base64 inside
SQLite), and `read_documents_again` reports, per file, what it was (BOM / tech pack) and whether it was read — a failure
is never silent again.

No network: the model is stubbed, the ERP is the fake Arinox site.

Run:  python3 tests/test_mail_documents.py
"""
from __future__ import annotations

import email.message
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"

from database import get_session, init_db                                    # noqa: E402
init_db()
import ai_nextsteps                                                          # noqa: E402
import config                                                                # noqa: E402
import deals                                                                 # noqa: E402
import inbound                                                               # noqa: E402
import functions                                                             # noqa: E402
from deal_harness import fake_erp, ADMIN                                     # noqa: E402
from models import MailAttachmentModel, MailMessageModel                     # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "BOM_C9043-U70-629.xls")

_PASS = 0
_FAIL = []


def check(name, cond, detail=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL  {name}   {detail}")


def _message(files: list[tuple[str, bytes]]) -> email.message.Message:
    m = email.message.EmailMessage()
    m["Subject"] = "Inquiry - two documents"
    m["From"] = "buyer@acme.test"
    m.set_content("Please find the tech pack and the BOM attached.")
    for name, blob in files:
        m.add_attachment(blob, maintype="application", subtype="octet-stream", filename=name)
    return m


def t_limit_from_config():
    print("\n1. The size limit is a setting, not a literal in the code")
    check("config carries the limit in bytes", isinstance(config.MAX_ATTACHMENT_BYTES, int) and config.MAX_ATTACHMENT_BYTES > 0,
          str(config.MAX_ATTACHMENT_BYTES))
    check("the default leaves room for a photo-heavy tech pack", config.MAX_ATTACHMENT_MB >= 25, f"{config.MAX_ATTACHMENT_MB} MB")
    src = open(os.path.join(ROOT, "inbound.py"), encoding="utf-8").read()
    check("inbound reads the cap from config, it does not repeat a number",
          "MAX_ATTACHMENT_BYTES = getattr(config" in src and "12 * 1024 * 1024" not in src)


def t_too_large_is_kept():
    print("\n2. A file over the cap is reported, never dropped")
    real = inbound.MAX_ATTACHMENT_BYTES
    inbound.MAX_ATTACHMENT_BYTES = 1024                       # pretend the limit is 1 KB
    try:
        msg = _message([("small.xls", b"x" * 200), ("BIG_TECHPACK.xlsx", b"y" * 5000)])
        atts = inbound._attachments(msg)
    finally:
        inbound.MAX_ATTACHMENT_BYTES = real
    sizes = {a["filename"]: a for a in atts}
    check("both attachments are seen", len(atts) == 2, str([a["filename"] for a in atts]))
    check("the small one keeps its bytes", bool(sizes["small.xls"].get("data")))
    big = sizes["BIG_TECHPACK.xlsx"]
    check("the big one is flagged, not silently gone", big.get("too_large") == 1, str(big.keys()))
    check("its name and size survive", big["size"] == 5000 and big["filename"] == "BIG_TECHPACK.xlsx", str(big))
    check("its bytes are not carried", "data" not in big)

    print("\n3. ... and it keeps a row that says why")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    mail = MailMessageModel(uid="t1", message_id="<t1@x>", from_addr="buyer@acme.test", subject="two documents",
                            body_text="see attached", received_at="2026-11-07T10:50:00+00:00", attachments="[]")
    db.add(mail)
    db.commit()
    row = functions._store_attachment(db, mail, {"filename": "BIG_TECHPACK.xlsx", "mime": "application/octet-stream",
                                                 "size": 18_400_000, "too_large": 1})
    db.commit()
    check("a row is created for it", row is not None and row.id, str(row))
    check("it says the file was too large", "too_large" in (row.error or ""), str(row.error))
    check("it names the caller's limit", f"{config.MAX_ATTACHMENT_MB} MB" in (row.error or ""), str(row.error))
    check("it has no path, so nothing pretends it was stored", not row.path, str(row.path))


def t_documents_card_data():
    print("\n4. The conversation reports what each file is and whether it was read")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Two documents")
    mail = MailMessageModel(uid="t2", message_id="<t2@x>", from_addr="buyer@acme.test", subject="two documents",
                            body_text="see attached", received_at="2026-11-07T10:50:00+00:00", attachments="[]",
                            thread_key="gm:t2", deal_id=d.id)
    db.add(mail)
    db.commit()
    d.mail_id, d.thread_key = mail.id, "gm:t2"
    db.commit()
    # attachments are only ever read from backend/data/mail/<id>/ (deals._load_bytes enforces that), so write there
    mail_dir = os.path.join(ROOT, "data", "mail", str(mail.id))
    os.makedirs(mail_dir, exist_ok=True)
    path = os.path.join(mail_dir, "t2_bom.xls")
    with open(FIXTURE, "rb") as f:
        blob = f.read()
    with open(path, "wb") as f:
        f.write(blob)
    db.add(MailAttachmentModel(mail_id=mail.id, filename="C9043-U70-629.xls", mime="application/vnd.ms-excel",
                               size=len(blob), path=os.path.relpath(path, ROOT), ok=1))
    db.add(MailAttachmentModel(mail_id=mail.id, filename="BIG_TECHPACK.xlsx", mime="application/vnd.ms-excel",
                               size=18_400_000, path="", ok=0, error="too_large — 17.6 MB is over the 40 MB limit"))
    db.commit()
    out = functions.FUNCTIONS["deal_documents"](db=db, deal_id=d.id)
    docs = {x["filename"]: x for x in out["documents"]}
    check("both files are listed", len(docs) == 2, str(list(docs)))
    check("the readable one says so", docs["C9043-U70-629.xls"]["readable"] is True)
    check("the missing one carries the reason", "too_large" in docs["BIG_TECHPACK.xlsx"]["error"],
          docs["BIG_TECHPACK.xlsx"]["error"])
    check("its size is shown for the person", docs["BIG_TECHPACK.xlsx"]["size_mb"] >= 17,
          str(docs["BIG_TECHPACK.xlsx"]["size_mb"]))


def t_read_reports_every_file():
    print("\n5. Reading again reports per file — a failure is never silent")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="read again")
    mail = MailMessageModel(uid="t3", message_id="<t3@x>", from_addr="buyer@acme.test", subject="two documents",
                            body_text="see attached", received_at="2026-11-07T10:50:00+00:00", attachments="[]")
    db.add(mail)
    db.commit()
    d.mail_id, d.thread_key = mail.id, "gm:t3"
    db.commit()
    with open(FIXTURE, "rb") as f:
        blob = f.read()
    mail_dir = os.path.join(ROOT, "data", "mail", str(mail.id))
    os.makedirs(mail_dir, exist_ok=True)
    path = os.path.join(mail_dir, "t3_bom.xls")
    with open(path, "wb") as f:
        f.write(blob)
    db.add(MailAttachmentModel(mail_id=mail.id, filename="C9043-U70-629.xls", mime="application/vnd.ms-excel",
                               size=len(blob), path=os.path.relpath(path, ROOT), ok=1))
    tp_path = os.path.join(mail_dir, "t3_techpack.txt")
    with open(tp_path, "w") as f:
        f.write("TECH PACK\nStyle: C9043-U70-629\nChest | S 20 | M 21 | L 22\n")
    db.add(MailAttachmentModel(mail_id=mail.id, filename="TECHPACK.txt", mime="text/plain", size=80,
                               path=os.path.relpath(tp_path, ROOT), ok=1))
    db.commit()

    replies = {
        "TECHPACK": json.dumps({"kind": "tech_pack", "style_no": "C9043-U70-629", "rows": [],
                                "measurements": [{"pom_code": "A", "point_of_measure": "Chest", "tolerance": 0.5,
                                                  "values": {"S": 20, "M": 21, "L": 22}}],
                                "construction_notes": "1/4\" turnback hem."}),
        ".xls": json.dumps({"kind": "bom", "style_no": "C9043-U70-629", "rows": [
            {"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
             "uom": "Yard", "consumption": 1.47}]}),
    }
    calls = []

    def fake_llm(db_, msg, timeout=120):
        for token, reply in replies.items():
            if token in msg:
                calls.append(token)
                return reply
        calls.append("?")
        return None

    saved = ai_nextsteps._llm
    ai_nextsteps._llm = fake_llm
    try:
        out = deals.read_documents_again(db, ADMIN, d.id)
    finally:
        ai_nextsteps._llm = saved
    reads = {r["file"]: r for r in out["reads"]}
    check("both files were sent to the model", len(calls) == 2, str(calls))
    check("each file says what it was", reads["C9043-U70-629.xls"]["kind"] == "bom"
          and reads["TECHPACK.txt"]["kind"] == "tech_pack", str(reads))
    check("the BOM produced lines", reads["C9043-U70-629.xls"]["rows"] == 1, str(reads["C9043-U70-629.xls"]))
    check("the tech pack produced a chart", reads["TECHPACK.txt"]["measurements"] == 1, str(reads["TECHPACK.txt"]))
    check("no file is reported as failed", not out["failed"], str(out["failed"]))
    s = json.loads(deals._get(db, d.id).styles or "[]")[0]
    check("the specification is on the style", bool(s.get("spec")), str(s.get("spec"))[:60])
    check("the BOM is on the style", len(s.get("bom") or []) == 1, str(len(s.get("bom") or [])))
    check("the timeline names what happened", any("tech pack read" in e.get("text", "")
                                                  for e in json.loads(deals._get(db, d.id).events or "[]")))

    print("\n6. A model that cannot answer is reported, not swallowed")
    saved = ai_nextsteps._llm
    ai_nextsteps._llm = lambda db_, msg, timeout=120: None
    try:
        out2 = deals.read_documents_again(db, ADMIN, d.id)
    finally:
        ai_nextsteps._llm = saved
    check("every unread file is named", len(out2["failed"]) >= 1, str(out2["failed"]))
    check("the reason says the model did not answer", any("did not answer" in f for f in out2["failed"]), str(out2["failed"]))


def main():
    if not os.path.isfile(FIXTURE):
        print(f"SKIP — the fixture is missing ({FIXTURE})")
        return 0
    print("Every document in the mail is read, and nothing is lost silently")
    t_limit_from_config()
    t_too_large_is_kept()
    t_documents_card_data()
    t_read_reports_every_file()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
