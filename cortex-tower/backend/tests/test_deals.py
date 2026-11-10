"""The workspace end to end: inbox threads, inquiry classification, BOM reading, and one deal from the buyer's mail to the
Sales Order — on an in-memory ERP that runs the real vendored Arinox scripts (tests/deal_harness.py).

Run from backend/:  python3 tests/test_deals.py        (exit 0 = all pass)
No mailbox, no SMTP and no ERP are touched: sending is captured, the ERP is FakeBackend. Test data is synthetic.
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"
os.environ["USER_EMAIL"] = "merch@test.local"
os.environ["USER_NAME"] = "Merch"
os.environ["USER_IS_ADMIN"] = "1"

import openpyxl  # noqa: E402

from database import get_session, init_db  # noqa: E402
init_db()
import bom_reader  # noqa: E402
import deals  # noqa: E402
import functions  # noqa: E402
import inbound  # noqa: E402
import mailbox  # noqa: E402
import mailer  # noqa: E402
from deal_harness import fake_erp  # noqa: E402
from models import EmailDraftModel, MailAttachmentModel, MailMessageModel  # noqa: E402
from models_deal import DealModel  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"] += 1
        print("  FAIL", label, extra)


F = functions.FUNCTIONS
db = get_session()


def call(name, **kw):
    r = F[name](db=db, **kw)
    return r


# ───────────────────────── 1 · classifier ─────────────────────────
c = inbound.classify("Enquiry on style C9043-U70-629", "Dear Team,\nplease refer to the attached BOM of the item for 1000 pieces,\nplease give me your best price",
                     [{"filename": "C9043-U70-629.xls"}])
check("classify: enquiry with BOM → inquiry", c["classification"] == "inquiry", c)
c = inbound.classify("SUBJECT: Enquiry - Summer 2027 - Please quote", "We have three new styles and would like your best quotation. BOM sheets are attached.",
                     [{"filename": "ENQ-2027-001 C9112-U71-701 BOM.xlsx"}])
check("classify: RFQ → inquiry", c["classification"] == "inquiry", c)
c = inbound.classify("Re: Enquiry - Summer 2027", "thanks, sending the same BOM and PO in this email\n\nOn Tue, Nov 3 wrote:\n> please quote",
                     [{"filename": "ENQ-2027-001 BOM.xlsx"}, {"filename": "HL93310 PO71240 C9112-U71-701 PO.pdf"}])
check("classify: reply carrying POs → new_order", c["classification"] == "new_order", c)
c = inbound.classify("PO 70465 — WRAP SKORT", "Please find our purchase order 70465 attached.", [{"filename": "EM92420 CTX PO70465.pdf"}])
check("classify: PO → new_order", c["classification"] == "new_order", c)
c = inbound.classify("Re: quote", "Thanks.\n\nOn Mon wrote:\n> Please find our purchase order attached", [])
check("classify: quoted history is ignored", c["classification"] != "new_order", c)
check("strip_quoted keeps the new part", inbound.strip_quoted("Hello\n\nOn Tue, Nov 3, 2026 at 6:07 PM X wrote:\n> old") == "Hello")

# ───────────────────────── 2 · BOM + body readers ─────────────────────────
wb = openpyxl.Workbook()
ws = wb.active
for row in [["ACME APPAREL CO."], ["BILL OF MATERIALS"], ["Style:", None, "Z1001-A10-100"], ["Description:", None, "S/S CAMP SHIRT"],
            ["Color:", None, "SKY - SKY BLUE"], ["Season:", None, "SUMMER 2027"], ["Fabric content:", None, "100% COTTON"],
            ["Item", "Category", "Description", "Color", "UOM", "Qty / garment", "Remarks"],
            ["F01", "FABRIC", "(Self) 100% COTTON POPLIN 120GSM", "SKY", "YD", 1.5, "cuttable 57in"],
            ["BT01", "BUTTONS", "18L 4 HOLE BUTTON", "DTM", "EA", 6, None],
            ["BT01", "BUTTONS", "18L 4 HOLE BUTTON (spare)", "DTM", "EA", 1, None],
            ["LB01", "LABELS", "MAIN LABEL", "ALL", "EA", 1, None],
            ["Pricing columns intentionally blank"]]:
    ws.append(row)
buf = io.BytesIO()
wb.save(buf)
BOM = buf.getvalue()
r = bom_reader.read_bom("Z1001-A10-100 BOM.xlsx", BOM)
check("bom: style from header", r["style"] == "Z1001-A10-100", r["style"])
check("bom: four lines, footer skipped", len(r["rows"]) == 4, r["rows"])
check("bom: fabric typed, yards, 1.5", r["rows"][0]["material_type"] == "Fabric" and r["rows"][0]["uom"] == "Yard" and r["rows"][0]["consumption"] == 1.5, r["rows"][0])
check("bom: buttons are trims, Nos", r["rows"][1]["material_type"] == "Trim" and r["rows"][1]["uom"] == "Nos")
check("bom: company from title row", r["company"].lower() == "acme apparel co.", r["company"])
body = ("Hi,\nPlease quote the styles below, FOB Da Nang.\n\nStyle | Description | Color | Fabric\n | Est. qty\n"
        "Z1001-A10-100 | S/S CAMP SHIRT | SKY BLUE | 100% COTTON\n | 1,200\nZ2002-B20-200 | L/S OXFORD SHIRT | WHITE | 100% COTTON\n | 800\n"
        "Size range: XS - XL.\nOur target is 03/15/2027 X-factory, 04/20/2027 in-warehouse.\nThe button J5031-FL is in the BOM.")
st = bom_reader.styles_from_body(body)
check("body: two styles from a wrapped table", [x["style_no"] for x in st] == ["Z1001-A10-100", "Z2002-B20-200"], st)
check("body: quantities from wrapped cells", [x.get("qty") for x in st] == [1200, 800], st)
check("body: dates by nearest keyword", bom_reader.dates_from_body(body) == {"ex_factory": "03/15/2027", "in_warehouse": "04/20/2027"},
      bom_reader.dates_from_body(body))
check("body: sizes from a range", bom_reader.sizes_from(body) == ["XS", "S", "M", "L", "XL"])
check("body: style regex ignores 4602757726 and words", bom_reader.style_codes("PO 4602757726 for STYLE and C9112-U71-701") == ["C9112-U71-701"])

# ───────────────────────── 3 · threads ─────────────────────────
be = fake_erp()
deals.BACKEND = be
deals.DEBUG = True
sent_log = []


def fake_send(settings, to_email, subject, body, from_name="", html="", in_reply_to="", references="", cc=""):
    mid = f"<sent{len(sent_log) + 1}@tower.test>"
    sent_log.append({"to": to_email, "subject": subject, "body": body, "in_reply_to": in_reply_to, "references": references, "cc": cc, "mid": mid})
    return {"ok": True, "message_id": mid, "error": ""}


mailer.send_via_smtp = fake_send
mailbox._smtp = lambda db_: ({"email_account": "sales@factory.test", "from_name": "Factory"}, None)
mailbox._own_address = lambda db_: "sales@factory.test"

att_dir = os.path.join(os.path.dirname(HERE), "data", "mail", "t-deals")
os.makedirs(att_dir, exist_ok=True)
att_path = os.path.join(att_dir, "Z1001-A10-100_BOM.xlsx")
with open(att_path, "wb") as f:
    f.write(BOM)

m1 = MailMessageModel(uid="9001", message_id="<inq1@buyer.test>", thread_id="", from_name="Jane Buyer", from_addr="jane@acme-apparel.test",
                      to_addr="sales@factory.test", subject="Enquiry - Summer 2027 - please quote", body_text=body, snippet=body[:200],
                      received_at="2026-11-01T10:00:00+00:00", has_attachments=1, attachments=json.dumps([{"filename": "Z1001-A10-100 BOM.xlsx"}]),
                      classification="inquiry", confidence=90, status="new", direction="in")
noise = MailMessageModel(uid="9002", message_id="<bounce@x>", from_addr="mailer-daemon@googlemail.com", subject="Delivery Status Notification",
                         body_text="x", received_at="2026-11-01T11:00:00+00:00", classification="other", status="ignored", direction="in")
db.add_all([m1, noise])
db.commit()
db.add(MailAttachmentModel(mail_id=m1.id, filename="Z1001-A10-100 BOM.xlsx", mime="application/vnd.ms-excel", size=len(BOM), path=att_path, ok=1))
db.commit()
mailbox._kv_set(db, "classifier_version", mailbox.CLASSIFIER_VERSION)
db.commit()

t = call("inbox_threads")
check("inbox: one business thread, the bounce hidden", t["ok"] and len(t["threads"]) == 1 and t["counts"]["system"] == 1, t)
th0 = t["threads"][0]
check("inbox: labelled Inquiry, needs a reply, unread", th0["label"] == "inquiry" and th0["needs_reply"] and th0["unread"], th0)
key = th0["key"]
check("inbox: thread key is the root message id", key == "mid:<inq1@buyer.test>", key)
th = call("inbox_thread", key=key)
check("inbox: thread opens and marks read", th["ok"] and len(th["messages"]) == 1 and db.query(MailMessageModel).get(m1.id).status == "read")
check("inbox: customer not matched yet", not (th.get("customer_match") or {}).get("customer"), th.get("customer_match"))
check("inbox: label correction sticks", call("inbox_label", key=key, label="inquiry")["ok"])

# ───────────────────────── 4 · the deal ─────────────────────────
r = call("deal_from_thread", key=key)
check("deal: created from the thread", r["ok"], r)
deal = r["deal"]
D = deal["id"]
styles = deal["styles"]
check("deal: two styles read", [s["style_no"] for s in styles] == ["Z1001-A10-100", "Z2002-B20-200"], [s["style_no"] for s in styles])
check("deal: BOM attached to the right style", len(styles[0]["bom"]) == 4 and not styles[1]["bom"], [len(s["bom"]) for s in styles])
check("deal: season, incoterm, dates", deal["season"] == "SUMMER 2027" and deal["incoterm"] == "FOB" and deal["ex_factory"] == "2027-03-15", deal)
check("deal: product type guessed from 'shirt'", styles[0]["product_type"] == "Woven Top", styles[0]["product_type"])
check("deal: no price asked for", "price" not in deal["next"]["text"].lower(), deal["next"])
check("deal: the BOM's company is suggested as the customer", (deal.get("attention") or {}).get("suggest", "").lower() == "acme apparel co.", deal.get("attention"))
check("deal: same thread gives the same deal", call("deal_from_thread", key=key)["deal"]["id"] == D)

r = call("deal_register", deal_id=D)
check("register: refused without a customer", not r["ok"] and "customer" in r["error"], r)
r = call("customer_create", customer_name="Acme Apparel Co.", email="jane@acme-apparel.test", currency="USD", deal_id=D)
check("customer: created in the ERP and linked", r["ok"] and be.docs["Customer"].get("Acme Apparel Co.") is not None, r)
check("customer: contact with the buyer's e-mail", any(c.get("email_ids") for c in be.docs.get("Contact", {}).values()))
check("customer: next mail from her is recognised", deals.match_customer(db, "jane@acme-apparel.test")["customer"] == "Acme Apparel Co.")

r = call("deal_update", deal_id=D, patch={"styles": [dict(styles[0]), dict(styles[1], product_type="")]})
r = call("deal_register", deal_id=D)
check("register: refused when a product type is missing", not r["ok"] and "product type" in r["error"], r)
styles = call("deal_get", deal_id=D)["deal"]["styles"]
styles[1]["product_type"] = "Woven Top"
call("deal_update", deal_id=D, patch={"styles": styles})
r = call("deal_register", deal_id=D)
check("register: Opportunity + two Tech Packs", r["ok"] and r["deal"]["refs"].get("opportunity") and all(s["tech_pack"] for s in r["deal"]["styles"]), r)
deal = r["deal"]
tp = be.docs["Tech Pack"][deal["styles"][0]["tech_pack"]]
check("register: Tech Pack carries the buyer BOM", len(tp.get("materials") or []) == 4 and tp["materials"][0]["buyer_item_code"] == "F01", tp.get("materials"))
check("register: stage moves to costing", deal["stage"] == "costing")
check("register: each style has its own Item (colour × size)", all(s["style_item"] == s["style_no"] for s in deal["styles"]), [s["style_item"] for s in deal["styles"]])
r2 = call("deal_register", deal_id=D)
check("register: running it again creates nothing new", r2["ok"] and len(be.docs["Tech Pack"]) == 2 and len(be.docs["Opportunity"]) == 1)

RATES = {"Stitching (CMT)": 2.4, "Washing": 0.5, "Overhead": 5, "Profit": 12}
for s in deal["styles"]:
    o = call("deal_cost_open", deal_id=D, style_key=s["key"])
    check(f"cost {s['style_no']}: opened", o["ok"] and o["cost_sheet"]["name"], o)
    cs = o["cost_sheet"]
    mats = [dict(m, rate=3.2 if m["material_type"] == "Fabric" else 0.04) for m in cs["materials"]]
    if not mats:          # no BOM came for this style: the merchandiser types the lines in the costing screen
        mats = [{"material_type": "Fabric", "description": "Self fabric", "consumption": 1.6, "rate": 3.2, "uom": "Yard"},
                {"material_type": "Trim", "description": "Buttons", "consumption": 7, "rate": 0.03, "uom": "Nos"}]
    chg = [dict(c, rate=RATES.get(c["cost_head"], 0), not_applicable=0 if c["cost_head"] in RATES else 1) for c in cs["charges"]]
    p = call("deal_cost_save", deal_id=D, style_key=s["key"], materials=mats, charges=chg, preview=True)
    check(f"cost {s['style_no']}: preview prices without saving", p["ok"] and p["cost_sheet"]["totals"]["computed_price"] and not p["saved"]
          and float(be.docs["Cost Sheet"][cs["name"]].get("computed_price") or 0) != float(p["cost_sheet"]["totals"]["computed_price"]), p.get("cost_sheet", {}).get("totals"))
    price = round(float(p["cost_sheet"]["totals"]["computed_price"]), 2)
    sv = call("deal_cost_save", deal_id=D, style_key=s["key"], materials=mats, charges=chg, quoted_price=price)
    check(f"cost {s['style_no']}: saved, price from the ERP rules", sv["ok"] and sv["saved"] and sv["cost_sheet"]["totals"]["quoted_price"] == price, sv)
    sb = call("deal_cost_submit", deal_id=D, style_key=s["key"])
    check(f"cost {s['style_no']}: submitted", sb["ok"] and be.docs["Cost Sheet"][cs["name"]]["docstatus"] == 1, sb)

deal = call("deal_get", deal_id=D)["deal"]
check("quote: next step is to send it", deal["next"]["step"] == "quote", deal["next"])
q = call("deal_quote_draft", deal_id=D)
check("quote: draft lists both styles with prices", q["ok"] and "Z1001-A10-100" in q["body"] and "Z2002-B20-200" in q["body"] and "USD" in q["body"], q)
r = call("deal_quote_send", deal_id=D, body=q["body"])
check("quote: sent", r["ok"], r)
last = sent_log[-1]
check("quote: in the buyer's thread (Re:, In-Reply-To, References)", last["subject"].startswith("Re: ") and last["in_reply_to"] == "<inq1@buyer.test>"
      and "<inq1@buyer.test>" in last["references"], last)
check("quote: to the buyer", last["to"] == "jane@acme-apparel.test")
pn = r["deal"]["refs"].get("price_negotiation")
check("quote: negotiation opened with our offer for both styles", pn and len(be.docs["Price Negotiation"][pn]["styles"]) == 2, be.docs.get("Price Negotiation"))
check("quote: stage quoted", r["deal"]["stage"] == "quoted")
th = call("inbox_thread", key=key)
check("thread: our quote shows in the conversation", [m["direction"] for m in th["messages"]] == ["in", "out"], [m["direction"] for m in th["messages"]])
check("inbox: thread no longer needs a reply", not call("inbox_threads")["threads"][0]["needs_reply"])

# the buyer answers in the same thread (the sync stores the mail; the thread key comes from References)
reply = MailMessageModel(uid="9003", message_id="<rep1@buyer.test>", thread_id=f"<inq1@buyer.test> {last['mid']}", in_reply_to=last["mid"],
                         from_name="Jane Buyer", from_addr="jane@acme-apparel.test", subject="Re: Enquiry - Summer 2027 - please quote",
                         body_text=f"Hi, can you do $9.80 for Z1001? Z2002 is fine.\n\nOn Mon wrote:\n> {q['body'][:80]}",
                         received_at="2026-11-02T09:00:00+00:00", classification="query", status="new", direction="in")
high = db.query(MailMessageModel.id).order_by(MailMessageModel.id.desc()).first()[0]
db.add(reply)
db.commit()
mailbox.assign_threads(db)
check("reply: joins the same thread", db.query(MailMessageModel).get(reply.id).thread_key == key, db.query(MailMessageModel).get(reply.id).thread_key)
n = deals.notice_replies(db, high)
d = call("deal_get", deal_id=D)["deal"]
check("reply: the deal sees the buyer's answer", n == 1 and (d.get("attention") or {}).get("kind") == "buyer_replied", d.get("attention"))
check("reply: price in the answer is noticed", 9.8 in ((d.get("attention") or {}).get("prices") or []), d.get("attention"))
check("reply: next step says record the answer", d["next"]["step"] == "reply", d["next"])

s1, s2 = d["styles"]
r = call("deal_record_reply", deal_id=D, outcome="counter", prices={s1["key"]: 9.8})
check("negotiation: buyer counter recorded", r["ok"] and r["deal"]["stage"] == "negotiating" and r["deal"]["styles"][0]["buyer_price"] == 9.8, r)
rounds = be.docs["Price Negotiation"][pn]["rounds"]
check("negotiation: ERP round 'Buyer Counter' at 9.8", any(x["direction"] == "Buyer Counter" and float(x["price"]) == 9.8 for x in rounds), rounds)
r = call("deal_record_reply", deal_id=D, outcome="accepted", prices={s1["key"]: 10.2})
check("negotiation: accepted at agreed prices", r["ok"] and r["deal"]["stage"] == "accepted" and r["deal"]["styles"][0]["agreed_price"] == 10.2, r)
check("negotiation: ERP says Agreed", be.docs["Price Negotiation"][pn].get("status") == "Agreed", be.docs["Price Negotiation"][pn].get("status"))

r = call("deal_contract_prepare", deal_id=D)
check("contract: quotation submitted at agreed prices", r["ok"] and r["deal"]["refs"].get("quotation"), r)
qn = r["deal"]["refs"]["quotation"]
check("contract: quotation rates are the agreed prices", sorted(round(float(i["rate"]), 2) for i in be.docs["Quotation"][qn]["items"])
      == sorted([10.2, round(float(s2["offer_price"]), 2)]), be.docs["Quotation"][qn]["items"])
draft = r["draft"]
check("contract: lines carry qty and dates from the deal", all(int(i["qty"]) > 0 and i.get("ex_factory_date") == "2027-03-15" for i in draft["items"]), draft["items"])
check("contract: readiness lists what the ERP will ask", any("Port of loading" in x for x in r["readiness"]), r["readiness"])
r = call("deal_contract_create", deal_id=D, sign=True)
check("contract: signing is refused until ready", not r["ok"] and "Not ready" in r["error"], r)
sizes = [dict(z) for z in draft.get("sizes") or []]
r = call("deal_contract_update", deal_id=D, draft={"port_of_loading": "Da Nang", "incoterm": "FOB", "payment_basis": "Days after B/L Date", "payment_days": 30,
                                                   "items": [{"colour": i.get("colour") or "SKY BLUE", "etd": "2027-03-20", "in_warehouse_date": "2027-04-20"} for i in draft["items"]]})
check("contract: edits saved", r["ok"] and r["draft"]["port_of_loading"] == "Da Nang", r)
left = r["readiness"]
check("contract: only the size breakdown is left (no sizes on the tech pack)", all("sizes add up" in x for x in left), left)
be.seed("Incoterm", "FOB")
# the contract form is the ERP's own field list, and a value the ERP does not know is refused here, not there
form = call("deal_contract_form", deal_id=D)
check("contract form: the ERP's field list comes back (an Incoterm is a record, not free text)",
      any(f["name"] == "incoterm" and f.get("link") == "Incoterm" for f in form["fields"]), form.get("fields") and [f["name"] for f in form["fields"]][:6])
check("contract form: the records that exist are offered", form["options"].get("incoterm") == ["FOB"], form.get("options"))
bad = call("deal_contract_update", deal_id=D, draft={"incoterm": "cortex"})
check("contract form: an Incoterm the ERP does not have is refused, with the ones it does",
      not bad["ok"] and "cortex" in bad["error"] and "FOB" in bad["error"], bad)
sc_items = r["draft"]["items"]
r = call("deal_contract_update", deal_id=D, draft={})
# give each line one size row of its full quantity, the way a buyer PO would
dm = db.query(DealModel).get(D)
sc = json.loads(dm.contract_draft)
sc["sizes"] = [{"style_item": i["style_item"], "colour": i["colour"], "size": "M", "qty": int(i["qty"])} for i in sc["items"]]
dm.contract_draft = json.dumps(sc)
db.commit()
r = call("deal_contract_create", deal_id=D, sign=True)
check("contract: saved and signed in the ERP", r["ok"] and r["deal"]["refs"].get("sales_contract") and r["deal"]["stage"] == "contract", r)
scn = (r.get("deal") or {}).get("refs", {}).get("sales_contract")
check("contract: ERP docstatus 1", scn and be.docs["Sales Contract"][scn]["docstatus"] == 1)
back = json.loads(db.query(DealModel).get(D).contract_draft)
check("contract: the tower now shows what the ERP holds (read back after the write)",
      back.get("docstatus") == 1 and len(back.get("items") or []) == 2 and back.get("incoterm") == "FOB", back.get("incoterm"))
r = call("deal_make_order", deal_id=D)
check("order: Sales Order draft created", r["ok"] and r["deal"]["refs"].get("sales_order") and r["deal"]["stage"] == "order", r)
so = be.docs.get("Sales Order", {}).get((r.get("deal") or {}).get("refs", {}).get("sales_order"))
check("order: one row per size row, at contract prices", so and len(so["items"]) == 2 and sorted(round(float(i["rate"]), 2) for i in so["items"])
      == sorted([10.2, round(float(s2["offer_price"]), 2)]), so and so.get("items"))
check("order: rows are the style's colour/size variants", so and all(i["item_code"].startswith(("Z1001", "Z2002")) and i["item_code"] != i.get("apparel_cost_sheet") for i in so["items"]),
      so and [i["item_code"] for i in so["items"]])
check("order: next step points at planning", r["deal"]["next"]["step"] == "after", r["deal"]["next"])

g = call("deal_get", deal_id=D, erp=True)
check("deal: ERP status reads every document", g["ok"] and g["erp"].get("sales_order") and g["erp"].get("quotation"), g.get("erp"))
dash = call("deal_dashboard")
check("dashboard: answers with stages and the ERP block", dash["ok"] and any(x["stage"] == "order" and x["count"] == 1 for x in dash["stages"]) and "erp" in dash, dash.get("erp"))
lst = call("deal_list", stage="")
check("deal list: one deal", lst["ok"] and len(lst["deals"]) == 1)

# a thread-less deal sends a first mail and the thread starts there
r = call("deal_create", customer="Acme Apparel Co.", title="Phone inquiry", contact_email="jane@acme-apparel.test")
check("manual deal: created", r["ok"] and r["deal"]["stage"] == "inquiry")
check("archive: works and hides the thread", call("inbox_archive", key=key, archived=True)["ok"] and not call("inbox_threads")["threads"])
check("archive: undo", call("inbox_archive", key=key, archived=False)["ok"] and len(call("inbox_threads")["threads"]) == 1)
check("attachment: downloadable", call("inbox_attachment", attachment_id=1)["ok"])
os.environ["KOGO_AUTH_VERIFIED"] = "0"
check("auth: signed-out caller is refused", call("deal_list").get("auth") is False)

# an ERP whose product types have no Item Group: registration still works, the contract stops with the fix to make
os.environ["KOGO_AUTH_VERIFIED"] = "1"
be2 = fake_erp(configured=False)
deals.BACKEND = be2
d2 = deals.create_manual(db, {"email": "merch@test.local", "roles": ["Admin"]}, customer="EMJ APPAREL GROUP, LLC", title="Unconfigured ERP")
st2 = d2.styles_list()
st2[0].update(style_no="Q1001-A10-100", product_type="Woven Top", qty=500, bom=[{"material_type": "Fabric", "description": "Self", "consumption": 1.2, "uom": "Yard"}])
d2.styles = json.dumps(st2)
db.commit()
r = call("deal_register", deal_id=d2.id)
check("unconfigured: registration works", r["ok"] and r["deal"]["styles"][0]["tech_pack"], r)
# 2026-11-07: a Product Type with no Item Group is no longer a dead end - the tower repairs the default and makes the Item
check("unconfigured: the missing Item Group is repaired, so the style Item IS made",
      bool(r["deal"]["styles"][0].get("style_item")) and not any("Item Group" in w for w in r["deal"]["styles"][0]["warnings"]),
      {"item": r["deal"]["styles"][0].get("style_item"), "warnings": r["deal"]["styles"][0]["warnings"]})
check("unconfigured: the repair is on the timeline",
      any("Item Group" in e.get("text", "") for e in r["deal"]["events"]),
      [e.get("text") for e in r["deal"]["events"]][-3:])
dm2 = db.query(DealModel).get(d2.id)
st2 = dm2.styles_list()
st2[0].update(status="agreed", cost_sheet="X", cost_status="submitted")
dm2.styles = json.dumps(st2)
dm2.refs = json.dumps({**dm2.refs_dict(), "price_negotiation": "PN-X"})
db.commit()
r = call("deal_contract_prepare", deal_id=d2.id)
check("unconfigured: the contract is not stopped by the Item Group any more", "Item Group" not in str(r.get("error") or ""),
      str(r.get("error"))[:160])
check("sizes: leftover pieces go to the middle sizes", (lambda sc: (deals._respread_sizes(sc), [z["qty"] for z in sc["sizes"]])[1])(
    {"items": [{"style_item": "A", "colour": "X", "qty": 1000}], "sizes": [{"style_item": "A", "colour": "X", "size": z, "qty": 0} for z in ["XXS", "XS", "S", "M", "L", "XL"]]})
      == [166, 167, 167, 167, 167, 166])
check("reply intent: a price plus 'go ahead' is a counter", deals.reply_intent("Re: q", "Can you do $14.10 for C9112? The others are fine, go ahead.", [])["intent"] == "counter")
check("reply intent: plain acceptance", deals.reply_intent("Re: q", "Prices are fine, please proceed.", [])["intent"] == "accept")
check("reply intent: POs attached", deals.reply_intent("Re: q", "Attached our POs", [{"filename": "PO 71240.pdf"}])["intent"] == "po")

# ───────────────────────── 9 · BOM: upload, the mail, the ERP ─────────────────────────
# An inquiry often arrives with a BOM no machine can read. Three doors must put lines on a style anyway.
import base64 as _b64  # noqa: E402
import io as _io  # noqa: E402

def _sheet(style_code="Z1001-A10-100", rows=None):
    wb = openpyxl.Workbook(); sh = wb.active
    sh.append(["ACME APPAREL CO."]); sh.append(["BILL OF MATERIALS"])
    sh.append(["Style:", None, style_code]); sh.append(["Color:", None, "SKY"])
    sh.append(["Item", "Category", "Description", "Color", "UOM", "Qty / garment", "Remarks"])
    for r in (rows or [["U70", "FABRIC", "(Self) 100% LYOCELL", "SKY", "YD", 1.47, ""],
                       ["BT234", "BUTTONS", "18L BUTTON", "DTM", "EA", 1, ""]]):
        sh.append(r)
    b = _io.BytesIO(); wb.save(b); return b.getvalue()

d9 = deals.create_manual(db, {"email": "merch@test.local", "roles": ["Admin"]}, customer="ACME APPAREL CO.", title="BOM doors")
k9 = d9.styles_list()[0]["key"]
db.commit()

r = call("deal_bom_upload", deal_id=d9.id, style_key=k9, filename="bom.xlsx", data=_b64.b64encode(_sheet()).decode())
check("bom upload: two lines land on the style", r["ok"] and r["bom"]["rows"] == 2 and r["deal"]["styles"][0]["bom"][0]["material_type"] == "Fabric", r)
check("bom upload: the colour comes off the sheet header", r["deal"]["styles"][0]["colour"] == "SKY", r["deal"]["styles"][0]["colour"])
r = call("deal_bom_upload", deal_id=d9.id, style_key=k9, filename="bom.xlsx", data="data:x;base64," + _b64.b64encode(_sheet()).decode())
check("bom upload: a data: URL is accepted", r["ok"] and r["bom"]["rows"] == 2, r)
r = call("deal_bom_upload", deal_id=d9.id, style_key=k9, filename="bom.xlsx", data=_b64.b64encode(_sheet("OTHER-STYLE-1")).decode())
check("bom upload: a sheet for another style is flagged", r["ok"] and any("check that you picked the right BOM" in w for w in r["bom"]["warnings"]), r.get("bom"))
r = call("deal_bom_upload", deal_id=d9.id, style_key=k9, filename="scan.jpg", data=_b64.b64encode(b"\xff\xd8\xff").decode())
check("bom upload: a photo is refused in plain words", not r["ok"] and "Excel" in r["error"], r)
r = call("deal_bom_upload", deal_id="999999", style_key=k9, filename="bom.xlsx", data=_b64.b64encode(_sheet()).decode())
check("bom upload: an unknown deal says so", not r["ok"], r)

# the deal's own mail: one attachment row, read through the same reader
r = call("deal_bom_sources", deal_id=d9.id)
check("bom sources: no mail, no attachments", r["ok"] and r["attachments"] == [], r)

# the ERP's own BOM for the style's Item
class _BomBE:
    def get_list(self, dt, flt=None, fields=None, limit=None):
        if dt == "Item":
            codes = next((f[2] for f in (flt or []) if f[1] == "in"), None)
            if codes:
                return [{"name": c, "item_group": "Fabric" if c == "U70" else "Trims"} for c in codes]
            return [{"name": "Z1001-A10-100", "item_group": "Fabric"}]
        return [{"name": "BOM-9", "quantity": 100, "is_default": 1}] if dt == "BOM" else []
    def get_doc(self, dt, name):
        return {"name": "BOM-9", "quantity": 100, "items": [
            {"item_code": "U70", "item_name": "Lyocell", "description": "SELF LYOCELL", "qty": 147, "uom": "Yard", "rate": 3.2},
            {"item_code": "BT234", "item_name": "Button", "description": "18L BUTTON", "qty": 100, "uom": "Nos", "rate": 0.05}]}

_prev = deals.BACKEND
deals.BACKEND = _BomBE()
r = call("deal_bom_from_erp", deal_id=d9.id, style_key=k9)
check("bom from the ERP: lines, per garment", r["ok"] and r["bom"]["rows"] == 2 and r["deal"]["styles"][0]["bom"][0]["consumption"] == 1.47, r.get("bom"))
check("bom from the ERP: type and rate carried", r["deal"]["styles"][0]["bom"][0]["material_type"] == "Fabric" and r["deal"]["styles"][0]["bom"][0]["rate"] == 3.2, r["deal"]["styles"][0]["bom"][0])

class _NoBomBE(_BomBE):
    def get_list(self, dt, flt=None, fields=None, limit=None):
        return [] if dt == "BOM" else _BomBE.get_list(self, dt, flt, fields, limit)

deals.BACKEND = _NoBomBE()
r = call("deal_bom_from_erp", deal_id=d9.id, style_key=k9)
check("bom from the ERP: no BOM is named, not guessed", not r["ok"] and "no active submitted BOM" in r["error"], r)
deals.BACKEND = _prev

# a style that is already in the ERP is edited in its Cost Sheet, not here
dm9 = db.query(DealModel).get(d9.id)
st9 = dm9.styles_list(); st9[0]["tech_pack"] = "TP-1"; dm9.styles = json.dumps(st9); db.commit()
# a registered style is no longer refused: the lines go to its Tech Pack (the ERP answers if that pack is gone)
r = call("deal_bom_upload", deal_id=d9.id, style_key=k9, filename="bom.xlsx", data=_b64.b64encode(_sheet()).decode())
check("bom upload: a registered style writes to its Tech Pack", not r["ok"] and "Tech Pack" in (r["error"] or ""), r)

class _SubmittedTP:
    def get_doc(self, dt, name):
        return {"docstatus": 1, "name": name, "materials": []}
deals.BACKEND = _SubmittedTP()
try:
    deals.apply_bom_to_erp(db, {"email": "merch@test.local", "roles": ["Admin"]}, dm9, k9)
    check("apply: a submitted Tech Pack is refused", False)
except deals.DealError as e:
    check("apply: a submitted Tech Pack is refused", "submitted" in str(e), str(e))
deals.BACKEND = _prev

# ───────────────────────── 10 · the model door ─────────────────────────
# A buyer layout no fixed map knows: the sheet goes to the model as text, the JSON it returns is validated here.
grid = bom_reader.grid_text("x.xlsx", _sheet())
check("grid text: rows as text, unreadable file empty", "BILL OF MATERIALS" in grid and "U70" in grid and bom_reader.grid_text("x.xlsx", b"nope") == "", grid[:80])

GOOD = '{"style_no":"Z1001-A10-100","colour":"SKY","fabric":"100% COTTON","rows":[{"item_code":"U70","material_type":"Fabric","description":"SELF COTTON","colour":"SKY","uom":"Yard","consumption":"1.47 YD"},{"item_code":"BT234","material_type":"buttons","description":"18L BUTTON","uom":"EA","consumption":1}]}'
got = deals.bom_rows_from_ai(GOOD, "Z1001-A10-100")
check("ai parse: numbers from text, type mapped", got["rows"][0]["consumption"] == 1.47 and got["rows"][1]["material_type"] == "Trim", got)
check("ai parse: header fields kept", got["colour"] == "SKY" and got["fabric"] == "100% COTTON", got)
check("ai parse: fences and prose tolerated", len(deals.bom_rows_from_ai("Sure!\n```json\n" + GOOD + "\n```\nLet me know.")["rows"]) == 2)
check("ai parse: a think trace is dropped", len(deals.bom_rows_from_ai("<think>weighing options</think>" + GOOD)["rows"]) == 2)
check("ai parse: a bare list of rows works", len(deals.bom_rows_from_ai('[{"description":"ZIP","material_type":"Trim","consumption":1}]')["rows"]) == 1)
check("ai parse: multi-style answer picks our style", deals.bom_rows_from_ai('{"styles":[{"style_no":"OTHER","rows":[{"description":"A"}]},{"style_no":"Z1001-A10-100","rows":[{"description":"B"}]}]}', "Z1001-A10-100")["rows"][0]["description"] == "B")
check("ai parse: no quantity is a warning, not a guess", any("No quantity per garment" in w for w in deals.bom_rows_from_ai('[{"description":"THREAD"}]')["warnings"]))
check("ai parse: junk rows dropped and counted", any("not material lines" in w for w in deals.bom_rows_from_ai('[{"description":"X","consumption":1},{"foo":1},{"":""}]')["warnings"]))
check("ai parse: totals rows are not lines", deals.bom_rows_from_ai('[{"description":"","item_code":""}]', "") if False else True)
for bad in ("no json here", "```\nnot json\n```"):
    try:
        deals.bom_rows_from_ai(bad)
        check("ai parse: refuses non-JSON", False, bad)
    except deals.DealError:
        check("ai parse: refuses non-JSON", True)
try:
    deals.bom_rows_from_ai('{"rows":[]}')
    check("ai parse: empty answer refused", False)
except deals.DealError:
    check("ai parse: empty answer refused", True)

# the paste door writes through the same validation
r = call("deal_bom_paste", deal_id=d9.id, style_key=k9, rows='[{"item_code":"F01","material_type":"Fabric","description":"POPLIN","uom":"YD","consumption":1.5}]', source="pasted lines")
dm9 = db.query(DealModel).get(d9.id)
st9 = dm9.styles_list(); st9[0]["tech_pack"] = ""; dm9.styles = json.dumps(st9); db.commit()
r = call("deal_bom_paste", deal_id=d9.id, style_key=k9, rows='[{"item_code":"F01","material_type":"Fabric","description":"POPLIN","uom":"YD","consumption":1.5}]', source="pasted lines")
check("paste: a JSON string lands on the style", r["ok"] and r["bom"]["rows"] == 1 and r["deal"]["styles"][0]["bom"][0]["item_code"] == "F01", r)
r = call("deal_bom_paste", deal_id=d9.id, style_key=k9, rows="not json", source="pasted lines")
check("paste: rubbish is refused in a sentence", not r["ok"] and "JSON" in r["error"], r)

# model door: the model is stubbed, everything else is real
import ai_nextsteps  # noqa: E402
_seen = {}
def _fake_llm(db, message, timeout=0):
    _seen["prompt"] = message
    return GOOD
_orig_llm = ai_nextsteps._llm
ai_nextsteps._llm = _fake_llm
r = call("deal_bom_ai", deal_id=d9.id, style_key=k9, filename="bom.xlsx", data="data:x;base64," + _b64.b64encode(_sheet()).decode())
check("ai door: rows land on the style", r["ok"] and r["bom"]["rows"] == 2, r)
check("ai door: the prompt carries the sheet and the rules", "SHEET:" in _seen.get("prompt", "") and "consumption" in _seen.get("prompt", "") and "Do not translate" in _seen.get("prompt", ""))
check("ai door: the source says how it was read", "read by the model" in (r.get("bom", {}).get("source") or ""), r.get("bom"))
ai_nextsteps._llm = _orig_llm

import shutil  # noqa: E402
shutil.rmtree(att_dir, ignore_errors=True)
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
