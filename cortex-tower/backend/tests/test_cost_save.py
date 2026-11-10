#!/usr/bin/env python3
"""Saving a costing (2026-11-07) — the `docstatus` refusal.

The user's report, with the whole error on screen:

    Not saved: materials row 1: docstatus changes only through Submit / Cancel; materials row 2: … row 3: … row 4: …

Nothing could be saved, recalculated or submitted: the Costing screen was dead for every style.

**What was wrong.** `deals.cost_save` merged the browser's edits *onto the ERP's own stored child row*
(`base = dict(by_idx[idx])`). Those rows carry Frappe's bookkeeping — `docstatus`, `doctype`, `parent`, `parentfield`,
`modified`, `owner` … — and sending them back is refused: `docstatus` may only move through Submit / Cancel. Rows the
browser had added had no `idx`, so they matched nothing and went through — which is why the error named exactly as many
rows as the sheet already had.

**The fix.** Row payloads are built from the app's whitelist only (`_MAT_FIELDS` / `_CHG_FIELDS`): no system fields, no
child `name`, no `amount` (the ERP computes it), numbers coerced from whatever the browser sent (`"00.06"` → `0.06`),
and a UOM that is not a real unit (the sheet often prints `—`) left out instead of being sent as a broken link.

Run:  python3 tests/test_cost_save.py
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


SYSTEM = ("docstatus", "doctype", "parent", "parentfield", "parenttype", "owner", "creation", "modified", "modified_by",
          "name", "amended_from")


def _deal_with_cost_sheet(db):
    be = fake_erp()
    deals.BACKEND = be
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Cost me", contact_email="b@acme.test")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500, "sizes": ["S", "M", "L"],
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 51% VISCOSE",
                               "uom": "Yard", "consumption": 1.69},
                              {"item_code": "FUS004", "material_type": "Fusing", "description": "9930 LIGHT FUSING",
                               "uom": "Yard", "consumption": 0.2},
                              {"item_code": "TH000", "material_type": "Thread", "description": "TS & OL: DTM",
                               "uom": "", "consumption": 1}]})
    d.styles = json.dumps(styles)
    db.commit()
    out = deals.register(db, ADMIN, d.id)
    s = json.loads(out.styles or "[]")[0]
    deals.cost_open(db, ADMIN, out.id, s["key"])          # the ERP makes the Cost Sheet from the Tech Pack
    return out, s


def t_payload_has_no_system_fields():
    print("\n1. The rows sent back carry no ERP bookkeeping")
    db = get_session()
    d, s = _deal_with_cost_sheet(db)
    cs = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    captured = {}
    real = deals._ex

    def spy(db_, me, req):
        captured.update(req)
        return real(db_, me, req)

    deals._ex = spy
    try:
        deals.cost_save(db, ADMIN, d.id, s["key"], cs["materials"], cs["charges"], quoted_price=4.5, preview=True)
    finally:
        deals._ex = real
    mats = (captured.get("data") or {}).get("materials") or []
    chgs = (captured.get("data") or {}).get("charges") or []
    check("the save sent rows at all", bool(mats), str(captured.keys()))
    check("no system field on any material row",
          all(not (set(r) & set(SYSTEM)) for r in mats), str([sorted(set(r) & set(SYSTEM)) for r in mats])[:200])
    check("no system field on any charge row",
          all(not (set(r) & set(SYSTEM)) for r in chgs), str([sorted(set(r) & set(SYSTEM)) for r in chgs])[:200])
    check("`amount` is left for the ERP to compute", all("amount" not in r for r in mats + chgs))
    check("the fields the form owns are still there",
          all("description" in r and "material_type" in r for r in mats), str(mats[:1]))


def t_numbers_and_units():
    print("\n2. Values the browser sends as text are made usable")
    db = get_session()
    d, s = _deal_with_cost_sheet(db)
    cs = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    mats = [dict(r) for r in cs["materials"]]
    mats[0]["rate"] = "00.06"                              # the exact thing that was on screen
    mats[0]["consumption"] = "1.69"
    thread = next((r for r in mats if (r.get("material_type") or "").lower() == "thread"), None)
    if thread:
        thread["uom"] = "—"
    captured = {}
    real = deals._ex

    def spy(db_, me, req):
        captured.update(req)
        return real(db_, me, req)

    deals._ex = spy
    try:
        deals.cost_save(db, ADMIN, d.id, s["key"], mats, cs["charges"], preview=True)
    finally:
        deals._ex = real
    sent = (captured.get("data") or {}).get("materials") or []
    check("a text rate becomes a number", sent[0].get("rate") == 0.06, str(sent[0].get("rate")))
    check("a text consumption becomes a number", sent[0].get("consumption") == 1.69, str(sent[0].get("consumption")))
    if thread:
        check("a dash UOM is dropped, not sent as a broken link", "uom" not in sent[-1], str(sent[-1]))


def t_save_recalculate_submit():
    print("\n3. Save, recalculate and submit all work on a live costing")
    db = get_session()
    d, s = _deal_with_cost_sheet(db)
    cs = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    check("a costing opens", bool(cs.get("name")), str(cs)[:80])
    prev = deals.cost_save(db, ADMIN, d.id, s["key"], cs["materials"], cs["charges"], quoted_price=5.0, preview=True)
    check("recalculate (preview) answers", prev.get("saved") is False and bool(prev.get("cost_sheet")), str(prev)[:80])
    saved = deals.cost_save(db, ADMIN, d.id, s["key"], cs["materials"], cs["charges"], quoted_price=5.0)
    check("save answers and is not refused", saved.get("saved") is True, str(saved)[:120])
    check("the quoted price stuck", saved["cost_sheet"]["totals"]["quoted_price"] == 5.0,
          str(saved["cost_sheet"]["totals"]["quoted_price"]))
    # the ERP refuses a head at 0 unless N/A is ticked - the screen has that checkbox, so use it
    after = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    charges = [{**c, "not_applicable": 1 if not c.get("rate") else 0} for c in after["charges"]]
    deals.cost_save(db, ADMIN, d.id, s["key"], after["materials"], charges, quoted_price=5.0)
    res = deals.cost_submit(db, ADMIN, d.id, s["key"])
    check("submit answers", bool(res.get("style")), str(res)[:120])
    again = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    check("the sheet is submitted afterwards", again.get("docstatus") == 1, str(again.get("docstatus")))
    refused = None
    try:
        deals.cost_save(db, ADMIN, d.id, s["key"], cs["materials"], cs["charges"], quoted_price=6.0)
    except deals.DealError as e:
        refused = str(e)
    check("a submitted costing cannot be edited from here", bool(refused) and "submitted" in (refused or "").lower(),
          str(refused))
    # and the ERP's own "Zero rate without N/A" refusal is turned into something a person can act on
    msg = deals._cost_refusal("Zero rate without N/A: Freight, Overhead, Profit")
    check("the zero-rate refusal is explained, the heads named", "N/A ticked" in msg and "Freight" in msg, msg)


def main():
    print("Saving a costing")
    t_payload_has_no_system_fields()
    t_numbers_and_units()
    t_save_recalculate_submit()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
