"""The ERP Cost Sheet fills itself from the standard costing — and N/A for what the workbook turns off.

The user's complaint (2026-11-07): *"The ERP refuses to submit a costing that leaves a mandatory head at 0 without
ticking N/A. Based on the given stuff it should auto populate, when required I do changes and move forward."*

So: `deals.cost_autofill` walks the Cost Sheet the ERP made from the Buyer BOM and puts the sheet's own figures on it —
the price of each item, the rate of each cost head, and the APPLY 1/0 column as the ERP's N/A tick — filling blanks only,
leaving a quote somebody chose alone, never clearing an N/A a person ticked, and never submitting.

It is a **button**, not an automatic write: the Cost sheet tab opens the document as the ERP holds it and only
*Fill from the costing sheet* calls this (the user's rule, 7 Nov: "do not auto put, have a button which when clicked it
does").
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
# never the live database: every run gets its own file (a stale KOGO_DB name here once wrote test deals into the
# user's own data - database.py reads DB_PATH_OVERRIDE, nothing else)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")

from database import get_session, init_db                                    # noqa: E402
import costing_sheet                                                         # noqa: E402
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


def _deal(db):
    be = fake_erp()
    deals.BACKEND = be
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Fill it", contact_email="b@acme.test")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500, "sizes": ["S", "M", "L"],
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% COTTON",
                               "uom": "Yard", "consumption": 1.4},
                              {"item_code": "U71", "material_type": "Fabric", "description": "(Content) 100% COTTON",
                               "uom": "Yard", "consumption": 0.1},
                              {"item_code": "BT234", "material_type": "Trim", "description": "BUTTON 18L",
                               "uom": "Nos", "consumption": 7},
                              {"item_code": "FZ900", "material_type": "Fusing", "description": "FUSE #9085",
                               "uom": "Yard", "consumption": 0.24}]})
    d.styles = json.dumps(styles)
    db.commit()
    out = deals.register(db, ADMIN, d.id)
    s = json.loads(out.styles or "[]")[0]
    deals.cost_open(db, ADMIN, out.id, s["key"])
    return out, s


def _by_head(cs_view):
    return {str(c.get("cost_head") or "").lower(): c for c in cs_view.get("charges") or []}


def _by_item(cs_view):
    """The Cost Sheet's material rows by item code, or by description when the ERP row has no item yet."""
    out = {}
    for m in cs_view.get("materials") or []:
        key = str(m.get("item") or m.get("description") or "").lower()
        out[key] = m
    return out


def _mat(cs_view, needle):
    for m in cs_view.get("materials") or []:
        if needle.lower() in f"{m.get('item') or ''} {m.get('description') or ''}".lower():
            return m
    return {}


def t_fills():
    print("\n1. The ERP cost sheet is filled from the standard costing")
    db = get_session()
    d, s = _deal(db)
    before = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    quoted_before = deals._ai_number(before["totals"].get("quoted_price"))
    check("it starts at zero - which is why the ERP refuses to submit it",
          not any(deals._ai_number(m.get("rate")) for m in before["materials"]))
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    tpl = {ln.tpl: ln for ln in lines if ln.tpl}
    check("the sheet opens with the workbook's own rates (main fabric 3.000)",
          tpl["M01"].rate == 3.0 and tpl["M13"].rate == 0.1, f"{tpl['M01'].rate} {tpl['M13'].rate}")

    out = deals.cost_autofill(db, ADMIN, d.id, s["key"])
    cs = out["cost_sheet"]
    heads = _by_head(cs)
    check("it priced the materials and heads it knows", out["priced"] >= 8, str(out["priced"]))
    check("the fabric took the sheet's price for that item", deals._ai_number(_mat(cs, "100% COTTON").get("rate")) == 3.0,
          str(_mat(cs, "100% COTTON").get("rate")))
    check("and its wastage came with the reason the ERP demands",
          deals._ai_number(_mat(cs, "100% COTTON").get("wastage_pct")) == 0.05
          and bool(_mat(cs, "100% COTTON").get("wastage_reason")))
    check("the trim line took its price too", deals._ai_number(_mat(cs, "BUTTON").get("rate")) == 0.1,
          str(_mat(cs, "BUTTON").get("rate")))
    check("MAKING CHARGES took the sheet's CMT", deals._ai_number(heads["stitching (cmt)"]["rate"]) == 5.0,
          str(heads.get("stitching (cmt)", {}).get("rate")))
    check("the fabric export / import heads took the per-metre cost",
          deals._ai_number(heads["fabric export cost"]["rate"]) == 0.25
          and deals._ai_number(heads["fabric import cost"]["rate"]) == 0.25)
    check("the percentage heads took the template's own percentages",
          deals._ai_number(heads["rejection allowance"]["rate"]) == 0.03
          and deals._ai_number(heads["overhead"]["rate"]) == 0.15,
          f"{heads.get('rejection allowance', {}).get('rate')} {heads.get('overhead', {}).get('rate')}")
    check("the profit head took the 15 % the sheet carries", deals._ai_number(heads["profit"]["rate"]) == 0.15)
    check("a head the workbook turns off (APPLY 0) is N/A, not a 0",
          int(heads["washing"].get("not_applicable") or 0) == 1
          and int(heads["printing"].get("not_applicable") or 0) == 1
          and int(heads["testing"].get("not_applicable") or 0) == 1)
    check("a head priced at 0 % is N/A as well", int(heads["buying agent commission"].get("not_applicable") or 0) == 1)
    check("a priced head is not marked N/A", not int(heads["stitching (cmt)"].get("not_applicable") or 0))
    check("a head the sheet does not cost at all is reported, not guessed",
          "Depreciation" in out["unmatched"], str(out["unmatched"]))
    # the ERP's own rule: a costing that has never been quoted takes the computed price. That is the ERP's arithmetic,
    # not the sheet's FOB, and it is the only thing this fill lets the ERP do with a price.
    check("the ERP's own quoted price is its computed price (not the sheet's FOB)",
          round(deals._ai_number(cs["totals"].get("quoted_price")) or 0, 2)
          == round(deals._ai_number(cs["totals"].get("computed_price")) or 0, 2),
          f"quoted {cs['totals'].get('quoted_price')} computed {cs['totals'].get('computed_price')}")
    check("the cost sheet stayed a draft", int(cs.get("docstatus") or 0) == 0)
    check("the ERP could compute a price from the filled lines", bool(deals._ai_number(cs["totals"].get("computed_price"))),
          str(cs["totals"].get("computed_price")))
    check("the consumption the BOM gave is untouched",
          deals._ai_number(_mat(cs, "100% COTTON").get("consumption")) == 1.4,
          str(_mat(cs, "100% COTTON").get("consumption")))
    check("the answer says what it did", out["written"] and out["na"] >= 1 and out["heads"] >= 5, str(out["na"]))
    return d, s


