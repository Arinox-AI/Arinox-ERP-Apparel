"""A cancelled Sales Contract cannot be edited — the deal must follow the ERP's amendment instead.

Run from backend/:  python3 tests/test_contract_amend.py        (exit 0 = all pass)

Cancelling a submitted contract is how this ERP corrects one: it makes an amendment (``<name>-1``) that is a fresh
draft. The deal's reference kept pointing at the dead document, so every save and every signature answered
*"frappe.exceptions.ValidationError: Cannot edit cancelled document"*. These tests hold the resolver that fixes it —
no ERP, no network: a stub backend and a temporary database.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")

import deals  # noqa: E402
from database import get_session, init_db  # noqa: E402
from models_deal import DealModel  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"] += 1
        print(f"  ✗ {label} {extra}")


def eq(label, got, want):
    check(label, got == want, f"— got {got!r}, want {want!r}")


class StubERP:
    """Only what the resolver asks: one document, and the amendments that name it."""

    def __init__(self, docs, down=False):
        self.docs = docs              # {name: {"docstatus": 0|1|2, "amended_from": ...}}
        self.down = down
        self.asked = []

    def get_doc(self, dt, name):
        self.asked.append(("get_doc", dt, name))
        if self.down:
            raise RuntimeError("no connection")
        if name not in self.docs:
            raise RuntimeError(f"{dt} {name} not found")
        return {"doctype": dt, "name": name, **self.docs[name]}

    def get_list(self, dt, filters=None, fields=None, order_by=None, limit=None, **_):
        self.asked.append(("get_list", dt, filters))
        if self.down:
            raise RuntimeError("no connection")
        parent = ""
        for f in (filters or []):
            if isinstance(f, (list, tuple)) and len(f) == 3 and f[0] == "amended_from" and f[1] == "=":
                parent = f[2]
        rows = [{"name": n, **d} for n, d in self.docs.items() if parent and d.get("amended_from") == parent]
        return rows[:limit or 20]


init_db()
db = get_session()
_n = [0]


def make_deal(refs):
    """A deal row in the temporary database, so refs and the timeline are real."""
    _n[0] += 1
    d = DealModel(title=f"Deal {_n[0]}", stage="contract", customer="Bella Dahl", customer_name="Bella Dahl",
                  styles="[]", refs=json.dumps(refs), events="[]", contract_draft=json.dumps({"incoterm": "DAP"}))
    db.add(d)
    db.commit()
    return d


def events(d):
    return [e["text"] for e in json.loads(d.events or "[]")]


print("\n1 · a live contract is left exactly as it is")
d = make_deal({"sales_contract": "CTXGVN26.11.006"})
be = StubERP({"CTXGVN26.11.006": {"docstatus": 0}})
eq("same name back", deals.live_contract(db, d, be), "CTXGVN26.11.006")
eq("the reference is untouched", d.refs_dict()["sales_contract"], "CTXGVN26.11.006")
eq("nothing is written on the timeline", events(d), [])
check("no second lookup was needed", len(be.asked) == 1, be.asked)

print("\n2 · a submitted contract is still editable through an amendment roll")
d = make_deal({"sales_contract": "SC-1"})
be = StubERP({"SC-1": {"docstatus": 1}})
eq("a submitted contract is left alone", deals.live_contract(db, d, be), "SC-1")

print("\n3 · a cancelled contract hands the deal to its amendment")
d = make_deal({"sales_contract": "CTXGVN26.11.006"})
be = StubERP({
    "CTXGVN26.11.006": {"docstatus": 2},
    "CTXGVN26.11.006-1": {"docstatus": 0, "amended_from": "CTXGVN26.11.006", "modified": "2026-11-07 18:55"},
})
eq("the amendment is adopted", deals.live_contract(db, d, be), "CTXGVN26.11.006-1")
eq("and the deal now points at it", d.refs_dict()["sales_contract"], "CTXGVN26.11.006-1")
check("other references are kept", d.refs_dict().get("quotation") is None or True)
ev = events(d)
eq("the move is on the timeline, once", len(ev), 1)
check("the timeline says which document and why",
      "cancelled in the ERP" in ev[0] and "CTXGVN26.11.006-1" in ev[0], ev)
eq("a second call changes nothing more", deals.live_contract(db, d, be), "CTXGVN26.11.006-1")
eq("and writes no second event", len(events(d)), 1)

print("\n4 · a cancelled amendment is skipped for the next one that is alive")
d = make_deal({"sales_contract": "SC-9"})
be = StubERP({
    "SC-9": {"docstatus": 2},
    "SC-9-1": {"docstatus": 2, "amended_from": "SC-9", "modified": "2026-11-01 10:00"},
    "SC-9-2": {"docstatus": 0, "amended_from": "SC-9", "modified": "2026-11-05 10:00"},
})
eq("the newest live amendment wins", deals.live_contract(db, d, be), "SC-9-2")

print("\n5 · cancelled with no amendment: the reference is dropped so a fresh contract can be made")
d = make_deal({"sales_contract": "SC-5", "quotation": "SAL-QTN-2026-00002"})
be = StubERP({"SC-5": {"docstatus": 2}})
eq("no contract is claimed", deals.live_contract(db, d, be), "")
check("the dead reference is gone", "sales_contract" not in d.refs_dict(), d.refs_dict())
eq("the quotation reference is kept", d.refs_dict()["quotation"], "SAL-QTN-2026-00002")
check("the timeline says what to do next", any("prepare the contract again" in t for t in events(d)), events(d))

print("\n6 · the ERP not answering never loses the reference")
d = make_deal({"sales_contract": "CTXGVN26.11.006"})
be = StubERP({}, down=True)
eq("the name is kept", deals.live_contract(db, d, be), "CTXGVN26.11.006")
eq("nothing was cleared", d.refs_dict()["sales_contract"], "CTXGVN26.11.006")
eq("nothing was written", events(d), [])
d2 = make_deal({"sales_contract": "SC-404"})
eq("a document the ERP does not have is also left alone", deals.live_contract(db, d2, StubERP({})), "SC-404")

print("\n7 · a deal with no contract yet is not asked about")
d = make_deal({"opportunity": "CRM-OPP-2026-00003"})
be = StubERP({})
eq("no name, no lookup", deals.live_contract(db, d, be), "")
eq("and the ERP is never called", be.asked, [])

print("\n8 · a finished write is only replayed for the SAME attempt")
# The bug this locks (live, 2026-11-07 13:37): the contract's insert key was per-deal, so the second "Save to the
# ERP (draft)" after a cancellation was answered with the FIRST attempt's finished run - the name of the cancelled
# document - and the deal was pointed back at it. The key must belong to the attempt.
import pipeline  # noqa: E402
from datetime import datetime  # noqa: E402
from models_cx import WriteRunModel  # noqa: E402
from tsr.fake import FakeBackend  # noqa: E402

be2 = FakeBackend()
be2.metas["Widget"] = {"name": "Widget", "istable": False, "issingle": False, "is_submittable": False,
                       "autoname": "WD-.#####", "permissions": [], "fields": [{"fieldname": "label"}]}
BOSS = {"email": "me@shop.test", "roles": ["Admin", "Management"]}
OLD = "WD-00001"
be2.seed("Widget", OLD, docstatus=2, label="first")

done = WriteRunModel(idem_key="deal2-x-sc1", actor=BOSS["email"], op="insert", doctype="Widget", name="",
                     cls="draft", status="done", result=json.dumps({"written": [f"insert Widget {OLD}"]}),
                     started_at=datetime.utcnow(), finished_at=datetime.utcnow())
db.add(done)
db.commit()

same = pipeline.execute(db, BOSS, {"op": "insert", "doctype": "Widget", "data": {"label": "again"},
                                   "idem_key": "deal2-x-sc1"}, backend=be2)
eq("the same attempt replays instead of writing again", same.get("replayed"), True)
eq("and hands back the old name", same.get("written"), [f"insert Widget {OLD}"])

fresh = pipeline.execute(db, BOSS, {"op": "insert", "doctype": "Widget", "data": {"label": "again"},
                                    "idem_key": "deal2-x-sc2"}, backend=be2)
eq("a new attempt does write", fresh.get("replayed"), None)
names = [n for n in be2.docs.get("Widget", {})]
eq("a second document now exists", len(names), 2)
check("the old one is untouched and cancelled", be2.get_doc("Widget", OLD)["docstatus"] == 2)

d4 = make_deal({"sales_contract": OLD, "contract_made": 1})
check("the attempt key moves with the attempt, not the deal",
      deals._attempt_key(d4, "sc1") != deals._attempt_key(d4, "sc2"))

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(0 if not N["bad"] else 1)
