#!/usr/bin/env python3
"""Sending an inquiry to the ERP a second time (2026-11-07) — the bare ``'doc'`` error.

The user's report: clicking **Send the inquiry to the ERP** on the re-read inquiry answered, in full, ``'doc'``.

That is a `KeyError('doc')` escaping to the UI. The chain:

* ``pipeline.execute`` stores a finished write's result **without the document body**
  (``run.result = {k: v for k, v in res.items() if k != "doc"}``) but keeps ``written: ["insert Opportunity CRM-OPP-…"]``;
* a second call with the **same idempotency key** is not a write, it is a *replay*: ``return {**stored, "ok": True,
  "replayed": True}``;
* ``deals.register`` then read ``res["doc"]["name"]`` — which only exists on a fresh write.

Why the key matched: deleting an inquiry and reading it again from the same mail gives the new deal the same row id
(SQLite reuses it), so ``f"deal{d.id}-opp"`` was the *deleted* deal's key. The key now carries the deal's creation
stamp, and every document name is read through :func:`deals._written_name`, which also understands a replayed answer.

This suite locks both halves down: the key, the name recovery, and a full ``register`` run whose writes all come back
replayed. It also checks that a re-read **adopts** the Opportunity / Tech Pack the ERP already holds for this buyer and
style instead of leaving duplicates behind.

Run:  python3 tests/test_register_replay.py
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

from database import get_session, init_db                                     # noqa: E402
init_db()
import deals                                                                 # noqa: E402
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


def t_written_name():
    print("\n1. A document name, however the answer carries it")
    check("a fresh write: doc.name", deals._written_name({"ok": True, "doc": {"name": "CRM-OPP-2026-00009"}}, "Opportunity")
          == "CRM-OPP-2026-00009")
    check("a replay: from written[]", deals._written_name({"ok": True, "replayed": True,
                                                           "written": ["insert Opportunity CRM-OPP-2026-00003"]},
                                                          "Opportunity") == "CRM-OPP-2026-00003")
    check("another doctype in written[] is not taken", deals._written_name(
        {"ok": True, "written": ["insert Cost Sheet CS-2026-00001"]}, "Opportunity") == "")
    check("a call in written[] is ignored", deals._written_name(
        {"ok": True, "written": ["call Opportunity x"]}, "Opportunity") == "")
    check("nothing to read -> empty, never a KeyError", deals._written_name({"ok": True}, "Opportunity") == "")


def t_attempt_key():
    print("\n2. The idempotency key belongs to the deal, not to the id it happens to hold")
    old = deals._attempt_key(type("D", (), {"id": 1, "created_at": "2026-11-07 09:48:32"})(), "opp")
    new = deals._attempt_key(type("D", (), {"id": 1, "created_at": "2026-11-07 10:08:30"})(), "opp")
    same = deals._attempt_key(type("D", (), {"id": 1, "created_at": "2026-11-07 10:08:30"})(), "opp")
    check("a re-created deal (same id, new stamp) gets a new key", old != new, f"{old} vs {new}")
    check("the same deal gets the same key twice", new == same, f"{new} vs {same}")
    check("different steps never share a key",
          deals._attempt_key(type("D", (), {"id": 1, "created_at": "x"})(), "opp") !=
          deals._attempt_key(type("D", (), {"id": 1, "created_at": "x"})(), "qtn"))
    check("the key still names the deal", new.startswith("deal1-"), new)


def t_register_on_replay():
    print("\n3. register() when every write comes back replayed (the user's click)")
    be = fake_erp()
    db = get_session()
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Inquiry on style Z1001-A10-100",
                            contact_email="jane@acme-apparel.test")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500,
                      "sizes": ["S", "M", "L"],
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
                               "uom": "Yard", "consumption": 1.47}]})
    d.styles = json.dumps(styles)
    db.commit()

    real_ex = deals._ex
    calls = []

    def replayed(db_, me, req):
        calls.append((req.get("op"), req.get("doctype")))
        if req.get("op") == "insert":                       # exactly what pipeline hands back on a replay
            return {"ok": True, "run_id": 5, "class": "draft", "replayed": True,
                    "written": [f'insert {req["doctype"]} {req["doctype"].replace(" ", "")}-REPLAYED-1']}
        return {"ok": True, "run_id": 6, "class": "draft", "written": []}

    deals.BACKEND = be
    deals._ex = replayed
    try:
        out = deals.register(db, ADMIN, d.id)
    except KeyError as e:
        deals._ex = real_ex
        check("register survives a replayed answer", False, f"KeyError({e}) — this is the user's bug")
        return
    finally:
        deals._ex = real_ex

    refs = out.refs_dict()
    check("register survives a replayed answer", True)
    check("the Opportunity name comes from written[]", refs.get("opportunity") == "Opportunity-REPLAYED-1", str(refs))
    s = json.loads(out.styles or "[]")[0]
    check("the Tech Pack name too", s.get("tech_pack") == "TechPack-REPLAYED-1", str(s.get("tech_pack")))
    check("the deal moves on to costing", out.stage == "costing", out.stage)
    check("the write was actually attempted with a key", any(op == "insert" for op, _ in calls), str(calls))


def t_register_adopts():
    print("\n4. A re-read adopts what the ERP already holds for this buyer and style")
    be = fake_erp()
    db = get_session()
    be.seed("Opportunity", "CRM-OPP-2026-00003", party_name="EMJ APPAREL GROUP, LLC", status="Open", docstatus=0,
            apparel_source_email="jane2@acme-apparel.test")
    be.seed("Tech Pack", "TP-2026-00003", customer="EMJ APPAREL GROUP, LLC", style_no="Z1001-A10-100", docstatus=0)
    be.seed("Cost Sheet", "CS-2026-00001", tech_pack="TP-2026-00003", style_no="Z1001-A10-100", docstatus=0)
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Re-read the same inquiry",
                            contact_email="jane2@acme-apparel.test")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500,
                      "style_name": "1 POCKET CROPPED BUTTON DOWN", "sizes": ["S", "M", "L"],
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
                               "uom": "Yard", "consumption": 1.47}]})
    d.styles = json.dumps(styles)
    db.commit()
    before = {dt: len(be.docs.get(dt, {}) or {}) for dt in ("Opportunity", "Tech Pack", "Cost Sheet")}
    deals.BACKEND = be
    try:
        out = deals.register(db, ADMIN, d.id)
    except deals.DealError as e:
        check("register adopts instead of duplicating", False, str(e))
        return
    after = {dt: len(be.docs.get(dt, {}) or {}) for dt in ("Opportunity", "Tech Pack", "Cost Sheet")}
    refs = out.refs_dict()
    s = json.loads(out.styles or "[]")[0]
    check("no second Opportunity/Tech Pack/Cost Sheet is made", before == after, f"{before} -> {after}")
    check("the existing Opportunity is adopted", refs.get("opportunity") == "CRM-OPP-2026-00003", str(refs))
    check("the existing Tech Pack is adopted", s.get("tech_pack") == "TP-2026-00003", str(s.get("tech_pack")))
    check("its draft Cost Sheet is picked up too", s.get("cost_sheet") == "CS-2026-00001", str(s.get("cost_sheet")))
    tp = be.get_doc("Tech Pack", "TP-2026-00003") or {}
    check("the adopted pack is refreshed from the sheet", len(tp.get("materials") or []) == 1, str(tp.get("materials")))
    check("the style description goes onto it", tp.get("style_name") == "1 POCKET CROPPED BUTTON DOWN", tp.get("style_name"))
    check("the sizes go onto it", [z.get("size") for z in tp.get("sizes") or []] == ["S", "M", "L"], str(tp.get("sizes")))
    events = [e.get("text", "") for e in json.loads(out.events or "[]")]
    check("the timeline says it was adopted, not created", any("adopted" in t for t in events), str(events[-3:]))


def t_erp_links_and_status():
    print("\n5. The Confirm-in-the-ERP links, and the status coming back")
    import erp
    real_base = erp._base_key
    erp._base_key = lambda: "https://erp.test:9446/"          # no network: just the URL rule
    try:
        check("a two-word doctype is slugged", erp.doc_url("Tech Pack", "TP-2026-00003")
              == "https://erp.test:9446/desk/tech-pack/TP-2026-00003", erp.doc_url("Tech Pack", "TP-2026-00003"))
        check("a one-word doctype too", erp.doc_url("Opportunity", "CRM-OPP-2026-00003")
              == "https://erp.test:9446/desk/opportunity/CRM-OPP-2026-00003")
        check("the desk root is offered", erp.desk_url() == "https://erp.test:9446/desk", erp.desk_url())
        check("no document, no link", erp.doc_url("Tech Pack", "") == "")
    finally:
        erp._base_key = real_base

    be = fake_erp()
    db = get_session()
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Confirm in the ERP")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "tech_pack": "TP-2026-00003", "cost_sheet": "CS-2026-00001"})
    d.styles = json.dumps(styles)
    db.commit()
    be.seed("Tech Pack", "TP-2026-00003", customer="EMJ APPAREL GROUP, LLC", docstatus=0, status="Draft")
    be.seed("Cost Sheet", "CS-2026-00001", docstatus=0, quoted_price=3.2, margin_pct=11.0)
    deals.BACKEND = be
    out = deals.erp_status(d, db)
    row = out.get("tech_pack:TP-2026-00003") or {}
    check("each document carries its ERP page", bool(row.get("url")), str(row))
    check("the ERP desk is offered for the panel", bool(out.get("base_url")), str(out.get("base_url")))
    s0 = json.loads(deals._get(db, d.id).styles or "[]")[0]
    check("a draft in the ERP reads as draft here", s0.get("tech_pack_status") == "draft", str(s0.get("tech_pack_status")))

    # the person submits it in the ERP, then refreshes the tower
    be.docs["Tech Pack"]["TP-2026-00003"]["docstatus"] = 1
    be.docs["Cost Sheet"]["CS-2026-00001"]["docstatus"] = 1
    deals.erp_status(d, db)
    s1 = json.loads(deals._get(db, d.id).styles or "[]")[0]
    check("submitting in the ERP moves the Tech Pack to submitted here", s1.get("tech_pack_status") == "submitted",
          str(s1.get("tech_pack_status")))
    check("the Cost Sheet's status comes back too", s1.get("cost_status") == "submitted", str(s1.get("cost_status")))


def main():
    print("Sending the inquiry to the ERP a second time")
    t_written_name()
    t_attempt_key()
    t_register_on_replay()
    t_register_adopts()
    t_erp_links_and_status()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
