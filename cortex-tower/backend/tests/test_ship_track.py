"""Ship & track: the plan the tower derives from a contract's own terms.

Run from backend/:  python3 tests/test_ship_track.py        (exit 0 = all pass)

Everything here is arithmetic on what the contract says — no ERP is touched, and the only database use is the
"given to the buyer" tick, which is the one fact the ERP has no field for. The point of the test is that the tower
never invents a date and never lets a contract contradict itself in silence.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")

import ship_track as st  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"] += 1
        print(f"  ✗ {label} {extra}")


def eq(label, got, want):
    check(label, got == want, f"— got {got!r}, want {want!r}")


# ── the contract this test reads: the one on the live deal, with its dates tightened so the arithmetic is checkable
CONTRACT = {
    "incoterm": "DAP", "named_place": "Los Angeles", "shipment_mode": "Air",
    "freight_by": "Seller", "insurance_by": "Seller",
    "documents_list": "Invoice, Packing List, FCR or MAWB",
    "days_ex_factory_to_etd": 6, "transit_days": 6,
    "payment_basis": "Days after Receipt of Goods (ROG)", "payment_days": 10,
    "contract_date": "2026-11-07",
    "production_lead_days": 25,
    "items": [{"style_no": "C2027-S84-304", "colour": "Print", "qty": 1000, "rate": 17.0,
               "ex_factory_date": "2026-12-08", "etd": "2026-12-14", "in_warehouse_date": "2026-12-22"}],
    "sizes": [], "_signed": True,
}
TODAY = date(2026, 11, 7)


class Deal:
    def __init__(self, refs=None):
        self.refs = refs or {}

    def refs_dict(self):
        return self.refs


print("\n1 · the eleven terms are the ERP's eleven, each explained")
eq("eleven terms", len(st.INCOTERMS), 11)
eq("codes are the ERP's list", [t["code"] for t in st.INCOTERMS],
   ["EXW", "FCA", "FAS", "FOB", "CPT", "CIP", "CFR", "CIF", "DAP", "DPU", "DDP"])
check("every term says who pays duty", all(t.get("duty") for t in st.INCOTERMS))
check("every term says where risk passes", all(t.get("risk") for t in st.INCOTERMS))
check("every term has a plain meaning", all(len(t.get("meaning") or "") > 40 for t in st.INCOTERMS))
eq("DAP puts duty on the buyer", st.TERMS["DAP"]["duty"], "Buyer")
eq("DDP puts duty on us", st.TERMS["DDP"]["duty"], "Seller")
eq("sea-only terms", st.SEA_ONLY, {"FAS", "FOB", "CFR", "CIF"})

print("\n2 · the dates come from the contract, not from today")
clocks = st._contract_clocks(CONTRACT)
eq("ex-factory is the latest line", clocks["ex_factory"].isoformat(), "2026-12-08")
eq("ETD is the line's own ETD", clocks["etd"].isoformat(), "2026-12-14")
eq("ETA is ETD + transit", clocks["eta"].isoformat(), "2026-12-20")
eq("in-warehouse is the line's own", clocks["in_warehouse"].isoformat(), "2026-12-22")
due, why = st._payment_due(clocks, None)
eq("payment due is warehouse + ROG days", due.isoformat(), "2027-01-01")
check("the payment rule is said in words", "10 days after the goods arrive" in why, why)

print("\n3 · ETD is derived when the line has none")
c2 = {**CONTRACT, "items": [{**CONTRACT["items"][0], "etd": None}]}
cl2 = st._contract_clocks(c2)
eq("ETD = ex-factory + days_ex_factory_to_etd", cl2["etd"].isoformat(), "2026-12-14")
eq("and ETA follows", cl2["eta"].isoformat(), "2026-12-20")

print("\n4 · nothing is invented: a contract with no dates says so")
bare = {"incoterm": "FOB", "documents_list": "Invoice", "items": []}
cb = st._contract_clocks(bare)
eq("no ex-factory date", cb["ex_factory"], None)
rows = st.schedule(bare, cb, None)
eq("the ex-factory row is undated", rows[0]["date"], "")
eq("and says why", rows[0]["basis"], "no date on the contract")
eq("its standing is 'unknown', not 'late'", rows[0]["state"], "unknown")

print("\n5 · the documents the contract names, with who produces each")
docs = st.documents(CONTRACT, clocks, {})
labels = [d["label"] for d in docs]
eq("four papers + the signed copy", len(docs), 5)
check("invoice", "Commercial Invoice" in labels, labels)
check("packing list", "Packing List" in labels, labels)
check("FCR read out of 'FCR or MAWB'", "FCR (forwarder's cargo receipt)" in labels, labels)
check("MAWB read out of 'FCR or MAWB'", "MAWB / AWB" in labels, labels)
by = {d["id"]: d for d in docs}
eq("the invoice is ours to issue", by["invoice"]["owner"], "us")
eq("the AWB is the carrier's", by["awb"]["owner"], "carrier")
eq("the invoice is due on ETD", by["invoice"]["date"], "2026-12-14")
eq("a certificate of origin would be due 3 days earlier",
   st._doc_due("certificate_of_origin", clocks)[0].isoformat(), "2026-12-11")
check("nothing is ticked yet", not any(d["ticked"] for d in docs))

print("\n6 · a document that is late is late, and a ticked one is not")
late = st._row("invoice", "Invoice", TODAY - timedelta(days=4), today=TODAY)
eq("late", late["state"], "late")
eq("days late", late["days_left"], -4)
eq("today", st._row("x", "X", TODAY, today=TODAY)["state"], "today")
eq("soon", st._row("x", "X", TODAY + timedelta(days=2), today=TODAY)["state"], "soon")
eq("later", st._row("x", "X", TODAY + timedelta(days=20), today=TODAY)["state"], "pending")

print("\n7 · a contract that contradicts itself is caught, not signed and forgotten")
good = st.date_notes(CONTRACT, clocks, TODAY)
eq("a consistent contract raises no date warning",
   [n["title"] for n in good], [])
bad_etd = {**CONTRACT, "items": [{**CONTRACT["items"][0], "etd": "2026-12-08"}]}
notes = st.date_notes(bad_etd, st._contract_clocks(bad_etd), TODAY)
check("ETD that ignores the lead time is flagged",
      any("ETD and the lead time disagree" in n["title"] for n in notes), notes)
bad_wh = {**CONTRACT, "items": [{**CONTRACT["items"][0], "in_warehouse_date": "2026-12-15"}]}
notes = st.date_notes(bad_wh, st._contract_clocks(bad_wh), TODAY)
check("goods arriving after the warehouse is flagged",
      any("arrive after they are in the warehouse" in n["title"] for n in notes), notes)
bad_exf = {**CONTRACT, "items": [{**CONTRACT["items"][0], "in_warehouse_date": "2026-12-01"}]}
notes = st.date_notes(bad_exf, st._contract_clocks(bad_exf), TODAY)
check("in-warehouse before ex-factory is flagged",
      any("before ex-factory" in n["title"] for n in notes), notes)

print("\n8 · a trade term that fights the contract's own lines is named")
tn = st.trade_term_notes(CONTRACT, clocks)
check("a coherent DAP contract is quiet on freight/insurance", not any(n["tone"] == "bad" for n in tn), tn)
fob_air = {**CONTRACT, "incoterm": "FOB"}
tn = st.trade_term_notes(fob_air, clocks)
check("FOB on an air shipment is a hard problem",
      any(n["tone"] == "bad" and "sea term" in n["title"] for n in tn), [n["title"] for n in tn])
tn = st.trade_term_notes({**CONTRACT, "freight_by": "Buyer"}, clocks)
check("DAP with the buyer paying freight is flagged",
      any("freight is seller" in n["title"].lower() for n in tn), [n["title"] for n in tn])
tn = st.trade_term_notes({**CONTRACT, "insurance_by": ""}, clocks)
check("blank insurance is flagged",
      any("Insurance party left blank" in n["title"] for n in tn), [n["title"] for n in tn])
tn = st.trade_term_notes({**CONTRACT, "incoterm": "cortex"}, clocks)
check("a word that is not a term is refused in words",
      any("not one of the eleven" in n["title"] for n in tn), [n["title"] for n in tn])
tn = st.trade_term_notes({**CONTRACT, "incoterm": ""}, clocks)
check("no Incoterm at all is a hard problem", tn and tn[0]["tone"] == "bad", tn)

print("\n9 · the whole plan, with the ERP down, still answers")
out = st.plan(Deal({"sales_contract": "CTXGVN26.11.006"}), CONTRACT, be=None, ticks={}, today=TODAY)
eq("signed", out["signed"], True)
eq("six schedule rows", len(out["schedule"]), 6)
eq("the contract is named", out["contract"], "CTXGVN26.11.006")
check("the term is explained", out["incoterm"]["code"] == "DAP")
eq("no shipments when the ERP cannot answer", out["shipments"], [])
check("no ERP error is invented", out["erp_error"] == "")
eq("papers counted", (out["documents_done"], out["documents_total"]), (0, 5))

print("\n9b · a draft with signature dates is still a draft")
draftish = {**CONTRACT, "_signed": False, "docstatus": 0,
            "buyer_signed_on": "2026-11-07", "company_signed_on": "2026-11-07"}
out = st.plan(Deal({}), draftish, be=None, ticks={}, today=TODAY)
eq("not signed while the ERP holds it as a draft", out["signed"], False)
check("so no signing row is claimed",
      not any(r["key"] == "signed" for r in out["schedule"]), [r["key"] for r in out["schedule"]])
out = st.plan(Deal({}), {**draftish, "docstatus": 1}, be=None, ticks={}, today=TODAY)
eq("submitted in the ERP means signed", out["signed"], True)
eq("and the signing date shows", [r["date"] for r in out["schedule"] if r["key"] == "signed"], ["2026-11-07"])

print("\n10 · a tick is kept, and a paper the contract never named cannot be ticked")
from database import get_session, init_db  # noqa: E402
init_db()
db = get_session()
ticks = {"invoice": {"on": "2026-12-14", "by": "merch@test.local", "note": "emailed with the AWB"}}
st.save_ticks(db, 7, ticks)
back = st.load_ticks(db, 7)
eq("the tick round-trips", back["invoice"]["on"], "2026-12-14")
eq("and who gave it", back["invoice"]["by"], "merch@test.local")
docs = st.documents(CONTRACT, clocks, back)
by = {d["id"]: d for d in docs}
check("the invoice is now ticked", by["invoice"]["ticked"])
eq("with its date", by["invoice"]["given_on"], "2026-12-14")
check("the AWB is still open", not by["awb"]["ticked"])
eq("another deal's ticks are not shared", st.load_ticks(db, 8), {})
out = st.plan(Deal({}), CONTRACT, be=None, ticks=back, today=TODAY)
eq("the plan counts it", out["documents_done"], 1)

print("\n11 · a shipment that misses the contract is flagged")
# a shipment whose paper trail is empty and whose ETD has slipped past the contract's
view = {"name": "SHIP-1", "etd": "2026-12-21", "awb": "", "booking_no": "", "cutoff": "2026-11-04",
        "documents": [], "mode": "Air"}
al = st.shipment_alerts(view, clocks, "Air", TODAY)
titles = [a["title"] for a in al]
check("ETD later than the contract", any("ETD pushed" in t for t in titles), titles)
check("cut-off passed with nothing on board", any("Cut-off passed" in t for t in titles), titles)
check("no AWB on an air shipment", any("No AWB number" in t for t in titles), titles)
check("no documents", any("No documents" in t for t in titles), titles)
# a shipment that is ten days out and has not been booked yet
near = {"ex_factory": TODAY, "etd": TODAY + timedelta(days=10), "eta": TODAY + timedelta(days=17),
        "in_warehouse": TODAY + timedelta(days=18), "gap": 10, "transit": 7, "payment_basis": "", "payment_days": 0,
        "items": []}
al = st.shipment_alerts({"name": "SHIP-2", "awb": "020-1", "booking_no": "", "cutoff": str(TODAY + timedelta(days=2)),
                         "documents": ["Invoice"], "mode": "Air"}, near, "Air", TODAY)
titles = [a["title"] for a in al]
check("no booking ten days before ETD", any("No booking yet" in t for t in titles), titles)
check("cut-off in two days", any("cut-off in 2 day(s)" in t.lower() for t in titles), titles)
al2 = st.shipment_alerts({"name": "S", "etd": "2026-12-14", "awb": "020-1", "booking_no": "BK1",
                          "cutoff": "2026-12-09", "tracking_url": "https://t.example/x",
                          "documents": ["Invoice"], "mode": "Air", "on_board": "2026-12-14"}, clocks, "Air", TODAY)
eq("a shipment on plan is quiet", [a["title"] for a in al2], [])

print("\n12 · the shipment card reads the ERP's own field names")
sv = st.shipment_view({"name": "S-9", "apparel_bol": "", "carrier": "Emirates SkyCargo", "awb_number": "176-1",
                       "tracking_url": "https://track/176-1", "tracking_status": "In Progress",
                       "apparel_forwarder": "DHL Global", "apparel_cutoff": "2026-12-09 14:00:00",
                       "apparel_containers": [{"container_no": "CXDU1234567"}],
                       "apparel_documents": [{"document_type": "Invoice"}]})
eq("carrier", sv["carrier"], "Emirates SkyCargo")
eq("awb", sv["awb"], "176-1")
eq("cutoff is a date", sv["cutoff"], "2026-12-09")
eq("containers", sv["containers"], ["CXDU1234567"])
eq("documents", sv["documents"], ["Invoice"])

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(0 if not N["bad"] else 1)
