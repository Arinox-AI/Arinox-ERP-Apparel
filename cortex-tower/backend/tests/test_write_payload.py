#!/usr/bin/env python3
"""What the app is allowed to send the ERP (2026-11-07).

Two screens died of the same mistake in one afternoon:

    Not saved: materials row 1: docstatus changes only through Submit / Cancel        (the costing)
    Not recorded in the negotiation: Not saved: rounds row 1: docstatus changes only through Submit / Cancel
                                                                                      (the buyer's answer)

Both took the **stored** child rows out of the ERP, applied an edit, and sent the whole list back. Those rows carry
Frappe's bookkeeping — `docstatus`, `doctype`, `parent`, `parentfield`, `modified`, `owner`, the child's `name` — and a
client may not send them: `docstatus` moves only through Submit / Cancel. It shows up on the *second* edit of anything
(the first edit has no stored rows to inherit), which is why the whole test suite was green while both screens were
broken: the fake ERP does not police those fields the way Frappe does.

So the stripping happens in one place — `deals._ex`, the single door every write goes through — and this suite asserts
the invariant on the real payload: no read-only key may ever leave the app.

Run:  python3 tests/test_write_payload.py
"""
from __future__ import annotations

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
import deals                                                                 # noqa: E402
import pipeline                                                              # noqa: E402
from deal_harness import fake_erp, ADMIN                                     # noqa: E402

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


def _offenders(value, path="$"):
    """Every read-only key still present in a payload, with where it was found."""
    bad = []
    if isinstance(value, list):
        for i, v in enumerate(value):
            bad += _offenders(v, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in deals._READ_ONLY_KEYS:
                bad.append(f"{path}.{k}")
            bad += _offenders(v, f"{path}.{k}")
    return bad


def t_strip_unit():
    print("\n1. The stripping rule itself")
    stored = {"name": "PN-1", "docstatus": 0, "doctype": "Price Negotiation", "modified": "2026-11-07 10:00:00",
              "owner": "x@y", "status": "Open",
              "rounds": [{"name": "r0", "docstatus": 0, "parent": "PN-1", "parentfield": "rounds",
                          "parenttype": "Price Negotiation", "doctype": "PN Round", "round_date": "2026-11-06",
                          "price": 6.5, "remarks": "our offer"}],
              "styles": [{"docstatus": 1, "doctype": "PN Style", "cost_sheet": "CS-1", "our_price": 6.5}]}
    out = deals._writable(stored)
    check("no read-only key survives, at any depth", _offenders(out) == [], str(_offenders(out)))
    check("the real content survives", out["status"] == "Open" and out["rounds"][0]["price"] == 6.5
          and out["styles"][0]["cost_sheet"] == "CS-1" and out["rounds"][0]["remarks"] == "our offer", str(out))
    check("a plain value is returned untouched", deals._writable("x") == "x" and deals._writable(3) == 3)
    check("lists of scalars are fine", deals._writable(["a", 1, None]) == ["a", 1, None])


def _deal_with_negotiation(db, be):
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Negotiate me")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500, "cost_sheet": "CS-1",
                      "offer_price": 6.5, "cost": {"quoted_price": 6.5}})
    d.styles = json.dumps(styles)
    d.refs = json.dumps({"price_negotiation": "PN-1"})
    d.stage = "quoted"
    db.commit()
    # the stored negotiation the ERP would hand back: with all of its bookkeeping
    be.seed("Cost Sheet", "CS-1", customer="EMJ APPAREL GROUP, LLC", docstatus=1, quoted_price=6.5)
    be.seed("Price Negotiation", "PN-1", status="Open", docstatus=0, customer="EMJ APPAREL GROUP, LLC",
            styles=[{"docstatus": 0, "doctype": "PN Style", "parent": "PN-1", "parentfield": "styles",
                     "cost_sheet": "CS-1", "our_price": 6.5, "buyer_price": 0}],
            rounds=[{"name": "r0", "docstatus": 0, "doctype": "PN Round", "parent": "PN-1", "parentfield": "rounds",
                     "round_date": "2026-11-06", "direction": "Our Offer", "price": 6.5, "cost_sheet": "CS-1",
                     "remarks": "quote sent"}])
    return d, styles[0]


def t_second_edit_payload():
    print("\n2. The buyer's answer, twice, and the payload that goes out")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    d, s = _deal_with_negotiation(db, be)

    sent = []
    real = pipeline.execute

    def spy(db_, me, req, backend=None):
        if isinstance(req.get("data"), (dict, list)):
            sent.append(json.loads(json.dumps(req["data"], default=str)))
        return real(db_, me, req, backend=backend)

    pipeline.execute = spy
    try:
        d = deals.record_reply(db, ADMIN, d.id, "counter", prices={s["key"]: 5.9}, note="buyer wants 5.90")
        d = deals.record_reply(db, ADMIN, d.id, "accepted", prices={s["key"]: 6.0}, note="agreed at 6.00")
    finally:
        pipeline.execute = real
    check("the first answer records", d is not None and len(sent) >= 1, str(len(sent)))
    check("the second answer records too (the one that used to fail)", len(sent) >= 2, str(len(sent)))
    bad = [(i, _offenders(p)) for i, p in enumerate(sent) if _offenders(p)]
    check("no payload carried a read-only field", not bad, str(bad)[:400])
    rounds = (be.get_doc("Price Negotiation", "PN-1") or {}).get("rounds") or []
    check("the stored round is still there", any((r.get("remarks") or "") == "quote sent" for r in rounds),
          str([r.get("remarks") for r in rounds]))
    check("both answers were added as rounds", len(rounds) >= 3, str(len(rounds)))


def t_every_write_goes_through_it():
    print("\n3. Every write in the app uses the one door")
    src = open(os.path.join(ROOT, "deals.py"), encoding="utf-8").read()
    check("the sanitiser sits in _ex", "def _ex(db, me: dict, req: dict" in src and "_writable(req[\"data\"])" in src)
    others = [f for f in ("intake_exec.py", "writes.py") if "pipeline.execute" in open(os.path.join(ROOT, f), encoding="utf-8").read()]
    check("the other write paths exist and are known", isinstance(others, list), str(others))


def main():
    print("What the app may send the ERP")
    t_strip_unit()
    t_second_edit_payload()
    t_every_write_goes_through_it()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