def t_idempotent(d, s):
    print("\n2. Running it again changes nothing (and never clears a tick)")
    db = get_session()
    _, _, rows = costing_sheet.open_sheet(db, d, s)
    # a person decides washing IS needed after all: a rate typed in the ERP
    cur = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    heads = {str(c["cost_head"]).lower(): c for c in cur["charges"]}
    charges = cur["charges"]
    for c in charges:
        if str(c.get("cost_head") or "").lower() == "washing":
            c["not_applicable"] = 0
            c["rate"] = 0.75
    deals.cost_save(db, ADMIN, d.id, s["key"], None, charges, quoted_price=None)
    out = deals.cost_autofill(db, ADMIN, d.id, s["key"])
    heads = _by_head(out["cost_sheet"])
    check("nothing was re-priced on the second run", out["priced"] == 0 and out["na"] == 0,
          f"priced={out['priced']} na={out['na']}")
    check("the rate a person typed stands", deals._ai_number(heads["washing"]["rate"]) == 0.75,
          str(heads["washing"].get("rate")))
    check("its N/A was not put back", not int(heads["washing"].get("not_applicable") or 0))
    check("the second run writes nothing", out["written"] is False)


def t_quote_preserved():
    print("\n3. A quote somebody chose is never overwritten by a fill")
    db = get_session()
    d, s = _deal(db)
    cur = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    deals.cost_autofill(db, ADMIN, d.id, s["key"])            # first fill: quote follows the computed price
    deals.cost_save(db, ADMIN, d.id, s["key"], None, None, quoted_price=12.50)   # a person decides a price
    # a blank appears in the ERP (a price wiped by hand) - the fill must put it back and leave the quote alone
    rows = [dict(m) for m in deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]["materials"]]
    rows[0]["rate"] = 0
    deals.cost_save(db, ADMIN, d.id, s["key"], rows, None, quoted_price=None)   # the price is gone in the ERP
    out = deals.cost_autofill(db, ADMIN, d.id, s["key"])
    check("the fill still works", out["priced"] >= 1, str(out["priced"]))
    check("the chosen quote is untouched", deals._ai_number(out["cost_sheet"]["totals"].get("quoted_price")) == 12.5,
          str(out["cost_sheet"]["totals"].get("quoted_price")))


def t_submitted_left_alone():
    print("\n4. A submitted costing is left exactly as it is")
    db = get_session()
    d, s = _deal(db)
    be = deals.BACKEND
    cs_name = json.loads(d.styles or "[]")[0]["cost_sheet"]
    doc = be.get_doc("Cost Sheet", cs_name)
    doc["docstatus"] = 1
    be.docs["Cost Sheet"][cs_name] = doc
    out = deals.cost_autofill(db, ADMIN, d.id, s["key"])
    check("it says so instead of writing", "submitted" in (out.get("note") or "").lower(), str(out.get("note")))
    check("and it wrote nothing", out["written"] is False)


def t_api_documented():
    print("\n5. There is one API for it, and it opens the sheet")
    import deal_api
    check("deal_cost_autofill is a published function", "deal_cost_autofill" in deal_api.FUNCTIONS)
    src = open(os.path.join(os.path.dirname(HERE), "document.md"), encoding="utf-8").read()
    check("and it is in document.md", "### `deal_cost_autofill`" in src)


def main():
    init_db()
    print("The ERP cost sheet fills itself from the costing")
    d, s = t_fills()
    t_idempotent(d, s)
    t_quote_preserved()
    t_submitted_left_alone()
    t_api_documented()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
