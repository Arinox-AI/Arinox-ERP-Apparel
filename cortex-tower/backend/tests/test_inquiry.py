"""Regression tests for the buyer-enquiry register — the edge cases behind "it did not sit anywhere".

Run:  python3 tests/test_inquiry.py

No network, no ERP writes. The ERP reads the history needs are stubbed with a fabricated
pool, so the verdicts are asserted against known records instead of whatever the instance
happens to hold today.

What is asserted
    A · styles      the client's real shapes are read; trim codes, EM order numbers and a
                    button reference inside a description are not
    B · dates       an ambiguous 11/09/2026 is read month-first for a US buyer and day-first
                    for a German one, and both readings are reported
    C · verdicts    made / costed / on file / new, with the price we last sold it at, and a
                    FAILED read reported as "unknown", never as "none"
    D · lines       quantity is claimed for one style; several styles with no split leave the
                    per-style quantity unknown instead of dividing by guesswork
    E · register    one row per enquiry, a follow-up in the same thread does not open a
                    second one, the status moves and the summary counts
    F · opportunity the styles reach the Opportunity as line rows, priced from history
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "data", "test_inquiry.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ["DB_PATH_OVERRIDE"] = DB

import database                                                          # noqa: E402
database.init_db()

import erp                                                               # noqa: E402
import functions as F                                                    # noqa: E402
import inquiry                                                           # noqa: E402
import intake_exec                                                       # noqa: E402
from models import BuyerInquiryModel, IntakeRunModel, MailMessageModel    # noqa: E402

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


print("\nA · the style codes, and the things that look like one")
ok(inquiry.styles_in("C9533-U71-725") == ["C9533-U71-725"], "a compound style")
ok(inquiry.styles_in("C9112 / C9208 / C9533") == ["C9112", "C9208", "C9533"], "bare styles in a subject")
ok(inquiry.styles_in("GGI-26-SS-131") == ["GGI-26-SS-131"], "the season-in-the-middle form")
ok(inquiry.styles_in("C9533-U71-725 and C9533") == ["C9533-U71-725"],
   "the bare code is dropped when the full one is there")
ok(inquiry.styles_in("FUS004 TH000 BT301 LB030 ST022 CL004 ST019 PT001 PB010") == [],
   "trim and material codes are not styles", str(inquiry.styles_in("FUS004 TH000 BT301")))
ok(inquiry.styles_in("EM92409 PO 69785") == [], "an EM order number and a PO number are not styles")
comp = inquiry.styles_for_mail(
    "Enquiry - Summer 2027 - C9112 / C9208 / C9533 - Please quote", "DDP Los Angeles",
    "C9112-U71-701 C9208-U71-712 C9533-U71-725 BT234 BUTTONS 18L 4 HOLE HORN BTN (#J5031-FL)")
ok(comp == ["C9112-U71-701", "C9208-U71-712", "C9533-U71-725"],
   "the pack COMPLETES a bare code, and does not add its own material references", " / ".join(comp))

print("\nB · a date written 11/09/2026 is two different days")
us = inquiry.read_date("11/09/2026", "United States")
ok(us["iso"] == "2026-11-09" and us["convention"] == "m/d/y",
   "read month-first for a US buyer", f'{us["iso"]} ({us["convention"]})')
de = inquiry.read_date("11/09/2026", "Germany")
ok(de["iso"] == "2026-09-11" and de["convention"] == "d/m/y",
   "day-first for a German one", f'{de["iso"]} ({de["convention"]})')
ok(us["other"] == "2026-09-11" and us["ambiguous"],
   "and both readings are kept, so the card can show what it did not choose")
ok(inquiry.read_date("02/11/2027", "United States")["iso"] == "2027-02-11",
   "the ship date reads the same way as the quote date")
ok(inquiry.read_date("25/12/2026", "United States")["iso"] == "2026-12-25",
   "an impossible month still reads as day-first", inquiry.read_date("25/12/2026", "US")["convention"])
ok(inquiry.read_date("9 Nov 2026")["iso"] == "2026-11-09", "a written month is never ambiguous")

print("\nC · what we already know about a style")
POOL = {
    "errors": [],
    "items": [
        {"name": "C2027-S84-304", "has_variants": 1, "item_group": "Finished Garments",
         "stock_uom": "Garment", "disabled": 0},
        {"name": "C2027-S84-304-S", "has_variants": 0}, {"name": "C2027-S84-304-M", "has_variants": 0},
        {"name": "C7540-S99-304", "has_variants": 0, "item_group": "Finished Garments",
         "stock_uom": "Garment", "disabled": 0},
        {"name": "C9051-U70-654", "has_variants": 1, "item_group": "Finished Garments",
         "stock_uom": "Garment", "disabled": 0},
    ],
    "prices": [{"item_code": "C9051-U70-654-S", "price_list_rate": 13.6, "currency": "USD",
                "valid_from": "2026-10-30"}],
    "costs": [{"name": "CS-2026-00069", "buyer_style_ref": "C2027-S84-304", "customer": "Bella Dahl",
               "total_fob": 16.3, "locked_fob": 16.3, "status": "Draft"}],
    "boms": [{"name": "BOM-C2027-S84-304-S-001", "item": "C2027-S84-304-S", "is_active": 1, "docstatus": 1},
             {"name": "BOM-C2027-S84-304-M-001", "item": "C2027-S84-304-M", "is_active": 1, "docstatus": 1}],
    "packs": [{"name": "BTP-2026-00002", "style_no": "C2027-S84-304", "pack_revision": "2025-11-05",
               "status": "Received"}],
    "orders": [
        {"name": "SAL-ORD-2026-00052", "customer": "Bella Dahl", "transaction_date": "2026-10-30",
         "status": "Draft", "currency": "USD",
         "items": [{"item_code": "C2027-S84-304-S", "qty": 500, "rate": 16.3, "amount": 8150},
                   {"item_code": "C2027-S84-304-M", "qty": 500, "rate": 16.3, "amount": 8150}]},
        {"name": "SAL-ORD-2026-00045", "customer": "Bella Dahl", "transaction_date": "2026-10-28",
         "status": "Cancelled", "currency": "USD",
         "items": [{"item_code": "C7540-S99-304", "qty": 250, "rate": 23.0, "amount": 5750}]},
    ],
}

made = inquiry.history("C2027-S84-304", POOL)
ok(made["verdict"] == "made", "a style with an order line is 'made before'", made["verdict"])
ok(made["last_price"] == 16.3 and made["currency"] == "USD", "with the price we last sold it at",
   str(made["last_price"]))
ok(made["last_order"]["sales_order"] == "SAL-ORD-2026-00052", "and which order it was",
   made["last_order"]["sales_order"])
ok(made["cost"]["name"] == "CS-2026-00069", "the cost sheet is found", made["cost"]["name"])
ok(made["bom"]["count"] == 2 and made["bom"]["active"] == 2, "the active BOMs per size are counted",
   str(made["bom"]["count"]))
ok(made["tech_pack"]["name"] == "BTP-2026-00002", "and the buyer's pack is on file")
ok(made["item"] == "C2027-S84-304" and made["sizes"] == ["M", "S"], "the size SKUs are listed",
   "/".join(made["sizes"]))
ok(made["quote_ready"] is True, "which makes it quotable from the record")

costed = inquiry.history("C9051-U70-654", POOL)
ok(costed["verdict"] == "costed", "a price list entry with no order is 'costed'", costed["verdict"])
onfile = inquiry.history("C7540-S99-304", POOL)
ok(onfile["verdict"] == "made", "a single-SKU style with a cancelled order is still 'made'",
   onfile["verdict"])
ok(onfile["last_price"] == 23.0, "and keeps its last price even from a cancelled order",
   str(onfile["last_price"]))
new = inquiry.history("C9112-U71-701", POOL)
ok(new["verdict"] == "new" and new["quote_ready"] is False, "a style we have never seen is 'new'")
ok(new["errors"] == [], "with no read errors claimed")

broken = dict(POOL, errors=["Cost Sheet: read failed"], costs=[], prices=[], orders=[])
lost = inquiry.history("C9112-U71-701", broken)
ok(lost["errors"] and "read failed" in lost["errors"][0],
   "a FAILED read is reported, not silently read as 'none'", str(lost["errors"]))

print("\nD · the quantity is claimed only when it is the buyer's own number")
one = inquiry.lines({"style": {"code": "C2027-S84-304"}, "commercial": {"total_qty": 3100}},
                    codes=["C2027-S84-304"], pool=POOL)
ok(one[0]["qty"] == 3100, "one style in the mail = the mail's quantity belongs to it")
three = inquiry.lines({"style": {"code": "C9533-U71-725"}, "commercial": {"total_qty": 3100}},
                      codes=["C9112-U71-701", "C9208-U71-712", "C9533-U71-725"], pool=POOL)
ok(all(l["qty"] is None for l in three),
   "three styles with no split leaves each quantity unknown — no division by guesswork")
ok(len({l["style"] for l in three}) == 3, "three lines, one per style")

print("\nE · the register: one row per enquiry, and it moves")
inquiry._pool = lambda max_age=60.0: POOL                                 # noqa: F811
mail = MailMessageModel(id=1, uid="1", message_id="q1@x", thread_id="",
                        from_addr="buyer@harborlane.com", from_name="HARBOR & LANE",
                        subject="Enquiry - Summer 2027 - C9112 / C9208 / C9533 - Please quote",
                        body_text="Please send your quote by 11/09/2026. Target 02/11/2027 x-factory.",
                        received_at="2026-11-01T09:00:00")
db.add(mail)
db.commit()
FACTS = {"document_type": "enquiry", "buyer": {"name": "HARBOR & LANE APPAREL CO.",
                                               "email": "buyer@harborlane.com", "country": "United States"},
         "style": {"code": "C9533-U71-725", "description": "S/S CAMP COLLAR SHIRT"},
         "commercial": {"total_qty": 3100}, "ship_date": "2027-02-11",
         "styles": ["C2027-S84-304", "C9112-U71-701"], "asks": ["Please send your quote by 11/09/2026."],
         "missing": ["currency"]}
run = IntakeRunModel(mail_id=1, route="enquiry", status="understood", facts=json.dumps(FACTS),
                     matches="{}", plan="[]", summary="HARBOR & LANE", created_refs="[]")
db.add(run)
db.commit()
row = inquiry.from_run(db, run, mail, refresh=True)
ok(row is not None and row.buyer_name == "HARBOR & LANE APPAREL CO.", "the row carries the buyer")
ok([l["style"] for l in json.loads(row.lines)] == ["C2027-S84-304", "C9112-U71-701"],
   "and one line per style the mail names")
ok(row.quote_due == "2026-11-09", "the quote-by date is read in the buyer's own format",
   f"{row.quote_due} from {row.quote_due_raw}")
ok(row.target_ship == "2027-02-11", "and the target ship date is the mail's")
d = row.to_dict()
ok(d["old_styles"] == ["C2027-S84-304"] and d["new_styles"] == ["C9112-U71-701"],
   "the register separates what we have from what we do not",
   f"old {d['old_styles']} / new {d['new_styles']}")

inquiry.from_run(db, run, mail, refresh=True)
again = db.query(BuyerInquiryModel).filter(BuyerInquiryModel.run_id == run.id).all()
ok(len(again) == 1, "re-syncing does not open a second enquiry for the same mail")

run.chain_id = 7
mail.chain_id = 7        # what chain.attach() does to the mail on the way in
db.commit()
reply = IntakeRunModel(mail_id=1, route="chain_reply", status="understood", chain_id=7,
                       facts=json.dumps({**FACTS, "styles": ["C9208-U71-712"], "style": {"code": "C9208-U71-712"}}),
                       matches="{}", plan="[]", summary="reply", created_refs="[]")
db.add(reply)
db.commit()
inquiry.from_run(db, reply, mail, refresh=True)
rows = db.query(BuyerInquiryModel).all()
ok(len(rows) == 1, "a follow-up in the SAME thread adds to the enquiry, it does not fork it",
   f"{len(rows)} row(s)")

res = F.update_buyer_inquiry(db, row.id, status="quoted", note="quotation sent")
ok(res["ok"] and res["inquiry"]["status"] == "quoted", "the status moves")
bad = F.update_buyer_inquiry(db, row.id, status="banana")
ok(not bad["ok"] and bad["error"] == "bad_status", "and refuses a status that is not one")
summ = inquiry.summary(db.query(BuyerInquiryModel).all())
ok(summ["total"] == 1 and summ["quoted"] == 1 and summ["styles"] >= 2, "the summary counts it",
   json.dumps(summ))

print("\nF · the ask reaches the Opportunity — as lines when it can, as notes when it cannot")
step = intake_exec._step_opportunity(FACTS, {"customer": "CUST-1", "chain": {}})
pl = step["payload"] or {}
notes = pl.get("notes") or []
ok(len(notes) == 3, "one note per style on the Opportunity", str(len(notes)))
ok("C2027-S84-304" in notes[1]["note"], "the style that is written on it", notes[1]["note"][:80])
ok("made before" in notes[1]["note"] and "16.30" in notes[1]["note"],
   "…with the verdict and the price we last sold it at", notes[1]["note"][:120])
ok("new style" in notes[2]["note"], "and a new style says so plainly", notes[2]["note"][:80])
ok(pl.get("items") == [] or not pl.get("items"),
   "NO item row for a qty we do not have — ERPNext refuses qty 0 and 1 would be a lie")
ok(any("3,100" in n["note"] for n in notes),
   "the quantity asked is written down even though it is not split")
ok(pl["title"] == "HARBOR & LANE APPAREL CO. — C2027-S84-304 / C9112-U71-701",
   "the title names every style asked for", pl["title"])

one_style = {**FACTS, "styles": ["C2027-S84-304"], "style": {"code": "C2027-S84-304"}}
step1 = intake_exec._step_opportunity(one_style, {"customer": "CUST-1", "chain": {}})
items1 = (step1["payload"] or {}).get("items") or []
ok(len(items1) == 1, "one style with a known quantity DOES become an item row", str(len(items1)))
ok(items1 and items1[0]["rate"] == 16.3 and items1[0]["item_code"] == "C2027-S84-304",
   "priced from history, with its item", f'{items1[0]["rate"] if items1 else "no row"}')
ok(items1 and items1[0]["qty"] == 3100 and items1[0]["amount"] == 50530.0,
   "and the amount is the arithmetic, not a guess", str(items1[0]["amount"]) if items1 else "")
ok((step1["payload"] or {}).get("opportunity_amount") == 50530.0,
   "which becomes the Opportunity value")

print(f"\n{'=' * 70}\n  {passed} passed · {failed} failed\n{'=' * 70}")
if os.path.exists(DB):
    os.remove(DB)
sys.exit(1 if failed else 0)
