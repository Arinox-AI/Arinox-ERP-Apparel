"""Regression tests for the mail chain — the edge cases that made an enquiry a dead end.

Run:  python3 tests/test_chain.py

Design: a throw-away SQLite file (``data/test_chain.db``), no network, no ERP writes.
``erp.erp_get`` is stubbed where ``match()`` would read the instance, and SMTP is never
touched — ``send_chain_reply`` is asserted up to the confirmation gate, which is the
point at which a human has to say yes.

What is asserted
    A · enquiry plan   a buyer who is not in the ERP gets a Customer step — the Opportunity
                       is no longer unrunnable, and the block has an exit
    B · candidate gate  a 60-85 % name match stops the run and asks, instead of forking the
                       buyer into two Customer records
    C · thread         a reply joins the chain it answers (References / In-Reply-To), a new
                       subject does not, and our own answer carries the headers that keep
                       the buyer's reply in the thread
    D · route          a follow-up in a live chain is a chain reply, not a second enquiry;
                       a PO inside the same thread is still a PO
    E · pack           an attachment that reads as a pack becomes a ready ingest step; a
                       mail with no attachment is a blocked step with a reason
    F · reply          no SMTP without confirm=1, an ungrounded number is refused and named,
                       and the buyer's address is required
    G · ingest         refuses without a Customer / without the file / when the builder is
                       missing — it never reports success without a record name
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "data", "test_chain.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ["DB_PATH_OVERRIDE"] = DB

import database                                                          # noqa: E402
database.init_db()

import chain as C                                                        # noqa: E402
import erp                                                               # noqa: E402
import functions as F                                                    # noqa: E402
import intake                                                            # noqa: E402
import intake_exec as X                                                  # noqa: E402
import pack_ingest                                                       # noqa: E402
from models import (EmailDraftModel, IntakeRunModel, MailChainModel,      # noqa: E402
                    MailMessageModel)

db = database.get_session()

passed = failed = 0


def ok(cond, what, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"   ok   {what}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"   FAIL {what}" + (f"  [{detail}]" if detail else ""))


# ── the ERP reads intake.match() would make ──────────────────────────────────
CUSTOMERS = [{"name": "Bella Dahl", "customer_name": "Bella Dahl", "email_id": "po@belladahl.com"}]


def _match(row, filters):
    """Just enough of a filter engine for the stubs: [field, op, value] equality/like."""
    for f in filters or []:
        if not isinstance(f, (list, tuple)) or len(f) != 3:
            return False
        field, op, value = f
        got = row.get(field.split(".")[-1])
        if op == "=" and str(got) != str(value):
            return False
        if op == "like" and str(value).strip("%").lower() not in str(got).lower():
            return False
    return True


def fake_erp_get(dt, fields=None, filters=None, limit=None, order=None):
    """A stub that HONOURS the filter: a dedupe check that ignores filters would 'find' a
    record for every buyer and link the wrong Customer (it did, on 2026-11-03)."""
    if dt == "Customer":
        return [c for c in CUSTOMERS if _match(c, filters)]
    if dt == "Customer Group":
        return [{"name": "Commercial", "is_group": 0}]
    if dt == "Territory":
        return [{"name": "Rest Of The World", "is_group": 0}]
    if dt == "Payment Terms Template":
        return [{"name": "15 Days ROG"}]
    if dt == "Company":
        return [{"name": "CORTEX FASHION (HK) LIMITED"}] if _match({"name": "CORTEX FASHION (HK) LIMITED"}, filters) else []
    return []


erp.erp_get = fake_erp_get                                          # noqa: F811


def enquiry_facts(buyer="HARBOR & LANE APPAREL CO.", email="buyer@harborlane.com"):
    return {
        "document_type": "enquiry",
        "buyer": {"name": buyer, "email": email, "country": "United States"},
        "po": {"number": None},
        "style": {"code": "C9533-U71-725", "fabric_code": "U71"},
        "commercial": {"currency": None, "rate": None, "total_qty": 3100},
        "ship_date": "2027-02-11",
        "asks": ["Please send your quote by 11/09/2026."],
        "missing": ["po number", "currency", "rate"],
        "confidence": {},
    }


def fresh_matches(facts):
    return {"customer": None, "customer_created": False, "customer_candidates": [],
            "po_existing": None, "style_item": None, "style_variants": [],
            "fabric_item": None, "currency_rate": None, "warnings": [], "blocking": []}


print("\nA · the enquiry plan has an exit when the buyer is not in the ERP")
facts = enquiry_facts()
m = fresh_matches(facts)
plan = X.build_plan(facts, m)
keys = [s["key"] for s in plan]
ok(keys[0] == "customer", "the Customer step comes first", ", ".join(keys))
ok(plan[0]["status"] == "ready", "the Customer step is ready (not blocked)")
ok(plan[0]["payload"].get("customer_name") == "HARBOR & LANE APPAREL CO.",
   "it carries the buyer name read from the mail")
opp = next(s for s in plan if s["key"] == "opportunity")
ok(opp["status"] == "ready", "the Opportunity is runnable — it was the dead end before")
ok(opp.get("depends_on") == "customer", "and it is declared as depending on the Customer")
ok("create the Customer first" not in json.dumps(plan),
   "the old dead-end reason is gone from the plan")
ok(any(s["key"] == "costing" for s in plan), "the costing task is still there")

print("\nA2 · a buyer already on file reuses it, and creates no Customer")
facts2 = enquiry_facts("Bella Dahl", "po@belladahl.com")
m2 = fresh_matches(facts2)
m2["customer"] = "Bella Dahl"
plan2 = X.build_plan(facts2, m2)
ok(plan2[0]["kind"] == "reuse", "the Customer step is a reuse", plan2[0]["kind"])
ok(plan2[0]["payload"].get("existing") == "Bella Dahl", "of the Customer already there")
ok(next(s for s in plan2 if s["key"] == "opportunity")["payload"]["party_name"] == "Bella Dahl",
   "and the Opportunity is addressed to it")

print("\nA3 · a name that is a word, not a company, cannot become a Customer")
for bad in ("estimate", "Buyer", "n/a", ""):
    st = X._step_customer({"buyer": {"name": bad}}, fresh_matches({}))
    ok(st["status"] == "blocked", f'"{bad}" is refused, not created', st.get("reason"))
ok(X._buyer_name_problem("HARBOR & LANE APPAREL CO.") == "",
   "a real company name passes", X._buyer_name_problem("HARBOR & LANE APPAREL CO."))
ok(X._buyer_name_problem("Nordic Retail AB") == "", "so does a short one")
ok(X._step_customer({"buyer": {"name": "estimate"}}, fresh_matches({}))["payload"] == {},
   "nothing is written for a name the reader got wrong")

print("\nB · a 60-85 % name match asks, it does not fork the buyer")
facts3 = enquiry_facts("Bella Dahl Inc")
m3 = fresh_matches(facts3)
m3["customer_candidates"] = [{"name": "Bella Dahl", "score": 0.72}]
plan3 = X.build_plan(facts3, m3)
cust3 = plan3[0]
ok(cust3["status"] == "blocked", "the Customer step blocks instead of creating a twin")
ok("Bella Dahl" in (cust3.get("reason") or ""), "and it names the candidate", cust3.get("reason"))
ok(cust3["payload"] == {}, "nothing is written while the question is open")

print("\nC · the thread is the identity")
m_in = MailMessageModel(id=1, uid="1", message_id="a@x", thread_id="", from_addr="buyer@harborlane.com",
                        from_name="Buyer", subject="Quote C9533", received_at="2026-10-30T09:00:00")
db.add(m_in)
db.commit()
ch1 = C.attach(db, m_in)
ok(ch1 is not None and ch1.key == "a@x", "a first mail starts a chain on its own id", ch1.key if ch1 else "")

m_reply = MailMessageModel(id=2, uid="2", message_id="b@x",
                           thread_id="<a@x> <zz@cortex>", from_addr="buyer@harborlane.com",
                           from_name="Buyer", subject="RE: Quote C9533",
                           received_at="2026-10-31T09:00:00")
db.add(m_reply)
db.commit()
ch2 = C.attach(db, m_reply)
ok(ch2.id == ch1.id, "a reply with a References header joins it", f"{ch1.id} vs {ch2.id}")

m_other = MailMessageModel(id=3, uid="3", message_id="c@x", thread_id="",
                           from_addr="someone@else.com", from_name="Other", subject="RE: Quote C9533",
                           received_at="2026-10-31T10:00:00")
db.add(m_other)
db.commit()
ch3 = C.attach(db, m_other)
ok(ch3.id != ch1.id, "the SAME subject from another sender does not join it", f"chain {ch3.id}")

hdrs = C.reply_headers(db, ch1)
ok(hdrs["in_reply_to"] == "b@x", "our reply answers the last mail the BUYER sent", hdrs["in_reply_to"])
ok(hdrs["references"].startswith("<a@x>") and "<b@x>" in hdrs["references"],
   "and references the whole chain, oldest first", hdrs["references"][:70])

C.note_outbound(db, ch1, "out1@cortex")
m_back = MailMessageModel(id=4, uid="4", message_id="d@x", thread_id="<a@x> <b@x> <out1@cortex>",
                          from_addr="buyer@harborlane.com", from_name="Buyer",
                          subject="RE: Quote C9533", received_at="2026-11-02T09:00:00")
db.add(m_back)
db.commit()
ok(C.attach(db, m_back).id == ch1.id, "the buyer's answer to OUR message lands in the same chain")

print("\nC2 · the reply that must NOT start a new conversation")
ok(F._reply_subject("SUBJECT: Enquiry - Summer 2027 - C9533 - Please quote")
   == "Re: SUBJECT: Enquiry - Summer 2027 - C9533 - Please quote",
   "the buyer's subject is kept EXACTLY — even a literal 'SUBJECT:' — so the client threads on it",
   F._reply_subject("SUBJECT: Enquiry - Summer 2027 - C9533 - Please quote"))
ok(F._reply_subject("Re: Fwd: Re: PO 69785") == "Re: PO 69785",
   "but a real reply chain collapses to one Re:", F._reply_subject("Re: Fwd: Re: PO 69785"))
ok("\n" not in F._reply_subject("a\r\n b"), "and a line break can never reach the header")

# a reply with NO reference headers (some clients strip them) still joins by sender+subject
bare = MailMessageModel(id=9, uid="9", message_id="bare@x", thread_id="",
                        from_addr="buyer@harborlane.com", from_name="Buyer",
                        subject="Re: Quote C9533", received_at="2026-11-02T18:00:00")
db.add(bare); db.commit()
ok(C.attach(db, bare).id == ch1.id,
   "a reply with no In-Reply-To/References joins on the same sender + same subject")
other_sender = MailMessageModel(id=10, uid="10", message_id="os@x", thread_id="",
                                from_addr="someone@else.com", from_name="Other",
                                subject="Re: Quote C9533", received_at="2026-11-02T18:30:00")
db.add(other_sender); db.commit()
ok(C.attach(db, other_sender).id != ch1.id,
   "…but a different sender on the same subject does not")

print("\nD · a follow-up in a live chain is a reply, not a second deal")
db.add(IntakeRunModel(mail_id=1, route="enquiry", status="approved", chain_id=ch1.id,
                      facts="{}", matches="{}", plan="[]", summary="enquiry"))
db.commit()
ctx = C.context(db, ch1.id)
ok(ctx["live"] is True, "the chain reports itself live")
f_reply = enquiry_facts()
f_reply["document_type"] = "other"
ok(intake.route(f_reply, {"chain": ctx}) == "chain_reply",
   "a follow-up with no document of its own is a chain reply")
f_po = enquiry_facts()
f_po["document_type"] = "purchase_order"
ok(intake.route(f_po, {"chain": ctx}) == "new_order",
   "but a PO in the same thread is still a PO")
ok(intake.route(enquiry_facts(), {}) == "enquiry", "and with no chain an enquiry is an enquiry")

print("\nE · the pack the thread was waiting for")
f_pack = {"_attachment_id": 7, "_attachment_name": "C9533 tech pack.xlsx",
          "_pack_words": ["tech pack", "bom"], "style": {"code": "C9533-U71-725"}}
step = X._steps_pack_ingest(f_pack, {"customer": "HARBOR & LANE", "chain": {"opportunity": "CRM-OPP-1"}})[0]
ok(step["status"] == "ready" and step["kind"] == "ingest_pack", "a readable pack is a ready step")
ok(step["payload"]["attachment_id"] == 7 and step["payload"]["opportunity"] == "CRM-OPP-1",
   "the step carries the file and the opportunity it belongs to")
step_none = X._steps_pack_ingest({"style": {"code": "C9533-U71-725"}}, {})[0]
ok(step_none["status"] == "blocked", "no attachment is a blocked step, not a silence",
   step_none.get("reason"))
ok(X.pack_words("invoice.pdf", "application/pdf", "total 1,200.00 USD") == [],
   "an invoice reads as no pack at all")
ok("measurement" in X.pack_words("C9533.xlsx", "", "POM MEASUREMENT SIZE XS S M"),
   "a measurement sheet does")
f_reply_plan = X.build_plan({"style": {"code": "C9533"}}, {"chain": {"live": True}})
ok([s["key"] for s in f_reply_plan] == ["pack", "ack"],
   "a chain reply plans the pack and the answer", ", ".join(s["key"] for s in f_reply_plan))

print("\nF · replying from the Tower")
r = F.send_chain_reply(db, chain_id=ch1.id, body="Dear buyer,\n\nHere is our offer.",
                       enforce_grounding=1)
ok(r.get("status") == "confirmation_required",
   "no SMTP without confirm=1 — the draft is made, nothing leaves", r.get("status"))
ok(r.get("conformation_required") or r.get("confirmation_required") is True,
   "and it says so explicitly")
last_from_buyer = (db.query(MailMessageModel)
                   .filter(MailMessageModel.chain_id == ch1.id,
                           MailMessageModel.from_addr == "buyer@harborlane.com")
                   .order_by(MailMessageModel.id.desc()).first())
ok((r.get("draft") or {}).get("in_reply_to") == last_from_buyer.message_id.strip("<>"),
   "the draft answers the LAST mail the BUYER sent",
   f'{(r.get("draft") or {}).get("in_reply_to")} vs {last_from_buyer.message_id}')
r2 = F.send_chain_reply(db, chain_id=ch1.id, subject="Re: Quote C9533",
                        body="We can do 3,100 pcs at USD 12.40.", enforce_grounding=1)
ok(r2.get("error") == "ungrounded", "with enforce_grounding=1 a figure not on the record is refused",
   r2.get("error"))
ok(any("12.40" in str(u) for u in (r2.get("unsourced") or [])),
   "and the offending number is named", str(r2.get("unsourced")))

# by default a human's own figures are INFORMED, not blocked: the reply quotes a price that
# does not exist in any record yet, which is the normal case for an enquiry (2026-11-03)
r2b = F.send_chain_reply(db, chain_id=ch1.id, subject="Re: Quote C9533",
                         body="We can do 3,100 pcs at USD 12.40.", enforce_grounding=0)
ok(r2b.get("status") == "confirmation_required",
   "by default the figures are reported and the send still asks for confirmation", r2b.get("status"))
ok(any("12.40" in str(u) for u in (r2b.get("unsourced") or [])),
   "the same figure is named, without blocking", str(r2b.get("unsourced")))

listy = F.send_chain_reply(db, chain_id=ch1.id, subject="Re: Quote C9533",
                           body="Payment: 1. 30% deposit\n2. 70% before shipment", enforce_grounding=0)
ok(not any(str(u).strip(".") == "1" for u in (listy.get("unsourced") or [])),
   "an ordered-list marker is markup, not a figure that needs sourcing",
   str(listy.get("unsourced")))

nope = F.send_chain_reply(db, chain_id=ch1.id, subject="Re: Quote",
                          body="Sent from the Control Tower.")
ok(nope.get("error") == "names_the_platform",
   "naming the platform in a buyer email is refused outright — that is a mistake, not a figure",
   nope.get("error"))

empty = db.query(MailChainModel).filter(MailChainModel.id == ch3.id).first()
empty.buyer_email = ""
db.commit()
r3 = F.send_chain_reply(db, chain_id=ch3.id, body="hello")
ok(r3.get("error") == "no_buyer_address", "a chain with no address cannot be answered", r3.get("error"))

print("\nG · the ingest never claims success it cannot prove")
no_cust = pack_ingest.ingest({"path": os.path.abspath(__file__), "customer": ""})
ok(not no_cust["ok"] and "Customer" in no_cust["note"], "no Customer → refused", no_cust["note"][:70])
no_file = pack_ingest.ingest({"path": "/nope/x.xlsx", "customer": "Bella Dahl"})
ok(not no_file["ok"] and "not on disk" in no_file["note"], "no file → refused", no_file["note"][:60])
already = pack_ingest.ingest({"path": os.path.abspath(__file__), "customer": "Bella Dahl",
                              "already": ["BTP-2026-00002"]})
ok(already["ok"] and already.get("skipped"), "already ingested → skipped, not duplicated twice",
   already["note"][:70])
ing = F.ingest_chain_pack(db, run_id=1)
ok(ing.get("error") == "no_attachment", "a run with no file cannot be ingested", ing.get("error"))

print("\nH · the chain finds what it produced")
row = db.query(MailChainModel).filter(MailChainModel.id == ch1.id).first()
C.link(db, row, "Opportunity", "CRM-OPP-2026-00070")
C.link(db, row, "Customer", "HARBOR & LANE APPAREL CO.")
db.commit()
ok(row.opportunity == "CRM-OPP-2026-00070", "the Opportunity is on the chain")
ok(row.customer == "HARBOR & LANE APPAREL CO.", "so is the Customer it created")
tl = C.timeline(db, row)
# three inbound, plus every draft this conversation wrote (sent or still a draft)
ins = db.query(MailMessageModel).filter(MailMessageModel.chain_id == ch1.id).count()
outs = db.query(EmailDraftModel).filter(EmailDraftModel.chain_id == ch1.id).count()
ok(len(tl) == ins + outs, "the timeline is every mail in and every reply out",
   f"{len(tl)} rows = {ins} in + {outs} out")
ok(all(t["dir"] == "in" for t in tl[:ins]) and all(t["dir"] == "out" for t in tl[ins:]),
   "the mails first, then our replies", ",".join(t["dir"] for t in tl))

print("\nJ · the pipeline itself: a reply that carries the pack")
from models import MailAttachmentModel                                    # noqa: E402

PACK_TEXT = """C9533-U71-725  S/S CAMP COLLAR SHIRT
TECH PACK  SEASON: SUMMER 2027
MEASUREMENT SPEC
POM      DESC                    TOL    XS     S      M      L      XL
T100     CHEST WIDTH             ±0.25  20.0   21.0   22.0   23.0   24.0
T130     FRONT LENGTH            ±0.375 26.0   27.0   28.0   29.0   30.0
BOM
U71      LINEN LYOCELL 55/45     180GSM   1.85 YD
"""
m_pack = MailMessageModel(id=5, uid="5", message_id="e@x", thread_id="<a@x> <b@x> <out1@cortex>",
                          from_addr="buyer@harborlane.com", from_name="Buyer",
                          subject="RE: Quote C9533 — tech pack and BOM attached",
                          received_at="2026-11-02T12:00:00", has_attachments=1,
                          attachments=json.dumps([{"filename": "C9533 tech pack.xlsx"}]))
db.add(m_pack)
db.commit()
att = MailAttachmentModel(mail_id=m_pack.id, filename="C9533 tech pack.xlsx",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          size=4096, sha256="abc123", path="", parser="openpyxl", pages=1,
                          chars=len(PACK_TEXT), ok=1, text=PACK_TEXT)
db.add(att)
db.commit()
run_pack = F._understand_mail(db, m_pack, [att], use_llm=False)
ok(run_pack is not None, "the reply opened a card — a one-line mail with a pack is worth one")
if run_pack is not None:
    ok(run_pack.route == "chain_reply", "on the chain_reply route, not a second enquiry", run_pack.route)
    plan_pack = json.loads(run_pack.plan or "[]")
    ok([s["key"] for s in plan_pack][-1] == "ack" and plan_pack[0]["key"].startswith("pack"),
       "it plans the pack(s) and the answer", ", ".join(s["key"] for s in plan_pack))
    step_pack = plan_pack[0]
    ok(step_pack["status"] == "ready" and step_pack["kind"] == "ingest_pack",
       "the pack step is ready to press", f"{step_pack['status']}/{step_pack.get('kind')}")
    ok((step_pack.get("payload") or {}).get("attachment_id") == att.id,
       "and it points at the file that arrived", str((step_pack.get("payload") or {}).get("attachment_id")))
    ok(run_pack.chain_id == ch1.id, "the run carries the chain", str(run_pack.chain_id))

print("\nI · what actually goes on the wire")
import smtplib                                                          # noqa: E402
import mailer                                                           # noqa: E402


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, pw):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


_real_smtp = smtplib.SMTP
smtplib.SMTP = FakeSMTP
try:
    wire = mailer.send_via_smtp({"email_account": "me@cortex.test", "password": "x", "use_tls": 1},
                                "buyer@harborlane.com", "Re: Quote C9533", "body",
                                "Cortex Textile", in_reply_to="b@x",
                                references="<a@x> <b@x>")
finally:
    smtplib.SMTP = _real_smtp
msg = FakeSMTP.sent[-1] if FakeSMTP.sent else None
ok(wire.get("ok") is True, "the transport reports ok against a stub server")
ok(msg is not None and msg["In-Reply-To"] == "<b@x>", "In-Reply-To is the message being answered",
   msg["In-Reply-To"] if msg else "")
ok(msg is not None and msg["References"] == "<a@x> <b@x>", "References is the whole thread",
   msg["References"] if msg else "")
ok(msg is not None and "b@x" not in (msg["Message-ID"] or ""), "our own Message-ID is new — never the one we answer")
FakeSMTP.sent.clear()
smtplib.SMTP = FakeSMTP
try:
    mailer.send_via_smtp({"email_account": "me@cortex.test", "password": "x", "use_tls": 1},
                         "me@cortex.test", "SMTP test", "hi")
finally:
    smtplib.SMTP = _real_smtp
plain = FakeSMTP.sent[-1]
ok(plain["In-Reply-To"] is None and plain["References"] is None,
   "a mail with no thread headers adds none — the SMTP test is unchanged")

# a buyer's subject can carry a line break — and `msg["Subject"] = ...` then raises before
# any socket is opened, which is how a send died silently on 2026-11-03
FakeSMTP.sent.clear()
smtplib.SMTP = FakeSMTP
try:
    nl = mailer.send_via_smtp({"email_account": "me@cortex.test", "password": "x", "use_tls": 1},
                              "buyer@harborlane.com",
                              "Re: SUBJECT: Enquiry - Summer 2027 - C9112 / C9208 / C9533 - Please quote\r\n (DDP Los Angeles)",
                              "body")
finally:
    smtplib.SMTP = _real_smtp
one = FakeSMTP.sent[-1] if FakeSMTP.sent else None
ok(nl.get("ok") is True and one is not None, "a subject with a line break still sends")
ok(one is not None and "\n" not in str(one["Subject"]) and "\r" not in str(one["Subject"]),
   "and the header on the wire is ONE line", str(one["Subject"])[:70] if one else "")
ok(one is not None and "(DDP Los Angeles)" in str(one["Subject"]),
   "with nothing dropped — only the break collapsed")

print("\nK · approving an enquiry creates the Customer FIRST and the Opportunity points at it")
made: list[dict] = []


def fake_create(doctype, data):
    made.append({"doctype": doctype, **data})
    name = {"Customer": "CUST-0009", "Opportunity": "CRM-OPP-2026-00071",
            "Task": "TASK-2026-00009"}.get(doctype, f"{doctype}-X")
    return True, {"name": name}, ""


_real_create = erp.erp_create
erp.erp_create = fake_create                                        # noqa: F811
try:
    # a buyer that does not exist on the site yet: the create path, not the link path
    facts_k = enquiry_facts("KESTREL OUTFITTERS LTD", "buyer@kestrel.example")
    matches_k = fresh_matches(facts_k)
    matches_k["company"] = "CORTEX FASHION (HK) LIMITED"
    # not `live`: a first enquiry in a fresh chain is an enquiry. A follow-up in a live chain
    # is a chain_reply on purpose — the word "quote" alone must not spawn a second Opportunity.
    matches_k["chain"] = {"id": ch1.id, "live": False, "opportunity": "", "customer": ""}
    plan_k = X.build_plan(facts_k, matches_k)
    run_k = IntakeRunModel(mail_id=m_pack.id, route="enquiry", status="understood",
                           chain_id=ch1.id, facts=json.dumps(facts_k),
                           matches=json.dumps(matches_k), plan=json.dumps(plan_k),
                           summary="enquiry", created_refs="[]")
    db.add(run_k)
    db.commit()
    res = X.execute(db, run_k, actor="test")
finally:
    erp.erp_create = _real_create                                   # noqa: F811

order = [m["doctype"] for m in made]
ok(order[:2] == ["Customer", "Opportunity"], "the Customer is created before the Opportunity",
   " → ".join(order))
cust = next((m for m in made if m["doctype"] == "Customer"), {})
ok(cust.get("customer_name") == "KESTREL OUTFITTERS LTD", "with the name off the mail",
   cust.get("customer_name"))
opp_k = next((m for m in made if m["doctype"] == "Opportunity"), {})
ok(opp_k.get("party_name") == "CUST-0009",
   "and the Opportunity's party is the Customer this same approval created", opp_k.get("party_name"))
ok(res.get("status") == "approved", "the approval reports itself approved", res.get("status"))
row_k = db.query(MailChainModel).filter(MailChainModel.id == ch1.id).first()
ok(row_k.opportunity == "CRM-OPP-2026-00071", "the opportunity is on the chain",
   row_k.opportunity)
ok(row_k.customer == "CUST-0009", "so is the customer", row_k.customer)

print(f"\n{'=' * 70}\n  {passed} passed · {failed} failed\n{'=' * 70}")
if os.path.exists(DB):
    os.remove(DB)
sys.exit(1 if failed else 0)
